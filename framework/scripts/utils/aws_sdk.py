"""Lazy offline SDK definitions; configuration is fixed per Sdk instance."""

import os
from functools import partial as _bind_framework_callback
from importlib import import_module
from threading import Lock

import utils.aws_mappings as _imports_utils_aws_mappings
from utils.lazy_definitions import load_once

_lock = Lock()
_instances = {}


def _callback_Sdk_session_load(self, /):
    session = self._factory()
    # Botocore reads this lazily, so bind it before the first loader request.
    session.set_config_variable('data_path', self.data_path)
    return session


def _callback_Sdk_service_model_load(self, service, /):
    session = self.session()
    with self._models_lock:
        return session.get_service_model(service)


class Sdk:
    def __init__(self, factory=None):
        if factory is None:
            get_session = aws_runtime().sdk_session
            factory = get_session
        self._factory = factory
        self.data_path = os.environ.get('AWS_DATA_PATH', '')
        self._lock = Lock()
        self._cache = {}
        self._models_lock = Lock()

    def session(self):
        load = _bind_framework_callback(_callback_Sdk_session_load, self)
        return load_once(self._lock, self._cache, ('session',), load)

    def service_model(self, service):
        load = _bind_framework_callback(_callback_Sdk_service_model_load, self, service)
        return load_once(self._lock, self._cache, ('service', service), load)


def sdk_for(root):
    definition_root = _imports_utils_aws_mappings.definition_root
    root = definition_root(root)
    return load_once(_lock, _instances, root, Sdk)


def aws_runtime():
    """Activate the optional SDK integration at the capability boundary."""
    return import_module("utils.aws_sdk_runtime")
