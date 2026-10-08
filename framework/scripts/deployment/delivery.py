"""Declared artifact placement and execution copies through the existing S3 boundary."""
import base64
import copy
import json
import re
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlencode

from cloudformation_inputs import Blocked, resolve_value, condition_active
from model_core import ARTIFACT_PROPERTIES
from s3_delivery import preflight as placement_preflight, read as placement_read, upload_options, verify_encryption


def placement(root, environment, directory, target, session, save, aws):
    """Only the existing S3 preflight interface; no scheduler, repair or approval access."""
    return SimpleNamespace(root=root, environment=environment, directory=directory, target=target,
                           session=session, save=save, aws=aws)


def source_path(root, artifact):
    path = (root / artifact["source"]).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_relative_to((root / "infra/cloudformation/artifacts").resolve()) or not path.is_file():
        raise Blocked(f"artifact source is missing or escapes its directory: {artifact['source']}")
    if artifact["property"] in {"Code", "Content"} and (path.suffix != ".zip" or not zipfile.is_zipfile(path)):
        raise Blocked("Lambda artifact must be a prebuilt ZIP file")
    return path


def verify_object(placement, obj):
    arguments = ["--bucket", obj["bucket"], "--key", obj["key"], "--expected-bucket-owner", placement.target.get("awsExecutionAccountId", placement.target["awsAccountId"]),
                 "--checksum-mode", "ENABLED"]
    if obj.get("version"):
        arguments += ["--version-id", obj["version"]]
    current = placement_read(placement, "head-object", *arguments)
    if current.get("ChecksumSHA256") != obj["checksum"] or current.get("ContentLength") != obj["size"]:
        raise Blocked("S3 artifact checksum/size changed; upload or execution blocked")
    if 'encryption' not in obj:
        raise Blocked('S3_PLACEMENT_INDETERMINATE: legacy object lacks resolved encryption conditions')
    conditions = placement_preflight(placement, obj['bucket'], obj['prefix'], [obj['key']])
    if conditions != obj['encryption']:
        raise Blocked('S3_PLACEMENT_CHANGED: object placement conditions changed')
    verify_encryption(current, conditions)
    return current


def upload(placement, file_digest, uploaded, path, bucket, prefix):
    digest = file_digest(path)
    obj = {"bucket": bucket, "key": prefix + digest + path.suffix,
           "checksum": base64.b64encode(bytes.fromhex(digest)).decode(), "size": path.stat().st_size,
           "prefix": prefix}
    obj['encryption'] = placement_preflight(placement, bucket, prefix, [obj['key']])
    cache_key = (bucket, obj["key"], digest)
    if cache_key in uploaded:
        verify_object(placement, uploaded[cache_key])
        return dict(uploaded[cache_key])
    try:
        current = verify_object(placement, obj)
    except Blocked as error:
        if not any(code in str(error) for code in ("(404)", "(NoSuchKey)", "(NotFound)")):
            raise
        try:
            current = placement.aws("put-object", "--bucket", bucket, "--key", obj["key"], "--body", str(path),
                "--expected-bucket-owner", placement.target.get("awsExecutionAccountId", placement.target["awsAccountId"]), "--if-none-match", "*",
                "--checksum-algorithm", "SHA256", "--checksum-sha256", obj["checksum"],
                *upload_options(obj['encryption']), service="s3api")
        except Blocked as error:
            if "(PreconditionFailed)" not in str(error):
                raise Blocked('S3_PLACEMENT_UPLOAD_DENIED_OR_FAILED: ' + str(error)) from error
            current = verify_object(placement, obj)
    if current.get("VersionId") not in {None, "null"}:
        obj["version"] = current["VersionId"]
    verify_object(placement, obj)
    uploaded[cache_key] = dict(obj)
    return obj


def artifact_bindings(target, aws, unit, document, parameters):
    pseudo = {"AWS::AccountId": target.get("awsExecutionAccountId", target["awsAccountId"]), "AWS::Region": target["awsRegion"], "AWS::StackName": unit["name"]}
    # Resolve every mapping before the first upload, including bucket/prefix consistency.
    bindings = []
    exports = {e["Name"]: e["Value"] for e in aws("list-exports").get("Exports", [])} if unit.get("artifacts") else {}
    for artifact in unit.get("artifacts", []):
        resource = document["Resources"][artifact["resource"]]
        if not condition_active(document, parameters, pseudo, resource):
            continue
        container = resource["Properties"]
        parts = artifact["property"].split(".")
        for part in parts[:-1]:
            container = container[part]
        value = container[parts[-1]]
        fields = ARTIFACT_PROPERTIES[(resource["Type"], artifact["property"])]
        if fields:
            if not isinstance(value, dict) or not {fields[0], fields[1]} <= value.keys():
                raise Blocked("artifact property must already declare its S3 bucket and key")
            bucket = resolve_value(value[fields[0]], parameters, pseudo, exports)
            key = resolve_value(value[fields[1]], parameters, pseudo, exports)
        else:
            uri = resolve_value(value, parameters, pseudo, exports)
            match = re.fullmatch(r"s3://([^/]+)/(.+)", uri)
            if not match:
                raise Blocked("artifact property must declare an S3 URI")
            bucket, key = match.groups()
        if bucket != artifact["bucket"] or not key.startswith(artifact["keyPrefix"]):
            raise Blocked("artifact bucket/keyPrefix differs from the approved template")
        bindings.append((artifact, container, parts[-1], fields))
    return bindings


def prepare_delivery_group(placement, units, states, templates, workdir, validated_digests, paths,
        input_digest, file_digest, uploaded, check_imports):
    """Read all destinations, stage all files, then allow bounded change set creation."""
    pending = [u for u in units if states[u['name']]['status'] not in {'RUNNING', 'SUCCESS'}]
    destinations = {}
    for unit in pending:
        check_imports(unit)
        document, parameters = templates[unit['name']]
        bindings = artifact_bindings(placement.target, placement.aws, unit, document, parameters)
        for artifact, _, _, _ in bindings:
            path = source_path(placement.root, artifact)
            key = artifact['keyPrefix'] + file_digest(path) + path.suffix
            destinations.setdefault((artifact['bucket'], artifact['keyPrefix']), set()).add(key)
        delivery = states[unit['name']].get('delivery', {})
        for obj in delivery.get('objects', []):
            destinations.setdefault((obj['bucket'], obj.get('prefix', '')), set()).add(obj['key'])
    for (bucket, prefix), keys in destinations.items():
        placement_preflight(placement, bucket, prefix, sorted(keys))
    # Artifact versions determine the actual execution-template byte size.
    for unit in pending:
        template_arguments(placement, unit, states[unit['name']], templates[unit['name']], paths(unit)[0], workdir, validated_digests, input_digest, file_digest, uploaded, stage_only=True)
    destinations = {}
    for unit in pending:
        delivery = states[unit['name']]['delivery']
        path = Path(delivery['path'])
        if path.stat().st_size > 51200:
            if not unit.get('templateBucket') or not unit.get('templateKeyPrefix'):
                raise Blocked('large template requires designed TemplateBucket and TemplateKeyPrefix')
            key = unit['templateKeyPrefix'] + file_digest(path) + path.suffix
            destinations.setdefault((unit['templateBucket'], unit['templateKeyPrefix']), set()).add(key)
    for (bucket, prefix), keys in destinations.items():
        placement_preflight(placement, bucket, prefix, sorted(keys))
    for unit in pending:
        template_arguments(placement, unit, states[unit['name']], templates[unit['name']], paths(unit)[0], workdir, validated_digests, input_digest, file_digest, uploaded)


def template_arguments(placement, unit, state, template_data, template_path, workdir, validated_digests,
        input_digest_for, file_digest, uploaded, stage_only=False):
    """Prepare only declared S3 references in a copy outside the repository."""
    if state.get("delivery"):
        delivery = state["delivery"]
        document, parameters = template_data
        artifact_bindings(placement.target, placement.aws, unit, document, parameters)
        if input_digest_for(unit) != delivery["inputDigest"]:
            raise Blocked("prepared deployment inputs changed")
        path = Path(delivery["path"])
        if file_digest(path) != delivery["templateSha256"]:
            raise Blocked("prepared deployment template changed")
        for obj in delivery["objects"]:
            verify_object(placement, obj)
        if delivery.get('arguments'):
            return delivery['arguments']
        path, objects = Path(delivery['path']), delivery['objects']
        input_digest = delivery['inputDigest']
    else:
        path, _ = (template_path, None)
        document, parameters = template_data
        document = copy.deepcopy(document)
        objects = []
        input_digest = input_digest_for(unit)
        if unit["name"] in validated_digests and validated_digests[unit["name"]] != input_digest:
            raise Blocked("deployment inputs changed after validation")
        bindings = artifact_bindings(placement.target, placement.aws, unit, document, parameters)
        if bindings:
            if workdir is None:
                raise Blocked("artifact packaging requires the external deployment session directory")
            for artifact, container, prop, fields in bindings:
                obj = upload(placement, file_digest, uploaded, source_path(placement.root, artifact), artifact["bucket"], artifact["keyPrefix"])
                objects.append(obj)
                if fields:
                    container[prop][fields[1]] = obj["key"]
                    container[prop].pop(fields[2], None)
                    if obj.get("version"):
                        container[prop][fields[2]] = obj["version"]
                else:
                    container[prop] = f"s3://{obj['bucket']}/{obj['key']}"
            workdir.mkdir(parents=True, exist_ok=True)
            path = workdir / (unit["name"] + ".json")
            path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            result = subprocess.run(["cfn-lint", "--regions", placement.target["awsRegion"], "--template", str(path)], capture_output=True, text=True)
            if result.returncode:
                raise Blocked("packaged template cfn-lint failed: " + result.stdout + result.stderr)
    size = path.stat().st_size
    if size > 1024 * 1024:
        raise Blocked("template exceeds the 1 MiB CloudFormation limit")
    state['delivery'] = {'inputDigest': input_digest, 'path': str(path),
                         'templateSha256': file_digest(path), 'objects': objects}
    placement.save()
    if stage_only:
        return []
    arguments = ["--template-body", "file://" + str(path)]
    if size > 51200:
        if not unit.get("templateBucket") or not unit.get("templateKeyPrefix"):
            raise Blocked("large template requires designed TemplateBucket and TemplateKeyPrefix")
        obj = upload(placement, file_digest, uploaded, path, unit["templateBucket"], unit["templateKeyPrefix"])
        objects.append(obj)
        suffix = "amazonaws.com.cn" if placement.target["awsRegion"].startswith("cn-") else "amazonaws.com"
        url = f"https://s3.{placement.target['awsRegion']}.{suffix}/{obj['bucket']}/{quote(obj['key'], safe='/')}"
        if obj.get("version"):
            url += "?" + urlencode({"versionId": obj["version"]})
        arguments = ["--template-url", url]
    if input_digest_for(unit) != input_digest:
        raise Blocked("deployment inputs changed while preparing artifacts")
    state["delivery"] = {"inputDigest": input_digest, "path": str(path), "arguments": arguments,
                         "templateSha256": file_digest(path), "objects": objects}
    placement.save()
    return arguments


