"""Common engine selection and environment/target placement checks."""

from . import terraform


def check_iac_selection(root, scope, accounts, template_mode, findings) -> None:
    active_engines = {values["engine"] for values in accounts.values()}
    engine_root = root / "infra" / "cloudformation"
    # A valid alias may itself be "cloudformation"; its Terraform subtree is not CFn IaC.
    alias_root = terraform.module_directory(root, "cloudformation").parent
    terraform_alias = any(key[1] == "cloudformation" and value["engine"] == "terraform"
                          for key, value in accounts.items())
    files = [path for path in engine_root.rglob("*")
             if path.is_file() and not path.name.startswith(".")
             and not (terraform_alias and path.is_relative_to(alias_root))]
    if template_mode:
        findings.check(not files, "template mode contains cloudformation implementation")
    elif "cloudformation" in active_engines:
        findings.check(engine_root.is_dir(), "selected IaC engine directory missing: cloudformation")
    else:
        only_terraform = (terraform_alias and engine_root.is_dir()
                          and set(engine_root.iterdir()) == {alias_root})
        findings.check(not engine_root.exists() or only_terraform, "unselected IaC engine directory remains: cloudformation")
    terraform.check_placement(root, scope, accounts, template_mode, findings)

    for engine, relative_base, label, placement in (
        ("cloudformation", "infra/cloudformation/parameters", "CloudFormation", "parameter"),
    ):
        base = root / relative_base
        for path in base.rglob("*"):
            if not path.is_file() or path.name.startswith("."):
                continue
            parts = path.relative_to(base).parts
            check = findings.check
            check(len(parts) >= 3, f"{label} {placement} must be scoped by environment/target directory: {findings.relative(path)}")
            if len(parts) >= 3:
                target = (parts[0], parts[1])
                if scope is not None and not any(item[:2] == target for item in scope):
                    continue
                check(target in accounts, f"{label} target is not defined: {findings.relative(path)}")
                if target in accounts:
                    check(accounts[target]["engine"] == engine, f"{label} is not selected: {findings.relative(path)}")

