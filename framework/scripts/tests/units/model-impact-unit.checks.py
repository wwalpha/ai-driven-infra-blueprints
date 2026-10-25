"""Pure semantic diff and traversal checks; no Git, saved Model or AWS access."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from types import SimpleNamespace

from model.impact_changes import changed_nodes, configurations, node
from model.impact_graph import Graph
from validation.task import TaskValidation

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

SCOPE = ("dev", "team", "iam")


def values(number="001", row="001", ref="first"):
    return {
        "desired.service.identity.lastAllocated": '{"IAM.Role":1}',
        f"desired.resource.{number}.logicalId": "IAM_Role_001",
        f"desired.resource.{number}.resourceType": "IAM.Role",
        f"desired.row.{number}-{row}.property": "IAM.Role.RoleName",
        f"desired.row.{number}-{row}.value": "role",
        f"desired.row.{number}-{row}.comment": "comment",
        f"desired.reference.{ref}.consumerKey": f"desired.row.{number}-{row}.value",
        f"desired.reference.{ref}.text": "role",
        f"desired.reference.{ref}.occurrence": "1",
        f"desired.reference.{ref}.producerKind": "resource",
        f"desired.reference.{ref}.producerScope": "dev/team/other",
        f"desired.reference.{ref}.producerLogicalId": "IAM_Role_001",
        f"desired.reference.{ref}.resourceType": "IAM.Role",
        f"desired.reference.{ref}.property": "IAM.Role.RoleName",
        f"desired.reference.{ref}.format": "name",
        f"desired.reference.{ref}.labelPolicy": "none",
    }


def check_internal_ids_and_comments():
    old = SimpleNamespace(authoritative=values())
    new = SimpleNamespace(authoritative=values("007", "009", "second"))
    new.authoritative["desired.row.007-009.comment"] = "new comment"
    new.authoritative["display.resource.007.label"] = "display only"
    assert configurations(old) == configurations(new)
    assert changed_nodes({SCOPE}, {SCOPE: old}, {SCOPE: new}, []) == set()
    new.authoritative["desired.row.007-009.value"] = "different-role"
    del_keys = [
        key for key in new.authoritative if key.startswith("desired.reference.")
    ]
    for key in del_keys:
        del new.authoritative[key]
    assert changed_nodes({SCOPE}, {SCOPE: old}, {SCOPE: new}, []) == {
        node(SCOPE, "resource", "IAM_Role_001")
    }


def check_minimal_fallback_and_cycles():
    graph = Graph()
    first, second = node(SCOPE, "resource", "Role1"), node(SCOPE, "resource", "Role2")
    target = node(("dev", "team", "consumer"), "resource", "Consumer1")
    graph.add(first, target)
    graph.add(target, first)
    assert graph.traverse({second}) == {second}
    assert graph.traverse({first}) == {first, target}
    graph.add(node(SCOPE), target)
    assert target in graph.traverse({second})
    assert target in graph.traverse({node(SCOPE)})


def check_invalid_baseline_and_counter():
    old = SimpleNamespace(authoritative=values())
    new = SimpleNamespace(authoritative=values())
    new.authoritative["desired.service.identity.lastAllocated"] = '{"IAM.Role":2}'
    reasons = []
    assert changed_nodes({SCOPE}, {SCOPE: old}, {SCOPE: new}, reasons) == {node(SCOPE)}
    assert reasons[0]["reason"] == "unexplained allocation change"
    reasons = []
    assert changed_nodes(
        {SCOPE}, {SCOPE: ValueError("bad old bytes")}, {SCOPE: old}, reasons
    ) == {node(SCOPE)}
    assert "uncomparable" in reasons[0]["reason"]


def check_design_requires_changed_authority():
    failures = []
    findings = SimpleNamespace(
        check=lambda passed, message: failures.append(message) if not passed else None,
        relative=lambda path: str(path),
    )
    task = TaskValidation(Path("/synthetic"), findings)
    task.task_type = "design"
    task.contract_text = "## Task contract\n- Workflow: `update`\n"
    task.design_impact = {SCOPE}
    task.changed_paths = {"project.json"}
    task.check_task_type_requirements()
    assert failures == [
        "design task must change authoritative properties service inputs"
    ]
    failures.clear()
    task.changed_paths = {"model/dev/team/iam.properties"}
    task.check_task_type_requirements()
    assert not failures


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
