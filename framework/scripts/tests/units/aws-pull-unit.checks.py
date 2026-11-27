"""Offline approved-key integrity and real editor/Change Validation regression."""

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import import_guard
import model.adapters.aws as aws
import pytest
from generation_inputs import GenerationInputs
from model.cli import main as model_cli
from model.format import parse, patch, serialize, split
from model.operations import prepare_edit, publish_edit
from model.pull_observed import proposed_values
from model.pull_review import MARKER, build, verify
from model.sources import SourceWriteContext, raw_model
from support.import_model_fixtures import resource_values
from support.producer_identifier_reference_fixtures import setup, write_model
from support.pytest_cli import run
from support.repository_fixtures import git
from task_contract_core import selected_task, start

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

KEY = "desired.row.001-001.value"
TASK = "tasks/pull.md"


def pair(tmp_path, after="7200"):
    scope = SimpleNamespace(
        root=tmp_path, environment="stg", target="cde", service="iam"
    )
    values = resource_values(
        "001", "IAM.Role", "role", "CREATE", [("MaxSessionDuration", "3600")]
    )
    path = tmp_path / "model/stg/cde/iam.properties"
    old = SimpleNamespace(
        scope=scope,
        authoritative=values,
        files={path: serialize(values)},
        documents={path: parse(serialize(values))},
        dependencies={},
    )
    new_values = dict(values, **{KEY: after})
    new = SimpleNamespace(
        scope=scope,
        authoritative=new_values,
        files={path: serialize(new_values)},
        documents={path: parse(serialize(new_values))},
        dependencies={},
    )
    return old, new


def contract(review):
    return (
        "## Task contract\n" + MARKER + "\n"
        "- Task type: `design`\n- Workflow: `update`\n"
        "- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n"
        "## AWS pull review\n" + json.dumps(review)
    )


def check_approved_and_no_difference(tmp_path):
    old, new = pair(tmp_path)
    review = build(old, new, TASK, {KEY: "iam.get_role, verified role, timestamp"})
    verify(old, new, TASK, contract(review))
    assert build(old, old, TASK, {})["changes"] == []
    verify(old, new, TASK, "## Task contract\n- Workflow: `update`")


@pytest.mark.parametrize(
    "mutation",
    [
        "before",
        "after",
        "extra",
        "identity",
        "mode",
        "scope",
        "task",
        "worktree",
        "comment",
    ],
)
def check_stale_or_unapproved_changes_rejected(tmp_path, mutation):
    old, new = pair(tmp_path)
    review = build(old, new, TASK, {KEY: "iam.get_role verified"})
    text = contract(review)
    if mutation == "before":
        old.authoritative[KEY] = "4000"
    elif mutation in {"after", "extra", "identity", "mode"}:
        key = {
            "after": KEY,
            "extra": "display.resource.001.comment",
            "identity": "desired.resource.001.logicalId",
            "mode": "desired.resource.001.resourceMode",
        }[mutation]
        new.authoritative[key] = "IMPORT" if mutation == "mode" else "changed"
    elif mutation == "scope":
        new.scope = copy.copy(old.scope)
        old.scope.service = "kms"
    elif mutation == "task":
        text = contract(dict(review, task="tasks/other.md"))
    elif mutation == "worktree":
        text = contract(dict(review, worktree="/other"))
    else:
        new.files[next(iter(new.files))] += "# unapproved\n"
    with pytest.raises(ValueError):
        verify(old, new, TASK, text)


def check_import_and_missing_evidence_rejected(tmp_path):
    old, new = pair(tmp_path)
    for model in (old, new):
        model.authoritative["desired.resource.002.resourceType"] = "IAM.Role"
        model.authoritative["desired.resource.002.resourceMode"] = "IMPORT"
        model.authoritative["desired.row.002-001.property"] = "IAM.Role.Description"
        model.authoritative["desired.row.002-001.value"] = "old"
    assert len(build(old, new, TASK, {KEY: "verified"})["changes"]) == 1
    new.authoritative["desired.row.002-001.value"] = "new"
    with pytest.raises(ValueError, match="CREATE"):
        build(old, new, TASK, {KEY: "verified"})
    old, new = pair(tmp_path)
    with pytest.raises(ValueError, match="evidence"):
        build(old, new, TASK, {})
    with pytest.raises(ValueError):
        verify(old, new, TASK, "## Task contract\n" + MARKER)


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        ([], "must be a JSON object"),
        ({}, "is missing for Model key"),
        ({KEY: {"api": "iam.get_role"}}, "must be a string for Model key"),
        ({KEY: None}, "must be a string for Model key"),
        ({KEY: " \t"}, "is blank for Model key"),
        ({KEY: "verified", "extra": "verified"}, "must name exactly the changed keys"),
    ],
)
def check_evidence_json_errors(tmp_path, evidence, message):
    old, new = pair(tmp_path)
    with pytest.raises(ValueError, match=message):
        build(old, new, TASK, evidence)


@pytest.mark.parametrize(
    "value",
    [
        '`[1,2,{"a":true}]`',
        '{"Statement":[{"Resource":{"$modelRef":{"logicalId":"KMS_Key_001","attribute":"Arn"}}}]}',
    ],
)
def check_review_preserves_exact_json(tmp_path, value):
    old, new = pair(tmp_path, value)
    review = build(old, new, TASK, {KEY: "verified"})
    assert review["changes"][0]["after"] == value
    verify(old, new, TASK, contract(review))


@pytest.mark.parametrize("mutation", ["comment", "format", "order", "property", "untouched-part"])
def check_raw_changes_rejected_before_review_and_save(tmp_path, mutation):
    old, new = pair(tmp_path)
    path = next(iter(old.files))
    # Keep comments, CRLF and the untouched IMPORT part byte-for-byte.
    values = dict(old.authoritative)
    values.update(resource_values("002", "IAM.Role", "imported", "IMPORT", [("Description", "old")]))
    old.authoritative = values
    old.files = split(path, values, limit=1)
    old.files = {p: text.replace("\n", "\r\n") for p, text in old.files.items()}
    old.documents = {p: parse(text) for p, text in old.files.items() if p != path}
    changed_path = next(p for p, doc in old.documents.items() if KEY in doc.values)
    old.files[changed_path] += "# retained comment\r\n\r\n"
    old.documents[changed_path] = parse(old.files[changed_path])
    new.authoritative = dict(values, **{KEY: "7200"})
    new.files = dict(old.files)
    new.files[changed_path] = patch(old.documents[changed_path], {KEY: "7200"})
    review = build(old, new, TASK, {KEY: "verified"})
    verify(old, new, TASK, contract(review))
    untouched = next(p for p, doc in old.documents.items() if "desired.row.002-001.value" in doc.values)
    assert new.files[untouched].encode("utf-8") == old.files[untouched].encode("utf-8")
    if mutation == "comment":
        new.files[changed_path] = new.files[changed_path].replace("retained", "unapproved")
    elif mutation == "format":
        new.files[changed_path] = new.files[changed_path].replace("\r\n", "\n")
    elif mutation == "order":
        lines = new.files[changed_path].splitlines(keepends=True)
        lines[1], lines[2] = lines[2], lines[1]
        new.files[changed_path] = "".join(lines)
    elif mutation == "property":
        key = "desired.row.002-001.value"
        new.authoritative[key] = "unapproved"
        new.files[untouched] = patch(old.documents[untouched], {key: "unapproved"})
    else:
        new.files[untouched] += "# unapproved\r\n"
    with pytest.raises(ValueError):
        build(old, new, TASK, {KEY: "verified"})
    with pytest.raises(ValueError):
        verify(old, new, TASK, contract(review))


@pytest.mark.parametrize("mutation", ["comment", "format", "order", "property"])
def check_real_sources_and_shared_change_validation(tmp_path, mutation):
    root = tmp_path / "repo"
    setup(root, ["iam"], ["IAM.ManagedPolicy"])
    values = resource_values(
        "001",
        "IAM.ManagedPolicy",
        "policy",
        "CREATE",
        [("ManagedPolicyName", "fixture"), ("Description", "old")],
    )
    path = root / "model/preview/team/iam.properties"
    write_model(path, values)
    assert raw_model(path).authoritative["desired.row.001-002.value"] == "old"
    before = raw_model(path)
    changed = dict(values, **{"desired.row.001-002.value": "new"})
    after = before._replace(authoritative=changed, files={path: serialize(changed)})
    review = build(
        before, after, TASK, {"desired.row.001-002.value": "verified iam.get_policy"}
    )
    listed = "\n".join("- `" + p + "`" for p in [TASK, str(path.relative_to(root))])
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    start(
        root,
        TASK,
        "## Task contract\n"
        + MARKER
        + "\n- Task type: `design`\n- Task status: `running`\n"
        "- Workflow: `update`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n"
        "## Required changes\n- [R1] update\n## Acceptance checks\n- [R1] `exists:project.json`\n"
        "## Validation scope\n- `preview/team/iam`\n## Modified files\n"
        + listed
        + "\n## Allowed paths\n"
        + listed
        + "\n## AWS pull review\n"
        + json.dumps(review),
    )
    with selected_task(root, TASK):
        inputs = GenerationInputs(root, task_file=TASK)
        context = SourceWriteContext._authorized(
            root,
            inputs,
            SimpleNamespace(action="edit"),
            lambda changes: None,
            frozenset({path}),
        )
        changed = dict(values, **{"desired.row.001-002.value": "new"})
        plan = prepare_edit(path, {path: serialize(changed)}, context)
        assert publish_edit(plan, context) == (path,)
        assert raw_model(path).authoritative["desired.row.001-002.value"] == "new"
        import_guard.require_import_changes(root)
        approved = path.read_text(encoding="utf-8")
        unapproved = {
            "comment": approved + "# unapproved\n",
            "format": approved + "\n",
            "order": "\n".join([approved.splitlines()[0], *reversed(approved.splitlines()[1:])]) + "\n",
            "property": serialize(dict(changed, **{"desired.row.001-001.value": "unapproved"})),
        }[mutation]
        with pytest.raises(ValueError):
            prepare_edit(path, {path: unapproved}, context)
        assert path.read_text(encoding="utf-8") == approved
        final_candidate = SimpleNamespace(
            base_commit=git(root, "rev-parse", "HEAD"),
            changed_paths={str(path.relative_to(root))},
            scope={("preview", "team", "iam")},
        )
        import_guard.require_import_changes(root, final_candidate=final_candidate)
        path.write_text(unapproved, encoding="utf-8")
        with pytest.raises(ValueError):
            import_guard.require_import_changes(root, final_candidate=final_candidate)


class ComparisonContext:
    resources = ()

    def __init__(self, *args):
        pass

    def verify(self):
        pass

    def model(self, path):
        return SimpleNamespace(resources=self.resources)


@pytest.mark.parametrize(
    "create_only,expected",
    [(True, ["CREATE", "default"]), (False, ["CREATE", "IMPORT", "default"])],
)
@pytest.mark.parametrize("unsupported_import", [False, True])
def check_comparator_create_filter(tmp_path, monkeypatch, create_only, expected, unsupported_import):
    root = tmp_path / "repo"
    setup(root, ["iam"], ["IAM.Role"])
    path = root / "model/preview/team/iam.properties"
    values = {}
    for number, mode in [("001", "CREATE"), ("002", "IMPORT"), ("003", "CREATE")]:
        prop = "Unsupported" if mode == "IMPORT" and unsupported_import else "Description"
        values.update(resource_values(number, "IAM.Role", "role-" + number, mode, [(prop, "old")]))
    del values["desired.resource.003.resourceMode"]
    write_model(path, values)
    resources = [
        SimpleNamespace(number=number, spec={"resourceMode": mode}, label=mode)
        for number, mode in [("001", "CREATE"), ("002", "IMPORT")]
    ]
    resources.append(SimpleNamespace(number="003", spec={}, label="default"))
    called = []
    monkeypatch.setattr(ComparisonContext, "resources", resources)
    monkeypatch.setattr(aws, "Context", ComparisonContext)
    monkeypatch.setattr(
        aws._imports_aws_mapping_compare, "comparison", lambda *args: (None, {"IAM.Role.Description": {}})
    )
    monkeypatch.setattr(
        aws,
        "compare_resource",
        lambda ctx, resource: called.append(resource.label) or [],
    )
    target = {
        "environment": "preview",
        "directory": "team",
        "awsAccountId": "111111111111",
        "awsRegion": "ap-northeast-1",
    }
    if unsupported_import and not create_only:
        with pytest.raises(ValueError, match="missing AWS Compare Mapping"):
            aws.run(root, [(target, path)], create_only=False)
        assert called == []
        return
    aws.run(root, [(target, path)], create_only=create_only)
    assert called == expected


def forbidden_acquisition(*args, **kwargs):
    raise AssertionError("Empty CREATE selection must not acquire AWS or validate IMPORT Mapping")


def check_no_create_resources_never_acquires(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    setup(root, ["iam"], ["IAM.Role"])
    path = root / "model/preview/team/iam.properties"
    write_model(path, resource_values("001", "IAM.Role", "imported", "IMPORT", [("Unsupported", "old")]))
    target = {
        "environment": "preview", "directory": "team",
        "awsAccountId": "111111111111", "awsRegion": "ap-northeast-1",
        "awsProfile": "configured",
    }
    monkeypatch.setattr(aws, "Context", forbidden_acquisition)
    monkeypatch.setattr(aws._imports_aws_mapping_compare, "comparison", forbidden_acquisition)
    result = aws.run(root, [(target, path)], session_factory=forbidden_acquisition, create_only=True)
    assert result["exitCode"] == 0
    assert result["results"][0]["reason"] == "no CREATE Resources selected"
    assert result["results"][0]["apis"] == []
    with pytest.raises(ValueError):
        aws.run(root, [(target, path)], profile="conflicting", create_only=True)
    with pytest.raises(ValueError):
        aws.run(root, [({**target, "awsAccountId": "invalid"}, path)], create_only=True)


def observation(service, kind, attribute, key, value):
    return {
        "environment": "preview",
        "target": "team",
        "service": service,
        "status": "identifier",
        "resource": kind.replace(".", "_") + "_001",
        "resourceType": kind,
        "propertiesKey": kind + "." + attribute,
        "observationKey": key,
        "awsValue": value,
    }


@pytest.mark.parametrize(
    "service,kind,attribute,previous,identifier",
    [
        ("vpc", "EC2.VPC", "VpcId", None, "vpc-0123456789abcdef0"),
        ("route53", "Route53.HostedZone", "Id", "`PENDING_DEPLOY`", "Z0123456789"),
        ("route53", "Route53.HostedZone", "Id", "`ZOLD`", "Z0123456789"),
    ],
)
def check_direct_observation_cli(tmp_path, capsys, service, kind, attribute, previous, identifier):
    root = tmp_path / "repo"
    setup(root, [service], [kind])
    path = root / f"model/preview/team/{service}.properties"
    reference = json.dumps(
        {"$modelRef": {"logicalId": kind.replace(".", "_") + "_001", "attribute": attribute}}
    )
    values = resource_values("001", kind, "fixture", "CREATE", [(attribute, reference)])
    observed = "observed.row.001-001.value"
    if previous is not None:
        values[observed] = previous
    path.parent.mkdir(parents=True)
    for file, content in split(path, values, limit=5).items():
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))
    before = raw_model(path)
    part = before.locations[KEY][0]
    base = ["pull-observed", str(path)]
    assert model_cli(base) == 0
    snapshot = tmp_path / "inputs.json"
    snapshot.write_text(capsys.readouterr().out, encoding="utf-8")
    identifiers = tmp_path / "identifiers.json"
    identifiers.write_text(
        json.dumps([observation(service, kind, attribute, observed, identifier)]),
        encoding="utf-8",
    )
    arguments = [*base, "--snapshot", str(snapshot), "--observations", str(identifiers)]
    assert model_cli(arguments) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "planned", "paths": [str(part)]}
    assert part.read_bytes() == before.files[part].encode("utf-8")

    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "add", ".")
    git(root, "commit", "-qm", "baseline")
    declared = "\n".join(f"- `{name}`" for name in (TASK, part.relative_to(root)))
    start(
        root,
        TASK,
        "## Task contract\n- Task type: `design`\n- Task status: `running`\n"
        "- Workflow: `update`\n- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n"
        "## Required changes\n- [R1] observe\n## Acceptance checks\n- [R1] `exists:project.json`\n"
        f"## Validation scope\n- `preview/team/{service}`\n## Modified files\n"
        f"{declared}\n## Allowed paths\n{declared}\n",
    )
    command = [*arguments, "--task-file", TASK]
    project = root / "project.json"
    original_project = project.read_bytes()
    project.write_bytes(original_project + b"\n")
    assert model_cli(command) == 1
    assert "inputs changed since acquisition" in capsys.readouterr().err
    assert part.read_bytes() == before.files[part].encode("utf-8")
    project.write_bytes(original_project)
    assert model_cli(command) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "saved", "paths": [str(part)]}
    expected = patch(before.documents[part], {observed: f"`{identifier}`"})
    assert part.read_bytes() == expected.encode("utf-8")
    assert path.read_bytes() == before.files[path].encode("utf-8")
    assert model_cli(base) == 0
    snapshot.write_text(capsys.readouterr().out, encoding="utf-8")
    assert model_cli(arguments) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "planned", "paths": []}


@pytest.mark.parametrize(
    "source_mode,attribute,key,value",
    [
        ("IMPORT", "VpcId", "observed.row.001-001.value", "vpc-valid"),
        ("CREATE", "CidrBlock", "observed.row.001-001.value", "vpc-valid"),
        ("CREATE", "VpcId", "desired.row.001-001.value", "vpc-valid"),
        ("CREATE", "VpcId", "observed.row.001-001.value", "PENDING_DEPLOY"),
        ("CREATE", "VpcId", "observed.row.001-001.value", "arn:aws:ec2:::vpc/vpc-valid"),
    ],
)
def check_pull_observation_rejects_unwritable_values(tmp_path, source_mode, attribute, key, value):
    values = resource_values(
        "001", "EC2.VPC", "fixture", source_mode,
        [(attribute, '{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}')],
    )
    snapshot = SimpleNamespace(
        scope=SimpleNamespace(root=tmp_path, environment="preview", target="team", service="vpc"),
        authoritative=values, values=values,
    )
    with pytest.raises(ValueError):
        proposed_values(snapshot, [observation("vpc", "EC2.VPC", attribute, key, value)])


@pytest.mark.parametrize(
    "source,raw,available",
    [
        ("aws", "vpc-actual", True),
        ("model", "vpc-request", False),
        ("aws", aws.MISSING, False),
        ("aws", None, False),
    ],
)
def check_identifier_hint_requires_an_aws_result(monkeypatch, source, raw, available):
    prop = "EC2.VPC.VpcId"
    field = aws.Field("base")
    definition = SimpleNamespace(field=field, source=source)
    ctx = SimpleNamespace(comparison=lambda service: (None, {prop: definition}), trace=[])
    resource = SimpleNamespace(
        kind="EC2.VPC", number="001", spec={},
        model=SimpleNamespace(path=Path("vpc.properties"), locations={}),
        module=SimpleNamespace(sensitive=lambda name: False),
        rows=[("001-001", {"property": prop, "value": "model"})],
    )
    monkeypatch.setattr(
        aws._imports_aws_mapping_compare, "value", lambda *args: ({}, raw)
    )
    result = aws.compare_resource(ctx, resource)
    assert ("observationKey" in result[0]) is available
    if available:
        assert result[0]["status"] == "identifier"
        assert result[0]["awsValue"] == raw


@pytest.mark.parametrize("field", ["environment", "target", "service", "resource", "resourceType", "propertiesKey"])
def check_pull_observation_rejects_a_different_resource_or_scope(tmp_path, field):
    prop = "VpcId"
    key = "observed.row.001-001.value"
    values = resource_values(
        "001", "EC2.VPC", "fixture", "CREATE",
        [(prop, '{"$modelRef":{"logicalId":"EC2_VPC_001","attribute":"VpcId"}}')],
    )
    snapshot = SimpleNamespace(
        scope=SimpleNamespace(root=tmp_path, environment="preview", target="team", service="vpc"),
        authoritative=values, values=values,
    )
    item = observation("vpc", "EC2.VPC", prop, key, "vpc-valid")
    item[field] = "other"
    with pytest.raises(ValueError):
        proposed_values(snapshot, [item])


if __name__ == "__main__":
    raise SystemExit(run(__file__))
