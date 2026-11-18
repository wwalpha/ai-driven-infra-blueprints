"""SNS service registration."""

from ..reference_data import ServiceDeclaration
from . import design
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "sns",
    (
        "SNS.Subscription",
        "SNS.Topic",
        "SNS.TopicPolicy",
    ),
    REFERENCES,
    design=design,
)
