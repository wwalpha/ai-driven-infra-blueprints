#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
from support.model_sources import allocate_fixture as allocate
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.cloudformation_deploy_fixtures import *

from support.model_v2_fixtures import deploy_properties_fixture

def check_sdk_execution():
    # Case 3: distinct AWS requests with the shared template and separate inputs.
    backend = StubAws()
    scoped = units(10, 10)
    for unit in scoped:
        backend.templates[unit["name"]] = ({}, {})
        state = {"status": "NOT_STARTED", "clientToken": "token-" + unit["name"]}
        assert backend.prepare(unit, state) == "READY"
        backend.execute(unit, state)
    creates = [args for operation, args in backend.calls if operation == "create_change_set"]
    assert len(creates) == 2 and creates[0]["StackName"] == "A" and creates[1]["StackName"] == "B"
    assert creates[0]["TemplateBody"] == creates[1]["TemplateBody"]
    assert creates[0]["Parameters"] == []
    assert creates[1]["Parameters"] == []
    executes = [args for operation, args in backend.calls if operation == "execute_change_set"]
    assert executes[0]["ChangeSetName"] == "cs-A" and executes[1]["ChangeSetName"] == "cs-B"
    # Cases 6/7: producer succeeds before real list-exports and consumer change set.
    backend = StubAws()
    scoped = units(10, 20)
    state = states(scoped)
    backend.templates = {"A": ({}, {}), "B": ({"Resources": {"Imported": {"Fn::ImportValue": "NetworkVpcId"}}}, {})}
    def execute(unit, entry):
        backend.calls.append(("executed", unit["name"]))
    backend.execute = execute
    def poll(unit, entry):
        if unit["name"] == "A":
            backend.exports = ["NetworkVpcId"]
        backend.calls.append(("terminal", unit["name"]))
        return "CREATE_COMPLETE"
    backend.poll = poll
    assert finish(scoped, 3, state, backend) == "COMPLETE"
    consumer_cs = next(i for i, (op, args) in enumerate(backend.calls) if op == "create_change_set" and args["StackName"] == "B")
    assert backend.calls.index(("terminal", "A")) < next(i for i, (op, _) in enumerate(backend.calls) if op == "list_exports") < consumer_cs
    for exports, expected in ((["NetworkVpcId"], "COMPLETE"), ([], "STOPPED")):
        backend = StubAws(exports)
        backend.templates["B"] = ({"Fn::ImportValue": "NetworkVpcId"}, {})
        backend.execute, backend.poll = lambda *args: None, lambda *args: "CREATE_COMPLETE"
        partial = [scoped[1]]
        state = states(partial)
        assert finish(partial, 2, state, backend) == expected
        creates = [args["StackName"] for op, args in backend.calls if op == "create_change_set"]
        assert creates == (["B"] if exports else []) and "A" not in state
    # Missing export after a successful producer still blocks consumer.
    backend = StubAws()
    backend.templates["B"] = ({"Fn::ImportValue": "NetworkVpcId"}, {})
    state = states([scoped[1]])
    assert finish([scoped[1]], 2, state, backend) == "STOPPED"
    assert state["B"]["status"] == "BLOCKED"
    assert "DeployOrder conflicts" in state["B"]["reason"]
    assert not any(op == "create_change_set" for op, _ in backend.calls)
    backend = StubAws()
    backend.templates = {"A": ({}, {}), "B": ({"Fn::ImportValue": "NetworkVpcId"}, {})}
    backend.execute, backend.poll = lambda *args: None, lambda *args: "CREATE_COMPLETE"
    state = states(scoped)
    assert finish(scoped, 2, state, backend) == "STOPPED"
    assert [entry["status"] for entry in state.values()] == ["SUCCESS", "BLOCKED"]
    assert [args["StackName"] for op, args in backend.calls if op == "create_change_set"] == ["A"]
    # Existing Export cannot bypass an unfinished in-scope producer in the same group.
    backend = StubAws()
    backend.templates["B"] = ({"Fn::ImportValue": "NetworkVpcId"}, {})
    backend.states = {"A": {"status": "RUNNING"}}
    backend.aws = lambda *args: {"Exports": [{"Name": "NetworkVpcId", "Value": "vpc-fixture", "ExportingStackId": "arn:aws:cloudformation:region:account:stack/A/id"}]}
    rejects(lambda: backend.check_imports(scoped[1]), "producer A has not succeeded")
    # Destructive change blocks. Human approval reuses and re-fetches exact ID/content.
    backend = StubAws(destructive=True)
    unit, state = scoped[0], {"status": "NOT_STARTED", "clientToken": "approved"}
    backend.templates["A"] = ({}, {})
    assert backend.prepare(unit, state) == "BLOCKED"
    assert not any(op == "execute_change_set" for op, _ in backend.calls)
    backend.approvals = {state["changeSetId"]}
    assert backend.prepare(unit, state) == "READY"
    with patch("model.adapters.observed.mappings", side_effect=AssertionError("Execute mapping forbidden")) as mapping_check:
        backend.execute(unit, state)
    assert mapping_check.call_count == 0
    assert sum(op == "create_change_set" for op, _ in backend.calls) == 1
    backend.change["Changes"][0]["ResourceChange"]["PolicyAction"] = "Retain"
    rejects(lambda: backend.prepare(unit, state), "approval invalid")
    rejects(lambda: backend.execute(unit, state), "approval invalid")
    backend.change["ExecutionStatus"] = "OBSOLETE"
    rejects(lambda: backend.prepare(unit, state), "AVAILABLE")
    for replacement in ("True", "Conditional"):
        backend = StubAws()
        backend.change["Changes"][0]["ResourceChange"].update(Action="Modify", Replacement=replacement)
        backend.templates["A"] = ({}, {})
        assert backend.prepare(unit, {"status": "NOT_STARTED"}) == "BLOCKED"
    backend.change["Changes"][0]["ResourceChange"]["Replacement"] = "Unknown"
    rejects(lambda: backend.prepare(unit, {"status": "NOT_STARTED"}), "unknown change set replacement")
    # A matching operation token and actual terminal stack status are both required.
    backend = Runtime(ROOT, "dev", "123456789012", TARGET)
    event = {"ResourceType": "AWS::CloudFormation::Stack", "ClientRequestToken": "current", "ResourceStatus": "CREATE_FAILED"}
    actual = ["ROLLBACK_IN_PROGRESS"]
    backend.aws = lambda operation, **args: ({"StackEvents": [event]} if operation == "describe_stack_events" else {"Stacks": [{"StackStatus": actual[0]}]})
    state = {"status": "RUNNING", "clientToken": "current", "changeSetId": "cs-A"}
    assert backend.poll(unit, state) == "ROLLBACK_IN_PROGRESS" and state["failureDetected"]
    actual[0], event["ResourceStatus"] = "ROLLBACK_COMPLETE", "ROLLBACK_COMPLETE"
    assert backend.poll(unit, state) == "ROLLBACK_COMPLETE"
    actual[0], event["ResourceStatus"] = "UPDATE_COMPLETE", "UPDATE_IN_PROGRESS"
    assert backend.poll(unit, state) == "UPDATE_IN_PROGRESS"  # Do not mistake old success for new success.
    backend.aws = lambda operation, **args: ({"StackEvents": []} if operation == "describe_stack_events" else {"ExecutionStatus": "EXECUTE_IN_PROGRESS"})
    assert backend.poll(unit, state) == "UPDATE_IN_PROGRESS"


def check_empty_rollback_recreation(tmp_path):
    class EmptyRollbackAws(StubAws):
        def __init__(self, root):
            super().__init__()
            self.root = root
            for unit in units(10, 10):
                template, parameters = self.paths(unit)
                template.parent.mkdir(parents=True, exist_ok=True); parameters.parent.mkdir(parents=True, exist_ok=True)
                template.write_text('Resources: {}'); parameters.write_text('[]')
            self.current = {'A': 'ROLLBACK_COMPLETE', 'B': 'ROLLBACK_COMPLETE'}
            self.actuals = [{'ResourceStatus': 'DELETE_COMPLETE', 'LogicalResourceId': 'Old',
                            'ResourceType': 'AWS::S3::Bucket', 'PhysicalResourceId': 'deleted-bucket'}]
            self.extra, self.deletes = {}, []
            self.templates = {name: ({'Resources': {'Item': {'Type': 'AWS::S3::Bucket',
                                   'DeletionPolicy': 'Retain'}}}, {}) for name in self.current}

        def aws(self, operation, **args):
            if operation in {'describe_stacks', 'list_stack_resources', 'delete_stack'}:
                self.calls.append((operation, args))
                target = args['StackName']
                name = target.removeprefix('old-')
                if operation == 'describe_stacks':
                    if self.current[name] is None:
                        raise M.Blocked('stack does not exist')
                    return {'Stacks': [{'StackId': 'old-' + name, 'StackStatus': self.current[name], **self.extra}]}
                if operation == 'list_stack_resources':
                    assert target == 'old-' + name
                    return {'StackResourceSummaries': self.actuals}
                assert target == 'old-' + name
                self.deletes.append(target)
                self.current[name] = None
                return {}
            return super().aws(operation, **args)

        def poll(self, unit, state):
            return 'CREATE_COMPLETE'

    scoped = units(10, 10)
    root = tmp_path
    (root / 'tasks').mkdir()
    (root / 'tasks/example.md').write_text('## Task contract\n- Task type: `infrastructure`\n- Task status: `running`\n- Infrastructure phase: `deploy`\n- Controlled repair: `allowed`\n## Modified files\n- `tasks/example.md`\n## Allowed paths\n- `tasks/example.md`\n', encoding='utf-8')
    # Both existing shells are deleted by ID before CREATE, without approval or IaC repair.
    backend = EmptyRollbackAws(root)
    saved = states(scoped)
    assert finish(scoped, 2, saved, backend) == 'COMPLETE', saved
    assert backend.deletes == ['old-A', 'old-B']
    for name in ('A', 'B'):
        deletion = next(i for i, (op, args) in enumerate(backend.calls) if op == 'delete_stack' and args["StackName"] == 'old-' + name)
        creation = next(i for i, (op, args) in enumerate(backend.calls) if op == 'create_change_set' and args["StackName"] == name)
        assert deletion < creation and saved[name]['operationType'] == 'CREATE'
        assert saved[name]['absentBeforeCreate'] and saved[name]['emptyStackRecreated']
    # Resumed FAILED states also recover when no authoritative IaC correction exists.
    backend = EmptyRollbackAws(root)
    saved = {name: {'status': 'FAILED', 'stackStatus': 'ROLLBACK_COMPLETE', 'stackId': 'old-' + name,
                   'changeSetId': 'stale', 'clientToken': 'stale', 'delivery': {'stale': True}}
             for name in ('A', 'B')}
    def no_repair(*args):
        raise M.Blocked('no unique IaC repair')
    backend.repair_plan = no_repair
    session = {'states': saved, 'metrics': {'observedSyncSeconds': 0}}
    def synced(_backend, items, entries):
        for unit in items:
            entries[unit['name']]['observedSynced'] = True
    with patch.object(M.session_ops, 'sync_successful', side_effect=synced):
        assert M.session_ops.run_session(scoped, 2, session, backend, lambda: None, sleep=lambda _: None) == 'COMPLETE'
    assert backend.deletes == ['old-A', 'old-B']
    assert all(entry['changeSetId'] != 'stale' and 'delivery' not in entry for entry in saved.values())
    # The same failure cannot trigger an unbounded recreation loop.
    saved['A'].update(status='FAILED', stackStatus='ROLLBACK_COMPLETE', stackId='old-A')
    backend.current['A'] = 'ROLLBACK_COMPLETE'
    assert not backend.repair(scoped[0], saved['A']) and backend.deletes == ['old-A', 'old-B']
    assert saved['A']['failureClassification'] == 'HUMAN_REQUIRED'
    for actuals in ([], [{'ResourceStatus': 'DELETE_COMPLETE'}]):
        backend = EmptyRollbackAws(root)
        backend.actuals = actuals
        assert backend.begin_prepare(scoped[0], {}) == 'CHANGESET_CREATING'
        assert backend.deletes == ['old-A']
    for status in ('CREATE_COMPLETE', 'DELETE_SKIPPED', 'CREATE_FAILED', 'DELETE_FAILED', None):
        backend = EmptyRollbackAws(root)
        backend.actuals = [{'ResourceStatus': status}]
        rejects(lambda: backend.begin_prepare(scoped[0], {}), 'not all deleted')
        assert not backend.deletes
    for extra in ({'EnableTerminationProtection': True}, {'ParentId': 'parent'}, {'StackId': 'other'}):
        backend = EmptyRollbackAws(root)
        backend.extra = extra
        rejects(lambda: backend.cleanup_failed_create(scoped[0], {'stackStatus': 'ROLLBACK_COMPLETE', 'stackId': 'old-A'}, empty_only=True), 'protected')
        assert not backend.deletes
    backend = EmptyRollbackAws(root)
    read = backend.aws
    backend.aws = lambda op, **args: {} if op == 'list_stack_resources' else read(op, **args)
    try:
        backend.begin_prepare(scoped[0], {})
        raise AssertionError('missing resource response accepted')
    except KeyError:
        pass
    assert not backend.deletes
    # Interrupted deletion resumes the pinned ID, without a second deletion.
    for interrupted_status in ('DELETE_IN_PROGRESS', 'DELETE_COMPLETE', None):
        backend = EmptyRollbackAws(root)
        backend.current['A'] = interrupted_status
        state = {'stackStatus': 'ROLLBACK_COMPLETE', 'stackId': 'old-A', 'cleanupStackId': 'old-A', 'cleanupStatus': 'DELETE_INTENT'}
        def completed(entry):
            backend.current['A'] = None
            entry['cleanupStatus'] = 'DELETE_COMPLETE'
        backend.wait_cleanup = completed
        assert backend.begin_prepare(scoped[0], state) == 'CHANGESET_CREATING' and not backend.deletes
    # A previous cleanup marker must not suppress deletion of a later failed StackId.
    backend = EmptyRollbackAws(root)
    state = {'stackStatus': 'ROLLBACK_COMPLETE', 'stackId': 'old-A', 'cleanupStackId': 'previous-id', 'cleanupStatus': 'DELETE_COMPLETE'}
    assert backend.cleanup_failed_create(scoped[0], state, empty_only=True) and backend.deletes == ['old-A']
    backend = EmptyRollbackAws(root)
    rejects(lambda: backend.begin_prepare(scoped[0], {'cleanupStatus': 'DELETE_COMPLETE', 'cleanupStackId': 'old-A'}), 'name was reused')
    assert not backend.deletes
    print('Empty ROLLBACK_COMPLETE recreation: PASS (two stacks, resume, pinned deletion, residual/protection/read guards, bounded retry)')


def check_template_validation(tmp_path):
    backend = Runtime(tmp_path, 'dev', '123456789012', TARGET)
    unit = units(10)[0]
    template, parameters = backend.paths(unit)
    template.parent.mkdir(parents=True); parameters.parent.mkdir(parents=True)
    template.write_text('Parameters: {Prefix: {Type: String, Default: Default}}\nResources: {}\n')
    parameters.write_text('[{"ParameterKey":"Prefix","ParameterValue":"Network"}]')
    with patch('socket.socket', side_effect=AssertionError('network forbidden')), patch.object(subprocess, 'run', side_effect=AssertionError('CLI forbidden')):
        backend.load_inputs(unit)
    assert backend.templates['A'][1] == {'Prefix': 'Network'}
    template.write_text('Transform: AWS::Serverless-2016-10-31\nResources: {}')
    rejects(lambda: backend.load_inputs(unit), 'transform template')


def check_delivery(tmp_path):
    base = tmp_path
    root = base / "repo"
    backend = DeliveryAws(root, base / "session.files")
    unit = units(10)[0]
    template, params = backend.paths(unit)
    template.parent.mkdir(parents=True)
    params.parent.mkdir(parents=True)
    params.write_text("[]", encoding="utf-8")
    backend.templates["A"] = ({"Resources": {}}, {})
    settings = {"templateBucket": "app-dev-assets", "templateKeyPrefix": "templates/"}
    # Measure UTF-8 bytes, with the exact 51,200 byte boundary and 1 MiB maximum.
    for size, mode in ((51200, "TemplateBody"), (51201, "TemplateURL"), (1024 * 1024, "TemplateURL")):
        template.write_bytes(("# あ\n".encode() * (size // 6)) + b" " * (size % 6))
        assert template.stat().st_size == size
        state = {"status": "NOT_STARTED"}
        assert backend.prepare(unit | settings, state) == "READY"
        validations = [args for op, args in backend.calls if op == "validate_template"]
        creates = [args for op, args in backend.calls if op == "create_change_set"]
        assert mode in validations[-1]
        assert validations[-1][mode] == creates[-1][mode]
        if mode == "TemplateURL":
            assert validations[-1][mode].endswith("?versionId=version%2B1")
        count = sum(op == "put_object" for op, _ in backend.calls)
        assert backend.prepare(unit | settings, state) == "READY"
        assert sum(op == "put_object" for op, _ in backend.calls) == count
    template.write_bytes(b" " * (1024 * 1024 + 1))
    rejects(lambda: backend.prepare(unit | settings, {}), "1 MiB")
    template.write_bytes(b" " * 51201)
    rejects(lambda: backend.prepare(unit, {}), "requires designed TemplateBucket")
    template.write_text("Resources: {}\n", encoding="utf-8")
    backend.calls.clear()
    assert backend.prepare(unit, {}) == "READY"
    assert not any(op in {"get_bucket_location", "head_object", "put_object"} for op, _ in backend.calls)

    source = root / "infra/cloudformation/artifacts/function-a.zip"
    source.parent.mkdir(parents=True)
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("index.py", "def handler(event, context): return event\n")
    def artifact(name, bucket="app-dev-assets", prop="Code", filename="function-a.zip"):
        return {"stack": "A", "resource": name, "property": prop,
                "source": "infra/cloudformation/artifacts/" + filename, "bucket": bucket, "keyPrefix": "lambda/"}
    resources = {name: {"Type": "AWS::Lambda::Function", "Properties": {"Handler": "index.handler",
                 "Code": {"S3Bucket": bucket, "S3Key": "lambda/current.zip"}}}
                 for name, bucket in (("First", "app-dev-assets"), ("Second", "app-dev-assets"), ("Third", "app-dev-other"))}
    document = {"Resources": resources}
    template.write_text(json.dumps(document), encoding="utf-8")
    original = template.read_bytes()
    backend.templates["A"] = (document, {})
    prepared = unit | {"artifacts": [artifact("First"), artifact("Second"), artifact("Third", "app-dev-other")]}
    backend.calls.clear()
    state = {"status": "NOT_STARTED"}
    with patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
        assert backend.prepare(prepared, state) == "READY"
    packaged = json.loads(Path(state["delivery"]["path"]).read_text())
    first, second, third = [packaged["Resources"][name]["Properties"]["Code"] for name in ("First", "Second", "Third")]
    assert first["S3Key"] == second["S3Key"] == third["S3Key"]
    assert first["S3Bucket"] != third["S3Bucket"] and first["S3ObjectVersion"] == "version+1"
    assert sum(op == "put_object" for op, _ in backend.calls) == 2  # Shared ZIP reused within a bucket.
    assert any(op == 'get_bucket_encryption' for op, _ in backend.calls)
    assert template.read_bytes() == original and document["Resources"]["First"]["Properties"]["Code"]["S3Key"] == "lambda/current.zip"
    assert packaged["Resources"]["First"]["Properties"]["Handler"] == "index.handler"
    assert max(i for i, (op, _) in enumerate(backend.calls) if op == "put_object") < next(i for i, (op, _) in enumerate(backend.calls) if op == "create_change_set")
    resumed = DeliveryAws(root, base / "session.files")
    resumed.objects, resumed.templates = backend.objects, backend.templates
    assert resumed.prepare(prepared, state) == "READY"
    assert not any(op in {"put_object", "create_change_set"} for op, _ in resumed.calls)
    obj = state["delivery"]["objects"][0]
    resumed.objects[obj["bucket"], obj["key"]]["ChecksumSHA256"] = "changed"
    rejects(lambda: resumed.prepare(prepared, state), "checksum/size changed")
    resumed.objects[obj["bucket"], obj["key"]]["ChecksumSHA256"] = obj["checksum"]
    old = source.read_bytes()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("index.py", "changed code")
    rejects(lambda: resumed.prepare(prepared, state), "inputs changed")
    source.write_bytes(old)
    copy_path = Path(state["delivery"]["path"])
    old_copy = copy_path.read_bytes()
    copy_path.write_text("{}")
    rejects(lambda: resumed.prepare(prepared, state), "template changed")
    copy_path.write_bytes(old_copy)

    # All declared destinations are checked before uploading anything.
    for changed in ({"bucket": "wrong-bucket"}, {"keyPrefix": "wrong/"}):
        resumed.calls.clear()
        bad = unit | {"artifacts": [artifact("First") | changed]}
        rejects(lambda: resumed.prepare(bad, {}), "differs from the approved template")
        assert not any(op in {"put_object", "create_change_set"} for op, _ in resumed.calls)
    fresh = DeliveryAws(root, base / "fresh.files")
    fresh.templates = backend.templates
    fresh.region = "us-east-1"
    rejects(lambda: fresh.prepare(prepared, {}), "region does not match")
    fresh.region, fresh.fail = "ap-northeast-1", "put_object"
    rejects(lambda: fresh.prepare(prepared, {}), "AccessDenied")
    assert not any(op == "create_change_set" for op, _ in fresh.calls)
    fresh.fail = None
    source.unlink()
    rejects(lambda: fresh.prepare(prepared, {}), "source is missing")
    source.write_text("not a zip")
    rejects(lambda: fresh.prepare(prepared, {}), "prebuilt ZIP")
    # Inject link resolution without requiring Windows symlink privileges.
    resolve = Path.resolve
    with patch.object(Path, "resolve", lambda path, *args, **kwargs:
                      base / "outside.zip" if path == source else resolve(path, *args, **kwargs)):
        rejects(lambda: fresh.source_path(artifact("First")), "escapes")
    source.write_bytes(old)

    # Layer, Glue script and Step Functions definition use the same explicit mapping.
    script = source.with_name("job.py")
    script.write_text("print('job')")
    definition = source.with_name("state.json")
    definition.write_text('{"StartAt":"End","States":{"End":{"Type":"Succeed"}}}')
    other = {"Resources": {
        "Layer": {"Type": "AWS::Lambda::LayerVersion", "Properties": {"Content": {"S3Bucket": "app-dev-assets", "S3Key": "lambda/current.zip"}}},
        "Job": {"Type": "AWS::Glue::Job", "Properties": {"Command": {"Name": "glueetl", "ScriptLocation": "s3://app-dev-assets/lambda/job.py"}}},
        "State": {"Type": "AWS::StepFunctions::StateMachine", "Properties": {"DefinitionS3Location": {"Bucket": "app-dev-assets", "Key": "lambda/state.json"}}}}}
    template.write_text(json.dumps(other))
    fresh.templates["A"] = (other, {})
    mapped = unit | {"artifacts": [artifact("Layer", prop="Content"), artifact("Job", prop="Command.ScriptLocation", filename="job.py"),
                                   artifact("State", prop="DefinitionS3Location", filename="state.json")]}
    with patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
        assert fresh.prepare(mapped, {}) == "READY"
    result = json.loads((fresh.workdir / "A.json").read_text())["Resources"]
    assert result["Job"]["Properties"]["Command"]["Name"] == "glueetl"
    assert result["State"]["Properties"]["DefinitionS3Location"]["Version"] == "version+1"

    # Model -> generated view -> projection retains settings and explicit file bindings.
    values = {f"desired.stack.001.{field}": value for field, value in unit.items()}
    values["display.stack.001.comment"] = "アプリケーションを配置するstack"
    reference = "[S3_Bucket_001](s3.md#resource-S3_Bucket_001)"
    values.update({"desired.deployment.templateBucket": reference, "desired.deployment.templateKeyPrefix": "templates/"})
    values.update({"desired.artifact.007." + field: value for field, value in artifact("First").items()})
    values["desired.artifact.007.bucket"] = reference
    design = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
    design.parent.mkdir(parents=True)
    model = root / "model/dev/123456789012/s3.properties"
    model.parent.mkdir(parents=True, exist_ok=True)
    write_model(model, 'desired.resource.001.resourceType=S3.Bucket\ndesired.resource.001.logicalId=S3_Bucket_001\ndesired.resource.001.anchor=resource-S3_Bucket_001\ndesired.service.identity.lastAllocated={"S3.Bucket":1}\ndesired.row.001-001.property=S3.Bucket.BucketName\ndesired.row.001-001.value=`app-dev-assets`\ndesired.row.001-001.comment=配置先bucket\n')
    design.write_text(markdown_for(design, values, root))
    view = design.read_text()
    assert "| Property | Value |" not in view and "| TemplateBucket |" not in view and "| TemplateKeyPrefix |" not in view
    assert "### 配置ファイル" in view and f"<!-- templateBucket: {reference} -->" in view
    source_model = model.with_name("cloudformation-stacks.properties")
    write_model(source_model, values)
    projected = stack_delivery(design) | {key: value for key, value in values.items() if key.startswith("desired.stack.")}
    settings, files = deployment_settings(projected)
    assert settings == deployment_settings(values)[0] and [a for _, a in files] == [a for _, a in deployment_settings(values)[1]]
    design.write_text(view + f"<!-- templateBucket: {reference} -->\n")
    rejects(lambda: stack_delivery(design), "duplicate S3 delivery setting")
    design.write_text(view.replace("<!-- templateKeyPrefix: templates/ -->", "<!-- templateKeyPrefix: -->"))
    rejects(lambda: stack_delivery(design), "invalid S3 delivery setting comment")
    design.write_text(view)
    source_model = model.with_name("cloudformation-stacks.properties")
    write_model(source_model, "\n".join(f"{key}={value}" for key, value in values.items()))
    _, loaded = M.load_units(root, "dev", "123456789012", ["A"])
    assert loaded[0]["templateBucket"] == "app-dev-assets" and loaded[0]["artifacts"][0]["bucket"] == "app-dev-assets"
    rejects(lambda: deployment_bucket("[S3_Bucket_999](s3.md#resource-S3_Bucket_999)", design, root), "Resource anchor is absent or ambiguous")
    rejects(lambda: deployment_settings(values | {"desired.deployment.templateBucket": "guessed-bucket"}), "Markdown Resource reference")
    missing = dict(values)
    del missing["desired.deployment.templateKeyPrefix"]
    rejects(lambda: deployment_settings(missing), "specified together")
    for field, invalid in (("source", "../secret"), ("keyPrefix", "../"), ("stack", "unknown"), ("property", "Other")):
        rejects(lambda: deployment_settings(values | {"desired.artifact.007." + field: invalid}), "artifact" if field not in {"keyPrefix"} else "keyPrefix")
    duplicate = values | {key.replace(".007.", ".008."): value for key, value in values.items() if key.startswith("desired.artifact.")}
    rejects(lambda: deployment_settings(duplicate), "duplicate artifact destination")
    # Exercise the actual scoped staging/generation path, including a referenced S3 model.
    spec = importlib.util.spec_from_file_location("delivery_sync", ROOT / "framework/scripts/sync-model.py")
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", **TARGET}]}) + "\n")
    values["desired.stack.001.name"] = values["desired.artifact.007.stack"] = "cfn-stack-app-dev-job-01"
    write_model(source_model, "\n".join(f"{key}={value}" for key, value in values.items()))
    (design.parent / "s3.md").write_text('# S3 詳細設計\n<a id="s3-app-dev-assets"></a>\n')
    saved_model = snapshot_model(model)
    with redirect_stdout(io.StringIO()):
        assert sync.sync(root, True, "dev", "123456789012", services=["cloudformation-stacks"]) == 0
        assert sync.sync(root, False, "dev", "123456789012", services=["cloudformation-stacks"]) == 0
    assert snapshot_model(model) == saved_model
    assert {k.removeprefix('desired.deployment.'):v for k,v in stack_delivery(design).items() if k.startswith('desired.deployment.')} == deployment_settings(values)[0]
    only_templates = {key: value for key, value in values.items() if not key.startswith("desired.artifact.")}
    template_view = markdown_for(design, only_templates, root)
    assert "## S3配置" not in template_view and "| Property | Value |" not in template_view
    write_model(source_model, only_templates)
    design.write_text(template_view)
    assert {k.removeprefix('desired.deployment.'):v for k,v in stack_delivery(design).items() if k.startswith('desired.deployment.')} == deployment_settings(values)[0]
    design.write_text(template_view.replace("<!-- templateKeyPrefix: templates/ -->", "<!-- templateKeyPrefix: changed/ -->"))
    plan = SimpleNamespace(root=root, read_inputs={}, expected_outputs={design: {design: template_view}}, failures=[], saved={})
    __import__('sync_runtime')._compare_generation(plan)
    assert plan.failures == ['generated Markdown is stale or missing: docs/designs/dev/123456789012/cloudformation-stacks.md']
    only_artifacts = {key: value for key, value in values.items() if not key.startswith("desired.deployment.template")}
    write_model(source_model, only_artifacts)
    design.write_text(markdown_for(design, only_artifacts, root))
    assert "| Property | Value |" not in design.read_text()
    assert deployment_settings(stack_delivery(design) | {"desired.stack.001.name": values["desired.stack.001.name"]})[1]

    backend.add_bucket('app-dev-assets')
    backend.add_bucket('app-dev-other')
    # Default delegation is model-only approval, preserved through display reparsing.
    approved = properties(read_model(model))
    approved.update({'desired.service.s3.serviceId': 's3',
                     'desired.service.s3.ownedCatalogResourceTypes': 'S3.Bucket',
                     'display.service.title': '# S3 詳細設計',
                     'desired.resource.001.deploymentEncryption': 'default'})
    from model.core import entries
    for identity, resource in entries(approved, 'desired.resource.'):
        approved[f'desired.resource.{identity}.resourceMode'] = 'IMPORT'
        approved[f'desired.resource.{identity}.anchor'] = 'resource-' + resource['logicalId']
        approved[f'display.resource.{identity}.comment'] = '配置先bucket'
    for identity, row in entries(approved, 'desired.row.'):
        approved[f'desired.row.{identity}.comment'] = '承認済み設定'
    bucket_view = design.with_name('s3.md')
    bucket_view.write_text(markdown_for(bucket_view, approved, root))
    assert bucket_view.read_text() == markdown_for(bucket_view, approved, root)
    assert dict(entries(approved, 'desired.resource.'))['001']['deploymentEncryption'] == 'default'
    rejects(lambda: entries(approved | {'desired.resource.001.deploymentEncryption': 'guessed'}, 'desired.resource.'), 'only default')
    # A producer Export changing after packaging cannot redirect the preserved bucket expression.
    template.write_text(json.dumps(document))
    document["Resources"]["First"]["Properties"]["Code"]["S3Bucket"] = {"Fn::ImportValue": "AssetsBucket"}
    backend.templates["A"] = (document, {})
    backend.export_values = {"AssetsBucket": "app-dev-assets"}
    one = unit | {"artifacts": [artifact("First")]}
    blocked = {"status": "NOT_STARTED"}
    with patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
        assert backend.prepare(one, blocked) == "READY"
    backend.export_values["AssetsBucket"] = "other-bucket"
    rejects(lambda: backend.execute(one, blocked), "differs from the approved template")
    assert not any(op == "execute_change_set" for op, _ in backend.calls)

    # A small bootstrap stack can run before a later large template needs its bucket.
    bootstrap = DeliveryAws(root, base / "bootstrap.files")
    scoped = units(10, 20)
    scoped[0]["template"], scoped[1]["template"] = "bucket.yaml", "large.yaml"
    scoped[1].update(settings | {"templateBucket": "app-dev-assets"})
    for entry, size in zip(scoped, (20, 51201)):
        file, inputs = bootstrap.paths(entry)
        file.write_bytes(b" " * size)
        inputs.write_text("[]")
    with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
            patch.object(subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
        for entry in scoped:
            bootstrap.load_inputs(entry)
    assert not bootstrap.calls
    original_aws, bucket_created = bootstrap.aws, [False]
    def ordered_aws(operation, **kwargs):
        if kwargs.get("service") == "s3":
            assert bucket_created[0], "bucket used before producer completed"
        return original_aws(operation, **kwargs)
    bootstrap.aws = ordered_aws
    def complete(entry, state):
        if entry["name"] == "A":
            bucket_created[0] = True
        return "CREATE_COMPLETE"
    bootstrap.poll = complete
    session = states(scoped)
    assert scheduler.run_group(scoped, 1, session, bootstrap, sleep=lambda _: None) == "GROUP_COMPLETE"
    assert session["B"]["status"] == "NOT_STARTED" and not any(op == "put_object" for op, _ in bootstrap.calls)
    assert finish(scoped, 1, session, bootstrap) == "COMPLETE", session
    assert any(op == "put_object" for op, _ in bootstrap.calls)


def check_delivery_encryption(tmp_path):
    from deploy.s3_delivery import preflight, model_conditions, policy_conditions, ALGORITHM
    def policy(bucket, header, operator, value, prefix='templates/'):
        return {'Statement': [{'Effect': 'Deny', 'Principal': '*', 'Action': 's3:PutObject',
                'Resource': f'arn:aws:s3:::{bucket}/{prefix}*', 'Condition': {operator: {header: value}}}]}
    algorithm_header = 's3:x-amz-server-side-encryption'
    key_header = algorithm_header + '-aws-kms-key-id'
    base, bucket, prefix = tmp_path, 'app-dev-assets', 'templates/'
    def fresh():
        backend = DeliveryAws(base / 'repo', base / 'session.files')
        source = base / 'template.yaml'
        source.write_bytes(b' ' * 51201)
        return backend, source
    # Inactive resources never create S3 placement destinations.
    backend, source = fresh()
    document = {'Conditions': {'Skip': {'Fn::Equals': ['one', 'two']}}, 'Resources': {
        'Function': {'Condition': 'Skip', 'Type': 'AWS::Lambda::Function', 'Properties': {
            'Code': {'S3Bucket': bucket, 'S3Key': 'lambda/old.zip'}}}}}
    mapping = {'resource': 'Function', 'property': 'Code', 'bucket': bucket, 'keyPrefix': 'lambda/'}
    assert backend.artifact_bindings({'name': 'A', 'artifacts': [mapping]}, document, {}) == []
    # Explicit SSE-S3, conditional PutObject, reuse and encryption drift.
    backend, source = fresh()
    obj = backend.upload(source, bucket, prefix)
    request = next(args for op, args in backend.calls if op == 'put_object')
    assert request['ServerSideEncryption'] == 'AES256'
    assert '--ssekms-key-id' not in request
    assert backend.upload(source, bucket, prefix) == obj
    assert sum(op == 'put_object' for op, _ in backend.calls) == 1
    assert all(v['effectiveWritePermission'] == 'UNCONFIRMED' for v in backend.session['placementPreflight'].values())
    backend.objects[bucket, obj['key']]['ServerSideEncryption'] = 'aws:kms'
    rejects(lambda: backend.upload(source, bucket, prefix), 'existing object encryption')
    # Explicit SSE-KMS and exact header policy, with ARN normalization for default/key identity.
    backend, source = fresh()
    backend.default_algorithm, backend.default_key = 'aws:kms', 'test-key'
    backend.add_bucket(bucket, 'aws:kms', backend.key_arn)
    backend.policy = policy(bucket, key_header, 'StringNotEquals', backend.key_arn)
    obj = backend.upload(source, bucket, prefix)
    request = next(args for op, args in backend.calls if op == 'put_object')
    assert request['ServerSideEncryption'] == 'aws:kms'
    assert request['SSEKMSKeyId'] == backend.key_arn
    backend.objects[bucket, obj['key']]['SSEKMSKeyId'] = backend.key_arn.replace('test-key', 'another-key')
    rejects(lambda: backend.verify_object(obj), 'existing object KMS key')
    # Existing logical KMS Key/Alias and parent mapping; no generated ARN in model.
    path = backend.root / 'model/dev/123456789012/kms.properties'
    write_model(path, '\n'.join([
        'desired.resource.001.resourceType=KMS.Key', 'desired.resource.001.logicalId=KMS_Key_001', 'desired.resource.001.anchor=kms-app-dev-key', 'desired.service.identity.lastAllocated={"KMS.Key":1,"KMS.Alias":1}',
        'desired.row.001-001.property=KMS.Key.KeyId', 'desired.row.001-001.value=[KMS_Key_001](kms.md#kms-app-dev-key)', 'desired.row.001-001.comment=固定Key ID',
        'observed.row.001-001.value=test-key', 'desired.resource.002.resourceType=KMS.Alias',
        'desired.resource.002.logicalId=KMS_Alias_001', 'desired.resource.002.anchor=resource-KMS_Alias_001', 'desired.resource.002.parentReference=[KMS_Key_001](kms.md#kms-app-dev-key)',
        'desired.row.002-001.property=KMS.Alias.AliasName', 'desired.row.002-001.value=alias/test', 'desired.row.002-001.comment=固定Alias']))
    for reference in ('[KMS_Key_001](kms.md#kms-app-dev-key)', '[KMS_Alias_001](kms.md#resource-KMS_Alias_001)'):
        backend.add_bucket(bucket, 'aws:kms', reference)
        before = snapshot_model(path)
        assert model_conditions(backend, bucket)['requestKey'] == backend.key_arn
        assert snapshot_model(path) == before
    write_model(path, read_model(path).replace('observed.row.001-001.value=test-key', 'observed.row.001-001.value=other-key'))
    rejects(lambda: model_conditions(backend, bucket), 'approved parent')
    # Reading a cross-Alias reference never authorizes KMS retrieval in that target.
    foreign = path.parent.parent / 'other' / path.name
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(path.read_bytes())
    project = backend.root / 'project.json'
    topology = json.loads(project.read_text())
    topology['targets'].append({'environment': 'dev', 'alias': 'other', **TARGET})
    project.write_text(json.dumps(topology), encoding='utf-8')
    backend.add_bucket(bucket, 'aws:kms', '[KMS_Key_001](../other/kms.md#kms-app-dev-key)')
    calls = len(backend.calls)
    rejects(lambda: model_conditions(backend, bucket), 'outside authorized S3 placement retrieval scope')
    assert len(backend.calls) == calls
    # Approval is explicit; default delegation omits both headers, including for KMS defaults.
    for algorithm, key in (('AES256', None), ('aws:kms', 'test-key')):
        backend, source = fresh()
        backend.default_algorithm, backend.default_key = algorithm, key
        backend.add_bucket(bucket, algorithm, key, delegation=True)
        obj = backend.upload(source, bucket, prefix)
        request = next(args for op, args in backend.calls if op == 'put_object')
        assert '--server-side-encryption' not in request and '--ssekms-key-id' not in request
        assert obj['encryption']['mode'] == 'default'
    # Default delegation cannot satisfy a request-header mandate.
    backend, source = fresh()
    backend.add_bucket(bucket, delegation=True)
    backend.policy = policy(bucket, algorithm_header, 'StringNotEquals', 'AES256')
    rejects(lambda: backend.upload(source, bucket, prefix), 'policy denies')
    assert not any(op == 'put_object' for op, _ in backend.calls)
    # Scope, AND/Null/IfExists semantics and unknown clauses stay fail-closed.
    explicit = model_conditions(DeliveryAws(base / 'repo', base / 'other.files'), bucket)
    assert explicit['mode'] == 'explicit'
    policy_conditions(policy(bucket, algorithm_header, 'StringNotEquals', 'aws:kms', 'other/'), bucket, 'templates/key', explicit)
    policy_conditions(policy(bucket, algorithm_header, 'Null', 'true'), bucket, 'templates/key', explicit)
    rejects(lambda: policy_conditions(policy(bucket, key_header, 'StringNotEqualsIfExists', 'key'), bucket, 'templates/key', explicit), 'policy denies')
    unknown = policy(bucket, algorithm_header, 'StringEquals', 'AES256')
    unknown['Statement'][0]['Condition']['StringEquals']['aws:PrincipalArn'] = 'arn:*'
    rejects(lambda: policy_conditions(unknown, bucket, 'templates/key', explicit), 'INDETERMINATE')
    for modification in ({'Principal': {'AWS': TARGET['awsAccountId']}}, {'NotResource': '*'}):
        item = policy(bucket, algorithm_header, 'StringNotEquals', 'aws:kms')
        item['Statement'][0].update(modification)
        rejects(lambda: policy_conditions(item, bucket, 'templates/key', explicit), 'INDETERMINATE')
    item = policy(bucket, algorithm_header, 'StringEquals', '${aws:PrincipalTag/encryption}')
    rejects(lambda: policy_conditions(item, bucket, 'templates/key', explicit), 'INDETERMINATE')
    item = policy(bucket, algorithm_header + '-context', 'StringEquals', 'context')
    rejects(lambda: policy_conditions(item, bucket, 'templates/key', explicit), 'INDETERMINATE')
    # Unknown read failures and malformed responses remain distinct from design mismatches.
    backend, source = fresh()
    aws = backend.aws
    def unreadable(operation, **args):
        if operation == 'get_bucket_policy':
            raise TimeoutError('read timed out')
        return aws(operation, **args)
    backend.aws = unreadable
    rejects(lambda: backend.upload(source, bucket, prefix), 'READ_UNCONFIRMED')
    def malformed(operation, **args):
        if operation == 'get_bucket_encryption':
            return {'ServerSideEncryptionConfiguration': {'Rules': [{}]}}
        return aws(operation, **args)
    backend.aws = malformed
    rejects(lambda: backend.upload(source, bucket, prefix), 'INDETERMINATE')
    def missing_policy(operation, **args):
        if operation == 'get_bucket_policy':
            return {}
        return aws(operation, **args)
    backend.aws = missing_policy
    rejects(lambda: backend.upload(source, bucket, prefix), 'INDETERMINATE')
    rejects(lambda: policy_conditions({}, bucket, 'templates/key', explicit), 'INDETERMINATE')
    # Design/AWS differences, refused reads, missing/unsupported models and key state.
    for change, expected in ((lambda b: setattr(b, 'default_algorithm', 'aws:kms'), 'MISMATCH'),
                             (lambda b: setattr(b, 'region', 'us-east-1'), 'MISMATCH')):
        backend, source = fresh()
        change(backend)
        rejects(lambda: backend.upload(source, bucket, prefix), expected)
        assert not any(op == 'put_object' for op, _ in backend.calls)
    for operation in ('head_bucket', 'get_bucket_location', 'get_bucket_encryption', 'get_bucket_policy', 'describe_key'):
        backend, source = fresh()
        backend.add_bucket(bucket, 'aws:kms', 'test-key')
        backend.default_algorithm, backend.default_key = 'aws:kms', 'test-key'
        aws = backend.aws
        def denied(op, **args):
            if op == operation:
                raise __import__('utils.aws.client', fromlist=['AwsError']).AwsError('s3', operation, 'AccessDenied', 403)
            return aws(op, **args)
        backend.aws = denied
        rejects(lambda: backend.upload(source, bucket, prefix), 'READ_DENIED')
        assert not any(op == 'put_object' for op, _ in backend.calls)
    backend, source = fresh()
    backend.add_bucket(bucket, 'aws:kms', 'test-key')
    backend.default_algorithm, backend.default_key = 'aws:kms', 'other-key'
    rejects(lambda: backend.upload(source, bucket, prefix), 'default KMS key differs')
    backend.default_key, backend.key_state = 'test-key', 'Disabled'
    rejects(lambda: backend.upload(source, bucket, prefix), 'not Enabled')
    backend.key_state, backend.key_arn = 'Enabled', backend.key_arn.replace('ap-northeast-1', 'us-east-1')
    rejects(lambda: backend.upload(source, bucket, prefix), 'account/region')
    backend, source = fresh()
    backend.add_bucket(bucket, 'aws:kms:dsse')
    rejects(lambda: backend.upload(source, bucket, prefix), 'INDETERMINATE')
    backend.add_bucket(bucket, 'UNSET')
    rejects(lambda: backend.upload(source, bucket, prefix), 'unconfirmed')
    model = backend.root / 'model/dev/123456789012/s3.properties'
    remove_model(model)
    rejects(lambda: backend.upload(source, bucket, prefix), 'INDETERMINATE')
    # Session restart rechecks AWS policy/default/alias and never adopts changed conditions.
    backend, source = fresh()
    obj = backend.upload(source, bucket, prefix)
    session = json.loads(json.dumps(backend.session))
    resumed = DeliveryAws(backend.root, base / 'session.files')
    resumed.session, resumed.objects = session, backend.objects
    resumed.policy = {'Statement': [{'Effect': 'Allow', 'Principal': '*', 'Action': 's3:GetObject', 'Resource': '*'}]}
    rejects(lambda: resumed.verify_object(obj), 'CHANGED')
    assert not any(op == 'put_object' for op, _ in resumed.calls)
    resumed.policy, resumed.default_algorithm = None, 'aws:kms'
    rejects(lambda: resumed.verify_object(obj), 'MISMATCH')
    backend, source = fresh()
    backend.add_bucket(bucket, 'aws:kms', 'alias/test')
    backend.default_algorithm, backend.default_key = 'aws:kms', 'alias/test'
    obj = backend.upload(source, bucket, prefix)
    resumed = DeliveryAws(backend.root, base / 'session.files')
    resumed.add_bucket(bucket, 'aws:kms', 'alias/test')
    resumed.session, resumed.objects = json.loads(json.dumps(backend.session)), backend.objects
    resumed.default_algorithm, resumed.default_key = 'aws:kms', 'alias/test'
    resumed.key_arn = resumed.key_arn.replace('test-key', 'rotated-key')
    rejects(lambda: resumed.verify_object(obj), 'CHANGED')
    # Entire same-order delivery barrier precedes any change set even at concurrency 1.
    backend, source = fresh()
    scoped = units(10, 10)
    for unit in scoped:
        unit['template'] = unit['name'] + '.yaml'
        template, parameters = backend.paths(unit)
        template.parent.mkdir(parents=True, exist_ok=True)
        parameters.parent.mkdir(parents=True, exist_ok=True)
        template.write_bytes(b' ' * 51201 + unit['name'].encode())
        parameters.write_text('[]')
        unit.update(templateBucket=bucket, templateKeyPrefix=prefix)
        backend.templates[unit['name']] = ({'Resources': {}}, {})
    state = states(scoped)
    backend.poll = lambda *args: 'CREATE_COMPLETE'
    assert finish(scoped, 1, state, backend) == 'COMPLETE'
    put_indices = [i for i, (op, _) in enumerate(backend.calls) if op == 'put_object']
    assert len(put_indices) == 2
    assert max(put_indices) < next(i for i, (op, _) in enumerate(backend.calls) if op == 'create_change_set')
    # A later peer's actual placement refusal prevents all new stacks, preserving drain.
    backend.calls.clear()
    backend.uploaded, backend.objects = {}, {}
    state = states(scoped)
    aws, count = backend.aws, [0]
    def refuse_second(operation, **args):
        if operation == 'put_object':
            count[0] += 1
            if count[0] == 2:
                raise __import__('utils.aws.client', fromlist=['AwsError']).AwsError('s3', operation, 'AccessDenied', 403)
        return aws(operation, **args)
    backend.aws = refuse_second
    assert finish(scoped, 1, state, backend) == 'STOPPED'
    assert 'AccessDenied' in state['A']['reason']
    assert state['B']['status'] == 'NOT_STARTED'
    assert not any(op in {'create_change_set', 'execute_change_set'} for op, _ in backend.calls)
    backend.aws, backend.fail = aws, 'put_object'
    state = states(scoped)
    state['A']['status'] = 'RUNNING'
    assert finish(scoped, 1, state, backend) == 'STOPPED'
    assert state['A']['status'] == 'SUCCESS' and state['B']['status'] == 'BLOCKED'
    assert not any(op == 'execute_change_set' for op, _ in backend.calls)
    print('S3 delivery encryption/preflight checks: PASS (SSE-S3/KMS/default, model/key/policy/read/write/object/resume guards, group barrier/drain)')


def check_session_cli(tmp_path):
    """Exercise entrypoint, preflight, persisted groups, approvals and immutable inputs."""
    base = tmp_path
    root = (base / "repo").resolve()
    root.mkdir(parents=True)
    (root / "project.json").write_text(json.dumps({"targets": [{"environment": "dev", **TARGET, "awsProfile": "dev-profile"}, {"environment": "stg", **TARGET}]}))
    (root / "tasks").mkdir()
    contract = root / "tasks/example.md"
    contract.write_text("\n".join(["## Task contract", "- Task status: `running`", "- Task type: `infrastructure`", "- Infrastructure phase: `deploy`",
                                 "- AWS API execution: `allowed`", "- Deploy/apply: `allowed`",
                                 "- Target environment: `dev`", "- Target AWS account: `123456789012`",
                                 "- Deployment scope: `A`, `B`", "- Authorized delete/replacement: `none`", "## Modified files", "- `tasks/example.md`", "## Allowed paths", "- `tasks/example.md`", "## Validation scope", "- `all`"]))
    values = {"desired.deployment.maxConcurrentStacks": "2"}
    for i, unit in enumerate(units(10, 20), 1):
        values.update({f"desired.stack.{i:03}.{key}": value for key, value in unit.items()})
        values[f"display.stack.{i:03}.comment"] = "アプリケーションを配置するstack"
    source = root / "model/dev/123456789012/cloudformation-stacks.properties"
    source.parent.mkdir(parents=True)
    write_model(source, "\n".join(f"{key}={value}" for key, value in values.items()))
    design = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
    design.parent.mkdir(parents=True)
    design.write_text(markdown_for(design, values, root))
    template = root / "infra/cloudformation/templates/app.yaml"
    template.parent.mkdir(parents=True)
    template.write_text("Resources: {}\n")
    params = root / "infra/cloudformation/parameters/dev/123456789012"
    params.mkdir(parents=True)
    for name in ("a", "b"):
        (params / (name + ".json")).write_text("[]\n")
    consumer = source.with_name("consumer.properties")
    reference = root / "model/stg/123456789012/reference.properties"
    reference.parent.mkdir(parents=True)
    write_model(reference, 'desired.resource.001.resourceType=Logs.LogGroup\ndesired.resource.001.logicalId=Logs_LogGroup_001\ndesired.resource.001.anchor=resource-Logs_LogGroup_001\ndesired.service.identity.lastAllocated={"Logs.LogGroup":1}\ndesired.row.001-001.property=Logs.LogGroup.LogGroupName\ndesired.row.001-001.value=approved\ndesired.row.001-001.comment=参照先\n')
    write_model(consumer, 'desired.resource.001.resourceType=Logs.LogGroup\ndesired.resource.001.logicalId=Logs_LogGroup_001\ndesired.resource.001.anchor=resource-Logs_LogGroup_001\ndesired.service.identity.lastAllocated={"Logs.LogGroup":1}\ndesired.row.001-001.property=Logs.LogGroup.LogGroupName\ndesired.row.001-001.value=[Logs_LogGroup_001](../../stg/123456789012/reference.md#resource-Logs_LogGroup_001)\ndesired.row.001-001.comment=参照する名前\n')
    stg_source = root / "model/stg/123456789012/cloudformation-stacks.properties"
    stg_source.parent.mkdir(parents=True, exist_ok=True)
    write_model(stg_source, read_model(source))
    stg_design = root / "docs/designs/stg/123456789012/cloudformation-stacks.md"
    stg_design.parent.mkdir(parents=True)
    stg_design.write_text(markdown_for(stg_design, values, root))
    state_file = base / "session.json"
    argv = ["--environment", "dev", "--aws-account-id", "123456789012", "--stack", "A", "--stack", "B", "--state", str(state_file), "--timing-log", str(base / "timing.jsonl")]
    backends, validation_calls = [], []
    destructive = [True]
    runtime_resume, recovered = [False], []
    def backend_factory(root, environment, tmp_path, target, profile, approvals):
        assert target["awsProfile"] == "dev-profile"
        backend = StubAws(destructive=destructive[0])
        if destructive[0]:
            # This scheduler/session fixture has no model; approval uses replacement.
            backend.change["Changes"][0]["ResourceChange"].update(Action="Modify", Replacement="True")
        backend.root, backend.approvals = root, set(approvals)
        backend.target, backend.profile = target, target.get("awsProfile") or profile
        def validate(unit):
            validation_calls.append(unit["name"])
            backend.templates.update({unit["name"]: ({}, {})})
        backend.validate = validate
        backend.load_inputs = lambda unit: backend.templates.update({unit["name"]: ({}, {})})
        backend.poll = lambda *args: "CREATE_COMPLETE"
        if runtime_resume[0]:
            def repair(unit, state):
                recovered.append((unit['name'], state['repairs'][-1]['clientRequestToken']))
                state['repairs'][-1]['stage'] = 'RETRY_READY'
                return True
            backend.repair = repair
        backends.append(backend)
        return backend
    session_runner = M.session_ops.run_session
    execution_limits = []
    mutation = [None]
    def run_session(*args):
        execution_limits.append(args[1])
        if mutation[0]:
            mutation[0]()
        args[3].guard()
        return session_runner(*args, sleep=lambda _: None)
    last_output = []
    def invoke(options=()):
        def subprocess_result(command, **kwargs):
            return SimpleNamespace(returncode=0, stdout='{"Account":"123456789012"}' if "get-caller-identity" in command else "", stderr="")
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors_output, \
                patch.object(M, "create_runtime", side_effect=backend_factory), \
                patch("deploy.context.get_caller_identity", return_value={"Account": "123456789012"}) as sts, \
                patch.object(subprocess, "run", side_effect=subprocess_result) as run, \
                patch.object(M.session_ops, "run_session", side_effect=run_session), \
                patch.object(Path, "cwd", return_value=base if options else root):
            result = M.main(argv + list(options), **({"root": root} if options else {}))
            if not state_file.exists() and "other" not in options:
                assert False, output.getvalue() + errors_output.getvalue()
            assert sts.call_count == 0 if 'other' in options else sts.call_count <= 1
            last_output.append(output.getvalue() + errors_output.getvalue())
            return result
    assert invoke(["--profile", "other"]) == 2
    assert not backends
    timing = [json.loads(line) for line in (base / "timing.jsonl").read_text().splitlines()]
    assert any(event["phase"] == "authenticationContext" and event["result"] == "FAIL" for event in timing)
    assert timing[-1]["phase"] == "controller" and timing[-1]["result"] == "FAIL"
    # Ordinary startup has no whole-scope mapping or static validation permission.
    with patch('model.adapters.observed.mappings', side_effect=AssertionError('startup mapping forbidden')):
        assert invoke() == 2
    session = json.loads(state_file.read_text())
    assert 'lintSeconds' not in session['metrics'] and 'validationStatus' not in session
    assert session["states"]["A"]["status"] == "BLOCKED", (session, last_output[-1])
    assert session["states"]["B"]["status"] == "NOT_STARTED"
    assert invoke(["--resume", "--approve-change-set", "cs-A"]) == 2
    session = json.loads(state_file.read_text())
    assert session["result"] == "STOPPED" and session["states"]["A"]["status"] == "SUCCESS"
    assert [args["StackName"] for op, args in backends[-1].calls if op == "create_change_set"] == ["B"], last_output[-1]
    assert invoke(["--resume"]) == 2
    session = json.loads(state_file.read_text())
    assert session["states"]["B"]["status"] == "BLOCKED", session
    assert invoke(["--resume", "--approve-change-set", "cs-B"]) == 0, last_output[-1]
    assert invoke(["--resume"]) == 0
    assert "validationCount" not in session["metrics"] and not validation_calls
    assert not backends[-1].calls  # Completed run never redeploys successful stacks.
    # A/B: unrelated environment bytes (even invalid JSON) are absent from guards/resume.
    unrelated = root / "infra/cloudformation/parameters/stg/123456789012/other.json"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("invalid JSON\n")
    assert invoke(["--resume"]) == 0
    assert set(json.loads(state_file.read_text())["infraManifest"]) == {
        p.relative_to(root).as_posix() for p in backends[-1].deployment_input_paths(units(10, 20))}
    # Older broad manifests are narrowed on resume without changing unit digests.
    legacy = json.loads(state_file.read_text())
    legacy["infraManifest"][unrelated.relative_to(root).as_posix()] = "old unrelated digest"
    state_file.write_text(json.dumps(legacy))
    assert invoke(["--resume"]) == 0
    mutation[0] = lambda: unrelated.write_text("other invalid JSON\n")
    assert invoke(["--resume"]) == 0
    mutation[0] = None
    # C/D/E/H/I and model/contract guards run after validation, immediately before mutation.
    assert M.load_units(root, "stg", "123456789012", ["A"])[1][0]["template"] == "app.yaml"
    for path, text in ((params / "a.json", '[{"ParameterKey":"Name","ParameterValue":"changed"}]'),
                       (template, "Resources: {}\n# shared dev/stg template changed\n"),
                       (source, read_model(source) + "display.deployment.comment=changed\n"),
                       (consumer, read_model(consumer) + "desired.row.002.value=changed\n"),
                       (reference, "desired.row.001.value=changed\n"),
                       (contract, contract.read_text() + "\n# contract changed\n")):
        canonical = path.suffix == '.properties' and path.is_relative_to(root / 'model')
        before = path.read_bytes()
        if canonical:
            text = before.decode()+"# canonical input changed\n"
        mutation[0] = lambda path=path, text=text: path.write_text(text)
        assert invoke(["--resume"]) == 2, path
        path.write_bytes(before)
        mutation[0] = None
        assert invoke(["--resume"]) == 0
    project = root / "project.json"
    before = project.read_bytes()
    for key, value in (("awsAccountId", "999999999999"), ("awsRegion", "us-east-1"),
                       ("awsProfile", "other-profile"), ("iacEngine", "terraform")):
        changed = json.loads(before)
        changed["targets"][0][key] = value
        mutation[0] = lambda changed=changed: project.write_text(json.dumps(changed))
        assert invoke(["--resume"]) == 2, key
        mutation[0] = None
        project.write_bytes(before)
    assert invoke(["--resume"]) == 0
    # Declared artifact bytes join the same controller manifest and mutation guard.
    saved_source, saved_design = snapshot_model(source), design.read_bytes()
    saved_state, saved_argv = state_file, argv[:]
    artifact_source = root / "infra/cloudformation/artifacts/job.py"
    artifact_source.parent.mkdir(parents=True)
    artifact_source.write_text("print('approved')\n")
    bucket_model = source.with_name("s3.properties")
    write_model(bucket_model, 'desired.resource.001.resourceType=S3.Bucket\ndesired.resource.001.logicalId=S3_Bucket_001\ndesired.resource.001.anchor=resource-S3_Bucket_001\ndesired.service.identity.lastAllocated={"S3.Bucket":1}\ndesired.row.001-001.property=S3.Bucket.BucketName\ndesired.row.001-001.value=`assets`\ndesired.row.001-001.comment=配布先bucket\n')
    artifact = {"stack": "A", "resource": "Job", "property": "Command.ScriptLocation",
                "source": artifact_source.relative_to(root).as_posix(), "bucket": "[S3_Bucket_001](s3.md#resource-S3_Bucket_001)", "keyPrefix": "jobs/"}
    with_artifact = values | {"desired.artifact.001." + key: value for key, value in artifact.items()}
    write_model(source, "\n".join(f"{key}={value}" for key, value in with_artifact.items()))
    design.write_text(markdown_for(design, with_artifact, root))
    state_file = base / "artifact.json"
    argv[argv.index("--state") + 1] = str(state_file)
    assert invoke() == 2  # Exact replacement approval still blocks the stub change set.
    assert artifact_source.relative_to(root).as_posix() in json.loads(state_file.read_text())["infraManifest"]
    mutation[0] = lambda: artifact_source.write_text("print('changed')\n")
    assert invoke(["--resume"]) == 2
    mutation[0] = None
    assert invoke(["--resume"]) == 2  # Resume also rejects changed target artifact bytes.
    for file,data in saved_source.items():file.write_bytes(data)
    design.write_bytes(saved_design)
    remove_model(bucket_model)
    state_file, argv = saved_state, saved_argv
    print("Deployment input isolation: PASS (A/B unrelated invalid stg guard/resume; C/D/E target/shared; artifact guard/resume; H framework; I target account/region/profile/engine; target/reference model/contract guards)")
    assert invoke(["--resume", "--approve-change-set", "cs-A"]) == 2
    template.write_text("Resources: {Changed: {}}\n")
    assert invoke(["--resume"]) == 2
    template.write_text("Resources: {}\n")
    contract.write_text(contract.read_text().replace("`infrastructure`", "`governance`"))
    assert invoke(["--resume"]) == 2

    # Cases 1/2/3: one invocation, one whole-scope validation, all barriers inside it.
    contract.write_text(contract.read_text().replace("`governance`", "`infrastructure`"))
    destructive[0] = False
    for orders, limit in (((10,), 1), ((10,) * 4, 4), ((10,) * 4 + (20,) * 4, 4)):
        selected = units(*orders)
        values = {"desired.deployment.maxConcurrentStacks": str(limit)}
        for number, unit in enumerate(selected, 1):
            values.update({f"desired.stack.{number:03}.{key}": value for key, value in unit.items()})
            values[f"display.stack.{number:03}.comment"] = "実行するstack"
            (params / unit["parameters"]).write_text("[]\n")
        write_model(source, "\n".join(f"{key}={value}" for key, value in values.items()))
        design.write_text(markdown_for(design, values, root))
        contract.write_text(contract.read_text().replace(next(l for l in contract.read_text().splitlines() if l.startswith("- Deployment scope:")),
                                                       "- Deployment scope: " + ", ".join("`" + u["name"] + "`" for u in selected)))
        state_file = base / f"success-{len(orders)}.json"
        argv = ["--environment", "dev", "--aws-account-id", "123456789012", "--state", str(state_file)]
        for unit in selected:
            argv += ["--stack", unit["name"]]
        assert invoke() == 0
        session = json.loads(state_file.read_text())
        assert session["result"] == "COMPLETE", session
        assert session["metrics"]["controllerInvocationCount"] == 1 and "validationCount" not in session["metrics"]
        assert session["metrics"]["deployOrderCount"] == len(set(orders))
        assert all(s["status"] == "SUCCESS" and s["observedSynced"] for s in session["states"].values())
        assert not any(op == "list-stacks" for op, _ in backends[-1].calls)
        assert invoke(["--resume"]) == 0 and not backends[-1].calls
        assert "validationCount" not in json.loads(state_file.read_text())["metrics"]
        # CLI resume dispatches the persisted bootstrap intent with the same token.
        session = json.loads(state_file.read_text())
        session['states']['A']['repairs'] = [{'classification': 'RUNTIME_BOOTSTRAP',
            'stage': 'BOOTSTRAP_INTENT', 'clientRequestToken': 'stable-bootstrap-token'}]
        state_file.write_text(json.dumps(session))
        runtime_resume[0] = True
        before = len(recovered)
        assert invoke(['--resume']) == 0 and recovered[before:] == [('A', 'stable-bootstrap-token')]
        assert not backends[-1].calls
        runtime_resume[0] = False
        # Project instructions remain part of the validation input boundary.
        instructions = root / "AGENTS.md"
        original_instructions = instructions.read_bytes() if instructions.exists() else None
        instructions.write_text("validation input " + str(len(orders)))
        prior = json.loads(state_file.read_text())["executionDigest"]
        assert invoke(["--resume"]) == 2 and not backends[-1].calls
        assert json.loads(state_file.read_text())["executionDigest"] == prior
        if original_instructions is None:
            instructions.unlink()
        else:
            instructions.write_bytes(original_instructions)
        if limit == 4:
            # Sequential is a session cap, not a design edit or per-stack invocation.
            state_file = base / f"sequential-{len(orders)}.json"
            argv[argv.index("--state") + 1] = str(state_file)
            before = snapshot_model(source)
            assert invoke(["--sequential"]) == 0 and execution_limits[-1] == 1
            assert snapshot_model(source) == before
            assert json.loads(state_file.read_text())["result"] == "COMPLETE"
            assert invoke(["--resume", "--sequential"]) == 0 and not backends[-1].calls
            assert invoke(["--resume"]) == 2  # Resume cannot expand the saved cap.
    # Explicit update handoff retains the older producer/consumer editing contract.
    contract.write_text(contract.read_text().replace("Infrastructure phase: `deploy`", "Infrastructure phase: `update`"))
    state_file = base / "update-handoff.json"
    argv[argv.index("--state") + 1] = str(state_file)
    assert invoke(["--pause-after-group"]) == 0
    session = json.loads(state_file.read_text())
    assert session["result"] == "GROUP_COMPLETE"
    assert all(session["states"][u["name"]]["observedSynced"] for u in selected[:4])
    pending = params / selected[4]["parameters"]
    pending.write_text('[{"ParameterKey":"Environment","ParameterValue":"dev"}]')
    assert invoke(["--resume", "--pause-after-group"]) == 0
    session = json.loads(state_file.read_text())
    assert session["result"] == "COMPLETE" and "validationCount" not in session["metrics"]
    prepared = params / selected[0]["parameters"]
    prepared.write_text('[{"ParameterKey":"Changed","ParameterValue":"value"}]')
    assert invoke(["--resume"]) == 2


def check_parallel_and_restart():
    scoped = units(10, 10, 10, 10, 20, 20, 20, 20)
    sequential = Fake({"B": ["CREATE_FAILED"]})
    saved = {"states": states(scoped), "metrics": {"observedSyncSeconds": 0}}
    with patch.object(M.session_ops, "sync_successful"):
        assert M.session_ops.run_session(scoped, 1, saved, sequential, lambda: None, sleep=lambda _: None) == "STOPPED"
    assert sequential.peak == 1 and starts(sequential) == ["A", "B"]
    assert all(saved["states"][u["name"]]["status"] == "NOT_STARTED" for u in scoped[2:])
    state = states(scoped)
    backend = Fake()
    # Polls actually overlap. A barrier fails deterministically if they become serial.
    barrier = Barrier(4, timeout=3)
    poll = backend.poll
    def parallel_poll(unit, snapshot):
        barrier.wait()
        return poll(unit, snapshot)
    backend.poll = parallel_poll
    synced = []
    def sync(backend, selected, saved):
        synced.append([u["name"] for u in selected])
        for unit in selected:
            saved[unit["name"]]["observedSynced"] = True
    session = {"states": state, "metrics": {"observedSyncSeconds": 0}}
    with patch.object(M.session_ops, "sync_successful", side_effect=sync):
        assert M.session_ops.run_session(scoped, 4, session, backend, lambda: None, sleep=lambda _: None) == "COMPLETE"
    assert backend.peak == 4 and synced == [["A", "B", "C", "D"], ["E", "F", "G", "H"]]
    assert session["metrics"]["deployOrderCount"] == 2
    assert starts(backend) == [u["name"] for u in scoped]
    first_poll = next(i for i, e in enumerate(backend.events) if e[0] == "poll")
    assert sum(e[0] == "start" for e in backend.events[:first_poll]) == 4

    # Nonblocking production preparation creates all change sets before the first wait.
    backend = StubAws()
    selected = scoped[:4]
    backend.templates = {u["name"]: ({}, {}) for u in selected}
    state = states(selected)
    poll_barrier, review_barrier = Barrier(4, timeout=3), Barrier(4, timeout=3)
    review = backend.describe_change_set
    def parallel_review(unit, snapshot):
        assert sum(op == "create_change_set" for op, _ in backend.calls) == 4
        if snapshot["status"] == "CHANGESET_CREATING":
            review_barrier.wait()
        return review(unit, snapshot)
    backend.describe_change_set = parallel_review
    controller_thread, classify = get_ident(), backend.review_prepared
    def controller_review(unit, snapshot, change_set=None):
        assert get_ident() == controller_thread, "approval decision escaped controller thread"
        return classify(unit, snapshot, change_set)
    backend.review_prepared = controller_review
    def stack_poll(unit, snapshot):
        poll_barrier.wait()
        return "CREATE_COMPLETE"
    backend.poll = stack_poll
    assert scheduler.run_group(selected, 4, state, backend, sleep=lambda _: None) == "GROUP_COMPLETE"
    assert sum(op == "execute_change_set" for op, _ in backend.calls) == 4

    # Interruption after submitting one stack, while its peer is prepared but unexecuted.
    selected = units(10, 10)
    state, backend = states(selected), Fake()
    execute = backend.execute
    def interrupted(unit, snapshot):
        execute(unit, snapshot)
        raise KeyboardInterrupt()
    backend.execute = interrupted
    with pytest.raises(KeyboardInterrupt):
        scheduler.run_group(selected, 2, state, backend, sleep=lambda _: None)
    assert state["A"]["status"] == "RUNNING" and state["B"]["status"] == "READY"
    backend.execute = execute
    assert finish(selected, 2, state, backend) == "COMPLETE"
    assert starts(backend) == ["A", "B"]  # A was polled, never redeployed.

    # Observed failure during restart also drains peers; it never leaves a RUNNING stack unobserved.
    state = {"A": {"status": "SUCCESS"}, "B": {"status": "RUNNING"}}
    backend = Fake({"B": ["CREATE_IN_PROGRESS", "CREATE_COMPLETE"]})
    backend.running = {"B"}
    session = {"states": state, "metrics": {"observedSyncSeconds": 0}}
    with patch.object(M.session_ops, "sync_successful", side_effect=ValueError("AMBIGUOUS_OBSERVED_MAPPING")):
        assert M.session_ops.run_session(selected, 2, session, backend, lambda: None, sleep=lambda _: None) == "STOPPED"
    assert state["B"]["status"] == "SUCCESS" and not backend.running and not starts(backend)
    assert session["observedError"] == "AMBIGUOUS_OBSERVED_MAPPING"


def check_api_timing(tmp_path):
    from deploy.timing import Timing
    from utils.aws import cloudformation as cfn
    from utils.aws.client import AwsError
    path = tmp_path / 'timing.jsonl'
    backend = Runtime(ROOT, 'dev', '123456789012', TARGET)
    backend.timing = Timing(ROOT, path)
    with patch.object(cfn, 'describe_stacks', return_value={'Stacks': []}):
        assert backend.aws('describe_stacks', StackName='private-stack') == {'Stacks': []}
    with patch.object(cfn, 'describe_stacks', side_effect=AwsError('cloudformation', 'describe_stacks', 'ReadTimeoutError')):
        with pytest.raises(M.Blocked): backend.aws('describe_stacks', StackName='private-stack')
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert [e['result'] for e in events] == ['PASS', 'FAIL']
    assert all(e['phase'] == 'awsApi' and e['seconds'] >= 0 for e in events)
    assert 'private-stack' not in path.read_text() and 'Stacks' not in path.read_text()


def check_controlled_repair(tmp_path):
    """Ten requested failure cases use real projection/edit/repair/scheduler/approval code."""
    from deploy.contracts import repair_changes, task_digest
    from cloudformation_inputs import load_template_inputs
    from support import model_design_fixtures as helpers
    base = tmp_path
    root = (base / 'repo').resolve()
    root.mkdir()
    (root / 'project.json').write_text(json.dumps({'targets': [{'environment': 'dev', **TARGET}]}))
    modeldir = root / 'model/dev/123456789012'
    modeldir.mkdir(parents=True)
    unit = {'name': 'A', 'template': 'a.yaml', 'parameters': 'a.json', 'deployOrder': '1'}
    following = dict(unit, name='B', template='b.yaml', parameters='b.json', deployOrder='2')
    scoped = [unit, following]
    values = {f'desired.stack.{i:03d}.{key}': value for i, u in enumerate(scoped, 1) for key, value in u.items()}
    for i in (1, 2):
        values[f'display.stack.{i:03d}.comment'] = '対象stack'
    write_model(modeldir / 'cloudformation-stacks.properties', helpers.text(values))
    template = root / 'infra/cloudformation/templates/a.yaml'
    template.parent.mkdir(parents=True)
    template.with_name('b.yaml').write_text('Resources: {}\n')
    parameters = root / 'infra/cloudformation/parameters/dev/123456789012'
    parameters.mkdir(parents=True)
    for key in ('a', 'b'):
        (parameters / (key + '.json')).write_text('[]\n')
    task = root / 'tasks/example.md'
    task.parent.mkdir(exist_ok=True)
    state_path = base / 'session.json'
    source_path = modeldir / 'ec2.properties'
    def configure(service, kind, rows, text, reason, *, create=False, repeated=False, destructive=False):
        for key in ('a', 'b'):
            (parameters / (key + '.json')).write_text('[]\n')
        template.with_name('b.yaml').write_text('Resources: {}\n')
        for i, u in enumerate(scoped, 1):
            values[f'desired.stack.{i:03d}.deployOrder'] = u['deployOrder']
        write_model(modeldir / 'cloudformation-stacks.properties', helpers.text(values))
        for path in modeldir.glob('*.properties'):
            if path.name != 'cloudformation-stacks.properties':
                path.unlink()
        resource = helpers.model(service, kind, 'app-dev-item', rows, 'Item')
        resource['desired.resource.001.cfn-logicalId'] = 'A-Item'
        modelpath = modeldir / (service + '.properties')
        write_model(modelpath, helpers.text(resource))
        template.write_text(text)
        relative = template.relative_to(root).as_posix()
        contract = '\n'.join(['## Task contract', '- Task type: `infrastructure`', '- Task status: `running`',
            '- Infrastructure phase: `deploy`', '- Controlled repair: `allowed`',
            f'- Deploy repair session: `{state_path}`', '## Validation scope', f'- `dev/123456789012/{service}`',
            '## Modified files', '- `tasks/example.md`', f'- `{relative}`',
            '## Allowed paths', '- `tasks/example.md`', f'- `{relative}`'])
        task.write_text(contract)
        backend = Runtime(root, 'dev', '123456789012', TARGET)
        session = {'states': states(scoped), 'metrics': {'observedSyncSeconds': 0},
                   'repository': str(root), 'taskFile': 'tasks/example.md', 'taskDigest': task_digest(contract),
                   'infraManifest': {p.relative_to(root).as_posix(): backend.file_digest(p) for p in backend.deployment_input_paths(scoped)},
                   'unitDigests': {u['name']: backend.input_digest(u) for u in scoped}}
        backend.session, backend.states = session, session['states']
        backend.expected_digests = session['unitDigests']
        backend.workdir = base / 'files'
        calls, executions, validations = [], [], []
        current = {'A': None if create else 'UPDATE_COMPLETE', 'B': None}
        stackid = {name: f'arn:aws:cloudformation:ap-northeast-1:123456789012:stack/{name}/session-unique' for name in ('A', 'B')}
        changes, tokens = {}, {}
        def aws(operation, **args):
            calls.append((operation, args))
            if operation in {'delete_stack', 'execute_change_set', 'create_change_set'}:
                backend.guard()
            if 'StackName' in args:
                name = args['StackName']
                name = name.split(':stack/')[-1].split('/')[0]
            else:
                name = 'A'
            if operation == 'describe_stacks':
                if current[name] is None:
                    raise M.Blocked('stack does not exist')
                return {'Stacks': [{'StackStatus': current[name], 'StackId': stackid[name]}]}
            if operation == 'list_stack_resources':
                return {'StackResourceSummaries': []}
            if operation == 'create_change_set':
                key = args['ChangeSetName']
                changes[name] = key
                return {'Id': key, 'StackId': stackid[name]}
            if operation == 'describe_change_set':
                replacement = destructive and executions.count('A') >= 1 and name == 'A'
                return {'Status': 'CREATE_COMPLETE', 'ExecutionStatus': 'AVAILABLE', 'ChangeSetId': args['ChangeSetName'], 'StackId': stackid[name], 'Changes': [{'ResourceChange': {
                    'LogicalResourceId': 'Item', 'ResourceType': 'AWS::' + kind.replace('.', '::'),
                    'Action': 'Modify' if replacement else 'Add', 'Replacement': 'True' if replacement else 'False'}}]}
            if operation == 'execute_change_set':
                executions.append(name)
                tokens[name] = args['ClientRequestToken']
                failed = name == 'A' and (executions.count('A') == 1 or repeated)
                current[name] = ('ROLLBACK_COMPLETE' if create else 'UPDATE_ROLLBACK_COMPLETE') if failed else 'CREATE_COMPLETE'
                return {}
            if operation == 'describe_stack_events':
                events = [{'ResourceType': 'AWS::CloudFormation::Stack', 'ClientRequestToken': tokens[name],
                           'ResourceStatus': current[name], 'StackId': stackid[name]}]
                if 'ROLLBACK' in current[name]:
                    events.append({'ResourceType': 'AWS::' + kind.replace('.', '::'), 'LogicalResourceId': 'Item',
                                   'ResourceStatus': 'CREATE_FAILED', 'ResourceStatusReason': reason,
                                   'ClientRequestToken': tokens[name]})
                return {'StackEvents': events}
            if operation == 'delete_stack':
                assert args['StackName'] == stackid['A']
                current['A'] = None
            return {}
        backend.aws = aws
        def guard():
            manifest = {p.relative_to(root).as_posix(): backend.file_digest(p) for p in backend.deployment_input_paths(scoped)}
            if manifest != session['infraManifest']:
                raise M.Blocked('unauthorized IaC change outside controlled repair')
            if any(backend.input_digest(u) != session['unitDigests'][u['name']] for u in scoped):
                raise M.Blocked('unit digest changed')
        backend.guard = guard
        def save():
            state_path.write_text(json.dumps(session))
        def validate(u):
            validations.append(u['name'])
            repair_changes(root, task.read_text(), {session['states'][u['name']]['repairs'][-1]['path']})
            backend.load_inputs(u)
            M.repair_ops.verify_repair(root, "dev", "123456789012", TARGET, backend.templates, u, session["states"][u["name"]])
            assert backend.input_digest(u) == session['unitDigests'][u['name']]
        backend.refresh_validation, backend.save = validate, save
        backend.load_inputs(unit)
        backend.load_inputs(following)
        backend.validated_digests = dict(session['unitDigests'])
        save()
        def run():
            def synced(_backend, items, saved):
                for item in items:
                    saved[item['name']]['observedSynced'] = True
            with patch.object(M.session_ops, 'sync_successful', side_effect=synced):
                return M.session_ops.run_session(scoped, 2, session, backend, save, sleep=lambda _: None)
        return backend, session, calls, executions, validations, run
    vpc = 'Resources:\n  Item:\n    Type: AWS::EC2::VPC\n    Properties:\n      EnableDnsSupport: true\n'
    # Case 1: an omitted typed model property is inserted, validated and retried.
    backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
        [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
    before = template.read_text()
    assert run() == 'COMPLETE', session
    assert executed == ['A', 'A', 'B'] and validated == ['A']
    assert 'EnableDnsSupport: true' in template.read_text() and 'CidrBlock: 10.0.0.0/16' in template.read_text()
    history = session['states']['A']['repairs']
    assert history[0]['classification'] == 'AUTO_REPAIRABLE' and history[0]['oldDigest'] != history[0]['newDigest']
    assert len({args['ChangeSetName'] for op, args in calls if op == 'create_change_set' and args["StackName"] == 'A'}) == 2
    # Real task validator consumes session evidence, rejects arbitrary extra changes.
    spec = importlib.util.spec_from_file_location('repair_task_validator', (Path(__file__).resolve().parents[2] / 'validate-blueprint.py'))
    vm = importlib.util.module_from_spec(spec); spec.loader.exec_module(vm)
    validator = vm.Validator(root); validator.task_type = 'infrastructure'; validator.infrastructure_phase = 'deploy'
    validator.changed_paths = {'infra/cloudformation/templates/a.yaml', 'tasks/example.md'}
    validator.check_task_type_requirements(); assert not validator.errors, validator.errors
    template.write_text(template.read_text() + '# unauthorized\n')
    validator.check_task_type_requirements(); assert validator.errors
    # Case 2: stale Subnet resolves from explicit CREATE identity, failed shell cleanup by StackId.
    lambda_text = '''Resources:
  Subnet:
    Type: AWS::EC2::Subnet
    Properties:
      VpcId: vpc-12345678
      CidrBlock: 10.0.0.0/24

  Item:
    Type: AWS::Lambda::Function
    Properties:
      Code:
        ZipFile: 'def handler(event, context): return 1'
      Runtime: python3.12
      Handler: index.handler
      Role: arn:aws:iam::123456789012:role/app-dev-role
      VpcConfig:
        SubnetIds: [subnet-0521f67350b825ab6]
        SecurityGroupIds: [sg-12345678]
'''
    backend, session, calls, executed, validated, run = configure('lambda', 'Lambda.Function',
        [('VpcConfig.SubnetIds', '[EC2_Subnet_001](ec2.md#ec2-app-dev-subnet)', 'subnet')], lambda_text, 'SubnetNotFound subnet-0521f67350b825ab6', create=True)
    subnet = helpers.model('ec2', 'EC2.Subnet', 'app-dev-subnet', [('SubnetId', '[EC2_Subnet_001](ec2.md#ec2-app-dev-subnet)', 'ID')], 'Subnet')
    subnet['desired.resource.001.cfn-logicalId'] = 'A-Subnet'
    write_model(source_path, helpers.text(subnet))
    task.write_text(task.read_text().replace('## Modified files', '- `dev/123456789012/ec2`\n## Modified files'))
    session['taskDigest'] = task_digest(task.read_text()); backend.save()
    assert run() == 'COMPLETE', session
    assert executed == ['A', 'A', 'B'] and any(op == 'delete_stack' for op, _ in calls)
    assert '!Ref' in template.read_text() and 'Subnet' in template.read_text()
    assert session['states']['A']['cleanupStatus'] == 'DELETE_COMPLETE'
    # A nonfailing external Role expression does not force consultation for a known Subnet repair.
    lambda_with_import = lambda_text.replace('Role: arn:aws:iam::123456789012:role/app-dev-role', 'Role: !ImportValue RoleArn')
    backend, session, calls, executed, validated, run = configure('lambda', 'Lambda.Function',
        [('VpcConfig.SubnetIds', '[EC2_Subnet_001](ec2.md#ec2-app-dev-subnet)', 'subnet'),
         ('Role', '[IAM_Role_001](iam.md#iam-app-dev-role)', 'role')], lambda_with_import, 'SubnetNotFound old subnet')
    write_model(source_path, helpers.text(subnet))
    role = helpers.model('iam', 'IAM.Role', 'app-dev-role', [('RoleName', '`app-dev-role`', '名前')], 'Role')
    role['desired.resource.001.cfn-logicalId'] = 'B-Role'
    write_model(modeldir / 'iam.properties', helpers.text(role))
    task.write_text(task.read_text().replace('## Modified files', '- `dev/123456789012/ec2`\n- `dev/123456789012/iam`\n## Modified files'))
    session['taskDigest'] = task_digest(task.read_text()); backend.save()
    event_subnet = {'LogicalResourceId': 'Item', 'ResourceType': 'AWS::Lambda::Function',
                    'ResourceStatus': 'CREATE_FAILED', 'ResourceStatusReason': 'SubnetNotFound old subnet'}
    state = session['states']['A']; state.update(status='FAILED', stackStatus='UPDATE_ROLLBACK_COMPLETE', failureEvents=[event_subnet])
    assert backend.repair(unit, state), state
    assert 'Role: !ImportValue RoleArn' in template.read_text()
    # Cross-stack Subnet correction confirms the existing actual Export expression and owner.
    external_lambda = 'Resources:\n  Item:' + lambda_text.split('\n  Item:', 1)[1]
    backend, session, calls, executed, validated, run = configure('lambda', 'Lambda.Function',
        [('VpcConfig.SubnetIds', '[EC2_Subnet_001](ec2.md#ec2-app-dev-subnet)', 'subnet')], external_lambda, 'SubnetNotFound old subnet')
    subnet['desired.resource.001.cfn-logicalId'] = 'B-Subnet'
    write_model(source_path, helpers.text(subnet))
    producer = {'Resources': {'Subnet': {'Type': 'AWS::EC2::Subnet', 'Properties': {'VpcId': 'vpc-12345678', 'CidrBlock': '10.0.0.0/24'}}},
                'Outputs': {'SubnetId': {'Value': {'Ref': 'Subnet'}, 'Export': {'Name': 'SubnetExport'}}}}
    template.with_name('b.yaml').write_text(json.dumps(producer))
    task.write_text(task.read_text().replace('## Modified files', '- `dev/123456789012/ec2`\n## Modified files'))
    session['taskDigest'] = task_digest(task.read_text())
    session['infraManifest']['infra/cloudformation/templates/b.yaml'] = backend.file_digest(template.with_name('b.yaml'), fresh=True)
    session['unitDigests']['B'] = backend.input_digest(following, fresh=True)
    original_aws = backend.aws
    def reference_aws(operation, **args):
        if operation == 'list_exports':
            calls.append((operation, args))
            return {'Exports': [{'Name': 'SubnetExport', 'Value': 'subnet-current',
                                 'ExportingStackId': 'arn:aws:cloudformation:ap-northeast-1:123456789012:stack/B/id'}]}
        if operation == 'get_template':
            calls.append((operation, args)); return {'TemplateBody': producer}
        if operation == 'describe_stacks' and args == {'StackName': 'B'}:
            calls.append((operation, args)); return {'Stacks': [{'StackStatus': 'CREATE_COMPLETE', 'Parameters': []}]}
        return original_aws(operation, **args)
    backend.aws = reference_aws
    state = session['states']['A']; state.update(status='FAILED', stackStatus='UPDATE_ROLLBACK_COMPLETE', failureEvents=[event_subnet])
    backend.save()
    assert backend.repair(unit, state), state
    assert '!ImportValue' in template.read_text() and 'SubnetExport' in template.read_text()
    assert sum(op == 'get_template' for op, _ in calls) == 1
    subnet['desired.resource.001.cfn-logicalId'] = 'A-Subnet'
    # Case 3: explicit approved account projection, not an inference from AccessDenied.
    glue_text = 'Resources:\n  Item:\n    Type: AWS::Glue::Database\n    Properties:\n      CatalogId: "111111111111"\n      DatabaseInput:\n        Name: app_dev_database\n'
    backend, session, calls, executed, validated, run = configure('glue', 'Glue.Database',
        [('CatalogId', '`123456789012`', 'approved own account')], glue_text, 'Catalog AccessDenied')
    assert run() == 'COMPLETE', session
    assert '!Ref' in template.read_text() and 'AWS::AccountId' in template.read_text() and executed == ['A', 'A', 'B']
    # Case 4: external key absent, authoritative handoff unresolved: no edits.
    backend, session, calls, executed, validated, run = configure('lambda', 'Lambda.Function',
        [('KmsKeyArn', '`UNSET`', 'external key unknown')], lambda_text, 'KMS key does not exist')
    before = template.read_bytes(); assert run() == 'STOPPED'
    assert template.read_bytes() == before and session['states']['A']['failureClassification'] == 'HUMAN_REQUIRED'
    assert not validated and not any(op == 'delete_stack' for op, _ in calls)
    # An IMPORT Key reference without an approved handoff is also never guessed.
    backend, session, calls, executed, validated, run = configure('lambda', 'Lambda.Function',
        [('KmsKeyArn', '[KMS_Key_001](kms.md#kms-app-dev-key)', 'external key')], lambda_text, 'KMS key does not exist')
    imported = helpers.model('kms', 'KMS.Key', 'app-dev-key', [('KeyId', '[KMS_Key_001](kms.md#kms-app-dev-key)', '外部鍵')], 'Key')
    imported['desired.resource.001.resourceMode'] = 'IMPORT'
    write_model(modeldir / 'kms.properties', helpers.text(imported))
    task.write_text(task.read_text().replace('## Modified files', '- `dev/123456789012/kms`\n## Modified files'))
    session['taskDigest'] = task_digest(task.read_text()); backend.save()
    before = template.read_bytes(); assert run() == 'STOPPED' and template.read_bytes() == before
    assert session['states']['A']['failureClassification'] == 'HUMAN_REQUIRED' and not validated
    # Case 5: approved cross-account CatalogId already matches, never rewrite to execution account.
    backend, session, calls, executed, validated, run = configure('glue', 'Glue.Database',
        [('CatalogId', '`111111111111`', 'cross-account')], glue_text, 'Catalog AccessDenied')
    before = template.read_bytes(); assert run() == 'STOPPED' and template.read_bytes() == before
    assert session['states']['A']['failureClassification'] == 'HUMAN_REQUIRED'
    # Case 6: new replacement change set reaches the existing exact-ID Human approval gate.
    backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
        [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing', destructive=True)
    assert run() == 'STOPPED' and executed == ['A']
    assert session['states']['A']['status'] == 'BLOCKED' and 'human confirmation' in session['states']['A']['reason']
    # Case 7: repeated logical error after deterministic repair has no new material correction.
    backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
        [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock request-id changed', repeated=True)
    assert run() == 'STOPPED' and executed == ['A', 'A'] and len(session['states']['A']['repairs']) == 1
    # Case 8: out-of-scope bytes cannot be absorbed into a repair transaction.
    backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
        [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
    template.with_name('b.yaml').write_text('Resources: {}\n# unauthorized\n')
    before = template.read_bytes(); assert run() == 'STOPPED' and template.read_bytes() == before
    assert 'unauthorized IaC' in session['states']['A']['reason']
    # Case 9: successful peer is drained/synced once, never restarted during repair.
    backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
        [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
    following['deployOrder'] = '1'
    assert run() == 'COMPLETE' and executed.count('B') == 1 and executed.count('A') == 2
    following['deployOrder'] = '2'
    # Case 10: UPDATE_ROLLBACK_FAILED/ResourcesToSkip never causes skip or deletion.
    backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
        [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
    state = session['states']['A']; state.update(status='FAILED', stackStatus='UPDATE_ROLLBACK_FAILED', reason='ResourcesToSkip required')
    before = template.read_bytes(); assert not backend.repair(unit, state)
    assert template.read_bytes() == before and state['failureClassification'] == 'HUMAN_REQUIRED'
    assert not any(op in {'delete_stack', 'continue-update-rollback'} for op, _ in calls)
    # The three-iteration cap is enforced independently of changing request/error strings.
    backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
        [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
    state = session['states']['A']
    event = {'LogicalResourceId': 'Item', 'ResourceType': 'AWS::EC2::VPC',
             'ResourceStatus': 'CREATE_FAILED', 'ResourceStatusReason': 'CidrBlock missing'}
    state.update(status='FAILED', stackStatus='UPDATE_ROLLBACK_COMPLETE', failureEvents=[event],
                 repairs=[{'failureClass': 'Item:CidrBlock|Peer' + str(i) + ':Property', 'newFileDigest': str(i), 'stage': 'RETRY_READY'} for i in range(3)])
    assert not backend.repair(unit, state) and 'iteration limit' in state['reason'] and not validated
    # Both interruption boundaries recover only persisted exact candidate bytes, then revalidate.
    for boundary in ('REPAIR_INTENT', 'VALIDATING'):
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
        state = session['states']['A']; state.update(status='FAILED', stackStatus='UPDATE_ROLLBACK_COMPLETE', failureEvents=[event])
        original_save = backend.save
        def interrupted():
            original_save()
            if state.get('repairs') and state['repairs'][-1]['stage'] == boundary:
                raise KeyboardInterrupt()
        backend.save = interrupted
        with pytest.raises(KeyboardInterrupt):
            backend.repair(unit, state)
        assert not validated
        backend.save = original_save
        assert backend.repair(unit, state) and validated == ['A'] and state['status'] == 'NOT_STARTED'
        assert len(state['repairs']) == 1
    # Concurrent scope/parameter edits during diagnostics or intent persistence cannot be admitted.
    for boundary in ('diagnostics', 'intent'):
        backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
            [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
        state = session['states']['A']; state.update(status='FAILED', stackStatus='UPDATE_ROLLBACK_COMPLETE', failureEvents=[event])
        untouched = template.read_bytes()
        if boundary == 'diagnostics':
            plan = backend.repair_plan
            def concurrent_plan(*args):
                result = plan(*args)
                (parameters / 'b.json').write_text('[]\n# scope change')
                return result
            backend.repair_plan = concurrent_plan
        else:
            original_save = backend.save
            def concurrent_intent():
                original_save()
                if state.get('repairs') and state['repairs'][-1]['stage'] == 'REPAIR_INTENT':
                    (parameters / 'a.json').write_text('[]\n# unauthorized parameter change')
            backend.save = concurrent_intent
        assert not backend.repair(unit, state) and not validated and not executed
        if boundary == 'diagnostics':
            assert template.read_bytes() == untouched
        else:
            assert 'outside the exact authorized candidate' in state['reason']
    # Isolated stale parameter keeps its template Ref and changes only the target parameter file.
    parameter_template = 'Parameters:\n  Cidr:\n    Type: String\nResources:\n  Item:\n    Type: AWS::EC2::VPC\n    Properties:\n      CidrBlock: !Ref Cidr\n'
    backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
        [('CidrBlock', '`10.0.0.0/16`', 'network')], parameter_template, 'CidrBlock invalid')
    parameter = parameters / 'a.json'
    parameter.write_text('[{"ParameterKey":"Cidr","ParameterValue":"10.1.0.0/16"}]')
    relative = parameter.relative_to(root).as_posix()
    task.write_text(task.read_text().replace('## Modified files', '## Modified files\n- `' + relative + '`').replace('## Allowed paths', '## Allowed paths\n- `' + relative + '`'))
    session['taskDigest'] = task_digest(task.read_text())
    session['infraManifest'][relative] = backend.file_digest(parameter, fresh=True)
    session['unitDigests']['A'] = backend.input_digest(unit, fresh=True)
    state = session['states']['A']; state.update(status='FAILED', stackStatus='UPDATE_ROLLBACK_COMPLETE', failureEvents=[event])
    backend.save()
    before = template.read_bytes()
    assert backend.repair(unit, state) and template.read_bytes() == before
    assert json.loads(parameter.read_text())[0]['ParameterValue'] == '10.0.0.0/16'
    # Reset to a template case for the rollback safety checks below.
    backend, session, calls, executed, validated, run = configure('ec2', 'EC2.VPC',
        [('CidrBlock', '`10.0.0.0/16`', 'network')], vpc, 'CidrBlock missing')
    state = session['states']['A']
    # Unknown provenance and retained resource conditions are checked before delete.
    state.update(stackStatus='ROLLBACK_COMPLETE', operationType='CREATE', absentBeforeCreate=True, stackId='id', operationStackId='other')
    def failed_without_id(operation, **args):
        if operation == 'describe_stacks':
            return {'Stacks': [{'StackId': 'id', 'StackStatus': 'ROLLBACK_COMPLETE'}]}
        return {'StackResourceSummaries': [{'LogicalResourceId': 'Item', 'ResourceType': 'AWS::EC2::VPC',
                                            'ResourceStatus': 'CREATE_FAILED'}]}
    backend.aws = failed_without_id
    rejects(lambda: backend.cleanup_failed_create(unit, state), 'provenance')
    state['operationStackId'] = 'id'
    backend.templates['A'][0]['Resources']['Item']['DeletionPolicy'] = 'Retain'
    rejects(lambda: backend.cleanup_failed_create(unit, state), 'retained')
    backend.templates['A'][0]['Resources']['Item'].pop('DeletionPolicy')
    def protected(operation, **args):
        return {'Stacks': [{'StackId': 'id', 'StackStatus': 'ROLLBACK_COMPLETE', 'EnableTerminationProtection': True}]}
    backend.aws = protected
    rejects(lambda: backend.cleanup_failed_create(unit, state), 'protected')
    def partial_asset(operation, **args):
        if operation == 'describe_stacks':
            return {'Stacks': [{'StackId': 'id', 'StackStatus': 'ROLLBACK_COMPLETE'}]}
        return {'StackResourceSummaries': [{'LogicalResourceId': 'Item', 'ResourceType': 'AWS::EC2::VPC',
                                            'ResourceStatus': 'CREATE_FAILED', 'PhysicalResourceId': 'vpc-existing'}]}
    backend.aws = partial_asset
    rejects(lambda: backend.cleanup_failed_create(unit, state), 'still owns resources')
    assert M.repair_ops.merge_selected([{'Key': 'Name', 'Value': 'old'}, {'Key': 'Owner', 'Value': 'keep'}],
                            [{'Key': 'Name', 'Value': 'new'}], 'Tags') == [{'Key': 'Name', 'Value': 'new'}, {'Key': 'Owner', 'Value': 'keep'}]
    empty = 'Resources:\n  Item:\n    Type: AWS::EC2::VPC\n'
    assert 'Properties:' in M.repair_ops.repair_template(empty, 'Item', 'CidrBlock', '10.0.0.0/16')
    flow = 'Resources: {Item: {Type: AWS::EC2::VPC, Properties: {CidrBlock: old, EnableDnsSupport: true}}}\n'
    assert 'EnableDnsSupport: true' in M.repair_ops.repair_template(flow, 'Item', 'CidrBlock', '10.0.0.0/16')
    # Source-span edits preserve sibling keys and comments across scalar/list/map values.
    sample = 'Resources:\n  Item:\n    Type: AWS::Glue::Database\n    Properties:\n      CatalogId: "old" # comment\n      DatabaseInput:\n        Name: db\n        Description: old\n      Tags: [one]\n'
    updated = M.repair_ops.repair_template(sample, 'Item', 'DatabaseInput', {'Name': 'db', 'Description': 'new'})
    assert 'Tags: [one]' in updated and 'CatalogId: "old" # comment' in updated
    print('Controlled deploy repair: PASS (Cases 1-10, typed projection, session evidence, no guessed values, provenance/retention gates)')


def check_secret_runtime_bootstrap(tmp_path):
    """Requested Cases 1-13 exercise the controller, ownership mappings and durable resumes."""
    from model.adapters.observed import mappings
    base = tmp_path
    root = base / 'repo'
    root.mkdir()
    (root / 'project.json').write_text(json.dumps({'targets': [{'environment': 'dev', **TARGET}]}))
    modeldir = root / 'model/dev/123456789012'
    modeldir.mkdir(parents=True)
    selected = [dict(name=name, template=name.lower() + '.yaml', parameters=name.lower() + '.json', deployOrder=str(order))
                for name, order in [('SecretOwner', 1), ('A', 2), ('B', 2), ('C', 3)]]
    template_dir = root / 'infra/cloudformation/templates'
    parameter_dir = root / 'infra/cloudformation/parameters/dev/123456789012'
    template_dir.mkdir(parents=True); parameter_dir.mkdir(parents=True)
    task = root / 'tasks/example.md'; task.parent.mkdir()
    task.write_text('\n'.join(['## Task contract', '- Task type: `infrastructure`', '- Task status: `running`', '- Infrastructure phase: `deploy`', '- Controlled repair: `allowed`', '- AWS API execution: `allowed`', '- Deploy/apply: `allowed`',
        '## Validation scope', '- `dev/123456789012/secretsmanager`', '- `dev/123456789012/quicksight`',
        '## Modified files', '- `tasks/example.md`', '## Allowed paths', '- `tasks/example.md`']), encoding='utf-8')
    write_model(modeldir / 'cloudformation-stacks.properties', '\n'.join(
        f'desired.stack.{i:03d}.{key}={value}' for i, unit in enumerate(selected, 1) for key, value in unit.items()))
    for service, kind, stack, logical in [('secretsmanager', 'SecretsManager.Secret', 'SecretOwner', 'Secret'),
                                         ('quicksight', 'QuickSight.DataSource', 'B', 'Consumer')]:
        write_model(modeldir / (service + '.properties'), '\n'.join([
            f'desired.resource.001.resourceType={kind}', f'desired.resource.001.cfn-logicalId={stack}-{logical}',
            f"desired.resource.001.logicalId={kind.replace('.', '_')}_001", 'desired.service.identity.lastAllocated=' + json.dumps({kind: 1}), 'display.resource.001.label=item']))
    arn = 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:app-dev-secret-abcdef'
    stack_ids = {u['name']: f"arn:aws:cloudformation:ap-northeast-1:123456789012:stack/{u['name']}/session-id" for u in selected}
    source = {'Resources': {'Secret': {'Type': 'AWS::SecretsManager::Secret', 'Properties': {'Name': 'app-dev-secret'}}},
              'Outputs': {'SecretId': {'Value': {'Ref': 'Secret'}, 'Export': {'Name': 'SecretExport'}}}}
    def consumer_reference(key):
        return {'Fn::Sub': ['{{resolve:secretsmanager:${Secret}:SecretString:' + key + '}}',
                           {'Secret': {'Fn::ImportValue': 'SecretExport'}}]}
    secret_model = modeldir / 'secretsmanager.properties'
    secret_model_text = read_model(secret_model)
    def configure(*, keys=('username', 'password'), create=True, repeated=False, future=False):
        active = selected + ([dict(name='FutureSecretOwner', template='future.yaml', parameters='future.json', deployOrder='4')] if future else [])
        future_values = properties(secret_model_text)
        if future:
            future_values.update({'desired.resource.002.resourceType': 'SecretsManager.Secret',
                                  'desired.resource.002.cfn-logicalId': 'FutureSecretOwner-OtherSecret',
                                  'display.resource.002.label': 'other'})
            future_values = allocate(future_values, ['002'])
        write_model(secret_model, future_values)
        write_model(modeldir / 'cloudformation-stacks.properties', '\n'.join(
            f'desired.stack.{i:03d}.{key}={value}' for i, u in enumerate(active, 1) for key, value in u.items()))
        consumer = {'Resources': {'Consumer': {'Type': 'AWS::QuickSight::DataSource', 'Properties': {
            'AwsAccountId': '123456789012', 'DataSourceId': 'app-dev-source', 'Name': 'app-dev-source', 'Type': 'POSTGRESQL',
            'DataSourceParameters': {'PostgreSqlParameters': {'Host': 'db.example', 'Port': 5432, 'Database': 'app'}},
            'Credentials': {'CredentialPair': {'Username': consumer_reference(keys[0]), 'Password': consumer_reference(keys[-1])}}}}}}
        docs = {'SecretOwner': json.loads(json.dumps(source)), 'A': {'Resources': {}}, 'B': consumer, 'C': {'Resources': {}}}
        if future:
            docs['FutureSecretOwner'] = {'Resources': {'OtherSecret': {'Type': 'AWS::SecretsManager::Secret'}}}
        for name, doc in docs.items():
            u = next(u for u in active if u['name'] == name)
            (template_dir / u['template']).write_text(json.dumps(doc), encoding='utf-8')
            (parameter_dir / u['parameters']).write_text('[]\n', encoding='utf-8')
        backend = Runtime(root, 'dev', '123456789012', TARGET)
        backend.units = active
        for unit in active:
            backend.load_inputs(unit)
        backend.mapping_plan = mappings(root, 'dev', '123456789012', backend.templates, active, target=TARGET)
        session = {'states': states(active), 'metrics': {'observedSyncSeconds': 0},
                   'unitDigests': {u['name']: backend.input_digest(u) for u in active}}
        session['states']['SecretOwner'].update(status='SUCCESS', stackId=stack_ids['SecretOwner'], observedSynced=True)
        backend.states = session['states']; backend.session = session
        backend.expected_digests = session['unitDigests']; backend.validated_digests = dict(session['unitDigests'])
        calls, executed, validations, syncs = [], [], [], []
        versions = {}
        knobs = {'getError': None, 'describeError': False, 'listError': False,
                 'canonicalArn': arn, 'ownerArn': arn, 'rotation': False, 'race': False, 'promotionRace': False,
                 'interruptPut': False, 'invalidVersionResponse': False, 'unsafeCleanup': False}
        statuses = {'SecretOwner': 'CREATE_COMPLETE', 'A': None, 'B': None if create else 'UPDATE_COMPLETE', 'C': None}
        if future:
            statuses['FutureSecretOwner'] = None
            stack_ids['FutureSecretOwner'] = 'arn:aws:cloudformation:ap-northeast-1:123456789012:stack/FutureSecretOwner/session-id'
        tokens = {}
        session_path = base / 'session.json'
        def save():
            session_path.write_text(json.dumps(session), encoding='utf-8')
        backend.save = save
        before = {p: p.read_bytes() for parent in (root / 'infra', modeldir) for p in parent.rglob('*') if p.is_file()}
        def guard():
            assert all(p.read_bytes() == data for p, data in before.items()), 'runtime bootstrap changed repository inputs'
        backend.guard = guard
        def aws(operation, service='cloudformation', **args):
            calls.append((operation, args))
            if service == 'secretsmanager':
                if operation == 'describe_secret':
                    if knobs['describeError']:
                        raise M.Blocked('ResourceNotFoundException')
                    return {'ARN': knobs['canonicalArn'], 'Name': 'app-dev-secret', 'RotationEnabled': knobs['rotation'],
                            'VersionIdsToStages': {k: list(v) for k, v in versions.items() if v}}
                if operation == 'list_secret_version_ids':
                    if knobs['listError']:
                        raise M.Blocked('AccessDeniedException')
                    if knobs['invalidVersionResponse']:
                        return {}
                    return {'ARN': arn, 'Versions': [{'VersionId': k, 'VersionStages': v} for k, v in versions.items()]}
                if operation == 'get_secret_value':
                    assert 'SecretString' not in args and 'Query' not in args
                    if knobs['getError']:
                        raise M.Blocked(knobs['getError'])
                    current = [k for k, v in versions.items() if 'AWSCURRENT' in v]
                    if not current:
                        error = M.Blocked('current version missing'); error.current_missing = True
                        raise error
                    return {'ARN': arn, 'VersionId': current[0], 'VersionStages': versions[current[0]], 'HasValue': True}
                if operation == 'put_secret_value':
                    guard()
                    saved = json.loads(session_path.read_text())['states']['B']['repairs'][-1]
                    assert saved['classification'] == 'RUNTIME_BOOTSTRAP' and saved['stage'] == 'PUT_SUBMITTED'
                    token = args['ClientRequestToken']
                    assert saved['clientRequestToken'] == token
                    assert session['states']['A']['observedSynced'], 'successful peers must sync before PUT'
                    if knobs['race']:
                        versions['external-version'] = ['AWSCURRENT']
                    stages = list(args['VersionStages'])
                    if not versions:
                        stages.append('AWSCURRENT')
                    versions.setdefault(token, stages)
                    if knobs['interruptPut']:
                        raise KeyboardInterrupt()
                    return {'ARN': arn, 'VersionId': token, 'VersionStages': versions[token]}
                if operation == 'update_secret_version_stage':
                    guard()
                    assert '--remove-from-version-id' not in args
                    if knobs['promotionRace']:
                        versions['external-version'] = ['AWSCURRENT']
                    if any('AWSCURRENT' in v for v in versions.values()):
                        raise M.Blocked('stage already exists')
                    versions[args['MoveToVersionId']].append('AWSCURRENT')
                    return {'ARN': arn, 'Name': 'app-dev-secret'}
                raise AssertionError(operation)
            name = args['StackName'] if 'StackName' in args else 'B'
            name = name.split(':stack/')[-1].split('/')[0]
            if operation == 'list_exports':
                return {'Exports': [{'Name': 'SecretExport', 'Value': arn, 'ExportingStackId': stack_ids['SecretOwner']}]}
            if operation == 'list_stack_resources':
                if name == 'FutureSecretOwner' and statuses[name] is None:
                    raise M.Blocked('stack does not exist')
                return {'StackResourceSummaries': ([{'LogicalResourceId': 'Secret', 'ResourceType': 'AWS::SecretsManager::Secret',
                    'ResourceStatus': 'CREATE_COMPLETE', 'PhysicalResourceId': knobs['ownerArn']}] if name == 'SecretOwner' else
                    [{'LogicalResourceId': 'Consumer', 'ResourceType': 'AWS::QuickSight::DataSource', 'ResourceStatus': 'DELETE_SKIPPED'}]
                    if knobs['unsafeCleanup'] else [])}
            if operation == 'get_template':
                return {'TemplateBody': docs[name]}
            if operation == 'describe_stacks':
                if statuses[name] is None:
                    raise M.Blocked('stack does not exist')
                return {'Stacks': [{'StackId': stack_ids[name], 'StackStatus': statuses[name], 'Parameters': []}]}
            if operation == 'create_change_set':
                return {'Id': args['ChangeSetName'], 'StackId': stack_ids[name]}
            if operation == 'describe_change_set':
                return {'Status': 'CREATE_COMPLETE', 'ExecutionStatus': 'AVAILABLE', 'Changes': [], 'ChangeSetId': args['ChangeSetName'], 'StackId': stack_ids[name]}
            if operation == 'execute_change_set':
                executed.append(name); tokens[name] = args['ClientRequestToken']
                failing = name == 'B' and (executed.count('B') == 1 or repeated)
                statuses[name] = ('ROLLBACK_COMPLETE' if create else 'UPDATE_ROLLBACK_COMPLETE') if failing else 'CREATE_COMPLETE'
                return {}
            if operation == 'describe_stack_events':
                events = [{'ResourceType': 'AWS::CloudFormation::Stack', 'ClientRequestToken': tokens[name],
                           'ResourceStatus': statuses[name], 'StackId': stack_ids[name]}]
                if 'ROLLBACK' in statuses[name]:
                    events.append({'LogicalResourceId': 'Consumer', 'ResourceType': 'AWS::QuickSight::DataSource',
                        'ResourceStatus': 'CREATE_FAILED', 'ClientRequestToken': tokens[name],
                        'ResourceStatusReason': "Secrets Manager can't find the specified secret value for staging label: AWSCURRENT"})
                return {'StackEvents': events}
            if operation == 'delete_stack':
                assert args == {'StackName': stack_ids['B']}
                statuses[name] = None; return {}
            if operation == 'validate_template':
                return {}
            raise AssertionError(operation)
        backend.aws = aws
        def validate(unit):
            validations.append(unit['name'])
            backend.load_inputs(unit)
            backend.mapping_plan = mappings(root, 'dev', '123456789012', backend.templates, active, target=TARGET)
        backend.refresh_validation = validate
        def synced(_backend, items, saved):
            for item in items:
                syncs.append(item['name']); saved[item['name']]['observedSynced'] = True
        def run():
            with patch.object(M.session_ops, 'sync_successful', side_effect=synced):
                return M.session_ops.run_session(active, 2, session, backend, backend.save, sleep=lambda _: None)
        def failed():
            state = session['states']['B']
            statuses['B'] = 'ROLLBACK_COMPLETE' if create else 'UPDATE_ROLLBACK_COMPLETE'
            state.update(status='FAILED', stackStatus=statuses['B'], stackId=stack_ids['B'],
                failureEvents=[{'LogicalResourceId': 'Consumer', 'ResourceType': 'AWS::QuickSight::DataSource',
                                'ResourceStatus': 'CREATE_FAILED', 'ResourceStatusReason': 'SECRET_CURRENT_VALUE_MISSING'}])
            session['states']['A'].update(status='SUCCESS', observedSynced=True)
            backend.save()
            return state
        save()
        return SimpleNamespace(backend=backend, session=session, calls=calls, executed=executed, validations=validations,
            syncs=syncs, versions=versions, knobs=knobs, docs=docs, run=run, failed=failed, saved=session_path, before=before)

    def puts(f):
        return [args for op, args in f.calls if op == 'put_secret_value']
    # Cases 1, 8, 13: one JSON PUT, failed CREATE cleanup/retry, peer sync and original remaining order.
    f = configure()
    assert f.run() == 'COMPLETE', f.session
    assert f.executed == ['A', 'B', 'B', 'C'] and f.validations == ['B'] and f.syncs.count('A') == 1
    assert len(puts(f)) == 1
    assert json.loads(puts(f)[0]['SecretString']) == {'username': 'DUMMY_DEPLOY_ONLY', 'password': 'DUMMY_DEPLOY_ONLY'}
    entry = f.session['states']['B']['repairs'][0]
    assert entry['classification'] == 'RUNTIME_BOOTSTRAP' and entry['stage'] == 'RETRY_READY'
    assert entry['requiredJsonKeys'] == ['password', 'username']
    assert all(p.read_bytes() == data for p, data in f.before.items()) and 'DUMMY_DEPLOY_ONLY' not in f.saved.read_text()
    assert 'SecretString' not in f.saved.read_text() and 'SecretBinary' not in f.saved.read_text()
    # Later uncreated Secret producers do not block the proven current Secret's bootstrap.
    f = configure(future=True)
    assert f.run() == 'COMPLETE' and f.executed == ['A', 'B', 'B', 'C', 'FutureSecretOwner'], f.session
    assert len(puts(f)) == 1 and not any(op == 'list_stack_resources' and args == ('--stack-name', 'FutureSecretOwner')
                                        for op, args in f.calls)
    # Cases 2-7: existing value, denied reads/KMS, absent resource, IMPORT, foreign/unknown owner never PUT/cleanup.
    for mode in ('current', 'denied', 'kms', 'absent', 'import', 'crossAccount', 'crossRegion', 'unknownOwner', 'unknownVersions', 'invalidResponse', 'rotation', 'listDenied'):
        f = configure(); state = f.failed()
        if mode == 'current': f.versions['existing-version'] = ['AWSCURRENT']
        if mode == 'denied': f.knobs['getError'] = 'AccessDeniedException'
        if mode == 'kms': f.knobs['getError'] = 'DecryptionFailure'
        if mode == 'absent': f.knobs['describeError'] = True
        if mode == 'import':
            owner_path = f.backend.mapping_plan[1]['SecretOwner']['Secret'][0]
            identity = f.backend.mapping_plan[1]['SecretOwner']['Secret'][1]
            write_model(owner_path, read_model(owner_path) + f'desired.resource.{identity}.resourceMode=IMPORT\n')
            f.backend.guard = lambda: None
        if mode == 'crossAccount': f.knobs['canonicalArn'] = arn.replace('123456789012', '999999999999')
        if mode == 'crossRegion': f.knobs['canonicalArn'] = arn.replace('ap-northeast-1', 'us-east-1')
        if mode == 'unknownOwner': f.knobs['ownerArn'] = 'external'
        if mode == 'unknownVersions': f.versions['previous-version'] = ['AWSPREVIOUS']
        if mode == 'invalidResponse': f.knobs['invalidVersionResponse'] = True
        if mode == 'rotation': f.knobs['rotation'] = True
        if mode == 'listDenied': f.knobs['listError'] = True
        assert not f.backend.repair(selected[2], state), mode
        assert state['failureClassification'] == 'HUMAN_REQUIRED' and not puts(f), (mode, state)
        assert not any(op == 'delete_stack' for op, _ in f.calls), mode
    # Case 9: whole credential JSON/unknown special schema and mixed string/key consumers stop.
    for mode in ('opaque', 'mixed', 'pinned', 'multiple', 'unresolved', 'badExport', 'inactive'):
        f = configure(); state = f.failed(); credential = f.docs['B']['Resources']['Consumer']['Properties']['Credentials']['CredentialPair']
        if mode == 'opaque':
            f.docs['B']['Resources']['Consumer']['Properties']['Credentials'] = consumer_reference('')
        if mode == 'mixed': credential['Username'] = consumer_reference('')
        if mode == 'pinned': credential['Username'] = consumer_reference('username:AWSPREVIOUS')
        if mode == 'multiple': credential['Username'] = '{{resolve:secretsmanager:other:SecretString:username}}'
        if mode == 'unresolved': credential['Username']['Fn::Sub'][1]['Secret'] = {'Ref': 'Unknown'}
        if mode == 'badExport': f.docs['SecretOwner']['Outputs']['SecretId']['Value'] = 'unproven'
        if mode == 'inactive':
            f.docs['B']['Conditions'] = {'Off': {'Fn::Equals': ['yes', 'no']}}
            f.docs['B']['Resources']['Consumer']['Condition'] = 'Off'
        f.backend.templates['B'] = (f.docs['B'], {})
        assert not f.backend.repair(selected[2], state) and not puts(f), (mode, state)
    # A proven scalar slot consumes the whole string; no JSON keys are invented.
    f = configure(keys=('', '')); assert f.run() == 'COMPLETE'
    assert puts(f)[0]['SecretString'] == 'DUMMY_DEPLOY_ONLY'
    # Explicit parameter files/defaults and Ref resolve the same owner, without failure-text IDs.
    for explicit in (True, False):
        f = configure(); state = f.failed()
        f.docs['B']['Parameters'] = {'SecretInput': {'Type': 'String', 'Default': arn}}
        pair = f.docs['B']['Resources']['Consumer']['Properties']['Credentials']['CredentialPair']
        for slot, key in (('Username', 'username'), ('Password', 'password')):
            pair[slot] = {'Fn::Sub': ['{{resolve:secretsmanager:${Secret}:SecretString:' + key + '}}', {'Secret': {'Ref': 'SecretInput'}}]}
        path = parameter_dir / 'b.json'
        (template_dir / 'b.yaml').write_text(json.dumps(f.docs['B']), encoding='utf-8')
        path.write_text(json.dumps([{'ParameterKey': 'SecretInput', 'ParameterValue': arn}] if explicit else []), encoding='utf-8')
        f.before[template_dir / 'b.yaml'] = (template_dir / 'b.yaml').read_bytes(); f.before[path] = path.read_bytes()
        f.session['unitDigests']['B'] = f.backend.input_digest(selected[2], fresh=True)
        f.backend.load_inputs(selected[2]); f.backend.save()
        assert f.backend.repair(selected[2], state) and len(puts(f)) == 1, state
    # Conditional imports inside Sub maps use only the active branch.
    f = configure(); state = f.failed()
    f.docs['B']['Parameters'] = {'Switch': {'Type': 'String', 'Default': 'yes'}}
    f.docs['B']['Conditions'] = {'Enabled': {'Fn::Equals': [{'Ref': 'Switch'}, 'yes']}}
    pair = f.docs['B']['Resources']['Consumer']['Properties']['Credentials']['CredentialPair']
    for value in pair.values():
        value['Fn::Sub'][1]['Secret'] = {'Fn::If': ['Enabled', {'Fn::ImportValue': 'SecretExport'}, {'Fn::ImportValue': 'MissingInactiveExport'}]}
    path = template_dir / 'b.yaml'; path.write_text(json.dumps(f.docs['B']), encoding='utf-8')
    f.before[path] = path.read_bytes(); f.session['unitDigests']['B'] = f.backend.input_digest(selected[2], fresh=True)
    f.backend.load_inputs(selected[2]); f.backend.save()
    assert f.backend.repair(selected[2], state) and len(puts(f)) == 1, state
    # A value appearing after durable missing-check persistence prevents even the initial PUT.
    f = configure(); state = f.failed(); save = f.backend.save
    def concurrent_value():
        save()
        if state.get('repairs') and state['repairs'][-1]['stage'] == 'VALUE_CHECKED_MISSING':
            f.versions['external-version'] = ['AWSCURRENT']
    f.backend.save = concurrent_value
    assert not f.backend.repair(selected[2], state) and not puts(f)
    assert f.versions == {'external-version': ['AWSCURRENT']}
    # Cases 10/11: process interruption before PUT, after accepted PUT, and before cleanup.
    for boundary in ('BOOTSTRAP_INTENT', 'VALUE_CHECKED_MISSING', 'PUT_SUBMITTED', 'afterPut', 'BOOTSTRAP_CONFIRMED', 'RETRY_READY'):
        f = configure(); state = f.failed(); save = f.backend.save
        def interrupted():
            save()
            records = state.get('repairs', [])
            if records and records[-1]['stage'] == boundary:
                raise KeyboardInterrupt()
        f.backend.save = interrupted
        f.knobs['interruptPut'] = boundary == 'afterPut'
        with pytest.raises(KeyboardInterrupt):
            f.backend.repair(selected[2], state)
        persisted = json.loads(f.saved.read_text())
        token = persisted['states']['B']['repairs'][0]['clientRequestToken']
        # Reload all persisted state, as a new process would; the AWS versions survive.
        f.session.clear(); f.session.update(persisted)
        previous = f.backend
        f.backend = Runtime(root, 'dev', '123456789012', TARGET)
        f.backend.session = f.session; f.backend.states = f.session['states']
        f.backend.units = selected; f.backend.mapping_plan = previous.mapping_plan
        f.backend.templates = previous.templates; f.backend.aws = previous.aws; f.backend.guard = previous.guard
        f.backend.expected_digests = f.session['unitDigests']
        f.backend.refresh_validation = lambda unit: f.backend.load_inputs(unit)
        state = f.backend.states['B']; f.backend.save = save; f.knobs['interruptPut'] = False
        if boundary != 'RETRY_READY':
            assert f.backend.repair(selected[2], state), (boundary, state)
        assert f.session['states']['B']['repairs'][0]['clientRequestToken'] == token
        assert len(puts(f)) == 1 and len(f.versions) == 1
        assert f.session['states']['B']['status'] == 'NOT_STARTED'
    # Case 12: the same failure after retry cannot trigger a second PUT or empty-shell recreation.
    f = configure(repeated=True)
    assert f.run() == 'STOPPED' and f.executed == ['A', 'B', 'B'] and len(puts(f)) == 1
    assert f.session['states']['B']['failureClassification'] == 'HUMAN_REQUIRED'
    assert f.session['states']['C']['status'] == 'NOT_STARTED'
    assert sum(op == 'delete_stack' for op, _ in f.calls) == 1
    # Existing UPDATE_ROLLBACK_COMPLETE handling does not delete/redeploy the successful peer.
    f = configure(create=False); assert f.run() == 'COMPLETE' and not any(op == 'delete_stack' for op, _ in f.calls)
    # Ownership, current-state, guard and cleanup uncertainty fail closed.
    f = configure(); state = f.failed(); f.knobs['unsafeCleanup'] = True
    assert not f.backend.repair(selected[2], state) and not any(op == 'delete_stack' for op, _ in f.calls)
    for race in ('race', 'promotionRace'):
        f = configure(); state = f.failed(); f.knobs[race] = True
        if race == 'promotionRace':
            f.versions.clear()
            original = f.backend.aws
            def staging_only(operation, **args):
                result = original(operation, **args)
                if operation == 'put_secret_value':
                    for v in f.versions.values():
                        if 'AWSCURRENT' in v: v.remove('AWSCURRENT')
                return result
            f.backend.aws = staging_only
        assert not f.backend.repair(selected[2], state) and f.versions['external-version'] == ['AWSCURRENT']
        assert len(puts(f)) == 1
    # The SDK service projects only metadata; structured transport errors never contain values.
    from utils.aws import secretsmanager as secrets
    from utils.aws.client import AwsError
    backend = Runtime(root, 'dev', '123456789012', TARGET)
    from deploy.timing import Timing
    backend.timing = Timing(root, base / 'timing.jsonl')
    with patch.object(secrets, 'request', return_value={'ARN': arn, 'VersionId': 'v', 'VersionStages': ['AWSCURRENT'], 'SecretString': 'DUMMY_DEPLOY_ONLY'}):
        assert 'DUMMY_DEPLOY_ONLY' not in str(backend.aws('get_secret_value', SecretId=arn, service='secretsmanager'))
    for code in ('AccessDeniedException', 'ReadTimeoutError', 'ResourceNotFoundException'):
        with patch.object(secrets, 'get_secret_value', side_effect=AwsError('secretsmanager', 'get_secret_value', code)):
            with pytest.raises(M.Blocked) as caught:
                backend.aws('get_secret_value', SecretId=arn, service='secretsmanager')
            assert 'DUMMY_DEPLOY_ONLY' not in str(caught.value)
    assert 'DUMMY_DEPLOY_ONLY' not in (base / 'timing.jsonl').read_text()
    print('Secrets Manager RUNTIME_BOOTSTRAP: PASS (Cases 1-13, one PUT, JSON/scalar, guards, interruption, peer sync/order, concurrent-value protection, redaction)')


if __name__ == '__main__':
    raise SystemExit(run(__file__))
