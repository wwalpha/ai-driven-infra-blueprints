"""CloudFormation preparation reading scope, independent of workflow prose."""

from task_contract_core import safe_path
from utils.aws_mappings import definition_root
from utils.markdown_format import markdown_sections

# Empty anchor means the complete file. Keep full-file and explicit section metadata.
REQUIRED_READINGS = {
    "task-contract.md": ("",),
    "detailed-design.md": (
        "cloudformation-stack-detailed-design",
        "policy-account-selection",
    ),
    "model-information.md": (
        "cloudformation-deployment-policy",
        "model-authority",
        "properties-first-updates-and-display-generation",
        "properties-format",
        "resource-management-mode",
    ),
    "cloudformation.md": ("", "controlled-deploy-repair"),
    "observed-values.md": ("",),
    "loop-engineering.md": (
        "infrastructure-task-completion",
        "local-loop",
        "validation-scope",
    ),
    "project-configuration.md": ("",),
}


def required_readings(root):
    """Return the same full sources and selected bodies used by preparation snapshots."""
    base = definition_root(root).resolve()
    readings = {}
    for filename, anchors in REQUIRED_READINGS.items():
        relative = "framework/rules/" + filename
        safe_path(base, relative)
        path = base / relative
        content = path.read_bytes().decode("utf-8")
        sections = markdown_sections(content)
        for anchor in anchors:
            if anchor and anchor not in sections:
                raise ValueError(
                    f"missing required Deploy rule section: {relative}#{anchor}"
                )
        readings[path] = {
            "sections": list(anchors),
            "sourceText": content,
            "text": content
            if "" in anchors
            else "\n".join(sections[a] for a in anchors),
        }
    return readings
