"""Explicit Issue scan scope validation."""

import re


def selected_scope(environment, directory, services):
    values = [environment, directory, *services]
    if not services or any(not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', value) for value in values):
        raise ValueError('explicit environment/target/services required')
    return {(environment, directory, service) for service in services}
