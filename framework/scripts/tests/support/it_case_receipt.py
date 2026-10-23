"""Explicit successful IT completion; no tracing or per-call path inspection."""

import sys

from utils.function_wrapper import FunctionWrapper


def _invoke_it_case(function, name, source, /, *args, **kwargs):
    result = function(*args, **kwargs)
    sys.audit('blueprint.it_case.completed', source, name)
    return result


def it_case(function):
    # Capture the suite before wrapping patch/input_scope, whose code lives elsewhere.
    source = sys._getframe(1).f_globals['__file__']
    name = function.__name__

    completed = FunctionWrapper(function, _invoke_it_case, name, source)

    return completed


def module_complete(source):
    sys.audit('blueprint.it_case.completed', source, '__module__')
