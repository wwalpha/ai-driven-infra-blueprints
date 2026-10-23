"""Invocation-local diagnostics and progress; elapsed time is not a work estimate."""

import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial as _bind_framework_callback

from utils.function_wrapper import FunctionWrapper

_current = ContextVar('sync_progress', default=None)
_output = ContextVar('sync_output', default=None)


def output_file(*, error=False):
    return _output.get() or (sys.stderr if error else sys.stdout)


@contextmanager
def diagnostics(output):
    token = _output.set(output)
    try:
        yield
    finally:
        _output.reset(token)


class Progress:
    def __init__(self, interval=30, output=None):
        self.started = time.monotonic()
        self.interval = interval
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.states = []
        self.consumers = set()
        self.completed = set()
        # The heartbeat thread has its own Context; retain this invocation's sink.
        self.output = output

    def emit(self, state, event):
        with self.lock:
            now = time.monotonic()
            label, phase, started, done, total, status = state
            count = f'{done}/{total}' if total is not None else 'unknown'
            print(f'sync-model progress: {event}; consumer={label}; '
                  f'completed={len(self.completed)}/{len(self.consumers) or "unknown"}; '
                  f'stage={phase}; items={count}; state={status}; '
                  f'elapsed={now-self.started:.1f}s; stage_elapsed={now-started:.1f}s; '
                  'remaining=unknown; heartbeat is not proof of progress', file=self.output or output_file(error=True), flush=True)

    def heartbeat(self):
        while not self.stop.wait(self.interval):
            with self.lock:
                for state in self.states:
                    self.emit(state, 'heartbeat')

    @contextmanager
    def worker(self, label):
        state = [label, 'contract-check', time.monotonic(), 0, None, 'running']
        token = _current.set((self, state))
        with self.lock:
            self.states.append(state)
            self.emit(state, 'start')
        try:
            yield
        except BaseException as error:
            state[5] = ('completed' if isinstance(error, SystemExit) and error.code == 0 else 'failed')
            self.emit(state, state[5])
            raise
        finally:
            with self.lock:
                self.states.remove(state)
            _current.reset(token)


def consumers(identities):
    if current := _current.get():
        progress, _ = current
        with progress.lock:
            progress.consumers.update('/'.join(identity) for identity in identities)


def completed(identity):
    if current := _current.get():
        progress, state = current
        with progress.lock:
            progress.completed.add('/'.join(identity))
            progress.emit(state, 'consumer-complete')


@contextmanager
def phase(name, total=None, status='running'):
    current = _current.get()
    if current is None:
        yield
        return
    progress, state = current
    with progress.lock:
        previous = state[1:]
        state[1:] = [name, time.monotonic(), 0, total, status]
        progress.emit(state, 'stage-start')
    try:
        yield
    except BaseException:
        state[5] = 'failed'
        progress.emit(state, 'stage-failed')
        raise
    finally:
        with progress.lock:
            progress.emit(state, 'stage-end')
            state[1:] = previous


def total(count):
    if current := _current.get():
        progress, state = current
        with progress.lock:
            state[3:5] = [0, count]


@contextmanager
def thread_lock(lock):
    if not lock.acquire(blocking=False):
        with phase('publication-lock', status='lock-wait'):
            lock.acquire()
    try:
        yield
    finally:
        lock.release()


def advance():
    if current := _current.get():
        progress, state = current
        with progress.lock:
            state[3] += 1


def _invoke_stage_decorate(function, name, /, *args, **kwargs):
    with phase(name):
        return function(*args, **kwargs)


def _callback_stage_decorate(name, /, function):
    wrapped = FunctionWrapper(function, _invoke_stage_decorate, name)
    return wrapped


def stage(name):
    decorate = _bind_framework_callback(_callback_stage_decorate, name)
    return decorate


def _invoke_tracked_sync(function, /, root, write, environment=None, target_directory=None, services=None, jobs=4, **kwargs):
    current = _current.get()
    if current is None:
        return function(root, write, environment, target_directory, services, jobs, **kwargs)
    progress, _ = current
    label = '/'.join((environment or '*', target_directory or '*', ','.join(services or ['*'])))
    with progress.worker(label):
        return function(root, write, environment, target_directory, services, jobs, **kwargs)


def tracked_sync(function):
    wrapped = FunctionWrapper(function, _invoke_tracked_sync)
    return wrapped


def _invoke_reported_main(function, /, *args, **kwargs):
    progress = Progress(output=output_file(error=True))
    thread = threading.Thread(target=progress.heartbeat, daemon=True)
    thread.start()
    try:
        with progress.worker('selection'):
            result = function(*args, **kwargs)
            _, state = _current.get()
            state[5] = ('failed' if result else 'completed' if progress.consumers == progress.completed else 'unfinished')
            progress.emit(state, state[5])
            return result
    finally:
        progress.stop.set()
        thread.join()


def reported_main(function):
    wrapped = FunctionWrapper(function, _invoke_reported_main)
    return wrapped
