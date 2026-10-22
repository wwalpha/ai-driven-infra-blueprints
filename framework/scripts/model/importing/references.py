"""Exact local reference matching; no acquisition, source edits or publication."""
import json
from pathlib import Path
import re

from model.core import LINK, entries, literal, ReferenceResolutionError
from model.identity import resource_link, address, parse_reference
from reference_contracts import (ARN_FORMS, VALUE_IDENTITIES, CONFIGURATION_PROPERTIES, CONTEXT_PROPERTIES,
                                 attributes_for, contract)


_UNOBSERVED = object()


def known(value):
    return (isinstance(value, str) and bool(value) and value not in
            {'UNSET', 'PENDING_DEPLOY', 'Pending', 'TBD', 'TODO', '未確定'} and
            not resource_link(value) and not any(text in value for text in ('${', '{{resolve:')))


def elements(raw):
    value = literal(raw)
    if value.startswith('[') and not resource_link(value):
        try:
            result = json.loads(value)
        except ValueError:
            return [raw]
        if isinstance(result, list):
            return result
    return [raw]


class Resolver:
    def __init__(self, root, environment, target, *, definitions_root=None, local=None, read_context=None):
        self.root, self.environment, self.target = Path(root), environment, target
        from utils.aws_mappings import definition_root
        self.definitions_root = definitions_root or definition_root(root)
        self.local = local or {}
        self.files, self.indexes, self.targets = {}, {}, {}
        self.metrics = {'referenceModelReads': 0, 'referenceResources': 0}
        self.context = None
        self.partition = None
        self.model_paths = set()
        self.warnings = []
        from model.sources import Scope
        self.consumer_scope = Scope(self.root, environment, target, '')
        from model.sources import FileReads
        self.reads, self.models = read_context or FileReads(), {}

    def index(self, kind):
        if kind in self.indexes:
            return self.indexes[kind]
        from model.importing.scope import reference_reader
        from model.sources import load_model, safe
        from utils.aws_mappings import owners, mappings_for
        self.reads.read(Path(self.definitions_root) / 'framework/mappings/aws/owners.json')
        service = owners(self.definitions_root).get(kind)
        result = {}
        self.indexes[kind] = result
        self.targets[kind] = {}
        if service is None:
            return result
        properties = attributes_for(kind)
        from aws_mapping import mapping_path
        self.reads.read(mapping_path(self.definitions_root, service))
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
            raise ReferenceResolutionError('IMPORT ambiguous local producer service: ' + kind)
        service = local_services[0] if local_services else service
        path = self.root / 'model' / self.environment / self.target / (service + '.properties')
        if service in self.local:
            models = [self.local[service]]
        else:
            safe(self.root, path)
            if path not in self.models:
                if self.reads.kind(path) == 'missing':
                    self.reads.read(path)
                    self.files[path] = None
                    self.models[path] = None
                else:
                    with reference_reader(path):
                        self.models[path] = load_model(path, self.reads)
                    self.model_paths.add(path)
                    self.metrics['referenceModelReads'] = len(self.model_paths)
            model = self.models[path]
            if model is None:
                return result
            self.files.update({file: None if raw is None else raw.decode('utf-8') for file, raw in model.dependencies.items()})
            self.warnings.extend(model.warnings)
            models = [model]
        for model in models:
            self.files.update(model.files)
            values = model.values
            from model.core import resource_row_index
            rows = resource_row_index(values)
            for rid, resource in entries(values, 'desired.resource.'):
                if resource.get('resourceType') != kind:
                    continue
                physical = {}
                for row_id, row in rows[rid]:
                    if row_id.rpartition('-')[0] != rid or row.get('property') not in selected_properties:
                        continue
                    raw = values.get('observed.row.' + row_id + '.value', row.get('value', ''))
                    value = literal(raw)
                    if known(value) or value == 'PENDING_DEPLOY':
                        physical.setdefault(row['property'].removeprefix(kind + '.'), set()).add(value)
                        for prop, group in aliases.items():
                            if row['property'] in group:
                                physical.setdefault(prop.removeprefix(kind + '.'), set()).add(value)
                candidate = {'service': service, 'id': rid, 'logicalId': resource['logicalId'], 'uri': address(model.scope, resource), 'anchor': resource.get('anchor'), 'scope': model.scope, 'kind': kind}
                self.targets[kind][service, rid] = candidate
                for form, candidates in physical.items():
                    if len(candidates) != 1:
                        self.warnings.append({'code': 'reference.ambiguous_identifier',
                            'message': 'IMPORT ambiguous producer physical identifier: ' + kind + '.' + form,
                            'status': 'unresolved', 'producer': '/'.join((self.environment, self.target, service, rid))})
                        continue
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
            raise ReferenceResolutionError('IMPORT ambiguous physical reference: ' + prop + ': ' + value)
        return next(iter(matches.values()), None)

    def verify(self, prop, raw, physical, context=None, *, contracts=None, require_links=True, location=None):
        position = ((location or {}).get('consumerKey'), (location or {}).get('pointer'))
        if isinstance(raw, str) and (position, raw) in getattr(self, 'literal_references', ()):
            contracts = {}  # External metadata owns tracking; still compare the acquired literal.
        try:
            return self._verify(prop, raw, physical, context, contracts=contracts, require_links=require_links)
        except ReferenceResolutionError as error:
            self.warnings.append({**error.diagnostic, 'property': prop, 'reference': raw,
                                  **({'acquiredValue': physical} if physical is not _UNOBSERVED else {}),
                                  **(location or {})})

    def candidate_matches(self, candidate, text):
        scope = getattr(self, 'consumer_scope', None)
        environment, target, service, anchor = parse_reference(text, scope)
        producer = candidate['scope']
        return (environment, target, service, anchor) == (producer.environment, producer.target, producer.service, candidate['anchor'])

    def _verify(self, prop, raw, physical, context=None, *, contracts=None, require_links=True):
        declared = contract(prop, context) if contracts is None else contracts
        reference = resource_link(raw) if declared or contracts is not None or physical is _UNOBSERVED else None
        if not require_links and reference is None:
            return
        if physical is _UNOBSERVED:
            if reference:
                candidates = []
                for kind in declared:
                    self.index(kind)
                    candidates.extend(candidate for candidate in self.targets[kind].values() if self.candidate_matches(candidate, raw))
                if len(candidates) != 1:
                    raise ReferenceResolutionError('IMPORT reference has no unique producer: ' + prop)
            return
        if reference is None:
            from model.importing.sources import typed_equal
            if not typed_equal(literal(raw) if isinstance(raw, str) else raw, physical):
                raise ValueError('IMPORT literal differs from acquired physical value: ' + prop)
        expected = self.match(prop, physical, context, contracts=contracts)
        if reference and physical == 'PENDING_DEPLOY' and not require_links:
            candidates = {identity: candidate for kind, forms in declared.items() for form in forms
                          for identity, candidate in self.index(kind).get((form, physical), {}).items()
                          if self.candidate_matches(candidate, raw)}
            if len(candidates) == 1:
                expected = next(iter(candidates.values()))
        if reference:
            if expected is None or not self.candidate_matches(expected, raw):
                raise ReferenceResolutionError('IMPORT reference differs from acquired physical reference: ' + prop)
        elif expected is not None:
            raise ReferenceResolutionError('IMPORT matching Model requires a Resource reference: ' + prop)

    def verify_tree(self, prop, desired, actual, context, *, require_links=True, location=None):
        if isinstance(desired, dict) and '$resource' in desired:
            if set(desired) - {'$resource', '$attribute'} or not resource_link(desired['$resource']):
                raise ValueError('invalid structured Resource reference')
            declared = contract(prop, context)
            if attribute := desired.get('$attribute'):
                declared = {kind: (attribute,) for kind, forms in declared.items() if attribute in forms}
            self.verify(prop, desired['$resource'], actual, context, contracts=declared,
                        require_links=require_links, location=location)
            return
        if isinstance(desired, (list, dict)):
            if actual is not _UNOBSERVED and (type(desired) is not type(actual) or (desired.keys() != actual.keys() if isinstance(desired, dict) else len(desired) != len(actual))):
                raise ValueError('IMPORT reference/observation structure differs: ' + prop)
            for key in desired if isinstance(desired, dict) else range(len(desired)):
                child_context = {prop: value[key] if isinstance(value, list) and isinstance(key, int) and key < len(value) else value
                                 for prop, value in context.items()}
                self.verify_tree(prop + '.' + key if isinstance(desired, dict) else prop, desired[key],
                                 _UNOBSERVED if actual is _UNOBSERVED else actual[key], child_context, require_links=require_links,
                                 location={**(location or {}), 'pointer': (location or {}).get('pointer', '') + '/' + str(key).replace('~', '~0').replace('/', '~1')})
        else:
            self.verify(prop, desired, actual, context, require_links=require_links, location=location)

    def verify_resource(self, values, rid, *, scope=None, require_links=True, identity_properties=None, properties=None, observed_only=False):
        from model.sources import Scope
        services = [fields['serviceId'] for _, fields in entries(values, 'desired.service.') if 'serviceId' in fields]
        self.consumer_scope = scope or Scope(self.root, self.environment, self.target, services[0] if len(services) == 1 else '')
        from model.references import declarations
        self.literal_references = {
            ((spec['consumerKey'], spec['pointer']), spec['text'])
            for spec in declarations(values).values()
            if spec['consumerKey'].startswith('desired.row.' + rid + '-')
            and 'pointer' in spec and spec['format'] in {'identifier', 'name'}
        }
        from model.core import resource_row_index
        from model.projection import catalog_outputs
        if identity_properties is None:
            identity_properties = catalog_outputs(self.definitions_root, values[f'desired.resource.{rid}.resourceType'])
        rows = resource_row_index(values).get(rid, [])
        context = {}
        for row_id, row in rows:
            prop = row['property']
            raw = row.get('value', '')
            observed = values.get('observed.row.' + row_id + '.value')
            location = {'resource': rid, 'consumerKey': 'desired.row.' + row_id + ('.document' if 'document' in row else '.value')}
            location['key'] = location['consumerKey']
            if prop.endswith(('.Type', '.Provider')):
                try:
                    context[prop] = json.loads(literal(raw))
                except ValueError:
                    context[prop] = literal(raw)
            if properties is not None and prop not in properties:
                continue
            from model.projection import scalar_reference
            selector = scalar_reference(row)
            if selector is not None:
                from reference_contracts import SCALAR_REFERENCE_PROPERTIES
                kind, attribute = SCALAR_REFERENCE_PROPERTIES[re.sub(r'\[\d+\]', '[]', prop)]
                self.verify(prop, selector['$resource'], _UNOBSERVED if observed is None else literal(observed),
                            context, contracts={kind: (attribute,)}, require_links=require_links, location=location)
                continue
            if prop in CONFIGURATION_PROPERTIES:
                selector, choices = CONFIGURATION_PROPERTIES[prop]
                desired = json.loads(row.get('document', literal(raw)))
                actual = json.loads(literal(observed)) if observed is not None else _UNOBSERVED if observed_only else desired
                def verify_config(desired, actual, provider, pointer=''):
                    if isinstance(desired, list):
                        if actual is not _UNOBSERVED and (not isinstance(actual, list) or len(desired) != len(actual)):
                            raise ValueError('IMPORT Configuration array dimensions differ')
                        for i, left in enumerate(desired):
                            verify_config(left, _UNOBSERVED if actual is _UNOBSERVED else actual[i],
                                          provider[i] if isinstance(provider, list) and i < len(provider) else provider, pointer + '/' + str(i))
                    else:
                        if not isinstance(desired, dict) or (actual is not _UNOBSERVED and
                                (not isinstance(actual, dict) or desired.keys() != actual.keys())):
                            raise ValueError('IMPORT Configuration requires matching objects')
                        for key, value in desired.items():
                            target = choices.get((provider, key)) if isinstance(provider, str) else None
                            contracts = {target[0]: (target[1],)} if target else {}
                            self.verify(prop + '.' + key, value, _UNOBSERVED if actual is _UNOBSERVED else actual[key],
                                        context, contracts=contracts, require_links=require_links,
                                        location={**location, 'pointer': pointer + '/' + key.replace('~', '~0').replace('/', '~1')})
                verify_config(desired, actual, context.get(selector))
                continue
            from model.importing.sources import has_reference
            if (not LINK.fullmatch(raw) and literal(raw).startswith(('[', '{')) and
                    (has_reference(row.get('document', raw)) or contract(prop, context) or prop in CONTEXT_PROPERTIES)):
                desired = json.loads(row.get('document', literal(raw)))
                actual = json.loads(literal(observed)) if observed is not None else _UNOBSERVED if observed_only else desired
                self.verify_tree(prop, desired, actual, context, require_links=require_links, location=location)
                continue
            # Identity outputs/self links and parentReference keep their own guards.
            links = elements(raw)
            physical = ([_UNOBSERVED] * len(links) if observed_only and observed is None else
                        elements(observed if observed is not None else raw))
            if len(links) != len(physical):
                raise ValueError('IMPORT reference/observation element count differs: ' + prop)
            if not contract(prop, context) and not any(isinstance(value, str) and resource_link(value) for value in links):
                continue
            for value, actual in zip(links, physical):
                link = resource_link(value)
                if link and prop in identity_properties and parse_reference(value, self.consumer_scope) == (self.environment, self.target, self.consumer_scope.service, values.get(f'desired.resource.{rid}.anchor')):
                    continue
                self.verify(prop, value, _UNOBSERVED if actual is _UNOBSERVED else literal(actual), context, require_links=require_links, location=location)
