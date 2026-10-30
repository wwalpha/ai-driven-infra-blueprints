"""Shared serialized comparison category and deferral contracts."""

CATEGORIES = ("matched", "difference", "deferred", "uncompared", "error", "excluded")
PHASES = ("unobserved", "pending_deploy", "awaiting_handoff")


def validate_cause(cause):
    if isinstance(cause, dict) and cause.get("kind") == "desired-value-excluded":
        if (
            set(cause) != {"kind", "phase", "consumer_property"}
            or cause["phase"] != "pending_deploy"
            or not isinstance(cause["consumer_property"], str)
            or not cause["consumer_property"].strip()
        ):
            raise ValueError("invalid desired PENDING_DEPLOY comparison cause")
        return
    if (
        not isinstance(cause, dict)
        or cause.get("kind")
        != (
            "import-reference-excluded"
            if cause.get("phase") == "pending_deploy"
            else "import-reference-deferred"
        )
        or cause.get("phase") not in PHASES
        or not isinstance(cause.get("consumer_property"), str)
        or not cause["consumer_property"]
        or not isinstance(cause.get("producer"), dict)
        or any(
            not isinstance(cause["producer"].get(key), str)
            or not cause["producer"][key]
            for key in ("service", "resource", "resourceType", "attribute")
        )
    ):
        raise ValueError("invalid IMPORT comparison cause")
