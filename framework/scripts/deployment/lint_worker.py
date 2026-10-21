"""Operation-owned cfn-lint imports; each invocation has private rule/schema state."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import json
import multiprocessing
from pathlib import Path
import signal
import subprocess
import sys
import traceback


class Worker:
    def __init__(self):
        self.process = None

    def run(self, args, **kwargs):
        if self.process is None:
            self.process = subprocess.Popen(
                [sys.executable, '-B', str(Path(__file__).resolve())],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8')
        try:
            self.process.stdin.write(json.dumps(args) + '\n')
            self.process.stdin.flush()
            response = json.loads(self.process.stdout.readline())
            if (set(response) != {'returncode', 'stdout', 'stderr'} or
                    type(response['returncode']) is not int or
                    not all(isinstance(response[key], str) for key in ('stdout', 'stderr'))):
                raise ValueError('invalid lint worker response')
            return subprocess.CompletedProcess(args, **response)
        except (OSError, ValueError, TypeError) as error:
            raise ValueError('cfn-lint worker communication failed') from error

    def close(self):
        if self.process is None:
            return
        try:
            try:
                self.process.stdin.close()
            except OSError:
                pass
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        finally:
            self.process.stdout.close()


@contextmanager
def scope(backend, units):
    # Windows keeps the existing CLI path; fork isolation is confined to this helper.
    if len(units) < 2 or sys.platform == 'win32':
        yield
        return
    worker = Worker()
    previous = getattr(backend, 'lint', None)
    backend.lint = worker.run
    try:
        yield
    finally:
        try:
            worker.close()
        finally:
            if previous is None:
                del backend.lint
            else:
                backend.lint = previous


def lint(args, connection):
    from cfnlint.runner import main
    stdout, stderr, code = io.StringIO(), io.StringIO(), 0
    sys.argv = args
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            main()
        except SystemExit as error:
            code = error.code or 0
            if not isinstance(code, int):
                print(code, file=sys.stderr)
                code = 1
        except BaseException:
            traceback.print_exc()
            code = 1
    connection.send({'returncode': code, 'stdout': stdout.getvalue(), 'stderr': stderr.getvalue()})
    connection.close()


def serve():
    # Fork only this single-threaded helper, never the controller.
    import cfnlint.runner
    context = multiprocessing.get_context('fork')
    def terminate(signum, frame):
        raise SystemExit(1)
    signal.signal(signal.SIGTERM, terminate)
    for line in sys.stdin:
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=lint, args=(json.loads(line), sender))
        try:
            process.start()
            sender.close()
            response = receiver.recv()
            process.join()
            if process.exitcode:
                raise RuntimeError('lint child exited without completing')
            print(json.dumps(response), flush=True)
        finally:
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                process.join()
                process.close()
            receiver.close()
            sender.close()


if __name__ == '__main__':
    serve()
