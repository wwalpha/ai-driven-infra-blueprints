"""Decorator state preserves calls, metadata and Python method descriptors."""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.function_wrapper import FunctionWrapper

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


def increment(function, amount, *args, **kwargs):
    return function(*args, **kwargs) + amount


def value(number=1):
    """The decorated public signature."""
    return number


def check_wrapper():
    wrapped = FunctionWrapper(value, increment, 2)
    assert wrapped(number=4) == 6
    assert wrapped.__name__ == value.__name__
    assert wrapped.__doc__ == value.__doc__
    assert inspect.signature(wrapped) == inspect.signature(value)
    assert wrapped.__wrapped__ is value


def method_value(self, number=1):
    return self.offset + number


class BoundExample:
    offset = 10
    method = FunctionWrapper(method_value, increment, 3)


def check_method_binding():
    instance = BoundExample()
    assert instance.method(2) == 15
    assert BoundExample.method(instance, 2) == 15
    assert str(inspect.signature(instance.method)) == '(number=1)'


if __name__ == "__main__":
    check_wrapper()
    check_method_binding()
    print("Function wrapper checks: PASS (2 checks)")
