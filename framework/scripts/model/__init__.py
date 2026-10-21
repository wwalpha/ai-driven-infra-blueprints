"""Public Model API. The caller supplies read and authorized publication contexts."""
from model.sources import load_model, list_models


def prepare_edit(snapshot, candidate, policy):
    from model.operations import prepare_edit as prepare
    return prepare(snapshot, candidate, policy)


def prepare_observed(snapshot, changes, policy):
    from model.observed import prepare_observed as prepare
    return prepare(snapshot, changes, policy)


def publish_edit(plan, context):
    from model.operations import publish_edit as publish
    return publish(plan, context)


def render_model(snapshot, context):
    from model.render import render_model as render
    return render(snapshot, context)
