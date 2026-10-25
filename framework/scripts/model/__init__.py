"""Public Model API. The caller supplies read and authorized publication contexts."""

from utils.script_loader import module

from model.sources import list_models as list_models
from model.sources import load_model as load_model


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
