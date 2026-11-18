"""Scheduler service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "scheduler",
    ("Scheduler.Schedule",),
    REFERENCES,
)
