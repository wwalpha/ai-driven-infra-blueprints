#!/usr/bin/env python3
"""Concurrent readers must never receive a partially initialized sibling module."""
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import sys
from threading import Event
from unittest.mock import patch

import script_loader


def main():
    started, release, entered, returned = (Event() for _ in range(4))
    name = '_script_loader_concurrent_fixture'

    class Loader:
        def create_module(self, spec):
            return None

        def exec_module(self, loaded):
            started.set()
            assert release.wait(5)
            loaded.ready = True

    spec = importlib.util.spec_from_loader(name, Loader())

    def second():
        entered.set()
        result = script_loader.module('fixture.py', name)
        returned.set()
        assert result.ready
        return result

    try:
        with patch.object(importlib.util, 'spec_from_file_location', return_value=spec) as locate, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(script_loader.module, 'fixture.py', name)
            assert started.wait(5)
            waiting = pool.submit(second)
            try:
                assert entered.wait(5)
                assert not returned.wait(0.1), 'partially initialized module escaped'
            finally:
                release.set()
            assert first.result(timeout=5) is waiting.result(timeout=5)
            assert locate.call_count == 1
    finally:
        sys.modules.pop(name, None)
    print('Script loader: PASS (concurrent initialization, complete module, shared identity)')


if __name__ == '__main__':
    main()
