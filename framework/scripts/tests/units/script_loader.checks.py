#!/usr/bin/env python3
"""Concurrent readers must never receive a partially initialized sibling module."""

import sys
from functools import partial as _bind_framework_callback
from functools import partialmethod as _bind_framework_method
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import importlib.util
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import script_loader

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')




def _main_create_module(self, spec):
    return None


def _callback_main_second(entered, name, returned, /):
    entered.set()
    result = script_loader.module('fixture.py', name)
    returned.set()
    assert result.ready
    return result


def _callback_main_Loader_exec_module(self, release, started, /, loaded):
    started.set()
    assert release.wait(5)
    loaded.ready = True


def main():
    started, release, entered, returned = (Event() for _ in range(4))
    name = '_script_loader_concurrent_fixture'

    class Loader:
        create_module = _main_create_module

        exec_module = _bind_framework_method(_callback_main_Loader_exec_module, release, started)

    spec = importlib.util.spec_from_loader(name, Loader())

    second = _bind_framework_callback(_callback_main_second, entered, name, returned)

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
