"""AutoScaling service registration."""

from ..reference_data import ServiceDeclaration
from .references import REFERENCES

DECLARATION = ServiceDeclaration(
    "auto-scaling",
    (
        "AutoScaling.AutoScalingGroup",
        "AutoScaling.LifecycleHook",
        "AutoScaling.ScalingPolicy",
        "AutoScaling.ScheduledAction",
    ),
    REFERENCES,
    package="auto_scaling",
)
