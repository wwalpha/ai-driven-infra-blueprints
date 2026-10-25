"""config design display/restoration helpers."""

import re

from model.core import literal


def config_role_arn(prop: str, value: str) -> bool:
    return prop == "Config.ConfigurationRecorder.RoleARN" and bool(
        re.fullmatch(
            r"arn:aws(?:-[a-z]+)*:iam::[0-9]{12}:role/(?:[!-~]{1,510}/)?[A-Za-z0-9_+=,.@-]{1,64}",
            literal(value),
        )
    )


def is_import_role_arn(prop: str, value: str, mode: str) -> bool:
    return mode == "IMPORT" and config_role_arn(prop, value)
