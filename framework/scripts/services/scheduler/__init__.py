"""Scheduler service registration."""

from ..import_contracts import ImportProfile
from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "scheduler",
    ("Scheduler.Schedule",),
    REFERENCES,
    import_profiles={
        "Scheduler.Schedule": ImportProfile(
            verify_list_fields=("Name", "GroupName"),
            verify_list_error="Schedule inventory does not confirm Name and GroupName",
        ),
    },
)
