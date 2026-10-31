"""macie: selected properties -> read-only SDK responses; inputs in fetch()."""

from model.adapters.aws import one

APIS = {
    ("macie2", "list_classification_jobs"),
    ("macie2", "get_macie_session"),
    ("macie2", "describe_classification_job"),
}


def sensitive(prop):
    return False


def fetch(ctx, r, getter):
    if getter == "session":
        return dict(
            ctx.call("macie2", "get_macie_session"),
            AwsAccountId=ctx.target.get(
                "awsExecutionAccountId", ctx.target["awsAccountId"]
            ),
        )
    current = r.current("jobId")
    if not current:
        names = ctx.pages(
            "macie2",
            "list_classification_jobs",
            filterCriteria={
                "includes": [
                    {"key": "name", "comparator": "EQ", "values": [r.value("name")]}
                ]
            },
        ).get("items", [])
        current = one(
            [v for v in names if v["name"] == r.value("name")],
            "macie2.list_classification_jobs",
        )["jobId"]
    return ctx.call("macie2", "describe_classification_job", jobId=current)


SDK_OPERATIONS = {"Macie.ClassificationJob": "describe_classification_job"}


def fetch_sdk(ctx, r, operation):
    # Reuse the existing job selector and its cached Describe response.
    return ctx.fetch(r, "job")
