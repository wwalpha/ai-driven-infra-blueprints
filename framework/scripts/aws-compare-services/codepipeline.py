"""codepipeline: selected properties -> read-only SDK responses; inputs in fetch()."""

from typing import Any

from model.adapters.aws import MISSING

APIS = {("codepipeline", "get_pipeline")}


def sensitive(prop: str) -> bool:
    return prop.endswith("EnvironmentVariables[].Value") or prop.endswith(
        "Stages[].Actions[].Configuration"
    )


def fetch(ctx, r, getter):
    result = ctx.call("codepipeline", "get_pipeline", name=r.value("Name"))
    return dict(
        result["pipeline"],
        PipelineArn=result.get("metadata", {}).get("pipelineArn", MISSING),
    )


SDK_OPERATIONS = {"CodePipeline.Pipeline": "get_pipeline"}


def fetch_sdk(ctx: Any, r: Any, operation: str) -> dict[str, Any]:
    return ctx.call("codepipeline", operation, name=r.value("Name"))
