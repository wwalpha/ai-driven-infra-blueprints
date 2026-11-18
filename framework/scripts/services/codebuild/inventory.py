"""Read and verify complete CodeBuild project batches."""

from typing import Any


def codebuild_details(ctx: Any, names: list[str]) -> list[dict[str, Any]]:
    if any(not isinstance(name, str) or not name for name in names) or len(
        set(names)
    ) != len(names):
        raise ValueError("IMPORT CodeBuild project names are invalid or duplicate")
    projects = []
    for offset in range(0, len(names), 100):
        requested = names[offset : offset + 100]
        response = ctx.call("codebuild", "batch_get_projects", names=requested)
        found = response.get("projects")
        missing = response.get("projectsNotFound", [])
        if not isinstance(found, list) or not isinstance(missing, list) or missing:
            raise ValueError("IMPORT CodeBuild batch has missing projects")
        returned = [
            item.get("name") if isinstance(item, dict) else None for item in found
        ]
        if len(returned) != len(set(returned)) or set(returned) != set(requested):
            raise ValueError("IMPORT CodeBuild batch response does not match request")
        projects.extend(found)
    return projects
