"""Static Macie comparison methods; container rules include their recursive contents."""

from comparison.methods import properties

RULES = {
    "Macie.Session": properties(
        scalars="""
            FindingPublishingFrequency
            Status
        """,
    ),
}
