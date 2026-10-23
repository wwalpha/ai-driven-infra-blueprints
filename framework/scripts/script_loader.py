"""Load named sibling scripts once, preserving existing patch/module identity."""
import importlib
import importlib.util
import sys
from pathlib import Path
from threading import RLock

_lock = RLock()


def module(filename, name):
    with _lock:
        if name.startswith('model.'):
            expected = Path(__file__).parent / filename
            canonical = Path(__file__).parent.joinpath(*name.split('.')).with_suffix('.py')
            if expected != canonical:
                raise ValueError('package module requires its canonical path: ' + name)
            return importlib.import_module(name)
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
            loaded = importlib.util.module_from_spec(spec)
            sys.modules[name] = loaded
            spec.loader.exec_module(loaded)
        return sys.modules[name]
