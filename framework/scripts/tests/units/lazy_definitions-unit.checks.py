#!/usr/bin/env python3
"""Caller-owned single-flight contracts, without AWS or timing-based synchronization."""

import sys
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from pathlib import Path
from threading import Barrier, Event, Lock
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
import utils.lazy_definitions as lazy
from support.pytest_cli import run

if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')


class Interrupted(BaseException):
    pass


class WaitingFuture(Future):
    def __init__(self, waiting):
        super().__init__()
        self.waiting = waiting

    def result(self, timeout=None):
        if not self.done():
            self.waiting.wait(timeout=10)
        return super().result(timeout)


class CheckedLock:
    def __init__(self):
        self.lock = Lock()
        self.entries = 0

    def __enter__(self):
        self.lock.acquire()
        self.entries += 1

    def __exit__(self, *args):
        self.lock.release()


class CheckedCache(dict):
    def __init__(self, lock, accesses):
        super().__init__()
        self.lock, self.accesses = lock, accesses

    def get(self, key):
        assert self.lock.lock.locked()
        self.accesses.append(('get', self.lock.entries))
        return super().get(key)

    def __setitem__(self, key, value):
        assert self.lock.lock.locked()
        self.accesses.append(('set', self.lock.entries))
        super().__setitem__(key, value)

    def __delitem__(self, key):
        assert self.lock.lock.locked()
        self.accesses.append(('del', self.lock.entries))
        super().__delitem__(key)


def blocked_load(entered, release, value, error):
    entered.set()
    assert release.wait(timeout=10)
    if error is not None:
        raise error
    return value


@pytest.mark.parametrize('error', [None, ValueError('failure'), Interrupted('cancelled')])
@pytest.mark.parametrize('evict', [False, True])
def check_waiters_share_one_flight(error, evict):
    entered, release, waiting = Event(), Event(), Barrier(4)
    cache, value = {}, object()
    load = Mock(side_effect=partial(blocked_load, entered, release, value, error))
    obtain = partial(lazy.load_once, Lock(), cache, 'key', load, evict_on_failure=evict)
    with patch.object(lazy, 'Future', partial(WaitingFuture, waiting)), ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(obtain)
        try:
            assert entered.wait(timeout=10)
            requests = [first, *(pool.submit(obtain) for _ in range(3))]
            waiting.wait(timeout=10)  # Every waiter has obtained the same pending Future.
        finally:
            release.set()
        if error is None:
            assert all(request.result(timeout=10) is value for request in requests)
        else:
            assert all(request.exception(timeout=10) is error for request in requests)
    assert load.call_count == 1
    assert ('key' in cache) == (error is None or not evict)


def parallel_load(barrier, value):
    barrier.wait(timeout=10)
    return value


def check_different_keys_load_in_parallel():
    lock, cache, barrier = Lock(), {}, Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(lazy.load_once, lock, cache, key, partial(parallel_load, barrier, key))
                    for key in ('first', 'other')]
        assert [request.result(timeout=10) for request in requests] == ['first', 'other']


@pytest.mark.parametrize('evict', [False, True])
def check_failure_policy_and_retry(evict):
    lock, accesses = CheckedLock(), []
    cache = CheckedCache(lock, accesses)
    error, value = Interrupted('cancelled'), object()
    load = Mock(side_effect=[error, value])
    with pytest.raises(Interrupted) as caught:
        lazy.load_once(lock, cache, 'key', load, evict_on_failure=evict)
    assert caught.value is error
    if evict:
        assert accesses == [('get', 1), ('set', 1), ('get', 2), ('del', 2)]
        assert lazy.load_once(lock, cache, 'key', load, evict_on_failure=True) is value
    else:
        with pytest.raises(Interrupted) as repeated:
            lazy.load_once(lock, cache, 'key', load)
        assert repeated.value is error
    assert load.call_count == (2 if evict else 1)


def replace_and_fail(lock, cache, replacement, error):
    with lock:
        cache['key'] = replacement
    raise error


def check_eviction_preserves_replacement():
    lock, cache, replacement, error = Lock(), {}, Future(), ValueError('failure')
    load = partial(replace_and_fail, lock, cache, replacement, error)
    with pytest.raises(ValueError) as caught:
        lazy.load_once(lock, cache, 'key', load, evict_on_failure=True)
    assert caught.value is error
    assert cache['key'] is replacement


def lookup(lock, accesses, found, value):
    assert lock.lock.locked()
    accesses.append(('lookup', lock.entries))
    return found, value


@pytest.mark.parametrize('value', [None, object()])
def check_lookup_hit_precedes_future_access(value):
    lock, accesses = CheckedLock(), []
    cache = CheckedCache(lock, accesses)
    load = Mock(side_effect=AssertionError('lookup hit must not load'))
    assert lazy.load_once(lock, cache, 'key', load,
                          lookup_locked=partial(lookup, lock, accesses, True, value)) is value
    assert accesses == [('lookup', 1)]
    assert not cache
    load.assert_not_called()


@pytest.mark.parametrize('cached', [False, True])
def check_lookup_miss_and_future_access_are_atomic(cached):
    lock, accesses, value = CheckedLock(), [], object()
    cache = CheckedCache(lock, accesses)
    if cached:
        future = Future()
        future.set_result(value)
        dict.__setitem__(cache, 'key', future)
    load = Mock(return_value=value)
    assert lazy.load_once(lock, cache, 'key', load,
                          lookup_locked=partial(lookup, lock, accesses, False, None)) is value
    assert accesses == [('lookup', 1), ('get', 1)] + ([] if cached else [('set', 1)])
    assert lock.entries == 1
    assert load.call_count == (0 if cached else 1)


def unlocked_load(lock, value):
    assert lock.acquire(blocking=False), 'load must run outside the caller lock'
    lock.release()
    return value


def check_four_argument_api_and_success_cache():
    lock, cache, value = Lock(), {}, object()
    load = Mock(side_effect=partial(unlocked_load, lock, value))
    assert lazy.load_once(lock, cache, 'key', load) is value
    assert lazy.load_once(lock, cache, 'key', load) is value
    load.assert_called_once_with()


if __name__ == '__main__':
    raise SystemExit(run(__file__, message='Single-flight contracts: PASS'))
