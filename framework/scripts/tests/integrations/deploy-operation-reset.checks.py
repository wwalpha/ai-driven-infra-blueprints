"""Real Reset files, CLI and persistence interruptions; no live AWS calls."""

import json
import sys
import tempfile
from functools import partial
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import current_state
from deploy import operation_journal as J
from deploy import operation_reset as R
from support.pytest_cli import run
from utils.file_operations import atomic_replace_file
from utils.json_format import fingerprint

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

TARGET = {
    "awsAccountId": "123456789012",
    "awsRegion": "ap-northeast-1",
    "iacEngine": "cloudformation",
}


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "project.json").write_text(
        json.dumps({"targets": [{"environment": "dev", **TARGET}]}), encoding="utf-8"
    )
    directory = tmp_path / "operations"
    directory.mkdir(mode=0o700)
    journal = directory / "journal.json"
    atomic_replace_file(journal, b"{damaged-old-record", mode=0o600)
    (directory / "resets").mkdir(mode=0o700)
    fence = directory / "resets" / ("b" * 64)
    fence.mkdir(parents=True, mode=0o700)
    atomic_replace_file(fence / "plan.json", b"{damaged-old-fence", mode=0o600)
    with patch.object(J, "location", return_value=journal):
        yield root, journal, fence


@pytest.mark.parametrize("legacy", [None, b"{}", b"{broken"])
def check_reset_once_ignores_legacy_storage(tmp_path, monkeypatch, legacy):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "project.json").write_text(
        json.dumps({"targets": [{"environment": "dev", **TARGET}]}), encoding="utf-8"
    )
    old = tmp_path / (
        "blueprint-cfn-operations-"
        + fingerprint([TARGET["awsAccountId"], TARGET["awsRegion"]])
    )
    if legacy is not None:
        old.mkdir(mode=0o700)
        atomic_replace_file(old / "journal.json", legacy, mode=0o600)
    journal = J.location(TARGET)
    journal.parent.mkdir(mode=0o700)
    current = journal.parent / "request-current.json"
    atomic_replace_file(current, b"{}", mode=0o600)
    document = R.plan(root, "dev", TARGET["awsAccountId"], None, "all")
    result, count = human_apply(root, document)
    assert result["result"] == "APPLIED" and count == 1
    assert not current.exists()
    if legacy is not None:
        assert (old / "journal.json").read_bytes() == legacy
    else:
        assert not old.exists()


def check_empty_reset_completes_once(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    root = tmp_path / "repo"
    root.mkdir()
    (root / "project.json").write_text(
        json.dumps({"targets": [{"environment": "dev", **TARGET}]}), encoding="utf-8"
    )
    document = R.plan(root, "dev", TARGET["awsAccountId"], None, "all")
    result, count = human_apply(root, document)
    assert not document["files"] and result["result"] == "APPLIED" and count == 1


def human_apply(root, document):
    with (
        patch.object(sys.stdin, "isatty", return_value=True),
        patch.object(sys.stdout, "isatty", return_value=True),
        patch("builtins.input", return_value=R.challenge(document)) as consent,
    ):
        result = R.apply(root, "dev", TARGET["awsAccountId"], None, document["id"])
    return result, consent.call_count


def interrupt_save(real, boundary, seen, path, content):
    if path.name == boundary and not seen:
        seen.append(path)
        raise InterruptedError("injected persistence interruption")
    return real(path, content)


def interrupt_delete(real, journal, seen, path, content, **kwargs):
    result = real(path, content, **kwargs)
    if path == journal and not seen:
        seen.append(path)
        atomic_replace_file(journal, b'{"newRequest":"not-approved"}', mode=0o600)
        raise InterruptedError("injected after deletion")
    return result


def check_one_reset_handles_corrupt_records_and_related_fences(workspace):
    root, journal, fence = workspace
    original, old_fence = journal.read_bytes(), (fence / "plan.json").read_bytes()
    document = R.plan(root, "dev", TARGET["awsAccountId"], None, "all")
    with patch(
        "utils.aws.client.client", side_effect=AssertionError("Reset must not call AWS")
    ):
        result, count = human_apply(root, document)
    case = TestCase()
    case.assertEqual(count, 1)
    case.assertEqual(result["result"], "APPLIED")
    case.assertEqual(
        json.loads(journal.read_text()), {"protocol": "current-request-v2"}
    )
    case.assertFalse((fence / "plan.json").exists())
    archive = Path(result["archive"])
    case.assertEqual((archive / "originals/journal.json").read_bytes(), original)
    case.assertEqual(
        (archive / "originals" / "resets" / fence.name / "plan.json").read_bytes(),
        old_fence,
    )
    with patch.object(
        R, "confirm", side_effect=AssertionError("same approval must be reused")
    ):
        case.assertEqual(
            R.apply(root, "dev", TARGET["awsAccountId"], None, document["id"])[
                "result"
            ],
            "ALREADY_APPLIED",
        )
    case.assertEqual(current_state.classify("UPDATE_IN_PROGRESS"), "RUNNING")


@pytest.mark.parametrize(
    "boundary", ["approval.json", "journal.json", "prepared.json", "result.json"]
)
def check_reset_resumes_each_persistence_boundary(workspace, boundary):
    root, journal, _ = workspace
    document = R.plan(root, "dev", TARGET["awsAccountId"], None, "all")
    seen = []
    with patch.object(
        R, "save_once", partial(interrupt_save, R.save_once, boundary, seen)
    ):
        with pytest.raises(InterruptedError):
            human_apply(root, document)
    approved = (journal.parent / "resets" / document["id"] / "approval.json").exists()
    new_request = (
        b'{"new":"outside-original-approval"}' if boundary == "journal.json" else None
    )
    if new_request:
        atomic_replace_file(journal, new_request, mode=0o600)
    if approved:
        if boundary == "prepared.json":
            project = json.loads((root / "project.json").read_text())
            project["targets"].append(
                {
                    "environment": "qa",
                    "awsAccountId": "999999999999",
                    "awsRegion": "ap-northeast-1",
                    "iacEngine": "cloudformation",
                }
            )
            (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
        with patch.object(
            R, "confirm", side_effect=AssertionError("approval repeated")
        ):
            result = R.apply(root, "dev", TARGET["awsAccountId"], None, document["id"])
    else:
        result, _ = human_apply(root, document)
    TestCase().assertEqual(result["result"], "APPLIED")
    TestCase().assertEqual(
        journal.read_bytes() if new_request else json.loads(journal.read_text()),
        new_request if new_request else {"protocol": "current-request-v2"},
    )


def check_new_request_survives_retry_after_missing_result(workspace):
    root, journal, _ = workspace
    document = R.plan(root, "dev", TARGET["awsAccountId"], None, "all")
    with (
        patch.object(
            R,
            "atomic_replace_file",
            side_effect=partial(interrupt_delete, R.atomic_replace_file, journal, []),
        ),
        pytest.raises(InterruptedError),
    ):
        human_apply(root, document)
    new = journal.read_bytes()
    with patch.object(R, "confirm", side_effect=AssertionError("approval repeated")):
        result = R.apply(root, "dev", TARGET["awsAccountId"], None, document["id"])
    TestCase().assertEqual(result["result"], "APPLIED")
    TestCase().assertEqual(journal.read_bytes(), new)


def check_legacy_fence_cli_uses_the_same_reset(workspace, monkeypatch):
    root, journal, fence = workspace
    atomic_replace_file(
        fence / "plan.json",
        json.dumps({"payload": {"removedRecords": [{"operations": {"Affected": {}}}]}}),
        mode=0o600,
    )
    atomic_replace_file(fence / "original.bin", b"old backup", mode=0o600)
    affected = journal.parent / "request-affected.json"
    unrelated = journal.parent / "request-unrelated.json"
    atomic_replace_file(affected, '{"name":"Affected"}', mode=0o600)
    atomic_replace_file(unrelated, '{"name":"Unrelated"}', mode=0o600)
    monkeypatch.chdir(root)
    TestCase().assertEqual(
        R.main(
            [
                "fence-plan",
                "--environment",
                "dev",
                "--aws-account-id",
                TARGET["awsAccountId"],
                "--fence",
                fence.name,
            ]
        ),
        0,
    )
    plan_file = next((journal.parent / "reset-plans").glob("*.json"))
    value = R.load_plan(journal, plan_file.stem)
    with (
        patch.object(sys.stdin, "isatty", return_value=True),
        patch.object(sys.stdout, "isatty", return_value=True),
        patch("builtins.input", return_value=R.challenge(value)),
    ):
        TestCase().assertEqual(
            R.main(
                [
                    "fence-apply",
                    "--environment",
                    "dev",
                    "--aws-account-id",
                    TARGET["awsAccountId"],
                    "--plan",
                    value["id"],
                ]
            ),
            0,
        )
    TestCase().assertFalse((fence / "plan.json").exists())
    TestCase().assertTrue(journal.exists())
    TestCase().assertFalse((fence / "original.bin").exists())
    TestCase().assertFalse(affected.exists())
    TestCase().assertTrue(unrelated.exists())


if __name__ == "__main__":
    raise SystemExit(run(__file__))
