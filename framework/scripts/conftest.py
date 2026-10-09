"""Keep concurrent Pilot invocations from sharing pytest cleanup state."""

import tempfile
import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if config.option.basetemp is None:
        directory = tempfile.TemporaryDirectory(prefix="model-design-pytest-")
        config.option.basetemp = directory.name
        config.add_cleanup(directory.cleanup)
