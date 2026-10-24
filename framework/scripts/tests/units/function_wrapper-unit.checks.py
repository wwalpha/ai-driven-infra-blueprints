"""Decorator state preserves calls, metadata and Python method descriptors."""
import inspect
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.function_wrapper import BoundCallback, FunctionWrapper

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


def captured_method(offset, self, number=1):
    return offset + self.offset + number


def check_callback_binding():
    callback = BoundCallback(captured_method, 3, number=2)
    instance = BoundExample()
    with patch.object(BoundExample, 'method', callback):
        assert instance.method() == 15
        assert BoundExample.method(instance, number=4) == 17
        assert callback(instance, number=5) == 18
    assert instance.method(2) == 15


def write_callback(original, failed, calls, /, path, data, *args, **kwargs):
    calls.append((path, data, kwargs))
    if path == failed:
        raise OSError('test write failure')
    return original(path, data, *args, **kwargs)


def check_path_write_text_binding():
    with tempfile.TemporaryDirectory() as directory:
        saved = Path(directory) / 'saved.md'
        failed = Path(directory) / 'failed.md'
        failed.write_text('old', encoding='utf-8')
        calls = []
        callback = BoundCallback(write_callback, Path.write_text, failed, calls)
        with patch.object(Path, 'write_text', callback):
            assert saved.write_text('日本語', encoding='utf-8') == 3
            assert Path.write_text(saved, 'class call', encoding='utf-8') == 10
            try:
                failed.write_text('changed', encoding='utf-8')
            except OSError as error:
                assert str(error) == 'test write failure'
            else:
                raise AssertionError('injected failure was not raised')
        assert calls == [(saved, '日本語', {'encoding': 'utf-8'}),
                         (saved, 'class call', {'encoding': 'utf-8'}),
                         (failed, 'changed', {'encoding': 'utf-8'})]
        assert saved.read_text(encoding='utf-8') == 'class call'
        assert failed.read_text(encoding='utf-8') == 'old'


if __name__ == "__main__":
    check_wrapper()
    check_method_binding()
    check_callback_binding()
    check_path_write_text_binding()
    print("Function wrapper checks: PASS (4 checks)")
