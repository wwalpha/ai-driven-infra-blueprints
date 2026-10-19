"""Exact local reference matching; no acquisition, source edits or publication."""
import json
from pathlib import Path
import re

from model_core import LINK, entries, literal
from reference_contracts import (ARN_FORMS, VALUE_IDENTITIES, CONFIGURATION_PROPERTIES, CONTEXT_PROPERTIES,
                                 attributes_for, contract)


_UNOBSERVED = object()


def known(value):
    return (isinstance(value, str) and bool(value) and value not in
            {'UNSET', 'PENDING_DEPLOY', 'Pending', 'TBD', 'TODO', '未確定'} and
            not LINK.fullmatch(value) and not any(text in value for text in ('<<', '${', '{{resolve:')))


def elements(raw):
    value = literal(raw)
    if value.startswith('[') and not LINK.fullmatch(value):
        try:
            result = json.loads(value)
        except ValueError:
            return [raw]
        if isinstance(result, list):
            return result
    return [raw]


class Resolver:
    def __init__(self, root, environment, target, *, definitions_root=None, local=None):
        self.root, self.environment, self.target = Path(root), environment, target
        self.definitions_root = definitions_root or root
        self.local = local or {}
        self.files, self.indexes, self.targets = {}, {}, {}
        self.metrics = {'referenceModelReads': 0, 'referenceResources': 0}
        self.context = None
        self.partition = None
        self.model_paths = set()

    def index(self, kind):
        if kind in self.indexes:
            return self.indexes[kind]
        from import_scope import reference_reader
        from model_templates import _reference_inputs, reference_values, source_paths, safe
        from utils.aws_mappings import owners, mappings_for
        service = owners(self.definitions_root).get(kind)
        result = {}
        self.indexes[kind] = result
        self.targets[kind] = {}
        if service is None:
            return result
        properties = attributes_for(kind)
        mapping = mappings_for(self.definitions_root).get(service)
        aliases = {prop: {prop} | {key for key, item in mapping.properties.items()
                                  if key.startswith(kind + '.') and item.field.getter and item.field.path
                                  and (item.field.getter, item.field.path) == (mapping.properties[prop].field.getter, mapping.properties[prop].field.path)
                                  and item.transform == mapping.properties[prop].transform}
                   for prop in properties if prop in mapping.properties}
        selected_properties = tuple(sorted(set(properties) | {alias for group in aliases.values() for alias in group}))
        local_services = [name for name, model in self.local.items()
                          if any(resource.get('resourceType') == kind for _, resource in entries(model.values, 'desired.resource.'))]
        if len(local_services) > 1:
            raise ValueError('IMPORT ambiguous local producer service: ' + kind)
        service = local_services[0] if local_services else service
        path = self.root / 'model' / self.environment / self.target / (service + '.properties')
        if service in self.local:
            models = [self.local[service]]
        else:
            _, template, directory = source_paths(path)
            for file in (template, directory / 'parameters.yaml', directory / 'bindings.json', directory / 'observed.json'):
                safe(self.root, file)
            if not directory.exists():
                self.files[directory / 'parameters.yaml'] = None
                self.files[directory / 'bindings.json'] = None
                return result
            with reference_reader(path):
                _, (_, files, _, _, _, fields) = _reference_inputs(path)
                self.files.update(files)
                ids = [key.split('.')[2] for key in fields
                       if key.startswith('desired.resource.') and key.endswith('.resourceType')]
                models = [reference_values(path, rid, kind, ('physical', selected_properties)) for rid in ids]
            self.files.setdefault(directory / 'observed.json', None)
            self.model_paths.add(path)
            self.metrics['referenceModelReads'] = len(self.model_paths)
        for model in models:
            self.files.update(model.files)
            values = model.values
            rows = entries(values, 'desired.row.')
            for rid, resource in entries(values, 'desired.resource.'):
                if resource.get('resourceType') != kind:
                    continue
                physical = {}
                for row_id, row in rows:
                    if row_id.rpartition('-')[0] != rid or row.get('property') not in selected_properties:
                        continue
                    raw = values.get('observed.row.' + row_id + '.value', row.get('value', ''))
                    value = literal(raw)
                    if known(value) or value == 'PENDING_DEPLOY':
                        physical.setdefault(row['property'].removeprefix(kind + '.'), set()).add(value)
                        for prop, group in aliases.items():
                            if row['property'] in group:
                                physical.setdefault(prop.removeprefix(kind + '.'), set()).add(value)
                candidate = {'service': service, 'id': rid, 'anchor': resource['anchor'], 'kind': kind}
                self.targets[kind][service, rid] = candidate
                for form, candidates in physical.items():
                    if len(candidates) != 1:
                        raise ValueError('IMPORT ambiguous producer physical identifier: ' + kind + '.' + form)
                    result.setdefault((form, next(iter(candidates))), {})[service, rid] = candidate
                self.metrics['referenceResources'] += 1
        return result

    def arn_identity(self, kind, form, value):
        descriptor = ARN_FORMS.get((kind, form))
        if descriptor is None or not (match := re.fullmatch(descriptor[1], value)):
            return None
        parts = match.groupdict()
        if self.context is None:
            from cloudformation_inputs import load_target
            self.context = load_target(self.root, self.environment, self.target)
            self.files[self.root / 'project.json'] = (self.root / 'project.json').read_bytes().decode('utf-8')
            from botocore.session import get_session
            self.partition = get_session().get_partition_for_region(self.context['awsRegion'])
        if parts['partition'] != self.partition:
            return None
        if 'account' in parts or 'region' in parts:
            if ('account' in parts and parts['account'] != self.context.get('awsExecutionAccountId', self.context['awsAccountId']) or
                    'region' in parts and parts['region'] != self.context['awsRegion']):
                return None
        return ({attribute: parts[group] for attribute, group in descriptor[0].items()}
                if isinstance(descriptor[0], dict) else {descriptor[0]: parts['id']})

    def match(self, prop, value, context=None, *, contracts=None):
        contracts = contract(prop, context) if contracts is None else contracts
        matches = {}
        if not known(value):
            return None
        for kind, forms in contracts.items():
            index = self.index(kind)
            if not index:
                continue
            converted = [item for form in forms if (item := self.arn_identity(kind, form, value)) is not None]
            converted += [{form: match['id']} for form in forms if
                          (pattern := VALUE_IDENTITIES.get((kind, form))) and (match := re.fullmatch(pattern, value))]
            for form in forms:
                matches.update(index.get((form, value), {}))
            for components in converted:
                groups = [index.get((form, raw), {}) for form, raw in components.items()]
                for identity in set.intersection(*(set(group) for group in groups)):
                    matches[identity] = groups[0][identity]
        if len(matches) > 1:
            raise ValueError('IMPORT ambiguous physical reference: ' + prop + ': ' + value)
        return next(iter(matches.values()), None)

    def verify(self, prop, raw, physical, context=None, *, contracts=None, require_links=True):
        reference = LINK.fullmatch(raw) if isinstance(raw, str) else None
        if not require_links and reference is None:
            return
        declared = contract(prop, context) if contracts is None else contracts
        if physical is _UNOBSERVED:
            if reference:
                if not declared:
                    raise ValueError('IMPORT explicit reference has no physical identification contract: ' + prop)
                candidates = []
                for kind in declared:
                    self.index(kind)
                    candidates.extend(candidate for candidate in self.targets[kind].values()
                                      if (reference[2], reference[3]) in {
                                          (candidate['service'] + '.md', candidate['anchor']),
                                          ('', candidate['anchor']) if candidate['service'] in self.local else (None, None)})
                if len(candidates) != 1:
                    raise ValueError('IMPORT explicit link has no unique design target: ' + prop)
            return
        if reference and not declared and raw == physical:
            return  # An identical acquired string is data, not an inferred reference.
        if reference is None:
            from import_sources import typed_equal
            if not typed_equal(literal(raw) if isinstance(raw, str) else raw, physical):
                raise ValueError('IMPORT literal differs from acquired physical value: ' + prop)
        expected = self.match(prop, physical, context, contracts=contracts)
        if reference and physical == 'PENDING_DEPLOY' and not require_links:
            # Destruction clears both identifiers; validate the explicit pending target only.
            candidates = {identity: candidate for kind, forms in declared.items() for form in forms
                          for identity, candidate in self.index(kind).get((form, physical), {}).items()
                          if (reference[2], reference[3]) in {
                              (candidate['service'] + '.md', candidate['anchor']),
                              ('', candidate['anchor']) if candidate['service'] in self.local else (None, None)}}
            if len(candidates) == 1:
                expected = next(iter(candidates.values()))
        if reference:
            if not declared:
                raise ValueError('IMPORT explicit reference has no physical identification contract: ' + prop)
            if expected is None or (reference[2], reference[3]) not in {
                    (expected['service'] + '.md', expected['anchor']),
                    ('', expected['anchor']) if expected['service'] in self.local else (None, None)}:
                raise ValueError('IMPORT explicit link differs from acquired physical reference: ' + prop)
        elif expected is not None:
            raise ValueError('IMPORT matching Model requires a reference link: ' + prop)

    def verify_tree(self, prop, desired, actual, context, *, require_links=True):
        if isinstance(desired, (list, dict)):
            if actual is not _UNOBSERVED and (type(desired) is not type(actual) or (desired.keys() != actual.keys() if isinstance(desired, dict) else len(desired) != len(actual))):
                raise ValueError('IMPORT reference/observation structure differs: ' + prop)
            for key in desired if isinstance(desired, dict) else range(len(desired)):
                child_context = {prop: value[key] if isinstance(value, list) and isinstance(key, int) and key < len(value) else value
                                 for prop, value in context.items()}
                self.verify_tree(prop + '.' + key if isinstance(desired, dict) else prop, desired[key],
                                 _UNOBSERVED if actual is _UNOBSERVED else actual[key], child_context, require_links=require_links)
        else:
            self.verify(prop, desired, actual, context, require_links=require_links)

    def verify_resource(self, values, rid, *, require_links=True, identity_properties=None, properties=None, observed_only=False):
        from model_files import resource_row_index
        from model_references import catalog_outputs
        if identity_properties is None:
            identity_properties = catalog_outputs(self.definitions_root, values[f'desired.resource.{rid}.resourceType'])
        rows = resource_row_index(values).get(rid, [])
        context = {}
        for row_id, row in rows:
            prop = row['property']
            raw = row.get('value', '')
            observed = values.get('observed.row.' + row_id + '.value')
            if prop.endswith(('.Type', '.Provider')):
                try:
                    context[prop] = json.loads(literal(raw))
                except ValueError:
                    context[prop] = literal(raw)
            if properties is not None and prop not in properties:
                continue
            if prop in CONFIGURATION_PROPERTIES:
                selector, choices = CONFIGURATION_PROPERTIES[prop]
                desired = json.loads(row.get('document', literal(raw)))
                actual = json.loads(literal(observed)) if observed is not None else _UNOBSERVED if observed_only else desired
                def verify_config(desired, actual, provider):
                    if isinstance(desired, list):
                        if actual is not _UNOBSERVED and (not isinstance(actual, list) or len(desired) != len(actual)):
                            raise ValueError('IMPORT Configuration array dimensions differ')
                        for i, left in enumerate(desired):
                            verify_config(left, _UNOBSERVED if actual is _UNOBSERVED else actual[i],
                                          provider[i] if isinstance(provider, list) and i < len(provider) else provider)
                    else:
                        if not isinstance(desired, dict) or (actual is not _UNOBSERVED and
                                (not isinstance(actual, dict) or desired.keys() != actual.keys())):
                            raise ValueError('IMPORT Configuration requires matching objects')
                        for key, value in desired.items():
                            target = choices.get((provider, key)) if isinstance(provider, str) else None
                            contracts = {target[0]: (target[1],)} if target else {}
                            self.verify(prop + '.' + key, value, _UNOBSERVED if actual is _UNOBSERVED else actual[key],
                                        context, contracts=contracts, require_links=require_links)
                verify_config(desired, actual, context.get(selector))
                continue
            from import_sources import has_reference
            if (not LINK.fullmatch(raw) and literal(raw).startswith(('[', '{')) and
                    (has_reference(row.get('document', raw)) or contract(prop, context) or prop in CONTEXT_PROPERTIES)):
                desired = json.loads(row.get('document', literal(raw)))
                actual = json.loads(literal(observed)) if observed is not None else _UNOBSERVED if observed_only else desired
                self.verify_tree(prop, desired, actual, context, require_links=require_links)
                continue
            # Identity outputs/self links and parentReference keep their own guards.
            links = elements(raw)
            physical = ([_UNOBSERVED] * len(links) if observed_only and observed is None else
                        elements(observed if observed is not None else raw))
            if len(links) != len(physical):
                raise ValueError('IMPORT reference/observation element count differs: ' + prop)
            if not contract(prop, context) and not any(isinstance(value, str) and LINK.fullmatch(value) for value in links):
                continue
            for value, actual in zip(links, physical):
                link = LINK.fullmatch(value)
                if link and prop in identity_properties and not link[2] and link[3] == values.get(f'desired.resource.{rid}.anchor'):
                    continue
                self.verify(prop, value, _UNOBSERVED if actual is _UNOBSERVED else literal(actual), context, require_links=require_links)
