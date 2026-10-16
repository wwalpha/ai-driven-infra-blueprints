"""Explicit successful IT completion; no tracing or per-call path inspection."""
from functools import wraps
import sys


def it_case(function):
    # Capture the suite before wrapping patch/input_scope, whose code lives elsewhere.
    source = sys._getframe(1).f_globals['__file__']
    name = function.__name__

    @wraps(function)
    def completed(*args, **kwargs):
        result = function(*args, **kwargs)
        sys.audit('blueprint.it_case.completed', source, name)
        return result

    return completed


def module_complete(source):
    sys.audit('blueprint.it_case.completed', source, '__module__')
