"""Shared diagnostic identity and redacted text."""

import hashlib
import json
import re

from utils.iac_values import safe_value


def identifier(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:20]


def safe_text(text):
    value = safe_value(text)
    value = re.sub(
        r"(?i)((?:password|secretstring|token|credential)\s*[=:]\s*)[^\s,;]+",
        r"\1<masked>",
        value,
    )
    return value.replace("\n", " ").replace("\r", " ")
