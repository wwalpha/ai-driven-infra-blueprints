"""Offline Model audit integration; synthetic Models and a fake AWS executable."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import io
import os
import socket
import subprocess
import tempfile
from contextlib import redirect_stdout
from functools import partial
from unittest.mock import patch

from support.it_case_receipt import it_case
from support.model_test_runner import load_fixture, prepare
from support.repository_fixtures import contract
from task_contract_core import SELECTOR, task_revision

from model import audit as generator

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def generation_only(real_run, command, **kwargs):
    assert command[0] == "git", "generation attempted an external operation"
    return real_run(command, **kwargs)


def change_contract(text, prompt, *args):
    prompt.write_text(text.replace("`running`", "`completed`"), encoding="utf-8")
    return "changed source", {}, []


@it_case
def check_cli_contract():
    inputs, _expected = load_fixture("audit/base")
    with tempfile.TemporaryDirectory(prefix="audit-cli-") as directory:
        root = Path(directory)
        offline = partial(generation_only, subprocess.run)
        with (
            patch.object(
                socket,
                "create_connection",
                side_effect=AssertionError("network forbidden"),
            ),
            patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("network forbidden"),
            ),
            patch.object(subprocess, "run", side_effect=offline),
        ):
            source = prepare(root, inputs)
            name = "tasks/audit.md"
            prompt = root / name
            prompt.parent.mkdir()
            contract_text = (
                contract("audit", ["tests/dev/cde/vpc.py"])
                .replace("`governance`", "`migration`")
                .replace("`framework`", "`dev/cde/vpc`")
            )
            prompt.write_text(contract_text)
            output = root / "tests/dev/cde/vpc.py"
            arguments = [
                "model/cli.py",
                "--repository-root",
                str(root),
                "--environment",
                "dev",
                "--target",
                "cde",
                "--service",
                "vpc",
                "--task-file",
                name,
            ]
            with (
                patch.object(generator, "ROOT", root),
                patch.dict(os.environ, {SELECTOR: name}),
                patch.object(sys, "argv", arguments),
                redirect_stdout(io.StringIO()) as messages,
            ):
                assert generator.main() == 0, messages.getvalue()
                before = output.read_bytes()
                assert before.decode() == source
                for state in ("completed", "suspend"):
                    prompt.write_text(
                        contract_text.replace("`running`", f"`{state}`")
                        + (
                            "\n## Suspension reason\nExplicit test stop\n"
                            if state == "suspend"
                            else ""
                        )
                    )
                    if state == "completed":
                        assert task_revision(root, name)[1] == prompt.read_text()
                    assert generator.main() == 2 and output.read_bytes() == before
                    output.unlink()
                    assert generator.main() == 2 and not output.exists()
                    output.write_bytes(before)
                prompt.write_text(contract_text)
                change = partial(change_contract, contract_text, prompt)
                with patch.object(generator, "generate", side_effect=change):
                    assert generator.main() == 2 and output.read_bytes() == before
                prompt.unlink()
                assert generator.main() == 2 and output.read_bytes() == before


if __name__ == "__main__":
    check_cli_contract()
