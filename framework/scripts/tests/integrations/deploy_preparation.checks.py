#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.deploy_preparation_fixtures import *

def check_preparation():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory).resolve()
        root = base / "repo"
        fixture(root)
        original = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        started = time.perf_counter()
        assert invoke(arguments(root, base)) == 0
        wall = time.perf_counter() - started
        run = next((base / "logs").iterdir())
        path = run / "preparation.json"
        plan = json.loads(path.read_text(encoding="utf-8"))
        assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == original
        assert plan["controllerArgv"].count("--stack") == 2
        assert "--sequential" in plan["controllerArgv"] and "--timing-log" in plan["controllerArgv"]
        assert plan["controllerArgv"][0] == sys.executable
        assert plan["scope"] == ["dev/123456789012/cloudformation-stacks", "dev/123456789012/ec2", "dev/123456789012/iam"]
        text = (run / "contract.md").read_text(encoding="utf-8")
        reserved = paths_in(text, "## Modified files")
        assert "model/parameters/dev/123456789012/ec2/observed.json" in reserved
        from model_templates import source_paths
        assert not any(source_paths(root/p) is not None or p.endswith("source.json") for p in reserved)
        assert {p for p in reserved if p.startswith("infra/")} == {
            "infra/cloudformation/templates/shared.yaml",
            "infra/cloudformation/parameters/dev/123456789012/1.json",
            "infra/cloudformation/parameters/dev/123456789012/2.json"}
        assert '- Controlled repair: `allowed`' in text
        assert f'- Deploy repair session: `{run / "session.json"}`' in text
        for document in plan["documents"]:
            assert all(len(Path(chunk).read_text(encoding="utf-8")) <= 6000 for chunk in document["chunks"])
        documents = {d["source"]: d for d in plan["documents"]}
        generated = {"docs/designs/dev/123456789012/" + name for name in
                     ("ec2.md", "iam.md", "cloudformation-stacks.md", "iam/worker-role-trust-policy.json")}
        assert plan["generatedViews"] == sorted(generated)
        assert generated <= plan["inputs"].keys() and generated <= reserved
        assert not generated & documents.keys()
        for relative, digest in plan["inputs"].items():
            assert digest == hashlib.sha256((root / relative).read_bytes()).hexdigest()
        assert {Path(c) for d in plan["documents"] for c in d["chunks"]} == {p.resolve() for p in (run / "documents").iterdir()}
        assert len(documents) == len(plan["documents"])
        entrance = root / "model/dev/123456789012/ec2.properties"
        assert all(p.relative_to(root).as_posix() in documents for p in __import__("model_templates").source_inputs(entrance))
        iam = documents["model/templates/123456789012/iam.properties.tpl"]
        assert "desired.row.row_001-002.document=" in "".join(Path(c).read_text(encoding="utf-8") for c in iam["chunks"])
        assert all("infra/cloudformation/parameters/dev/123456789012/" + str(i) + ".json" in documents for i in (1, 2))
        assert "AGENTS.md" in documents
        assert all(name in plan["controllerArgv"] for name in STACKS)
        model_rules = documents["framework/rules/model-information.md"]
        selected = "".join(Path(chunk).read_text(encoding="utf-8") for chunk in model_rules["chunks"])
        assert "## CloudFormation deployment policy" in selected
        assert "### Resource-level CloudFormation identity" in selected
        assert "## Service display inputs" not in selected
        assert model_rules["readCharacters"] < model_rules["sourceCharacters"]
        assert "framework/rules/task-contract.md" in documents
        assert "framework/rules/issue-gate.md" in documents
        assert "framework/rules/project-configuration.md" in documents
        assert "framework/rules/terraform.md" not in documents and "README.md" not in documents
        assert invoke(["--repository-root", str(root), "--register", str(path)]) == 0
        registered = contracts(root)["tasks/deploy-offline.md"]
        from task_contract import reservations, worktree_owner, worktree_identity
        assert paths_in(registered, "## Modified files") == paths_in(text, "## Modified files")
        assert worktree_owner(registered) == worktree_identity(root)
        entry = reservations(root, contracts(root))["tasks/deploy-offline.md"]
        assert entry.active == entry.files and not entry.deferred
        assert invoke(arguments(root, base)) == 1  # Registered tasks keep the existing resume path.
        with patch.object(M.subprocess, "run", return_value=subprocess.CompletedProcess(plan["controllerArgv"], 2)) as launch:
            assert M.main(["--repository-root", str(root), "--run-controller", str(path)]) == 2
            assert launch.call_count == 1 and launch.call_args.args[0] == plan["controllerArgv"]
            assert launch.call_args.kwargs["env"]["BLUEPRINT_TASK_FILE"] == "tasks/deploy-offline.md"
        events = [json.loads(line) for line in (run / "timing.jsonl").read_text().splitlines()]
        assert {"environment", "contractPreparation", "documentRead", "documentReview", "contractRegistration"} <= {e["phase"] for e in events}
        assert all(e["result"] == "PASS" and e["seconds"] >= 0 for e in events)
        assert all("aws" not in e["phase"].lower() for e in events)
        (run / "session.json").write_text("{}", encoding="utf-8")
        with patch.object(M.subprocess, "run", side_effect=AssertionError("existing session restarted")), redirect_stderr(io.StringIO()):
            assert M.main(["--repository-root", str(root), "--run-controller", str(path)]) == 1
        print(f"Offline preparation benchmark: {wall:.3f}s; phase timing generated (fixture, no AWS)")


def check_stale_and_conflicts():
    for reason in ("input", "issue", "reservation", "runtime", "candidate", "model", "markdown-change",
                   "markdown-delete", "json-change", "json-delete", "legacy-change", "legacy-delete"):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "repo"
            fixture(root)
            assert invoke(arguments(root, base)) == 0
            run = next((base / "logs").iterdir())
            path = run / "preparation.json"
            if reason.startswith(("markdown-", "json-", "legacy-")):
                generated = root / "docs/designs/dev/123456789012" / ("iam/worker-role-trust-policy.json" if reason.startswith("json-") else "ec2.md")
                if reason.startswith("legacy-"):
                    plan = json.loads(path.read_text(encoding="utf-8"))
                    plan.pop("generatedViews")
                    path.write_text(json.dumps(plan), encoding="utf-8")
                if reason.endswith("delete"):
                    generated.unlink()
                else:
                    generated.write_text("changed", encoding="utf-8")
            elif reason == "model":
                source = root / "model/dev/123456789012/iam.properties"
                write_model(source, read_model(source) + "# changed\n")
            elif reason == "input":
                # Unread sections still invalidate the full-file immutable input guard.
                path_to_rule = root / "framework/rules/model-information.md"
                path_to_rule.write_text(path_to_rule.read_text(encoding="utf-8") + "\n## Unread section\nchanged\n", encoding="utf-8")
            elif reason == "issue":
                issue = root / "issues/dev/123456789012/issues.md"
                issue.parent.mkdir(parents=True)
                issue.write_text("### ec2\n1. 未解決\n", encoding="utf-8")
            elif reason == "reservation":
                text = (run / "contract.md").read_text(encoding="utf-8").replace("tasks/deploy-offline.md", "tasks/other.md")
                start(root, "tasks/other.md", text)
            elif reason == "candidate":
                (run / "contract.md").write_text("changed", encoding="utf-8")
            with patch.dict(M.os.environ, {"PATH": "changed"}) if reason == "runtime" else patch.dict(M.os.environ, {}):
                result = invoke(["--repository-root", str(root), "--register", str(path)])
                assert result == (0 if reason == "reservation" else 1), reason
            if reason == "reservation":
                from task_contract import reservations
                entry = reservations(root, contracts(root))["tasks/deploy-offline.md"]
                assert entry.state == "running" and entry.deferred
                assert entry.active == {"tasks/deploy-offline.md"}
                continue
            assert json.loads((run / "timing.jsonl").read_text().splitlines()[-1])["result"] == "FAIL"


def check_generated_boundaries():
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory).resolve()
        root = base / "repo"
        fixture(root)
        source = root / "model/dev/123456789012/iam.properties"
        original = read_model(source)
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
        controller = M.module("boundary_controller", root / "framework/scripts/cloudformation-deploy.py")
        real_module = M.module
        real_load = controller.load_units
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
        def modules(name, path):
            return controller if name == "preparation_controller" else real_module(name, path)
        with patch.object(controller, "load_units", side_effect=load_with_artifacts), patch.object(M, "module", side_effect=modules):
            assert invoke(arguments(root, base)) == 0
        run = next((base / "logs").iterdir())
        plan = json.loads((run / "preparation.json").read_text(encoding="utf-8"))
        documents = {d["source"] for d in plan["documents"]}
        assert "infra/cloudformation/artifacts/execution.json" in documents
        assert "infra/cloudformation/artifacts/build.zip" not in documents
        assert "infra/cloudformation/artifacts/build.zip" in plan["inputs"]
        assert "infra/cloudformation/artifacts/build.zip" not in plan["generatedViews"]
        for relative, digest in plan["inputs"].items():
            assert digest == M.sha(root / relative)
        with patch.object(controller.AwsBackend, "paths", return_value=(root / "docs/designs/dev/123456789012/iam/worker-role-trust-policy.json", artifacts / "execution.json")), patch.object(M, "module", side_effect=modules):
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


def check_service_generated_equality():
    # Only the valid IAM model/view is used for schema/generated equality evidence.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve() / "repo"
        fixture(root)
        shutil.copytree(ROOT / "framework/materials", root / "framework/materials")
        sync = M.module("equality_sync", ROOT / "framework/scripts/sync-model.py")
        contract, _, _, _ = M.candidate(root, "tasks/deploy-offline.md", "dev", "123456789012", TARGET, STACKS, ["iam"])
        start(root, "tasks/deploy-offline.md", contract)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            assert sync.sync(root, True, "dev", "123456789012", services=["iam"]) == 0
            assert sync.sync(root, False, "dev", "123456789012", services=["iam"]) == 0
            for relative in ("iam.md", "iam/worker-role-trust-policy.json"):
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

