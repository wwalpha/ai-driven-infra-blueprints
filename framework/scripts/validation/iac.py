"""Common engine selection and environment/target placement checks."""

def check_iac_selection(root, scope, accounts, template_mode, findings) -> None:
    active_engines = {values["engine"] for values in accounts.values()}
    for engine in ("cloudformation", "terraform"):
        engine_root = root / "infra" / engine
        files = [
            path
            for path in engine_root.rglob("*")
            if path.is_file() and not path.name.startswith(".")
            and (engine == "cloudformation" or not any(
                part.startswith(".") for part in path.relative_to(engine_root).parts))
        ]
        if template_mode:
            findings.check(not files, f"template mode contains {engine} implementation")
        elif engine in active_engines:
            if engine == "cloudformation":
                findings.check(engine_root.is_dir(), f"selected IaC engine directory missing: {engine}")
        else:
            if engine == "cloudformation":
                findings.check(not engine_root.exists(), f"unselected IaC engine directory remains: {engine}")
            else:
                for path in files:
                    findings.check_file(False, path, f"unselected IaC engine file remains: {findings.relative(path)}")

    for engine, relative_base, label, placement in (
        ("cloudformation", "infra/cloudformation/parameters", "CloudFormation", "parameter"),
        ("terraform", "infra/terraform/environments", "Terraform", "composition"),
    ):
        base = root / relative_base
        if engine == "terraform" and not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.name.startswith(".") or (
                    engine == "terraform" and any(part.startswith(".") for part in path.relative_to(base).parts)):
                continue
            parts = path.relative_to(base).parts
            check = (lambda condition, message: findings.check_file(condition, path, message)) if engine == "terraform" else findings.check
            check(len(parts) >= 3, f"{label} {placement} must be scoped by environment/target directory: {findings.relative(path)}")
            if len(parts) >= 3:
                target = (parts[0], parts[1])
                if scope is not None and not any(item[:2] == target for item in scope) and not (
                    engine == "terraform" and findings.relative(path) in (findings.file_gate_paths or set())):
                    continue
                check(target in accounts, f"{label} target is not defined: {findings.relative(path)}")
                if target in accounts:
                    check(accounts[target]["engine"] == engine, f"{label} is not selected: {findings.relative(path)}")

