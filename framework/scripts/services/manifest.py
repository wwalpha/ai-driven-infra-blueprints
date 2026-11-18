"""Explicit registration list. Each service declares its own capabilities."""

from .contracts import ServiceDefinition

SERVICES: tuple[ServiceDefinition, ...] = ()
