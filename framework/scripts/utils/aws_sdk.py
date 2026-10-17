"""Lazy offline SDK definitions; configuration is fixed per Sdk instance."""
import os
from threading import Lock

from utils.lazy_definitions import load_once

_lock = Lock()
_instances = {}


class Sdk:
    def __init__(self, factory=None):
        if factory is None:
            from botocore.session import get_session
            factory = get_session
        self._factory = factory
        self.data_path = os.environ.get('AWS_DATA_PATH', '')
        self._lock = Lock()
        self._cache = {}
        self._models_lock = Lock()

    def session(self):
        def load():
            session = self._factory()
            # Botocore reads this lazily, so bind it before the first loader request.
            session.set_config_variable('data_path', self.data_path)
            return session
        return load_once(self._lock, self._cache, ('session',), load)

    def service_model(self, service):
        def load():
            session = self.session()
            with self._models_lock:
                return session.get_service_model(service)
        return load_once(self._lock, self._cache, ('service', service), load)


def sdk_for(root):
    from utils.aws_mappings import definition_root
    root = definition_root(root)
    return load_once(_lock, _instances, root, Sdk)
