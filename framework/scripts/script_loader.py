"""Load named sibling scripts once, preserving existing patch/module identity."""
import importlib.util
from pathlib import Path
import sys


def module(filename, name):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[name] = loaded
        spec.loader.exec_module(loaded)
    return sys.modules[name]
