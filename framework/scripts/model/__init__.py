"""Public Model API. The caller supplies read and authorized publication contexts."""

from contracts.model import key_kind as key_kind
from contracts.model import key_parts as key_parts
from contracts.model import row_has_resource_prefix as row_has_resource_prefix
from contracts.model import row_resource as row_resource
from utils.script_loader import module

import model.sources as _sources
from model.sources import list_models as list_models
from model.sources import load_model as load_model

# Callers retain publication_lock, authorization and fixed-input checks.
publish_transaction = _sources._publish_transaction
invocation_reads = _sources._invocation_reads
load_model_in_session = _sources._load_model
read_source_in_session = _sources._read_source_snapshot


def prepare_edit(snapshot, candidate, policy):
    prepare = module("model/operations.py", "model.operations").prepare_edit
    return prepare(snapshot, candidate, policy)


def prepare_observed(snapshot, changes, policy):
    prepare = module("model/observed.py", "model.observed").prepare_observed
    return prepare(snapshot, changes, policy)


def publish_edit(plan, context):
    publish = module("model/operations.py", "model.operations").publish_edit
    return publish(plan, context)


def render_model(snapshot, context):
    render = module("model/render.py", "model.render").render_model
    return render(snapshot, context)


def publish_edits(plans, context):
    """Publish prepared services as one guarded transaction."""
    _publish_plans = module("model/operations.py", "model.operations")._publish_plans
    return _publish_plans(tuple(plans), context)


def __getattr__(name):
    if name == "ModelView":
        return module("model/view.py", "model.view").ModelView
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def rebase_snapshot(snapshot, source_root, root):
    return module("model/snapshot_ops.py", "model.snapshot_ops").rebase_snapshot(
        snapshot, source_root, root
    )


def reference_snapshot(snapshot, keys):
    return module("model/snapshot_ops.py", "model.snapshot_ops").reference_snapshot(
        snapshot, keys
    )


def update_observed_snapshot(snapshot, outputs):
    return module(
        "model/snapshot_ops.py", "model.snapshot_ops"
    ).update_observed_snapshot(snapshot, outputs)


def parse_reference_field(key, raw):
    return module("model/references.py", "model.references")._json(key, raw)
