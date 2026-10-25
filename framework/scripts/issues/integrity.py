"""Explicit Issue scan scope validation."""

import re


def selected_scope(environment, directory, services):
    values = [environment, directory, *services]
    if not services or any(
        not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", value) for value in values
    ):
        raise ValueError("explicit environment/target/services required")
    return {(environment, directory, service) for service in services}


def target_services(root, environment, directory):
    """Discover target membership without loading or validating other services."""
    selected_scope(environment, directory, ["scope"])
    services = {
        path.stem
        for base, suffix in (("model", ".properties"), ("docs/designs", ".md"))
        for path in (root / base / environment / directory).glob("*" + suffix)
        if path.is_file()
    }
    if not services:
        raise ValueError("target has no Model or design services")
    selected_scope(environment, directory, sorted(services))
    return sorted(services)


def whole_target(artifact):
    services, expected = artifact["services"], artifact["target_services"]
    selected_scope(artifact["environment"], artifact["target"], services)
    if (
        not isinstance(expected, list)
        or not expected
        or expected != sorted(set(expected))
        or services != expected
    ):
        missing = sorted(set(expected) - set(services))
        raise ValueError(
            f"whole-target snapshot required; missing services: {', '.join(missing)}"
        )
    results = artifact["service_results"]
    if (
        not isinstance(results, list)
        or len(results) != len(services)
        or sorted(item["service"] for item in results) != services
    ):
        raise ValueError("each target service requires an explicit result")
    if any(item.get("service") not in services for item in artifact["iac"]):
        raise ValueError("IaC record is outside snapshot service scope")
    for result in results:
        if result.get("status") not in {"scanned", "unverified"}:
            raise ValueError("invalid service result")
        if result["status"] == "unverified" and (
            not isinstance(result.get("reason"), str) or not result["reason"].strip()
        ):
            raise ValueError("unverified service result needs a reason")
