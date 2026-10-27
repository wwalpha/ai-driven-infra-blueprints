"""Translate one-based Model array positions to registered definition paths."""

import re


def definition_path(path):
    return re.sub(r"\[[1-9][0-9]*\]", "[]", path)
