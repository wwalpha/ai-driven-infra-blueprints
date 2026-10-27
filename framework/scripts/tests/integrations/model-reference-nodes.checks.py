"""Design artifact and Markdown round-trip through typed cross-service references."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from design.policy_tables import rendered_design
from model.projection import generated_document, reference_resolver
from model.render import generate_files, generate_markdown
from model.sources import load_model
from support.it_case_receipt import it_case
from support.model_reference_fixtures import FRAMEWORK, project, save
from sync_files import save_files
from utils.aws_mappings import mapping_alias
from utils.json_format import validate_aws_document

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@it_case
def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        with mapping_alias(FRAMEWORK, root):
            producer, values, consumer, policy = project(root)
            view = root / "docs/designs/qa/team/iam.md"
            artifact = view.with_suffix("") / "policy.json"
            original = consumer.path.read_bytes()
            for observed, expected in [
                (None, "unresolved"),
                ("PENDING_DEPLOY", "PENDING_DEPLOY"),
                (
                    "12345678-1234-1234-1234-123456789012",
                    "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                ),
            ]:
                if observed is not None:
                    values["desired.row.001-001.property"] = "KMS.Key.KeyId"
                    values["observed.row.001-001.value"] = "`" + observed + "`"
                    save(producer, values)
                if observed not in (None, "PENDING_DEPLOY"):
                    producer_view = view.with_name("kms.md")
                    producer_view.parent.mkdir(parents=True, exist_ok=True)
                    producer_view.write_text(
                        generate_markdown(
                            producer_view, load_model(producer).values, root
                        ),
                        encoding="utf-8",
                    )
                snapshot = load_model(consumer)
                markdown = generate_markdown(view, snapshot.values, root)
                if observed in (None, "PENDING_DEPLOY"):
                    assert "$modelRef" in markdown and "KMS_Key_001" in markdown
                else:
                    assert "$modelRef" not in markdown
                    assert "](kms.md#saved-001)" in markdown
                files = generate_files(view, snapshot.values, root)
                save_files(files)
                display = rendered_design(view, definitions_root=FRAMEWORK)
                assert display == markdown
                if observed != "PENDING_DEPLOY":
                    assert expected not in display
                document = json.loads(artifact.read_bytes())
                assert document["Statement"][0]["Resource"] == (
                    json.loads(policy["desired.row.001-002.document"])["Statement"][0][
                        "Resource"
                    ]
                    if observed is None
                    else expected
                )
                if observed is not None:
                    assert "$modelRef" not in json.dumps(document)
                    validate_aws_document(document)
                contract = dict(
                    resolver=reference_resolver(snapshot.values, consumer, root),
                    scope=consumer,
                    property_name="IAM.ManagedPolicy.PolicyDocument",
                )
                assert document == generated_document(
                    json.loads(policy["desired.row.001-002.document"]), root, **contract
                )
                assert consumer.path.read_bytes() == original
                assert load_model(consumer).authoritative == policy
                assert "$modelRef" in policy["desired.row.001-002.document"]
    print("Model reference round-trip: PASS")


if __name__ == "__main__":
    main()
