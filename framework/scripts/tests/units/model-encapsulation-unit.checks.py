"""The Model boundary gate and adversarial checks of its actual failure path."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from support.model_encapsulation import check_sources as _check_sources
from support.model_encapsulation import violations

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


@pytest.mark.parametrize(
    "source,rule",
    [
        ("from model.sources import _load_model as load", "model-private-api"),
        (
            "from model.core import (\n entries as enumerate_resources,\n)",
            "model-structural-api",
        ),
        ("import model.sources as s\nf = s._load_model\nf(scope)", "model-private-api"),
        ("import model\nmodel.sources._load_model(scope)", "model-private-api"),
        ("def f(snapshot):\n snapshot._replace(values={})", "model-private-state"),
        (
            "from model import load_model as load\nx=load(scope)\ny=x\ny._replace(values={})",
            "model-private-state",
        ),
        (
            "from model.sources import ModelSnapshot as S\nx=S(scope=scope)",
            "model-snapshot-construction",
        ),
        (
            "from dataclasses import replace as clone\ndef f(snapshot):\n clone(snapshot, values={})",
            "model-snapshot-construction",
        ),
        ("def f(snapshot):\n snapshot.authoritative['x']='v'", "model-state-write"),
        (
            "def f(snapshot):\n state=snapshot.dependencies\n alias=state\n alias.update({})",
            "model-state-write",
        ),
        ("def f(snapshot):\n snapshot.values={}", "model-state-write"),
        ("def f(snapshot):\n del snapshot.files['x']", "model-state-write"),
        ("def f(snapshot):\n snapshot.values |= {}", "model-state-write"),
        (
            "from model import ModelView as V\nv=V(values)\nv._values.update({})",
            "model-private-state",
        ),
        ("import model as m\nv=m.ModelView(values)\nv._index={}", "model-state-write"),
        ("def f(snapshot):\n setattr(snapshot, 'values', {})", "model-state-write"),
        (
            "def f(snapshot):\n getattr(snapshot, '_replace')(values={})",
            "model-private-state",
        ),
        (
            "import model.sources as m\ngetattr(m, '_load_model')(scope)",
            "model-private-api",
        ),
        ("owner = row_id.rsplit('-', 1)[0]", "model-row-owner"),
        (
            "from model import copy_snapshot_warnings as fork\nx=fork(snapshot)\nx._replace(values={})",
            "model-private-state",
        ),
        (
            "import importlib as i\nm=i.import_module('model.sources')\nm._load_model(scope)",
            "model-private-api",
        ),
        ("owner = row_id.rpartition('-')[0]", "model-row-owner"),
        ("owner = key.split('.')[2].rpartition('-')[0]", "model-key-grammar"),
        ("if key.startswith('desired.resource.'):\n pass", "model-key-grammar"),
        (
            r"import re; pattern=re.compile(r'desired\.row\.([^.]+)')",
            "model-key-grammar",
        ),
        (
            "m=module('model/core.py','model.core')\nf=m.structural_entries",
            "model-structural-api",
        ),
    ],
)
def check_forbidden_sources_fail(source, rule, tmp_path):
    assert any(found == rule for _, found in violations(source))
    (tmp_path / "consumer.py").write_text(source, encoding="utf-8")
    with pytest.raises(AssertionError, match=rule):
        _check_sources(tmp_path)


@pytest.mark.parametrize(
    "source",
    [
        "from model import ModelView as V\nv=V(values)\nrows=v.rows('001')\nrows.clear()",
        "from contracts.model import key_parts, row_resource\nowner=row_resource(key_parts(key)[2])",
        "from model.sources import ModelSnapshot as S\ndef f(snapshot: S):\n return snapshot.authoritative.get('key')",
        "from model import load_model\ns=load_model(scope)\nv=dict(s.authoritative)\nv.update({'x':'v'})",
        "from model import publish_transaction as _publish\n_publish(root, outputs, (), journal)",
        "label='desired.row.001.value'; print(label)",
        "visible=line.startswith('desired.resource.')",
        "owner=grid.rpartition('-')[0]",
        r"import re; allowed=re.fullmatch(r'desired\.row\.[A-Za-z0-9_-]+\.(?:value|document)', key)",
        "key='desired.resource.001.logicalId'; value=values[key]",
        "part, sep, logical=value.rpartition('-')",
        "property_kind=prop.split('.')[0]",
        "def f(record):\n return record._replace(value=1)",
        "import dataclasses\nnew=dataclasses.replace(record, value=1)",
        "model=module('model/adapters/aws.py', 'model.adapters.aws')\nfield=model.Field('api','x','n')",
        "def f(snapshot):\n return snapshot.locations.get(key)",
    ],
)
def check_public_and_unrelated_operations_pass(source):
    assert violations(source) == []


@pytest.mark.parametrize(
    "path", ["model/sources.py", "contracts/model.py", "tests/support/fixture.py"]
)
def check_implementation_and_synthetic_fixtures_pass(path):
    assert (
        violations("snapshot._replace(values={}); snapshot.values.update({})", path)
        == []
    )


def check_repository_model_boundary():
    _check_sources(Path(__file__).resolve().parents[2])


if __name__ == "__main__":
    from support.pytest_cli import run

    raise SystemExit(run(__file__))
