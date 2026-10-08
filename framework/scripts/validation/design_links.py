"""Design overview, references/anchors and artifact consistency."""


from __future__ import annotations
import json
import re
from pathlib import Path
from design_layout import (
    CLOUDTRAIL_DATA_RESOURCE, LINKED_LIST_PROPERTIES,
    linked_list_property, DETAILS_HEADING, DISPLAY_PROPERTY_ALIASES, GROUPED,
    REQUIRED_NAME_TAG_TYPES, RESOURCE_REFERENCE_PROPERTIES, RESOURCE as RESOURCE_HEADING_PATTERN,
    resource_heading_lines,
)
from service_rows import CODEBUILD_FORMAL_VARIABLE, CODEPIPELINE_STAGE
from security_group_tables import security_group_table_lines
from design_document import DesignIndex
from .design import (
    ANCHOR_PATTERN, JAPANESE_TEXT_PATTERN, LINK_PATTERN, LOWER_KEBAB_PATTERN, OVERVIEW_HEADING,
    OVERVIEW_TYPE_HEADING_PATTERN, RESOURCE_LINK_PATTERN, S3_KMS_MASTER_KEY_ID, TABLE_ALIGNMENT,
    TABLE_HEADER, design_files, normalized, unquoted,
)

def check_design_overviews(paths: list[Path] | None = None, *, findings, root, scope) -> None:
    for path in design_files(root=root, scope=scope) if paths is None else paths:
        lines = resource_heading_lines(path.read_text(encoding="utf-8").splitlines())
        try:
            lines = security_group_table_lines(lines)
        except ValueError:
            pass
        overview_indices = [
            index for index, line in enumerate(lines) if line == OVERVIEW_HEADING
        ]
        findings.check(
            len(overview_indices) == 1,
            f"resource overview must appear exactly once: {findings.relative(path)}",
        )
        details_indices = [index for index, line in enumerate(lines) if line == DETAILS_HEADING]
        findings.check(
            len(details_indices) == 1,
            f"resource details heading must appear exactly once: {findings.relative(path)}",
        )
        resources: dict[str, tuple[str, str]] = {}
        resource_indices: list[int] = []
        previous = ""
        for index, line in enumerate(lines):
            if re.match(r"^#{1,6} [A-Za-z0-9]+\.[A-Za-z0-9]+: ", line):
                findings.check(
                    RESOURCE_HEADING_PATTERN.fullmatch(line) is not None,
                    f"resource detail heading must use H3: {findings.relative(path)}: {line}",
                )
            if heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                anchor = ANCHOR_PATTERN.fullmatch(previous)
                if anchor:
                    resources[anchor.group(1)] = heading.groups()
                resource_indices.append(index)
            if line.strip():
                previous = line.strip()
        if len(overview_indices) != 1 or len(details_indices) != 1 or not resource_indices:
            continue

        overview_index = overview_indices[0]
        details_index = details_indices[0]
        first_resource_index = min(resource_indices)
        findings.check(
            overview_index < details_index < first_resource_index
            and all(
                not line.startswith(("## ", "### ")) or RESOURCE_HEADING_PATTERN.fullmatch(line)
                for line in lines[details_index + 1:]
            ),
            f"resource details must follow the overview and contain every resource: {findings.relative(path)}",
        )
        if not overview_index < details_index < first_resource_index:
            continue
        findings.check(
            not any(ANCHOR_PATTERN.fullmatch(line) for line in lines[overview_index:details_index]),
            f"resource anchors must be inside resource details: {findings.relative(path)}",
        )

        listed: list[str] = []
        overview_types: list[str] = []
        current_type = ""
        index = overview_index + 1
        while index < details_index:
            line = lines[index]
            if heading := OVERVIEW_TYPE_HEADING_PATTERN.fullmatch(line):
                current_type = heading.group(1)
                overview_types.append(current_type)
                index += 1
                continue
            if not line.startswith("|"):
                index += 1
                continue
            table: list[str] = []
            while index < details_index and lines[index].startswith("|"):
                table.append(lines[index])
                index += 1
            findings.check(bool(current_type), f"resource overview table lacks a resource type heading: {findings.relative(path)}")
            findings.check(len(table) >= 3, f"resource overview table is incomplete: {findings.relative(path)}: {current_type}")
            if not current_type or len(table) < 3:
                continue
            headers = [cell.strip() for cell in table[0].strip("|").split("|")]
            alignment = [cell.strip() for cell in table[1].strip("|").split("|")]
            findings.check(
                headers == ["No.", "ResourceName", "Comment"],
                f"resource overview must use No., ResourceName, Comment: {findings.relative(path)}: {current_type}",
            )
            findings.check(
                len(alignment) == len(headers)
                and all(re.fullmatch(r":?---+:?", cell) for cell in alignment),
                f"invalid resource overview table alignment: {findings.relative(path)}: {current_type}",
            )
            for number, row in enumerate(table[2:], 1):
                cells = [cell.strip() for cell in row.strip("|").split("|")]
                findings.check(
                    len(cells) == len(headers),
                    f"resource overview row width mismatch: {findings.relative(path)}: {current_type}",
                )
                if len(cells) != len(headers):
                    continue
                findings.check(cells[0] == str(number), f"resource overview numbering error: {findings.relative(path)}: {current_type}")
                findings.check(
                    JAPANESE_TEXT_PATTERN.search(cells[-1]) is not None,
                    f"resource overview Comment must describe the resource in Japanese: {findings.relative(path)}: {current_type}",
                )
                link = RESOURCE_LINK_PATTERN.fullmatch(cells[1])
                findings.check(
                    bool(link and not link.group(2)),
                    f"resource overview resource column must link to a same-file detail block: {findings.relative(path)}: {current_type}",
                )
                if not link or link.group(2):
                    continue
                label, _, anchor = link.groups()
                findings.check(
                    not re.fullmatch(
                        rf".*[（(]\s*{re.escape(label)}\s*[）)]\s*の(?:設定|説明|用途|役割)",
                        cells[-1],
                    )
                    and cells[-1] not in {f"{label}の設定", f"{current_type}の設定", "セキュリティグループの設定"},
                    f"resource overview Comment must state a distinct purpose or role: {findings.relative(path)}: {current_type}: {label}",
                )
                resource = resources.get(anchor)
                findings.check(
                    bool(
                        resource and resource[0] == current_type
                        and label == resource[1]
                    ),
                    f"resource overview link must match its detail block: {findings.relative(path)}: {current_type}: {label}",
                )
                listed.append(anchor)

        detail_types = [resource_type for resource_type, _ in resources.values()]
        findings.check(
            len(overview_types) == len(set(overview_types))
            and set(overview_types) == set(detail_types),
            f"resource overview types must match detail resource types: {findings.relative(path)}",
        )
        findings.check(
            len(listed) == len(set(listed)) and set(listed) == set(resources),
            f"resource overview must list every detail resource exactly once: {findings.relative(path)}",
        )


def check_design_links(identifier_outputs: dict[str, set[str]], paths: list[Path] | None = None, *,
                       design_index: DesignIndex | None = None, findings, root, scope) -> None:
    design_index = design_index or DesignIndex()
    sources = design_files(root=root, scope=scope) if paths is None else paths
    references = {path.resolve() for path in sources}
    fragments = {}
    visible_text = {source: design_index.get(source).visible_text for source in sources}
    for source in sources:
        for raw in LINK_PATTERN.findall(visible_text[source]):
            target, separator, fragment = raw.partition("#")
            if separator and not raw.startswith(("http://", "https://", "mailto:")):
                linked = (source.parent / target if target else source).resolve()
                if linked.is_file() and linked.suffix == ".md" and linked.is_relative_to(root / "docs/designs"):
                    references.add(linked)
                    fragments.setdefault(linked, set()).add(fragment)
    anchors = {
        path: design_index.get(path).anchors
        for path in references
    }
    resources: dict[tuple[Path, str], tuple[str, dict[str, str]]] = {}
    configured_names: dict[tuple[Path, str], dict[str, str]] = {}
    hidden_ids: dict[tuple[Path, str], str] = {}
    tagged_names: dict[tuple[Path, str], tuple[str, str]] = {}
    type_names: dict[tuple[Path, str], str] = {}
    name_properties = {"CodeCommit.Repository.RepositoryName", "CodeBuild.Project.Name"}
    name_properties.update(kind + "." + field for kind, field in RESOURCE_REFERENCE_PROPERTIES.values())
    source_paths = {path.resolve() for path in sources}
    for path in sorted(references):
        document = design_index.get(path)
        view = document.headings if path in source_paths else document.view(frozenset(fragments.get(path, set())))
        source_lines = view.lines
        try:
            identities = view.logical_ids
        except ValueError:
            identities = {}
        pending_anchor = ""
        for line in source_lines:
            if match := ANCHOR_PATTERN.fullmatch(line):
                pending_anchor = match.group(1)
            elif heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                if heading.group(1) in REQUIRED_NAME_TAG_TYPES:
                    tagged_names[path.resolve(), pending_anchor] = heading.groups()
                if heading.group(1) == heading.group(2):
                    type_names[path.resolve(), pending_anchor] = heading.group(1)
                if heading.groups() in identities and identities[heading.groups()] != heading.group(2):
                    hidden_ids[path.resolve(), pending_anchor] = identities[heading.groups()]
        pending_anchor = ""
        current: tuple[Path, str] | None = None
        lines = source_lines
        try:
            lines, children = view.expanded
            for anchor, child in children.items():
                identity = GROUPED[child["resourceType"]]["identityProperty"]
                if identity != "Id":
                    value = unquoted(child["rows"][0][2])
                    if value != child["logicalId"]:
                        hidden_ids[path.resolve(), anchor] = child["logicalId"]
        except ValueError as error:
            if path in source_paths:
                findings.check(False, f"invalid grouped design: {findings.relative(path)}: {error}")
        for line in lines:
            if anchor := ANCHOR_PATTERN.fullmatch(line):
                pending_anchor = anchor.group(1)
            elif heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                current = (path.resolve(), pending_anchor)
                resources[current] = (heading.group(1), {})
                configured_names[current] = {}
                pending_anchor = ""
            elif current and line.startswith("|") and line not in {TABLE_HEADER, TABLE_ALIGNMENT}:
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if len(cells) == 4 and cells[1] in name_properties:
                    configured_names[current][cells[1]] = unquoted(cells[2])
                if len(cells) == 4 and (
                    cells[1]
                    in identifier_outputs.get(resources[current][0], set())
                    or cells[1] == "KMS.Alias.AliasName"
                    or cells[1] == "SecretsManager.Secret.Name"
                ):
                    resources[current][1][cells[1]] = unquoted(cells[2])
    for source in sources:
        for line in visible_text[source].splitlines():
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            for link in re.finditer(r"\[([^\]]+)\]\(([^)]*?)#([^)]+)\)", line):
                label, target_text, fragment = link.groups()
                target = (source if not target_text else source.parent / target_text).resolve()
                findings.check(label != hidden_ids.get((target, fragment)), f"design link must not display internal logical ID: {findings.relative(source)}: {label}")
                if role_name := configured_names.get((target, fragment), {}).get("IAM.Role.RoleName"):
                    findings.check(label == role_name, f"IAM Role link must display RoleName: {findings.relative(source)}: {label}")
                if tagged := tagged_names.get((target, fragment)):
                    kind, name = tagged
                    observed = resources.get((target, fragment), ("", {}))[1].values()
                    identifier_reference = len(cells) == 4 and RESOURCE_LINK_PATTERN.fullmatch(cells[2]) and label in observed
                    resource = "Endpoint" if kind == "EC2.VPCEndpoint" else "Instance"
                    findings.check(label == name or identifier_reference, f"{resource} link must display Name tag value or observed identifier: {findings.relative(source)}: {label}")
                if name := type_names.get((target, fragment)):
                    observed = resources.get((target, fragment), ("", {}))[1].values()
                    identifier_reference = len(cells) == 4 and RESOURCE_LINK_PATTERN.fullmatch(cells[2]) and label in observed
                    findings.check(label == name or identifier_reference, f"nameless resource link must display resource type or observed identifier: {findings.relative(source)}: {label}")
        for raw in LINK_PATTERN.findall(visible_text[source]):
            if raw.startswith(("http://", "https://", "mailto:")):
                continue
            target_text, separator, fragment = raw.partition("#")
            findings.check(not Path(target_text).is_absolute(), f"design link must be relative: {findings.relative(source)}: {raw}")
            target = (source if not target_text else source.parent / target_text).resolve()
            findings.check(target.is_file(), f"broken design link: {findings.relative(source)}: {raw}")
            if separator and target.is_file():
                findings.check(fragment in anchors.get(target, set()), f"missing design anchor: {findings.relative(source)}: {raw}")
        document = design_index.get(source)
        source_lines = document.lines
        pipeline_rows = []
        pipeline_id = ""
        providers = {}
        for line in source_lines:
            if heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                pipeline_id = heading.group(2) if heading.group(1) == "CodePipeline.Pipeline" else ""
            elif line.startswith("#"):
                pipeline_id = ""
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            match = CODEPIPELINE_STAGE.fullmatch(cells[1]) if pipeline_id and len(cells) == 4 else None
            if match:
                identity = pipeline_id, match.group(1), match.group(2) or "1"
                pipeline_rows.append((identity, match.group(3), cells[2]))
                if match.group(3) == "ActionTypeId.Provider":
                    providers[identity] = unquoted(cells[2])
        for identity, field, value in pipeline_rows:
            if not field.startswith("Configuration."):
                continue
            key = field.removeprefix("Configuration.")
            expected = {
                ("CodeCommit", "RepositoryName"): ("CodeCommit.Repository", "RepositoryName"),
                ("CodeBuild", "ProjectName"): ("CodeBuild.Project", "Name"),
            }.get((providers.get(identity), key))
            link = RESOURCE_LINK_PATTERN.fullmatch(value)
            if expected:
                findings.check(bool(link), f"CodePipeline Configuration.{key} must link to its resource: {findings.relative(source)}")
            if not link:
                continue
            label, target_text, fragment = link.groups()
            target = (source if not target_text else source.parent / target_text).resolve()
            resource = resources.get((target, fragment))
            findings.check(
                bool(resource and target.parent == source.parent.resolve()),
                f"CodePipeline Configuration must link to a resource in the same target: {findings.relative(source)}: {value}",
            )
            if expected:
                findings.check(
                    bool(resource and resource[0] == expected[0] and configured_names.get((target, fragment), {}).get(expected[0] + "." + expected[1]) == label),
                    f"CodePipeline Configuration.{key} must display the referenced {expected[0]} name: {findings.relative(source)}: {value}",
                )
        list_resource_type = ""
        for line in document.headings.lines:
            if heading := RESOURCE_HEADING_PATTERN.fullmatch(line):
                list_resource_type = heading.group(1)
            elif line.startswith("#"):
                list_resource_type = ""
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != 4:
                continue
            cloudtrail = CLOUDTRAIL_DATA_RESOURCE.fullmatch(cells[1])
            linked_list = linked_list_property(cells[1], list_resource_type)
            if not cloudtrail and not linked_list:
                continue
            link = RESOURCE_LINK_PATTERN.fullmatch(cells[2])
            if not link:
                continue  # The display-row parser reports the missing resource link.
            _, target_text, fragment = link.groups()
            target = (source if not target_text else source.parent / target_text).resolve()
            resource = resources.get((target, fragment))
            expected = (
                {"S3": "S3.Bucket", "Lambda": "Lambda.Function"}[cloudtrail.group(2)]
                if cloudtrail else
                LINKED_LIST_PROPERTIES[linked_list[0]]
            )
            findings.check(
                bool(resource and resource[0] == expected and target.parent == source.parent.resolve()),
                f"{('CloudTrail DataResources' if cloudtrail else 'Subnet/Security Group list')} must link to a {expected} in the same target: {findings.relative(source)}: {cells[2]}",
            )
        try:
            source_lines = document.raw.display_lines
        except ValueError as error:
            findings.check(False, f"invalid Security Group tables: {findings.relative(source)}: {error}")
        variable_type = ""
        for line in source_lines:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) == 4:
                cells[1] = DISPLAY_PROPERTY_ALIASES.get(cells[1], cells[1])
                if cells[1] == CODEBUILD_FORMAL_VARIABLE + "Type":
                    variable_type = unquoted(cells[2])
            link = RESOURCE_LINK_PATTERN.fullmatch(cells[2]) if len(cells) == 4 else None
            if not link:
                continue
            label, target_text, fragment = link.groups()
            target = (source if not target_text else source.parent / target_text).resolve()
            resource = resources.get((target, fragment))
            if expected := RESOURCE_REFERENCE_PROPERTIES.get(cells[1]):
                findings.check(
                    bool(resource and resource[0] == expected[0] and target.parent == source.parent.resolve()),
                    f"{cells[1]} must link to a {expected[0]} in the same target: {findings.relative(source)}: {cells[2]}",
                )
                findings.check(
                    configured_names.get((target, fragment), {}).get(expected[0] + "." + expected[1]) == label,
                    f"{cells[1]} must display the referenced {expected[0]}.{expected[1]}: {findings.relative(source)}: {label}",
                )
                continue
            if cells[1] == CODEBUILD_FORMAL_VARIABLE + "Value":
                expected_type = {"SECRETS_MANAGER": "SecretsManager.Secret", "PARAMETER_STORE": "SSM.Parameter"}.get(variable_type)
                findings.check(
                    bool(resource and target.parent == source.parent.resolve() and (not expected_type or resource[0] == expected_type)),
                    f"CodeBuild environment variable must link to a {expected_type or 'resource'} in the same target: {findings.relative(source)}: {label}",
                )
                if variable_type == "SECRETS_MANAGER" and resource:
                    secret_name = resource[1].get("SecretsManager.Secret.Name", "")
                    findings.check(
                        bool(secret_name and (label == secret_name or label.startswith(secret_name + ":"))),
                        f"CodeBuild secret reference must display its configured name and optional selector: {findings.relative(source)}: {label}",
                    )
                continue
            if cells[1] == "EC2.SecurityGroup.VpcId":
                findings.check(
                    bool(resource and resource[0] == "EC2.VPC" and target.parent == source.parent.resolve()),
                    f"Security Group VpcId must link to a VPC in the same target: {findings.relative(source)}: {label}",
                )
            if cells[1] == S3_KMS_MASTER_KEY_ID:
                alias_name = (
                    resource[1].get("KMS.Alias.AliasName") if resource else None
                )
                findings.check(
                    bool(
                        resource
                        and resource[0] == "KMS.Alias"
                        and alias_name == label
                        and label.startswith("alias/")
                    ),
                    f"S3 KMSMasterKeyID must display the referenced KMS alias name: {findings.relative(source)}: {label}",
                )
                continue
            if not resource or not resource[1]:
                continue
            source_leaf = normalized(cells[1].split(".")[-1].replace("[]", ""))
            exact = [
                value
                for property_name, value in resource[1].items()
                if normalized(property_name.split(".")[-1]) == source_leaf
            ]
            expected = exact or list(resource[1].values())
            findings.check(
                label in expected,
                f"identifier reference does not match observed target: {findings.relative(source)}: {cells[1]}: {label}",
            )


def check_design_artifacts(paths: list[Path] | None = None, *, accounts, findings, markdown_design_artifacts, root) -> None:
    base = root / "docs" / "designs"
    artifacts = {path.resolve() for path in base.rglob("*.json")} if paths is None else {
        artifact.resolve() for path in paths for artifact in path.with_suffix("").rglob("*.json")
    }
    for artifact in sorted(artifacts):
        relative = artifact.relative_to(base)
        findings.check(len(relative.parts) == 4, f"design JSON artifact must be <environment>/<target-directory>/<service-id>/<file>: {findings.relative(artifact)}")
        if len(relative.parts) != 4:
            continue
        target = (relative.parts[0], relative.parts[1])
        findings.check(target in accounts, f"design JSON artifact target is not defined: {findings.relative(artifact)}")
        findings.check(LOWER_KEBAB_PATTERN.fullmatch(relative.parts[2]) is not None, f"invalid design JSON service ID: {findings.relative(artifact)}")
        findings.check(LOWER_KEBAB_PATTERN.fullmatch(artifact.stem) is not None, f"invalid design JSON artifact ID: {findings.relative(artifact)}")
        findings.check((artifact.parent.parent / f"{relative.parts[2]}.md").is_file(), f"design JSON artifact has no owning service Markdown: {findings.relative(artifact)}")
        try:
            content = json.loads(artifact.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            findings.errors.append(f"invalid design JSON artifact: {findings.relative(artifact)}: {error}")
            continue
        findings.check(isinstance(content, dict), f"design JSON artifact root must be an object: {findings.relative(artifact)}")
    findings.check(artifacts == markdown_design_artifacts, "design JSON artifacts must match Markdown links")

