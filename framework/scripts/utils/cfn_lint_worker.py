"""Private cfn-lint subprocess: SDK state and offline enforcement live here."""

import hashlib
import importlib.metadata
import io
import json
import multiprocessing
import os
import signal
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from json import JSONDecodeError
from pathlib import Path
from types import SimpleNamespace as _CallbackState

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib.util

from yaml.parser import ParserError
from yaml.scanner import ScannerError

from utils.cfn_lint import (
    VERSION,
    directory_state,
    failure,
    file_state,
    glob_state,
    interrupted,
    merge_progress,
    runtime,
)
from utils.function_wrapper import BoundCallback as _bind_framework_callback

try:
    import cfnlint.helpers as helpers
    import cfnlint.schema.manager as manager_module
    from cfnlint.config import ConfigMixIn
    from cfnlint.decode import cfn_json, cfn_yaml
    from cfnlint.formatters import JsonFormatter
    from cfnlint.match import Match
    from cfnlint.rules.errors import ConfigError
    from cfnlint.runner import Runner
    from cfnlint.schema import PROVIDER_SCHEMA_MANAGER as manager
    from cfnlint.schema._exceptions import ResourceNotFoundError
    from cfnlint.schema.manager import ProviderSchemaManager
except ImportError as error:
    CFN_RUNTIME_ERROR = error
else:
    CFN_RUNTIME_ERROR = None

class OfflineError(RuntimeError):
    pass


def _callback_structured_track(files, /, path):
    path = Path(path).absolute()
    if str(path) not in files:
        files[str(path)] = file_state(path)


def _callback_structured_offline(response, /, *args, **kwargs):
    response['processing_errors'].append(dict(code='schema_unavailable'))
    response['fatal'] = True
    raise OfflineError('offline schemas unavailable')


def _callback_structured_provider(offline, original_provider, track, /, self, region):
    track(self._providers_dir/'us-east-1.json')
    if not (self._providers_dir/'us-east-1.json').is_file():
        offline()
    path = self._providers_dir/(region+'.json')
    track(path)
    return original_provider(self,region)


def _callback_structured_schema(ResourceNotFoundError, offline, original_schema, progress, response, track, /, self, region, resource_type):
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
            failure = dict(code='schema_unavailable', resource_type=str(resource_type), region=str(region),
                           exception=type(error.__cause__).__name__)
            if failure not in response['processing_errors']:
                response['processing_errors'].append(failure)
            response['fatal'] = True
            progress()
        raise


def _callback_structured_track_config(config, manager, noecho, response, sensitive, track, track_directory, /):
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


def _callback_structured_parameters(noecho, parameters_property, sensitive, /, self):
    sets = parameters_property.fget(self)
    for parameter_set in sets:
        for key,value in parameter_set.parameters.items():
            if key in noecho:
                sensitive.add(str(value))
    return sets


def _callback_structured_template_args(original_template_args, track_config, /, self, template):
    original_template_args(self, template)
    # Observe effective Metadata dependencies before rules/parameter-file execution.
    track_config()


def _callback_structured_observe_load(cfn_json, cfn_yaml, loader, noecho, response, sensitive, /, path):
    event = dict(loader=loader.__module__, locator=str(path), success=False)
    response['decode'].append(event)
    try:
        value = loader(path)
    except BaseException as error:
        event['exception'] = type(error).__name__

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


def _callback_structured_observe(cfn_json, cfn_yaml, noecho, response, sensitive, /, loader):
    load = _bind_framework_callback(_callback_structured_observe_load, cfn_json, cfn_yaml, loader, noecho, response, sensitive)
    return load


def _callback_structured_track_directory(directories, track, /, path, pattern='*', *, contents=True):
    state = directory_state(path, pattern)
    directories.setdefault((state['locator'],pattern), state)
    if contents:
        for file in state['files']:
            track(file)


def _callback_structured_progress(dependencies, directories, emit, files, redact, request, response, selections, sent_directories, sent_files, sent_selections, /, match=None):
    if emit is None:
        return
    decoded = [event for event in response['decode'] if event['locator']==request['template']]
    success = bool(decoded and decoded[-1].get('success') and decoded[-1].get('root') in {'dict','dict_node'})
    state = {key:response[key] for key in ('completed','status','decode','effective_templates','requested_region','effective_regions','configuration_sources','schema_roots','effective_config_fingerprint','processing_errors','unverified','fatal') if key in response}
    state.update(decode_complete=success,input_defect=bool(decoded and not success and (decoded[-1].get('input_error') or decoded[-1].get('success'))))
    delta = dict(runtime=dependencies['runtime'],files=[value for key,value in files.items() if key not in sent_files],
                 directories=[value for key,value in directories.items() if key not in sent_directories],
                 selections=[value for key,value in selections.items() if key not in sent_selections])
    sent_files.update(files)
    sent_directories.update(directories)
    sent_selections.update(selections)
    packet = dict(state=state,dependencies=delta)
    if match is not None:
        safe = redact(match)
        if not success:
            safe['Message'] = 'Template decode incomplete; see Rule and Location'
        packet['match'] = safe
    emit({'progress':packet})


def _callback_structured_selected_files(original_glob, selections, /, self, filenames, raise_exception=True):
    for filename in filenames:
        pattern = str(Path(filename).absolute())
        selections.setdefault(pattern,glob_state(pattern))
    return original_glob(self,filenames,raise_exception=raise_exception)


def _recursive_structured_redact(sensitive, /, value):
    if isinstance(value,str):
        if any(secret and secret in value for secret in sensitive):
            return '<masked sensitive parameter>'
        return value
    if isinstance(value,list):
        return [_recursive_structured_redact(sensitive, v) for v in value]
    if isinstance(value,dict):
        return {k:_recursive_structured_redact(sensitive, v) for k,v in value.items()}
    return value


def _callback_structured_audit(_state_structured_217, response, track, /, event, args):
    pass
    if _state_structured_217.busy:
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
    _state_structured_217.busy = True
    try:
        track(path)
    finally:
        _state_structured_217.busy = False


def structured(request, emit=None):
    """Runs only inside a fresh child. Never persist exception text or source snippets."""
    _state_structured_217 = _CallbackState()
    os.chdir(request['cwd'])
    sys.dont_write_bytecode = True
    dependencies = dict(runtime=runtime(request['cwd']), files=[], directories=[], selections=[])
    response = dict(completed=False, status='processing_error', matches=[], decode=[], processing_errors=[],
                    unverified=[], dependencies=dependencies, fatal=False)
    files, directories, selections = {}, {}, {}
    track = _bind_framework_callback(_callback_structured_track, files)
    track_directory = _bind_framework_callback(_callback_structured_track_directory, directories, track)
    for base in (Path.home(), Path.cwd()):
        for name in ('.cfnlintrc','.cfnlintrc.yaml','.cfnlintrc.yml'):
            track(base/name)
    track(request['template'])
    if dependencies['runtime']['cfn_lint'] != VERSION:
        result = failure('lint.runtime_version_unavailable', fatal=True)
        return dict(response, **{k:v for k,v in result.items() if k!='dependencies'})
    sensitive, noecho = set(), set()
    redact = _bind_framework_callback(_recursive_structured_redact, sensitive)
    sent_files, sent_directories, sent_selections = set(),set(),set()
    progress = _bind_framework_callback(_callback_structured_progress, dependencies, directories, emit, files, redact, request, response, selections, sent_directories, sent_files, sent_selections)
    effective = []
    config = None
    stage = 'configuration'
    _state_structured_217.busy = False
    package = Path(dependencies['runtime']['distribution'])
    audit = _bind_framework_callback(_callback_structured_audit, _state_structured_217, response, track)
    sys.addaudithook(audit)
    try:
        offline = _bind_framework_callback(_callback_structured_offline, response)
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
        provider = _bind_framework_callback(_callback_structured_provider, offline, original_provider, track)
        ProviderSchemaManager._load_provider_module = provider
        original_schema = ProviderSchemaManager.get_resource_schema
        schema = _bind_framework_callback(_callback_structured_schema, ResourceNotFoundError, offline, original_schema, progress, response, track)
        schema.cache_clear = original_schema.cache_clear  # Preserve reset/override behavior of the pinned cached API.
        ProviderSchemaManager.get_resource_schema = schema
        original_glob = ConfigMixIn._glob_filenames
        selected_files = _bind_framework_callback(_callback_structured_selected_files, original_glob, selections)
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
        track_config = _bind_framework_callback(_callback_structured_track_config, config, manager, noecho, response, sensitive, track, track_directory)
        parameters_property = ConfigMixIn.parameters
        parameters = _bind_framework_callback(_callback_structured_parameters, noecho, parameters_property, sensitive)
        ConfigMixIn.parameters = property(parameters)
        original_template_args = ConfigMixIn.set_template_args
        template_args = _bind_framework_callback(_callback_structured_template_args, original_template_args, track_config)
        ConfigMixIn.set_template_args = template_args
        observe = _bind_framework_callback(_callback_structured_observe, cfn_json, cfn_yaml, noecho, response, sensitive)
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
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        return structured(request, emit)


# Strip parser subclasses through the existing JSON diagnostic contract before pickle.
def _callback_child_send(partial, sender, /, packet):
    # Strip parser subclasses through the existing JSON diagnostic contract before pickle.
    packet = json.loads(json.dumps(packet, allow_nan=False))
    if 'progress' in packet:
        merge_progress(partial, packet)
    sender.send(packet)


def child(request, sender):
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    partial = {}
    send = _bind_framework_callback(_callback_child_send, partial, sender)
    try:
        send(execute(request, send))
    except BaseException:
        send(interrupted(partial, 'child_execution'))
    finally:
        sender.close()




def _serve_terminate(signum, frame):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise SystemExit(1)


def reap_child(process):
    if process.pid is None:
        return
    try:
        if process.is_alive():
            process.terminate()
            process.join(timeout=0.1)
            if process.is_alive():
                process.kill()
        process.join()
    finally:
        process.close()


def serve():
    context = multiprocessing.get_context('fork')
    signal.signal(signal.SIGTERM, _serve_terminate)
    for line in sys.stdin:
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=child, args=(json.loads(line), sender))
        try:
            process.start()
            sender.close()
            partial = {}
            deadline = time.monotonic()+120
            while True:
                remaining = max(0, deadline-time.monotonic())
                if not receiver.poll(remaining):
                    result = interrupted(partial, 'timeout', fatal=True)
                    break
                try:
                    packet = receiver.recv()
                except EOFError:
                    result = interrupted(partial, 'child_abnormal_exit', fatal=True)
                    break
                if isinstance(packet, dict) and 'progress' in packet:
                    merge_progress(partial, packet)
                    emit_packet(sys.stdout, packet)
                else:
                    result = packet
                    break
            process.join(timeout=0.1)
            if process.exitcode not in (None, 0):
                result = interrupted(partial, 'child_abnormal_exit', fatal=True)
        finally:
            reap_child(process)
            receiver.close()
            sender.close()
        emit_packet(sys.stdout, result)


def emit_packet(protocol, packet):
    protocol.write(json.dumps(packet)+'\n')
    protocol.flush()


if __name__=='__main__':
    sys.dont_write_bytecode = True
    if '--once' in sys.argv:
        protocol = sys.stdout
        emit = _bind_framework_callback(emit_packet, protocol)
        print(json.dumps(execute(json.load(sys.stdin),emit)))
    else:
        serve()
