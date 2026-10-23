"""Target-batched, local desired → CloudFormation comparison. No AWS/provider calls."""
from __future__ import annotations

import hashlib
import re

from cloudformation_inputs import Blocked, load_template_inputs
from model.adapters.observed import resource_index
from model.core import entries, stack_model
from model.sources import model_exists
from model.files import load_model, resource_row_index
from policy_tables import literal


def model(self, service):
    if not re.fullmatch(r'[a-z0-9]+(?:[-_][a-z0-9]+)*', service):
        raise ValueError('invalid reference service')
    if service not in self.models:
        path = self.root / 'model' / self.environment / self.directory / (service + '.properties')
        loaded = load_model(path)
        self.warnings.extend(getattr(loaded, "warnings", ()))
        if service != 'cloudformation-stacks' and loaded.values.get(f'desired.service.{service}.serviceId') != service:
            raise ValueError(f'mismatched service ID: {path}')
        self.models[service] = loaded
        self._index = None
        self.symbols.clear()
        self.inputs.update(loaded.dependencies)
        self.read_hashes.update({file: None if raw is None else hashlib.sha256(raw).hexdigest() for file, raw in loaded.dependencies.items()})
        self.metrics['model_loads'] += 1
        self.metrics['model_parses'] += 1
        self.resources[service] = dict(entries(loaded.values, 'desired.resource.'))
        self.rows[service] = resource_row_index(loaded.values)
        for rows in self.rows[service].values():
            for _, row in rows:
                if re.search(r'password|secretstring|secretbinary|token|credential|privatekey', '.'.join(row.get('property', '').split('.')[2:]), re.I):
                    raw = row.get('document', row.get('value', ''))
                    self.sensitive_values.update((raw, literal(raw)))
    return self.models[service]


def source(self, service, key):
    location = self.models[service].locations.get(key) if service in self.models else None
    return {'path': location[0].relative_to(self.root).as_posix(), 'line': location[1], 'key': key} if location else None


def track(self, path):
    self.inputs.add(path)
    if path not in self.read_hashes:
        self.read_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def index(self):
    if self._index is None:
        loaded = {self.root / 'model' / self.environment / self.directory / (service + '.properties'): model.values
                  for service, model in self.models.items() if service != 'cloudformation-stacks'}
        self._index = resource_index(loaded, self.catalog)
    return self._index


def templates(self):
    if self._templates is not None:
        return self._templates
    stackpath = self.root / 'model' / self.environment / self.directory / 'cloudformation-stacks.properties'
    if not model_exists(stackpath):
        self._templates = []
        return self._templates
    _, stacks = stack_model(self.model('cloudformation-stacks').values)
    self._templates = stacks
    return self._templates


def stack(self, unit):
    name = unit['name']
    if name in self.stack_errors:
        raise self.stack_errors[name].with_traceback(None)
    try:
        return self.stack_input(unit)
    except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
        self.stack_errors[name] = error
        raise


def stack_input(self, unit):
    name = unit['name']
    template = self.root / 'infra/cloudformation/templates' / self.target.get('alias', '') / unit['template']
    parameters_path = self.root / 'infra/cloudformation/parameters' / self.environment / self.directory / unit['parameters']
    self.track(template)
    self.track(parameters_path)
    if name in self.stack_inputs:
        return template, self.stack_inputs[name]
    for path in (template, parameters_path):
        if not path.is_file():
            blocked = Blocked(f'stack input missing: {path.relative_to(self.root).as_posix()}')
            blocked.iac_cause = {'kind': 'template-missing' if path == template else 'parameters-missing',
                                 'path': path.relative_to(self.root).as_posix(), 'stack': name,
                                 'relationship': 'stack-input'}
            raise blocked
    if template not in self.documents:
        from utils.cloudformation_format import decode_file
        document, errors = decode_file(template, locations=self.template_locations)
        self.metrics['template_decodes'] += 1
        if errors or not isinstance(document, dict):
            raise ValueError(f'invalid template: {template}')
        self.documents[template] = document
    document = self.documents[template]
    _, values = load_template_inputs(template, parameters_path, strict_parameters=True, document=document)
    definitions = document.get('Parameters', {})
    for key, definition in definitions.items():
        if definition.get('NoEcho') or re.search(r'password|secret|token|credential', key, re.I):
            value = values[key]
            self.sensitive_values.update(str(item) for item in (value if isinstance(value, list) else [value]))
    pseudo = {'AWS::StackName': name, 'AWS::AccountId': self.target.get('awsExecutionAccountId', self.target['awsAccountId']),
              'AWS::Region': self.target['awsRegion'], 'AWS::NoValue': {'$noValue': True}}
    if not hasattr(self, 'partition'):
        from botocore.loaders import Loader
        self.partition = next((part['partition'] for part in Loader().load_data('endpoints')['partitions']
                               if self.target['awsRegion'] in part['regions']), None)
    if self.partition is not None:
        pseudo['AWS::Partition'] = self.partition
    self.stack_inputs[name] = document, values, pseudo
    self.metrics['stack_evaluations'] += 1
    return template, self.stack_inputs[name]


