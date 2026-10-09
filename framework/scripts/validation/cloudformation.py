"""CloudFormation syntax, Environment and stack design checks."""


import json
import re
from pathlib import Path
from design_layout import stack_design, stack_deployment_policy
from model_core import properties
from model_files import read_model
from .design import JAPANESE_TEXT_PATTERN, stack_design_files
from .project import check_target_file

SHORT_CF_INTRINSICS = (
    "Ref", "Fn::And", "Fn::Base64", "Fn::Cidr", "Fn::Equals", "Fn::FindInMap",
    "Fn::GetAtt", "Fn::GetAZs", "Fn::GetStackOutput", "Fn::If", "Fn::ImportValue",
    "Fn::Join", "Fn::Not", "Fn::Or", "Fn::Select", "Fn::Split", "Fn::Sub",
    "Fn::Transform",
)
_SHORT_CF_NAMES = "|".join(re.escape(name) for name in SHORT_CF_INTRINSICS)
LONG_CF_KEY = re.compile(rf"(?<![A-Za-z0-9_])(?:{_SHORT_CF_NAMES})\s*:")
QUOTED_LONG_CF_KEY = re.compile(
    rf"(?P<prefix>^|[{{,]|-\s)\s*(?P<quote>['\"])(?:{_SHORT_CF_NAMES})(?P=quote)\s*:"
)
YAML_REUSE = re.compile(r"(?<![A-Za-z0-9_-])(?:[&*][A-Za-z0-9_-]+|<<\s*:)")


def unquoted_yaml(line: str) -> str:
    code: list[str] = []
    quote = ""
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            if quote == '"' and char == "\\" and index + 1 < len(line):
                code.extend("  ")
                index += 2
                continue
            if quote == "'" and char == "'" and index + 1 < len(line) and line[index + 1] == "'":
                code.extend("  ")
                index += 2
                continue
            if char == quote:
                quote = ""
            code.append(" ")
        elif char in "'\"":
            quote = char
            code.append(" ")
        elif char == "#":
            break
        else:
            code.append(char)
        index += 1
    return "".join(code)


def check_cloudformation_yaml_rules(root, iac_paths, findings) -> None:
    base = root / "infra" / "cloudformation" / "templates"
    for path in sorted(base.rglob("*")):
        if iac_paths is not None and path not in iac_paths:
            continue
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        scalar_indent: int | None = None
        for index, line in enumerate(lines):
            indent = len(line) - len(line.lstrip(" "))
            if scalar_indent is not None:
                if not line.strip() or indent > scalar_indent:
                    continue
                scalar_indent = None
            code = unquoted_yaml(line)
            if YAML_REUSE.search(code):
                findings.check_file(False, path, f"CloudFormation YAML anchor/alias/merge is forbidden: {findings.relative(path)}:{index + 1}")
            # ImportValue must use its full name when its value is a short Sub tag.
            sub_import = re.search(r"(?P<prefix>^|[{,]|-\s)\s*(?P<key>Fn::ImportValue|'Fn::ImportValue'|\"Fn::ImportValue\")\s*:\s*(?P<value>.*)$", line)
            if sub_import and sub_import.group("prefix") == code[sub_import.start("prefix"):sub_import.end("prefix")]:
                value = unquoted_yaml(sub_import.group("value")).strip()
                if not value:
                    for later in lines[index + 1:]:
                        value = unquoted_yaml(later).strip()
                        if value:
                            if len(later) - len(later.lstrip(" ")) <= indent:
                                value = ""
                            break
                if re.match(r"!Sub(?:\s|$)", value):
                    start, end = sub_import.span("key")
                    line = line[:start] + " " * (end - start) + line[end:]
                    code = unquoted_yaml(line)
            for match in re.finditer(r"!ImportValue\s*\{\s*(?P<key>Fn::Sub|'Fn::Sub'|\"Fn::Sub\")\s*:", line):
                if code[match.start():].startswith("!ImportValue"):
                    start, end = match.span("key")
                    line = line[:start] + " " * (end - start) + line[end:]
                    code = unquoted_yaml(line)
            quoted_long = any(
                match.group("prefix") == code[match.start("prefix"):match.end("prefix")]
                for match in QUOTED_LONG_CF_KEY.finditer(line)
            )
            # YAML cannot stack short tags; also allow the parameterized export suffix join.
            for match in re.finditer(r"!ImportValue\s*\{Fn::Join:\s*\[(?:''|\"\"),\s*\['[A-Z][A-Za-z0-9]*',\s*!Ref [A-Za-z][A-Za-z0-9]*\]\]\}", line):
                if code[match.start():].startswith("!ImportValue"):
                    code = code[:match.start()] + code[match.start():match.end()].replace("Fn::Join:", " " * 9) + code[match.end():]
            if LONG_CF_KEY.search(code) or quoted_long:
                findings.check_file(False, path, f"CloudFormation intrinsic must use YAML short form: {findings.relative(path)}:{index + 1}")

            tag = re.search(r"![A-Za-z][A-Za-z0-9]*\s*$", code)
            if tag and re.fullmatch(r"![A-Za-z][A-Za-z0-9]*\s*(?:#.*)?", line[tag.start():]):
                for later in lines[index + 1:]:
                    if not later.strip() or later.lstrip().startswith("#"):
                        continue
                    if len(later) - len(later.lstrip(" ")) > indent and later.lstrip().startswith("- "):
                        findings.check_file(False, path, f"CloudFormation intrinsic array must use YAML flow form: {findings.relative(path)}:{index + 1}")
                    break

            if re.search(r":\s*(?:![A-Za-z][A-Za-z0-9]*\s*)?[>|][+-]?\s*$", code):
                scalar_indent = indent
                continue

        resource_types: set[str] = set()
        in_metadata = False
        standalone_marker = False
        in_resources = False
        resource_indent: int | None = None
        property_indent: int | None = None
        seen_resource = False
        for index, line in enumerate(lines):
            code = unquoted_yaml(line)
            if not code.strip():
                continue
            indent = len(code) - len(code.lstrip(" "))
            if indent == 0:
                in_metadata = code.strip() == "Metadata:"
                in_resources = code.startswith("Resources:")
                resource_indent = property_indent = None
                continue
            if in_metadata and indent == 2 and code.strip() == "RolePlacement: standalone":
                standalone_marker = True
            if not in_resources:
                continue
            resource = re.fullmatch(r"( +)[A-Za-z0-9]+:\s*", code)
            if resource and (resource_indent is None or indent <= resource_indent):
                if seen_resource:
                    findings.check_file(not lines[index - 1].strip(), path, f"CloudFormation resources must be separated by a blank line: {findings.relative(path)}:{index + 1}")
                seen_resource = True
                resource_indent, property_indent = indent, None
                continue
            if resource_indent is None or indent <= resource_indent:
                continue
            if property_indent is None:
                property_indent = indent
            if indent == property_indent:
                resource_type = re.fullmatch(r"\s*Type:\s*(AWS::[A-Za-z0-9:]+)\s*", code)
                if resource_type:
                    resource_types.add(resource_type.group(1))

        support_types = {
            "AWS::IAM::Role", "AWS::IAM::Policy", "AWS::IAM::ManagedPolicy",
            "AWS::IAM::InstanceProfile",
        }
        is_security_group = lambda kind: kind.startswith("AWS::EC2::SecurityGroup")
        requires_consumer = (
            "AWS::IAM::Role" in resource_types
            or any(kind.startswith("AWS::Logs::") for kind in resource_types)
            or any(is_security_group(kind) for kind in resource_types)
        )
        role_only = "AWS::IAM::Role" in resource_types and resource_types <= {
            "AWS::IAM::Role", "AWS::IAM::Policy", "AWS::IAM::ManagedPolicy",
        }
        rules_only = bool(resource_types) and resource_types <= {
            "AWS::EC2::SecurityGroupIngress", "AWS::EC2::SecurityGroupEgress",
        }
        if role_only:
            findings.check_file(standalone_marker, path, f"Role-only template requires Metadata.RolePlacement: standalone: {findings.relative(path)}")
        elif standalone_marker:
            findings.check_file(False, path, f"Metadata.RolePlacement: standalone requires a Role-only template: {findings.relative(path)}")
        if requires_consumer and not role_only and not rules_only:
            findings.check_file(
                any(
                    not kind.startswith("AWS::Logs::")
                    and kind not in support_types
                    and not is_security_group(kind)
                    for kind in resource_types
                ),
                path,
                f"CloudWatch Logs, IAM Role, and Security Group must share the consuming resource template: {findings.relative(path)}",
            )


def check_cloudformation_environment_parameters(root, iac_paths, accounts, stack_design_files, findings) -> None:
    def uses_environment(value) -> bool:
        if isinstance(value, list):
            return any(uses_environment(item) for item in value)
        if not isinstance(value, dict):
            return False
        if value.get("Ref") == "Environment":
            return True
        if "Fn::Sub" in value:
            argument = value["Fn::Sub"]
            text, variables = (argument, {}) if isinstance(argument, str) else (
                argument if isinstance(argument, list) and len(argument) == 2 else ("", {}))
            if isinstance(text, str) and isinstance(variables, dict):
                return any(uses_environment(variables[name]) if name in variables else name == "Environment"
                           for name in re.findall(r"\$\{([^}]+)\}", text) if not name.startswith("!"))
        return any(uses_environment(item) for item in value.values())

    def selection_paths(value, location=""):
        if isinstance(value, list):
            for index, item in enumerate(value):
                yield from selection_paths(item, f"{location}[{index}]")
        elif isinstance(value, dict):
            for key, argument in value.items():
                child = f"{location}.{key}" if location else key
                if key == "Conditions" and not location and isinstance(argument, dict):
                    for name, expression in argument.items():
                        if uses_environment(expression):
                            yield f"{child}.{name}"
                    continue
                selectors = []
                if isinstance(argument, list):
                    if key == "Fn::FindInMap":
                        selectors = argument[:3]
                    elif key == "Fn::If" or key == "Fn::Select":
                        selectors = argument[:1]
                    elif isinstance(key, str) and key.startswith("Fn::ForEach::"):
                        selectors = argument[1:2]
                if any(uses_environment(selector) for selector in selectors):
                    yield child
                yield from selection_paths(argument, child)

    templates = root / "infra" / "cloudformation" / "templates"
    parameters = root / "infra" / "cloudformation" / "parameters"
    stack_parameters: dict[Path, Path] = {}
    designed_targets: set[tuple[str, str]] = set()
    for design in stack_design_files:
        target_parts = design.relative_to(root / "docs" / "designs").parts
        if len(target_parts) != 3:
            continue
        designed_targets.add((target_parts[0], target_parts[1]))
        try:
            stacks = stack_design(design)
        except ValueError:
            continue
        for stack in stacks:
            parameter_path = parameters / target_parts[0] / target_parts[1] / stack["parameters"]
            findings.check(parameter_path not in stack_parameters, f"parameter file belongs to multiple stacks: {stack['parameters']}")
            alias = accounts.get((target_parts[0], target_parts[1]), {}).get("alias", "")
            stack_parameters[parameter_path] = templates / alias / stack["template"]
    environment_templates: set[Path] = set()
    for path in sorted(templates.rglob("*")):
        if iac_paths is not None and path not in iac_paths:
            continue
        if not path.is_file() or path.suffix.lower() not in {".yaml", ".yml", ".json"}:
            continue
        try:
            from cfnlint.decode import decode
        except ImportError:
            findings.check(False, "cfn-lint Python runtime is required for CloudFormation Environment validation")
            return
        document, decode_errors = decode(str(path))
        if decode_errors or not isinstance(document, dict):
            detail = decode_errors[0] if decode_errors else "expected a template object"
            findings.check_file(False, path, f"invalid CloudFormation template for Environment validation: {findings.relative(path)}: {detail}")
            continue
        for location in selection_paths(document):
            findings.check_file(False, path,
                            f"CloudFormation must not branch on Environment: {findings.relative(path)}: {location}. "
                            "Environment may be used for naming/tags/value composition, but must not control "
                            "Conditions or environment-specific value selection. "
                            "Pass the differing value explicitly through deployment parameters instead.")
        if uses_environment(document):
            environment_templates.add(path)
            definitions = document.get("Parameters", {})
            declared = isinstance(definitions, dict) and "Environment" in definitions
            findings.check_file(declared, path, f"CloudFormation resource uses Environment without Parameters.Environment: {findings.relative(path)}")

    for path in sorted(parameters.rglob("*.json")):
        if iac_paths is not None and path not in iac_paths:
            continue
        parts = path.relative_to(parameters).parts
        if len(parts) < 3:
            continue
        environment, target_directory = parts[:2]
        candidates = [
            templates / target_directory / f"{path.stem}{suffix}"
            for suffix in (".yaml", ".yml", ".json")
        ] + [templates / f"{path.stem}{suffix}" for suffix in (".yaml", ".yml", ".json")]
        matching_template = stack_parameters.get(path) or next((candidate for candidate in candidates if candidate.is_file()), None)
        findings.check_file(
            (environment, target_directory) not in designed_targets or path in stack_parameters,
            path,
            f"parameter file is absent from stack design: {findings.relative(path)}",
        )
        requires_environment = matching_template in environment_templates
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            findings.check_file(False, path, f"invalid CloudFormation parameter JSON: {findings.relative(path)}: {error}")
            continue
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            findings.check_file(False, path, f"CloudFormation parameter file must be a parameter array: {findings.relative(path)}")
            continue
        environment_values = [entry.get("ParameterValue") for entry in entries if entry.get("ParameterKey") == "Environment"]
        if requires_environment or environment_values:
            findings.check_file(
                environment_values == [environment],
                path,
                f"CloudFormation Environment parameter must equal target environment: {findings.relative(path)}",
            )
        component = re.compile(rf"(?<![a-z0-9]){re.escape(environment)}(?![a-z0-9])", re.IGNORECASE)
        for entry in entries:
            value = entry.get("ParameterValue")
            if entry.get("ParameterKey") != "Environment" and isinstance(value, str):
                findings.check_file(
                    component.search(value) is None,
                    path,
                    f"CloudFormation parameter value contains Environment component: {findings.relative(path)}: {entry.get('ParameterKey')}",
                )


def check_stack_designs(paths: list[Path] | None = None, *, accounts, findings, root, scope) -> None:
    names: set[tuple[str, str, str]] = set()
    for path in stack_design_files(root=root, scope=scope) if paths is None else paths:
        target = check_target_file(path, root / "docs" / "designs", accounts=accounts, findings=findings)
        if target is None or target not in accounts:
            continue
        findings.check(
            accounts[target]["engine"] == "cloudformation",
            f"stack design requires CloudFormation target: {findings.relative(path)}",
        )
        try:
            from design_layout import stack_delivery
            from model_core import deployment_settings
            from model_references import deployment_bucket
            stack_deployment_policy(path)
            stacks = stack_design(path)
            from cloudformation_observed import validate_mapping_targets
            source = (root / "model" / path.relative_to(root / "docs" / "designs")).with_suffix(".properties")
            if source.is_file():
                mapping_values = properties(read_model(source))
                from model_core import stack_model
                stack_model(mapping_values)
                validate_mapping_targets(root, target[0], target[1], mapping_values)
            values = stack_delivery(path) | {f"desired.stack.{number:03d}.name": stack["name"]
                                           for number, stack in enumerate(stacks, 1)}
            settings, artifacts = deployment_settings(values)
            for reference in ([settings["templateBucket"]] if settings else []) + [a["bucket"] for _, a in artifacts]:
                deployment_bucket(reference, path, root)
        except ValueError as error:
            findings.check(False, f"invalid stack design: {findings.relative(path)}: {error}")
            continue
        findings.check(len({stack["name"] for stack in stacks}) == len(stacks), f"duplicate stack name in design: {findings.relative(path)}")
        parameter_files: set[str] = set()
        for stack in stacks:
            name = stack["name"]
            findings.check(
                JAPANESE_TEXT_PATTERN.search(stack["comment"]) is not None,
                f"stack Comment must describe its purpose in Japanese: {findings.relative(path)}: {name}",
            )
            findings.check(re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,127}", name) is not None, f"invalid stack name: {name}")
            identity = (accounts[target]["account"], accounts[target]["region"], name)
            findings.check(identity not in names, f"duplicate stack in AWS account/region: {name}")
            names.add(identity)
            template = Path(stack["template"])
            findings.check(
                template.name == stack["template"] and template.suffix in {".yaml", ".yml"},
                f"invalid stack template filename: {findings.relative(path)}: {name}",
            )
            parameters = Path(stack["parameters"])
            findings.check(
                parameters.name == stack["parameters"] and parameters.suffix == ".json",
                f"invalid stack parameter filename: {findings.relative(path)}: {name}",
            )
            findings.check(stack["parameters"] not in parameter_files, f"parameter file belongs to multiple stacks: {stack['parameters']}")
            parameter_files.add(stack["parameters"])

