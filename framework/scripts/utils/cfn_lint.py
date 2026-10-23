"""Isolated cfn-lint 1.57.2 adapter. All version-specific private API stays here."""
from contextlib import contextmanager, redirect_stdout, redirect_stderr
import hashlib
import glob
import importlib.metadata
import io
import json
import multiprocessing
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

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
                result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--once'],
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
                self.process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve())],
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

    def run(self, args, **kwargs):
        response = self.request(args)
        if (set(response) != {'returncode','stdout','stderr'} or type(response['returncode']) is not int
                or not all(isinstance(response[key],str) for key in ('stdout','stderr'))):
            raise ValueError('cfn-lint worker communication failed')
        return subprocess.CompletedProcess(args, **response)

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


@contextmanager
def scope(backend, units):
    # Retain the historical compatibility scope, without changing deploy callers.
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


class OfflineError(RuntimeError):
    pass


def structured(request, emit=None):
    """Runs only inside a fresh child. Never persist exception text or source snippets."""
    os.chdir(request['cwd'])
    sys.dont_write_bytecode = True
    dependencies = dict(runtime=runtime(request['cwd']), files=[], directories=[], selections=[])
    response = dict(completed=False, status='processing_error', matches=[], decode=[], processing_errors=[],
                    unverified=[], dependencies=dependencies, fatal=False)
    files, directories, selections = {}, {}, {}
    def track(path):
        path = Path(path).absolute()
        if str(path) not in files:
            files[str(path)] = file_state(path)
    def track_directory(path, pattern='*', *, contents=True):
        state = directory_state(path, pattern)
        directories.setdefault((state['locator'],pattern), state)
        if contents:
            for file in state['files']:
                track(file)
    for base in (Path.home(), Path.cwd()):
        for name in ('.cfnlintrc','.cfnlintrc.yaml','.cfnlintrc.yml'):
            track(base/name)
    track(request['template'])
    if dependencies['runtime']['cfn_lint'] != VERSION:
        result = failure('lint.runtime_version_unavailable', fatal=True)
        return dict(response, **{k:v for k,v in result.items() if k!='dependencies'})
    sensitive, noecho = set(), set()
    def redact(value):
        if isinstance(value,str):
            if any(secret and secret in value for secret in sensitive):
                return '<masked sensitive parameter>'
            return value
        if isinstance(value,list):
            return [redact(v) for v in value]
        if isinstance(value,dict):
            return {k:redact(v) for k,v in value.items()}
        return value
    sent_files, sent_directories, sent_selections = set(),set(),set()
    def progress(match=None):
        if emit is None:
            return
        decoded = [event for event in response['decode'] if event['locator']==request['template']]
        success = bool(decoded and decoded[-1].get('success') and decoded[-1].get('root') in {'dict','dict_node'})
        state = {key:response[key] for key in ('decode','effective_templates','requested_region','effective_regions','configuration_sources','schema_roots','effective_config_fingerprint','processing_errors','unverified','fatal') if key in response}
        state.update(decode_complete=success,input_defect=bool(decoded and not success and (decoded[-1].get('input_error') or decoded[-1].get('success'))))
        delta = dict(runtime=dependencies['runtime'],files=[value for key,value in files.items() if key not in sent_files],
                     directories=[value for key,value in directories.items() if key not in sent_directories],
                     selections=[value for key,value in selections.items() if key not in sent_selections])
        sent_files.update(files);sent_directories.update(directories);sent_selections.update(selections)
        packet = dict(state=state,dependencies=delta)
        if match is not None:
            safe = redact(match)
            if not success:
                safe['Message'] = 'Template decode incomplete; see Rule and Location'
            packet['match'] = safe
        emit({'progress':packet})
    effective = []
    config = None
    stage = 'configuration'
    busy = False
    package = Path(dependencies['runtime']['distribution'])
    def audit(event, args):
        nonlocal busy
        if busy:
            return
        if event == 'socket.connect':
            response['processing_errors'].append(dict(code='schema_unavailable'))
            raise OfflineError('offline')
        if event != 'open' or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(args[0])).absolute()
        mode = args[1]
        flags = args[2]
        if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT)):
            raise OfflineError('issues lint cannot write files')
        if path.suffix in {'.py','.pyc'} or str(path).startswith('/dev/'):
            return
        busy = True
        try:
            track(path)
        finally:
            busy = False
    sys.addaudithook(audit)
    try:
        from cfnlint.config import ConfigMixIn
        from cfnlint.runner import Runner
        from cfnlint.formatters import JsonFormatter
        from cfnlint.decode import cfn_yaml, cfn_json
        from cfnlint.schema.manager import ProviderSchemaManager
        from cfnlint.schema._exceptions import ResourceNotFoundError
        from cfnlint.schema import PROVIDER_SCHEMA_MANAGER as manager
        import cfnlint.schema.manager as manager_module
        import cfnlint.helpers as helpers
        def offline(*args, **kwargs):
            response['processing_errors'].append(dict(code='schema_unavailable'))
            response['fatal'] = True
            raise OfflineError('offline schemas unavailable')
        ProviderSchemaManager.update = offline
        for module in (manager_module, helpers):
            for name in ('get_url_content','get_url_metadata','get_url_retrieve','url_has_newer_version'):
                if hasattr(module,name):
                    setattr(module,name,offline)
        manager.__init__()
        # Include both alternatives and version dates used to select cache vs bundled schemas.
        for base in (package/'data', Path(helpers.get_cache_dir())):
            track(base/'version.json')
            track_directory(base/'providers','*.json', contents=False)
        original_provider = ProviderSchemaManager._load_provider_module
        def provider(self, region):
            track(self._providers_dir/'us-east-1.json')
            if not (self._providers_dir/'us-east-1.json').is_file():
                offline()
            path = self._providers_dir/(region+'.json')
            track(path)
            return original_provider(self,region)
        ProviderSchemaManager._load_provider_module = provider
        original_schema = ProviderSchemaManager.get_resource_schema
        def schema(self, region, resource_type):
            schema_hash = None
            normalized = self._normalize_resource_type(resource_type)
            if resource_type not in self._registry_schemas and normalized != 'Module' and normalized not in self._removed_types:
                mapping = self._load_provider_module(region)
                schema_hash = mapping.get(self._normalize_resource_type(resource_type))
                if schema_hash:
                    path = self._resources_dir/(schema_hash+'.json')
                    track(path)
                    if not path.is_file():
                        offline()
            try:
                return original_schema(self,region,resource_type)
            except ResourceNotFoundError as error:
                # The pinned loader chains only provider I/O/JSON/Schema construction failures.
                if schema_hash and error.__cause__ is not None:
                    failure = dict(code='schema_unavailable', resource_type=str(resource_type), region=region,
                                   exception=type(error.__cause__).__name__)
                    if failure not in response['processing_errors']:
                        response['processing_errors'].append(failure)
                    response['fatal'] = True
                    progress()
                raise
        schema.cache_clear = original_schema.cache_clear  # Preserve reset/override behavior of the pinned cached API.
        ProviderSchemaManager.get_resource_schema = schema
        original_glob = ConfigMixIn._glob_filenames
        def selected_files(self, filenames, raise_exception=True):
            for filename in filenames:
                pattern = str(Path(filename).absolute())
                selections.setdefault(pattern,glob_state(pattern))
            return original_glob(self,filenames,raise_exception=raise_exception)
        ConfigMixIn._glob_filenames = selected_files
        config = ConfigMixIn(['--regions', request['region'], '--template', request['template'], '--format','json'])
        config.validate()
        if config.deployment_files:
            raise ValueError('deployment_files conflicts with explicit template')
        response['configuration_sources'] = [str(p) for p in (config._user_config_file,config._project_config_file,config._custom_config_file) if p]
        response['schema_roots'] = dict(providers=str(manager._providers_dir),resources=str(manager._resources_dir))
        config._manual_args['build_graph'] = False
        effective = [str(Path(path).resolve()) for path in config.templates]
        response['effective_templates'] = effective
        response['requested_region'] = request['region']
        response['effective_regions'] = list(config.regions)
        # Use ConfigMixIn's resolution, including Metadata and merge_configs; never parse rc ourselves.
        def track_config():
            response['effective_regions'] = list(config.regions)
            for region in config.regions:
                manager._load_provider_module(region)
            for attr in ('parameter_files','append_rules','override_spec','registry_schemas','custom_rules'):
                values = getattr(config,attr)
                if not values:
                    continue
                for value in values if isinstance(values,list) else [values]:
                    path = Path(os.path.expanduser(str(value)))
                    if not path.exists() and attr=='append_rules':
                        import importlib.util
                        spec = importlib.util.find_spec(str(value))
                        if spec and spec.origin:
                            path = Path(spec.origin).parent
                    if path.is_dir():
                        track_directory(path)
                    else:
                        track(path)
            for parameter_set in config.parameters:
                for key,value in parameter_set.parameters.items():
                    if key in noecho:
                        sensitive.add(str(value))
        parameters_property = ConfigMixIn.parameters
        def parameters(self):
            sets = parameters_property.fget(self)
            for parameter_set in sets:
                for key,value in parameter_set.parameters.items():
                    if key in noecho:
                        sensitive.add(str(value))
            return sets
        ConfigMixIn.parameters = property(parameters)
        original_template_args = ConfigMixIn.set_template_args
        def template_args(self, template):
            original_template_args(self, template)
            # Observe effective Metadata dependencies before rules/parameter-file execution.
            track_config()
        ConfigMixIn.set_template_args = template_args
        def observe(loader):
            def load(path):
                event = dict(loader=loader.__module__, locator=str(path), success=False)
                response['decode'].append(event)
                try:
                    value = loader(path)
                except BaseException as error:
                    event['exception'] = type(error).__name__
                    from yaml.parser import ParserError
                    from yaml.scanner import ScannerError
                    from json import JSONDecodeError
                    event['input_error'] = isinstance(error,(ParserError,ScannerError,JSONDecodeError,UnicodeError,cfn_yaml.CfnParseError,cfn_json.JSONDecodeError))
                    raise
                event.update(success=True, root=type(value).__name__)
                if isinstance(value,dict) and isinstance(value.get('Parameters',{}),dict):
                    for key,definition in value.get('Parameters',{}).items():
                        if isinstance(definition,dict) and definition.get('NoEcho'):
                            noecho.add(key)
                            if 'Default' in definition:
                                sensitive.add(str(definition['Default']))
                return value
            return load
        cfn_yaml.load = observe(cfn_yaml.load)
        cfn_json.load = observe(cfn_json.load)
        if not effective:
            response.update(status='excluded_by_config')
            response['unverified'].append(dict(code='excluded_by_config'))
        elif effective != [request['template']]:
            raise ValueError('effective template set differs from explicit target')
        else:
            track_config()
            response['effective_config_fingerprint'] = hashlib.sha256(repr(config).encode()).hexdigest()
            progress()
            stage = 'execution'
            runner = Runner(config)
            # Even exceptional iterators retain matches already yielded.
            for match in runner.run():
                response['matches'].append(json.loads(json.dumps(match, cls=JsonFormatter.CustomEncoder)))
                progress(response['matches'][-1])
            response.update(completed=True,status='completed')
            track_config()
        response['effective_config_fingerprint'] = hashlib.sha256(repr(config).encode()).hexdigest()
    except BaseException as error:
        if stage=='configuration' and not isinstance(error,OfflineError):
            from cfnlint.match import Match
            from cfnlint.rules.errors import ConfigError
            from cfnlint.formatters import JsonFormatter
            match = Match('Effective lint configuration unavailable; exception text withheld',ConfigError(),None)
            response['matches'].append(json.loads(json.dumps(match,cls=JsonFormatter.CustomEncoder)))
        response['processing_errors'].append(dict(code='schema_unavailable' if isinstance(error,OfflineError) else 'lint.execution', exception=type(error).__name__))
        response['unverified'].append(dict(code='lint.execution_not_completed'))
    finally:
        dependencies['files'] = list(files.values())
        dependencies['directories'] = list(directories.values())
        dependencies['selections'] = list(selections.values())
    # The final YAML/JSON outcome wins; a successful JSON fallback is not a failed decode.
    decoded = [event for event in response['decode'] if event['locator']==request['template']]
    success = bool(decoded and decoded[-1].get('success') and decoded[-1].get('root') in {'dict','dict_node'})
    response['decode_complete'] = success
    response['input_defect'] = bool(decoded and not success and
        (decoded[-1].get('input_error') or decoded[-1].get('success')))
    if decoded and not success and not response['input_defect']:
        response['processing_errors'].append(dict(code='lint.decode_processing'))
    if effective and not success:
        response['unverified'].append(dict(code='lint.rules_after_decode_not_run'))
    # Match text may include an entire malformed source line. Drop it when no safe NoEcho model exists.
    if not success:
        for match in response['matches']:
            match['Message'] = 'Template decode incomplete; see Rule and Location'
    if response['processing_errors']:
        response['status'] = 'processing_error'
        response['completed'] = False
        if not response['unverified']:
            response['unverified'].append(dict(code='lint.processing_incomplete'))
    response['matches'] = redact(response['matches'])
    response['sensitive_values'] = list(sensitive)  # In-memory only; caller merges into its existing redactor.
    return response


def execute(request, emit=None):
    # Raw CLI compatibility is confined to this branch, with its historical network semantics.
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        if isinstance(request,dict):
            return structured(request,emit)
        from cfnlint.runner import main
        sys.argv = request
        code = 0
        try:
            main()
        except SystemExit as error:
            code = error.code or 0
            if not isinstance(code,int):
                code = 1
        except BaseException:
            import traceback
            traceback.print_exc()
            code = 1
        return dict(returncode=code, stdout=stdout.getvalue(), stderr=stderr.getvalue())


def child(request, sender):
    try:
        sender.send(execute(request,lambda packet:sender.send(packet)))
    except BaseException:
        sender.send(failure('child_execution'))
    finally:
        sender.close()


def serve():
    try:
        import cfnlint.runner  # Import once here; every job gets private rules/schema state after fork.
    except ImportError:
        pass
    context = multiprocessing.get_context('fork')
    def terminate(signum, frame):
        raise SystemExit(1)
    signal.signal(signal.SIGTERM,terminate)
    for line in sys.stdin:
        receiver,sender = context.Pipe(duplex=False)
        process = context.Process(target=child,args=(json.loads(line),sender))
        try:
            process.start()
            sender.close()
            partial = {}
            deadline = time.monotonic()+120
            while True:
                remaining = max(0,deadline-time.monotonic())
                if not receiver.poll(remaining):
                    result = interrupted(partial,'timeout')
                    break
                try:
                    packet = receiver.recv()
                except EOFError:
                    result = interrupted(partial,'child_abnormal_exit')
                    break
                if isinstance(packet,dict) and 'progress' in packet:
                    merge_progress(partial,packet)
                else:
                    result = packet
                    break
            process.join(timeout=1)
            if process.exitcode not in (None,0):
                result = interrupted(partial,'child_abnormal_exit')
            print(json.dumps(result),flush=True)
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


if __name__=='__main__':
    sys.dont_write_bytecode = True
    if '--once' in sys.argv:
        protocol = sys.stdout
        def emit(packet):
            protocol.write(json.dumps(packet)+'\n');protocol.flush()
        print(json.dumps(execute(json.load(sys.stdin),emit)))
    else:
        serve()
