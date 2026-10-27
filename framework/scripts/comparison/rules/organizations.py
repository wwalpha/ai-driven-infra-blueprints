"""Static Organizations comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "Organizations.Policy": properties(
        objects="""
            Content
            Tags[]
        """,
        ordered="""
            TargetIds
        """,
        scalars="""
            Description
            Name
            Tags[].Key
            Tags[].Value
            Type
        """,
        tags="""
            Tags
        """,
    ),
}
