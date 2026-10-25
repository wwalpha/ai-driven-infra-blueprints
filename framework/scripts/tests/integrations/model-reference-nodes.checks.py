"""Design artifact and Markdown round-trip through typed cross-service references."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from design.policy_tables import rendered_design
from model.projection import json_sha256
from model.render import generate_files, generate_markdown
from model.sources import load_model
from support.it_case_receipt import it_case
from support.model_reference_fixtures import FRAMEWORK, project, save
from sync_files import save_files
from utils.aws_mappings import mapping_alias
from utils.json_format import document_sha256, validate_aws_document

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
                ("PENDING_DEPLOY", "pending_deploy"),
                (
                    "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                    "arn:aws:kms:ap-northeast-1:123456789012:key/12345678-1234-1234-1234-123456789012",
                ),
            ]:
                if observed is not None:
                    values["observed.row.001-001.value"] = "`" + observed + "`"
                    save(producer, values)
                snapshot = load_model(consumer)
                markdown = generate_markdown(view, snapshot.values, root)
                assert "$modelRef" not in markdown and expected in markdown
                if observed in (None, "PENDING_DEPLOY"):
                    try:
                        generate_files(view, snapshot.values, root)
                    except ValueError as error:
                        assert expected in str(
                            error
                        ) and "/Statement/0/Resource" in str(error)
                    else:
                        raise AssertionError(
                            "unresolved reference generated an artifact"
                        )
                    assert not artifact.exists() and not view.exists()
                    continue
                files = generate_files(view, snapshot.values, root)
                save_files(files)
                display = rendered_design(view, definitions_root=FRAMEWORK)
                assert "$modelRef" not in display and expected in display
                document = json.loads(artifact.read_bytes())
                assert document["Statement"][0]["Resource"] == expected
                assert json_sha256(artifact) == document_sha256(document)
                validate_aws_document(document)
                assert consumer.path.read_bytes() == original
                assert load_model(consumer).authoritative == policy
                assert "$modelRef" in policy["desired.row.001-002.document"]
    print("Model reference round-trip: PASS")


if __name__ == "__main__":
    main()
