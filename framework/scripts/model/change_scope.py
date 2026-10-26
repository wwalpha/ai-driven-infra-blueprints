"""Read policy shared by Change Plan and reference resolution."""

from contextlib import contextmanager
from contextvars import ContextVar

_inputs = ContextVar("model_change_inputs", default=None)

_roots = ContextVar("model_change_index_roots", default=None)

_active = ContextVar("model_change_reads", default=False)


def active():
    return _active.get()


@contextmanager
def change_reads(root=None, reads=None, models=None):
    token = _active.set(True)
    inputs = _inputs.set(
        (root, reads, models or {}) if root is not None else _inputs.get()
    )
    try:
        yield
    finally:
        _inputs.reset(inputs)
        _active.reset(token)


def index_root(root):
    return (_roots.get() or {}).get(root, root)


@contextmanager
def index_stage(root, stage):
    token = _roots.set({**(_roots.get() or {}), stage: index_root(root)})
    try:
        yield
    finally:
        _roots.reset(token)


def inputs_for(root):
    value = _inputs.get()
    return value if value is not None and value[0] == root else (root, None, {})
