#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.deploy_preparation_fixtures import *
from contextlib import chdir


@it_case
def check_preparation():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory).resolve()
        root = base / "repo"
        fixture(root)
        original = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        with chdir(root):
            assert invoke(arguments(root, base)[2:]) == 0
        run = next((base / "logs").iterdir())
        path = run / "preparation.json"
        plan = json.loads(path.read_text(encoding="utf-8"))
        assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == original
        assert plan["controllerArgv"].count("--stack") == 2
        assert "--repository-root" not in plan["controllerArgv"]
        assert not (root / "framework").exists()
        assert "--sequential" in plan["controllerArgv"] and "--timing-log" in plan["controllerArgv"]
        assert plan["controllerArgv"][0] == sys.executable
        assert plan["scope"] == ["dev/123456789012/cloudformation-stacks", "dev/123456789012/ec2", "dev/123456789012/iam"]
        text = (run / "contract.md").read_text(encoding="utf-8")
        declared = paths_in(text, "## Modified files")
        from model.sources import model_parts, source_inputs
        outputs = {p.relative_to(root).as_posix() for p in model_parts(root / "model/dev/123456789012/ec2.properties")}
        assert outputs <= declared
        assert "model/dev/123456789012/iam.properties" in declared
        assert not any(p.endswith(("observed.json", "source.json", ".tpl")) for p in declared)
        assert not {p for p in declared if p.startswith('infra/')}
        assert '- Runtime recovery: `allowed`' in text
        assert '- External IaC repair: `forbidden`' in text
        assert f'- Deploy repair session: `{run / "session.json"}`' in text
        for document in plan["documents"]:
            assert all(len(Path(chunk).read_text(encoding="utf-8")) <= 6000 for chunk in document["chunks"])
        documents = {d["source"]: d for d in plan["documents"]}
        generated = {"docs/designs/dev/123456789012/" + name for name in
                     ("ec2.md", "iam.md", "cloudformation-stacks.md", "iam/worker-role-trust-policy.json")}
        assert plan["generatedViews"] == sorted(generated)
        assert generated <= plan["inputs"].keys() and generated <= declared
        assert not generated & documents.keys()
        for relative, digest in plan["inputs"].items():
            assert digest == hashlib.sha256(((ROOT if relative.startswith(("framework/", ".agents/")) else root) / relative).read_bytes()).hexdigest()
        assert {Path(c) for d in plan["documents"] for c in d["chunks"]} == {p.resolve() for p in (run / "documents").iterdir()} | {run / "target-summary.json"}
        assert len(documents) == len(plan["documents"])
        entrance = root / "model/dev/123456789012/ec2.properties"
        assert all(p.relative_to(root).as_posix() in plan['inputs'] for p in source_inputs(entrance))
        assert any(name.startswith('model/') for name in documents)
        assert any(name.startswith('infra/') for name in documents)
        assert 'AGENTS.md' in documents and 'target-summary' in documents
        assert all(name in plan['controllerArgv'] for name in STACKS)
        assert 'readingCharacters' not in plan and 'readingStages' not in plan
        assert all('readCharacters' not in doc for doc in plan['documents'])
        assert "framework/rules/task-contract.md" in documents
        assert "framework/rules/issue-gate.md" in documents
        assert "framework/rules/project-configuration.md" in documents
        assert "framework/rules/terraform.md" not in documents and "README.md" not in documents
        assert invoke(["--repository-root", str(root), "--register", str(path)]) == 0
        registered = contracts(root)["tasks/deploy-offline.md"]
        assert paths_in(registered, "## Modified files") == paths_in(text, "## Modified files")
        assert invoke(arguments(root, base)) == 1  # Registered tasks keep the existing resume path.
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(plan["controllerArgv"], 2)) as launch:
            assert M.main(["--repository-root", str(root), "--run-controller", str(path)]) == 2
            assert launch.call_count == 1 and launch.call_args.args[0] == plan["controllerArgv"]
            assert launch.call_args.kwargs["env"]["BLUEPRINT_TASK_FILE"] == "tasks/deploy-offline.md"
        plan = json.loads(path.read_text(encoding="utf-8"))
        original_command = plan["controllerArgv"][:]
        for command in ([str(base / "other-python"), *original_command[1:]],
                        [original_command[0], str(base / "other-controller.py"), *original_command[2:]],
                        [*original_command[:2], "--repository-root", str(root), *original_command[2:]],
                        [*original_command, "--repository-root=" + str(root)]):
            plan["controllerArgv"] = command
            path.write_text(json.dumps(plan), encoding="utf-8")
            with patch.object(subprocess, "run", side_effect=AssertionError("foreign Project launched")), redirect_stderr(io.StringIO()):
                assert M.main(["--repository-root", str(root), "--run-controller", str(path)]) == 1
        plan["controllerArgv"] = original_command
        for field, value in (("repository", str(base / "other")), ("registeredContractDigest", "changed")):
            saved = plan[field]
            plan[field] = value
            path.write_text(json.dumps(plan), encoding="utf-8")
            with patch.object(subprocess, "run", side_effect=AssertionError("unapproved plan launched")), redirect_stderr(io.StringIO()):
                assert M.main(["--repository-root", str(root), "--run-controller", str(path)]) == 1
            plan[field] = saved
        path.write_text(json.dumps(plan), encoding="utf-8")
        events = [json.loads(line) for line in (run / "timing.jsonl").read_text().splitlines()]
        assert {"environment", "contractPreparation", "documentRead", "documentReview", "contractRegistration"} <= {e["phase"] for e in events}
        assert all(e["result"] == "PASS" and e["seconds"] >= 0 for e in events)
        assert all("aws" not in e["phase"].lower() for e in events)
        (run / "session.json").write_text("{}", encoding="utf-8")
        with patch.object(subprocess, "run", side_effect=AssertionError("existing session restarted")), redirect_stderr(io.StringIO()):
            assert M.main(["--repository-root", str(root), "--run-controller", str(path)]) == 1
        print("Offline preparation: required bodies, input fingerprints and audit timing verified")


@it_case
def check_stale_and_conflicts():
    for reason in ("issue", "runtime", "candidate", "model", "markdown-change",
                   "markdown-delete", "json-change", "json-delete"):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "repo"
            fixture(root)
            assert invoke(arguments(root, base)) == 0
            run = next((base / "logs").iterdir())
            path = run / "preparation.json"
            if reason.startswith(("markdown-", "json-")):
                generated = root / "docs/designs/dev/123456789012" / ("iam/worker-role-trust-policy.json" if reason.startswith("json-") else "ec2.md")
                if reason.endswith("delete"):
                    generated.unlink()
                else:
                    generated.write_text("changed", encoding="utf-8")
            elif reason == "model":
                source = root / "model/dev/123456789012/iam.properties"
                write_model(source, read_model(source) + "# changed\n")
            elif reason == "issue":
                issue = root / "issues/dev/123456789012/issues.md"
                issue.parent.mkdir(parents=True)
                issue.write_text("### ec2\n1. 未解決\n", encoding="utf-8")
            elif reason == "candidate":
                (run / "contract.md").write_text("changed", encoding="utf-8")
            with patch.dict(M.os.environ, {"PATH": "changed"}) if reason == "runtime" else patch.dict(M.os.environ, {}):
                result = invoke(["--repository-root", str(root), "--register", str(path)])
                assert result == 1, reason
            assert json.loads((run / "timing.jsonl").read_text().splitlines()[-1])["result"] == "FAIL"


@it_case
def check_generated_boundaries():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory).resolve()
        root = base / "repo"
        fixture(root)
        source = root / "model/dev/123456789012/iam.properties"
        from model.sources import load_model
        from model.format import serialize
        original = serialize(load_model(source).authoritative)
        write_model(source, "\n".join(line for line in original.splitlines() if ".document=" not in line) + "\n")
        try:
            M.candidate(root, "tasks/deploy-offline.md", "dev", "123456789012", TARGET, STACKS, ["iam"])
        except ValueError as error:
            assert all(value in str(error) for value in ("authoritative JSON document missing", "resource 001", "row 001-002", "iam/worker-role-trust-policy.json"))
        else:
            raise AssertionError("missing document accepted")
        write_model(source, original)
        write_model(source, original.replace("iam/worker-role-trust-policy.json", "ec2/worker-role-trust-policy.json"))
        try:
            M.candidate(root, "tasks/deploy-offline.md", "dev", "123456789012", TARGET, STACKS, ["iam"])
        except ValueError as error:
            assert "belong to selected service" in str(error)
        else:
            raise AssertionError("foreign JSON accepted")
        write_model(source, original)
        real_load = M.load_units
        artifacts = root / "infra/cloudformation/artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "execution.json").write_text('{"StartAt":"Done"}', encoding="utf-8")
        with zipfile.ZipFile(artifacts / "build.zip", "w") as archive:
            archive.writestr("main.py", "pass")
        def load_with_artifacts(*args):
            limit, units = real_load(*args)
            units[0]["artifacts"] = [
                {"source": "infra/cloudformation/artifacts/execution.json", "property": "DefinitionS3Location"},
                {"source": "infra/cloudformation/artifacts/build.zip", "property": "Code"},
            ]
            return limit, units
        with patch.object(M, 'load_units', side_effect=load_with_artifacts):
            assert invoke(arguments(root, base)) == 0
        run = next((base / "logs").iterdir())
        plan = json.loads((run / "preparation.json").read_text(encoding="utf-8"))
        documents = {d["source"] for d in plan["documents"]}
        assert "infra/cloudformation/artifacts/execution.json" in documents
        assert "infra/cloudformation/artifacts/execution.json" in plan["inputs"]
        assert "infra/cloudformation/artifacts/build.zip" not in documents
        assert "infra/cloudformation/artifacts/build.zip" in plan["inputs"]
        assert "infra/cloudformation/artifacts/build.zip" not in plan["generatedViews"]
        for relative, digest in plan["inputs"].items():
            assert digest == M.sha((ROOT if relative.startswith(("framework/", ".agents/")) else root) / relative)
        with patch.object(M, "paths", return_value=(root / "docs/designs/dev/123456789012/iam/worker-role-trust-policy.json", artifacts / "execution.json")), patch.object(M, "deployment_input_paths", return_value=[root / "docs/designs/dev/123456789012/iam/worker-role-trust-policy.json"]):
            output = io.StringIO()
            with redirect_stderr(output):
                assert M.main(arguments(root, base)) == 1
            assert "generated view conflicts with execution/required input" in output.getvalue()
        view = root / "docs/designs/dev/123456789012/cloudformation-stacks.md"
        original_view = view.read_text(encoding="utf-8")
        view.write_text(original_view + "changed", encoding="utf-8")
        try:
            real_load(root, "dev", "123456789012", STACKS)
        except Exception as error:
            assert "stack model/generated design mismatch" in str(error)
        else:
            raise AssertionError("stack mismatch accepted")
        view.write_text(original_view, encoding="utf-8")
        parameter = root / "infra/cloudformation/parameters/dev/123456789012/1.json"
        parameter.unlink()
        parameter.symlink_to(parameter.with_name("2.json"))
        output = io.StringIO()
        with redirect_stderr(output):
            assert M.main(arguments(root, base)) == 1
        assert "task path must not use symlinks" in output.getvalue()


@it_case
def check_service_generated_equality():
    # Only the valid IAM model/view is used for schema/generated equality evidence.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve() / "repo"
        fixture(root)
        from model.files import load_model
        source = root / "model/dev/123456789012/iam.properties"
        values = dict(load_model(source).authoritative)
        values["desired.resource.001.cfn-logicalId"] = STACKS[0] + "-WorkerRole"
        values["desired.row.001-002.value"] = "[Trust](iam/iam-role-001-trust-policy.json)"
        write_model(source, values)
        (root / "docs/designs/dev/123456789012/iam/worker-role-trust-policy.json").rename(
            root / "docs/designs/dev/123456789012/iam/iam-role-001-trust-policy.json")
        sync = __import__("sync_runtime")
        contract, _, _, _ = M.candidate(root, "tasks/deploy-offline.md", "dev", "123456789012", TARGET, STACKS, ["iam"])
        start(root, "tasks/deploy-offline.md", contract)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert sync.sync(root, True, "dev", "123456789012", services=["iam"]) == 0
            assert sync.sync(root, False, "dev", "123456789012", services=["iam"]) == 0
            for relative in ("iam.md", "iam/iam-role-001-trust-policy.json"):
                path = root / "docs/designs/dev/123456789012" / relative
                original = path.read_text(encoding="utf-8")
                path.write_text(original + "\nchanged\n", encoding="utf-8")
                try:
                    sync.sync(root, False, "dev", "123456789012", services=["iam"])
                except ValueError as error:
                    assert "generated Markdown is stale or missing" in str(error)
                else:
                    raise AssertionError("service generated mismatch accepted")
                path.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        check_preparation()
        check_stale_and_conflicts()
        check_generated_boundaries()
        check_service_generated_equality()
        print("Deployment preparation checks: PASS")

