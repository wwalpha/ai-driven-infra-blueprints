"""Public API annotations resolve without altering persisted values or call contracts."""

import ast
import importlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from deploy import controller, failures, handoff
from deploy.typing import DeliveryBoundary, Session, StackUnit
from model.sources import ModelSnapshot

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

MODULES = ('deploy.scheduler', 'deploy.session', 'deploy.controller', 'deploy.handoff', 'deploy.failures',
           'model.sources', 'model.operations', 'model.importing.approval', 'comparison.runner')


def public_apis(module):
    tree = ast.parse(Path(module.__file__).read_text(encoding='utf-8'))
    result = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
            result.append(getattr(module, node.name))
        elif isinstance(node, ast.ClassDef):
            cls = getattr(module, node.name)
            for method in node.body:
                if isinstance(method, ast.FunctionDef) and (not method.name.startswith('_') or method.name == '__init__'):
                    value = getattr(cls, method.name)
                    result.append(value.fget if isinstance(value, property) else value)
    return result


@pytest.mark.parametrize('name', MODULES)
def check_public_annotations(name):
    module = importlib.import_module(name)
    apis = public_apis(module)
    assert apis
    for function in apis:
        hints = get_type_hints(function)
        signature = inspect.signature(function)
        required = {p for p in signature.parameters if p not in {'self', 'cls'}} | {'return'}
        assert required <= hints.keys(), (name, function.__qualname__, required - hints.keys())
        assert all(hints[key] not in {object} and str(hints[key]) != 'typing.Any' for key in required)
    if name == 'model.sources':
        assert get_type_hints(ModelSnapshot)['scope'] is module.Scope
    if name == 'comparison.runner':
        assert get_type_hints(module.Settings)['result'] is module.RowResult


def check_typed_records_keep_json_and_runtime_shape(tmp_path):
    unit = {'name': 'A', 'template': 'app.yaml', 'parameters': 'a.json', 'deployOrder': '10'}
    session = {'states': {'A': {'status': 'RUNNING', 'clientToken': 'token'}}, 'metrics': {}}
    assert StackUnit(**unit) == unit
    assert Session(**session) == session
    assert get_origin(get_type_hints(Session)['states']) is dict
    assert get_args(get_type_hints(Session)['states'])[0] is str
    assert get_type_hints(DeliveryBoundary)['importNames'] == dict[str, set[str]]
    path = tmp_path / 'state.json'
    handoff.save(path, session)
    assert json.loads(path.read_text(encoding='utf-8')) == session
    runtime = controller.create_runtime(tmp_path, 'dev', 'team',
        {'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'cloudformation'})
    assert runtime.root == tmp_path and runtime.states == {} and callable(runtime.prepare)
    error = ValueError('no AWS call')
    state = {'status': 'RUNNING'}
    assert failures.exception(state, error, 'POLL') is None
    assert state['status'] == 'RUNNING' and state['failure']['executionState'] == 'UNKNOWN'




@pytest.mark.parametrize('name', MODULES)
def check_fresh_import_and_hints(name):
    code = """
import importlib, inspect, sys, typing
module = importlib.import_module(sys.argv[1])
for value in vars(module).values():
    if inspect.isfunction(value) and value.__module__ == module.__name__ and not value.__name__.startswith('_'):
        typing.get_type_hints(value)
"""
    result = subprocess.run([sys.executable, '-B', '-c', code, name], capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2])}, timeout=30)
    assert result.returncode == 0, result.stderr


if __name__ == '__main__':
    from support.pytest_cli import run
    raise SystemExit(run(__file__))
