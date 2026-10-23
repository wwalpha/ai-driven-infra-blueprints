"""Explicit decorator state with ordinary function metadata and method binding."""

from functools import partial, update_wrapper
from types import MethodType


class FunctionWrapper:
    def __init__(self, function, invoke, *state):
        update_wrapper(self, function)
        self._invoke = invoke
        self._state = state

    def __call__(self, *args, **kwargs):
        return self._invoke(self.__wrapped__, *self._state, *args, **kwargs)

    def __get__(self, instance, owner=None):
        return self if instance is None else MethodType(self, instance)


class BoundCallback(partial):
    """Bind captured state while retaining function-style method access."""

    def __get__(self, instance, owner=None):
        return self if instance is None else MethodType(self, instance)
