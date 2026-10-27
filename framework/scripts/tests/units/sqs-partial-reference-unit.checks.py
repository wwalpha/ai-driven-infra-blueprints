"""SQS partial display uses the complete candidate reference snapshot."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from design.document import model_resource_reference_tables
from model.core import ReferenceDiagnosticError
from model.format import owner
from model.projection import reference_display, validate_json_documents
from model.render import generate_markdown
from support.model_reference_fixtures import (
    FRAMEWORK,
    project,
    reference,
    resource,
    save,
)
from support.pytest_cli import run
from utils.aws_mappings import mapping_alias

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.fixture
def sqs(tmp_path):
    with mapping_alias(FRAMEWORK, tmp_path):
        project(tmp_path)
        scope, queue = resource(tmp_path, "sqs", "SQS.Queue", attribute="QueueName")
        queue["desired.row.001-001.value"] = "`synthetic-queue`"
        _, policy = resource(
            tmp_path, "sqs", "SQS.QueuePolicy", attribute="Queues[]", number="002"
        )
        values = {
            **queue,
            **{
                key: value
                for key, value in policy.items()
                if owner(key, policy)[0] == "resource"
            },
            "desired.service.identity.lastAllocated": '{"SQS.Queue": 1, "SQS.QueuePolicy": 1}',
            "desired.resource.002.logicalId": "SQS_QueuePolicy_001",
            "desired.service.sqs.ownedCatalogResourceTypes": "SQS.Queue,SQS.QueuePolicy",
            "desired.row.002-001.value": '`["https://sqs.ap-northeast-1.amazonaws.com/123456789012/synthetic-queue"]`',
            "desired.row.002-002.property": "SQS.QueuePolicy.PolicyDocument",
            "desired.row.002-002.value": "[Policy](sqs/policy.json)",
            "desired.row.002-002.comment": "合成ポリシー",
            "desired.row.002-002.document": json.dumps(
                {
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": "*",
                            "Action": "sqs:SendMessage",
                            "Resource": reference("SQS_Queue_001", "Arn"),
                        }
                    ]
                }
            ),
        }
        save(scope, values)
        path = tmp_path / "docs/designs/qa/team/sqs.md"
        yield scope, path, values


def policy_result(path, markdown, values):
    return dict(
        (anchor, (tables, error))
        for anchor, tables, error in model_resource_reference_tables(
            path, markdown, values, FRAMEWORK
        )
    )["saved-002"]


def check_other_group_producer(sqs):
    _, path, values = sqs
    markdown = generate_markdown(path, values, FRAMEWORK)
    tables, error = policy_result(path, markdown, values)
    assert error is None, error
    assert {r.logical_id for table in tables for r in table.resources} == {
        "SQS_QueuePolicy_001"
    }


def check_deleted_candidate_producer(sqs):
    scope, path, values = sqs
    markdown = generate_markdown(path, values, FRAMEWORK)
    candidate = {
        key: value
        for key, value in values.items()
        if owner(key, values) != ("resource", "001")
    }
    # Only the candidate policy block remains; the old authority stays on disk.
    from_block = markdown.index("<!-- resource-logical-id: SQS_QueuePolicy_001 -->")
    markdown = "## リソース詳細\n\n" + markdown[from_block:]
    tables, error = policy_result(path, markdown, candidate)
    assert tables is None and "Model expected display" in str(error)
    projected = generate_markdown(path, candidate, FRAMEWORK)
    assert "$modelRef" in projected and "[synthetic-queue](#saved-001)" not in projected
    with pytest.raises(ReferenceDiagnosticError) as invalid:
        validate_json_documents(candidate, scope.path)
    assert any(
        d["code"] == "MODEL_REF_TARGET_MISSING" for d in invalid.value.diagnostics
    )
    assert "SQS_Queue_001" in scope.path.read_text(encoding="utf-8")


def check_candidate_producer_attribute(sqs):
    scope, path, values = sqs
    candidate = {**values, "desired.row.001-001.value": "`candidate-queue`"}
    markdown = generate_markdown(path, candidate, FRAMEWORK)
    assert "[candidate-queue](#saved-001)" in markdown
    tables, error = policy_result(path, markdown, candidate)
    assert error is None, error
    selected = {
        key: value
        for key, value in candidate.items()
        if owner(key, candidate) != ("resource", "001")
    }
    displayed = reference_display(
        selected, path, scope.root, reference_values=candidate
    )
    assert (
        json.loads(displayed["desired.row.002-002.document"])["Statement"][0][
            "Resource"
        ]
        == "arn:aws:sqs:ap-northeast-1:123456789012:candidate-queue"
    )
    assert tables
    assert "synthetic-queue" in scope.path.read_text(encoding="utf-8")


def check_unrelated_group_generation_failure(sqs):
    _, path, values = sqs
    candidate = dict(values)
    candidate.update(
        {
            key.replace(".002", ".003", 1): value
            for key, value in values.items()
            if owner(key, values) == ("resource", "002")
        }
    )
    candidate.update(
        {
            "desired.service.identity.lastAllocated": '{"SQS.Queue": 1, "SQS.QueuePolicy": 2}',
            "desired.resource.003.logicalId": "SQS_QueuePolicy_002",
            "desired.resource.003.anchor": "saved-003",
            "desired.row.003-002.value": "[Policy](sqs/unrelated.json)",
            "desired.row.003-002.document": json.dumps(
                {
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": "sqs:SendMessage",
                            "Resource": "*",
                            "Principal": "*",
                        }
                    ]
                }
            ),
        }
    )
    markdown = generate_markdown(path, candidate, FRAMEWORK)
    assert "### SQS.QueuePolicy: SQS_QueuePolicy_001" in markdown
    tables, error = policy_result(path, markdown, candidate)
    assert error is None, error
    assert tables
    candidate["desired.row.003-001.extra"] = "invalid display row"
    with pytest.raises(ValueError, match="invalid resource row"):
        generate_markdown(path, candidate, FRAMEWORK)
    tables, error = policy_result(path, markdown, candidate)
    assert error is None, error
    assert tables


if __name__ == "__main__":
    raise SystemExit(run(__file__))
