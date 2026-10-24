"""Isolated cfn-lint 1.57.2 adapter. All version-specific private API stays here."""

import glob
import hashlib
import importlib.metadata
import json
import os
import runpy
import select
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

POLICY = 'issues-raw-offline-v1'
VERSION = '1.57.2'


def runtime(cwd):
    try:
        version = importlib.metadata.version('cfn-lint')
        distribution = str(importlib.metadata.distribution('cfn-lint').locate_file('cfnlint').resolve())
    except importlib.metadata.PackageNotFoundError:
        version, distribution = None, None
    return dict(cwd=str(Path(cwd).resolve()), home=str(Path.home().resolve()), python=sys.version,
                executable=str(Path(sys.executable).resolve()), cache_environment={key:os.environ.get(key) for key in ('XDG_CACHE_HOME','LOCALAPPDATA')}, cfn_lint=version, distribution=distribution, policy=POLICY)


def file_state(path):
    path = Path(path).absolute()
    kind = 'symlink' if path.is_symlink() else 'file' if path.is_file() else 'directory' if path.is_dir() else 'missing'
    result = dict(locator=str(path), kind=kind)
    try:
        if kind in {'file', 'symlink'}:
            result['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        result['unreadable'] = type(error).__name__
    return result


def directory_state(path, pattern='*'):
    path = Path(path).absolute()
    return dict(locator=str(path), pattern=pattern,
                files=sorted(str(p.absolute()) for p in path.rglob(pattern) if p.is_file() or p.is_symlink()))


def glob_state(pattern):
    return dict(pattern=pattern, files=sorted(str(Path(p).absolute()) for p in glob.glob(pattern,recursive=True)))


def verify_dependencies(dependencies, *, cwd=None):
    if dependencies.get('runtime') != runtime(cwd or Path.cwd()):
        raise ValueError('stale scan: lint runtime/cwd/HOME differs; rescan in the same environment')
    for expected in dependencies.get('files', []):
        if file_state(expected['locator']) != expected:
            raise ValueError('stale scan: lint input changed: ' + expected['locator'])
    for expected in dependencies.get('selections', []):
        if glob_state(expected['pattern']) != expected:
            raise ValueError('stale scan: lint selected file set changed')
    for expected in dependencies.get('directories', []):
        if directory_state(expected['locator'], expected['pattern']) != expected:
            raise ValueError('stale scan: lint dependency file set changed: ' + expected['locator'])


def merge_progress(partial, packet):
    progress = packet['progress']
    if 'match' in progress:
        partial.setdefault('matches',[]).append(progress['match'])
    partial.update(progress.get('state',{}))
    dependencies = partial.setdefault('dependencies',{})
    for key,values in progress.get('dependencies',{}).items():
        if isinstance(values,list):
            dependencies.setdefault(key,[]).extend(values)
        else:
            dependencies[key] = values


def interrupted(partial, code, *, fatal=None):
    result = dict(partial)
    result.update(completed=False,status='processing_error',fatal=partial.get('fatal',False) if fatal is None else fatal)
    result.setdefault('matches',[])
    result.setdefault('decode',[])
    result.setdefault('processing_errors',[]).append(dict(code=code))
    result.setdefault('unverified',[]).append(dict(code=code))
    return result


def decode_response(stdout, *, timeout=False, abnormal=False):
    partial, result = {}, None
    if isinstance(stdout,bytes):
        stdout = stdout.decode('utf-8',errors='replace')
    for line in (stdout or '').splitlines():
        try:
            packet = json.loads(line)
            if not isinstance(packet,dict):
                raise ValueError('protocol')
            if 'progress' in packet:
                merge_progress(partial,packet)
            else:
                result = packet
        except (ValueError,TypeError,KeyError):
            if not timeout:
                return interrupted(partial,'invalid_protocol')
    return interrupted(partial,'timeout' if timeout else 'child_abnormal_exit') if timeout or abnormal else result or interrupted(partial,'invalid_protocol')


class Worker:
    """One single-threaded import helper; never fork the scan/validation process."""
    def __init__(self):
        self.process = None

    def request(self, request, timeout=120):
        if sys.platform == 'win32':
            try:
                result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('cfn_lint_worker.py').resolve()), '--once'],
                    input=json.dumps(request), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding='utf-8', timeout=timeout)
            except subprocess.TimeoutExpired as error:
                return decode_response(error.stdout,timeout=True)
            except OSError:
                return failure('launch_failure',fatal=True)
            if result.returncode:
                return decode_response(result.stdout,abnormal=True)
            return decode_response(result.stdout)
        if self.process is None:
            try:
                self.process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).with_name('cfn_lint_worker.py').resolve())],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
            except OSError:
                return failure('launch_failure',fatal=True)
        try:
            self.process.stdin.write(json.dumps(request)+'\n')
            self.process.stdin.flush()
            if not select.select([self.process.stdout], [], [], timeout+5)[0]:
                self.close()
                self.process = None
                return failure('timeout')
            result = json.loads(self.process.stdout.readline())
            if not isinstance(result, dict):
                raise ValueError('protocol')
            return result
        except (OSError, ValueError, TypeError):
            self.close()
            self.process = None
            return failure('invalid_protocol')


    def close(self):
        if self.process is None:
            return
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        finally:
            self.process.stdout.close()




def failure(code, *, fatal=False):
    return dict(completed=False, status='processing_error', matches=[], decode=[],
                processing_errors=[dict(code=code)], unverified=[dict(code=code)], fatal=fatal)


class LintSession:
    def __init__(self, cwd):
        self.cwd = str(Path(cwd).resolve())
        self.worker = Worker()
        self.fatal = False

    def validate(self, template, region):
        if self.fatal:
            return dict(completed=False, status='not_run', matches=[], decode=[], processing_errors=[],
                        unverified=[dict(code='lint.runtime_unavailable')])
        result = self.worker.request(dict(cwd=self.cwd, template=str(Path(template).resolve()), region=region))
        if (not isinstance(result,dict) or result.get('status') not in {'completed','processing_error','excluded_by_config','not_run'}
                or not isinstance(result.get('matches'), list) or type(result.get('completed')) is not bool
                or any(not isinstance(match,dict) or not isinstance(match.get('Rule'),dict)
                       or not isinstance(match.get('Rule',{}).get('Id'),str) or not isinstance(match.get('Level'),str)
                       or not isinstance(match.get('Location'),dict) or not isinstance(match.get('Message'),str) for match in result.get('matches', []))
                or any(not isinstance(result.get(key,[]),list) or any(not isinstance(v,dict) for v in result.get(key,[]))
                       for key in ('processing_errors','unverified','decode'))):
            result = failure('invalid_protocol')
        self.fatal = result.get('fatal', False)
        return result


@contextmanager
def lint_session(cwd):
    session = LintSession(cwd)
    try:
        yield session
    finally:
        session.worker.close()


def validate_template(session, template, region):
    return session.validate(template, region)




if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).with_name('cfn_lint_worker.py')), run_name='__main__')
