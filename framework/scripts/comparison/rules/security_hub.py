"""Static SecurityHub comparison methods; container rules include their recursive contents."""

from ..methods import properties

RULES = {
    "SecurityHub.FindingAggregator": properties(
        ordered="""
            Regions
        """,
        scalars="""
            RegionLinkingMode
        """,
    ),
    "SecurityHub.Hub": properties(
        objects="""
            Tags
        """,
        scalars="""
            AutoEnableControls
            ControlFindingGenerator
            EnableDefaultStandards
        """,
    ),
}
