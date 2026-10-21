"""Preservation proof for the explicitly declared one-time identity rewrite."""
from pathlib import Path
from types import MappingProxyType
import re
from model.core import entries
from model.format import parse, validate_blocks
from model.identity import COUNTERS, resource_index, URI, counters, sequence, reference_tokens
from model.references import _json, LINKS, link_scope
from model.sources import FileReads, ModelSnapshot, model_parts, target_for, scope_for


def baseline_snapshot(scope, reads=None):
    """Read historical authority only for rewrite comparison; never ordinary resolution."""
    reads = reads or FileReads()
    _, project = target_for(scope, reads)
    parts = tuple(model_parts(scope.path, read_context=reads))
    files = {path: reads.read(path).decode('utf-8') for path in dict.fromkeys((scope.path, *parts))}
    documents = {path: parse(files[path]) for path in parts}
    values, locations = validate_blocks(documents)
    return ModelSnapshot(scope, MappingProxyType(values), MappingProxyType(values),
                         MappingProxyType(documents), MappingProxyType(locations), MappingProxyType(files),
                         MappingProxyType({scope.root / 'project.json': project,
                             **{path: text.encode('utf-8') for path, text in files.items()}}), parts)


class BaselineIndex:
    def __init__(self, root, *, legacy):
        self.root, self.legacy, self.reads = root, legacy, FileReads()
        self.models, self.resources, self.anchors, self.logical = {}, {}, {}, {}
        self.cfn = {}

    def model(self, scope):
        if scope not in self.models:
            path = self.root / 'model' / (scope + '.properties')
            snapshot = baseline_snapshot(scope_for(path), self.reads)
            resources = dict(entries(snapshot.authoritative, 'desired.resource.'))
            self.models[scope], self.resources[scope] = snapshot, resources
            self.anchors[scope], self.logical[scope] = {}, {}
            for rid, resource in resources.items():
                for field, index in [('anchor', self.anchors[scope]), ('logicalId', self.logical[scope])]:
                    if resource.get(field):
                        index.setdefault(resource[field], []).append(rid)
            if not self.legacy:
                from model.core import validate_authority
                from model.references import declarations
                validate_authority(snapshot.authoritative)
                declarations(snapshot.authoritative)
        return self.models[scope]

    def cfn_mapping(self, scope, rid, after):
        """Prove the historical fallback against existing templates, only in this baseline."""
        from design_catalog import DesignSchemaCatalog
        from cloudformation_inputs import load_template_inputs
        from model.sources import model_paths, safe
        target_scope = scope.rsplit('/', 1)[0]
        if target_scope not in self.cfn:
            environment, directory = target_scope.split('/')
            target, _ = target_for(scope_for(self.root / 'model' / (scope + '.properties')), self.reads)
            if target['iacEngine'] != 'cloudformation':
                raise ValueError('CFn identity completion requires CloudFormation')
            catalog = DesignSchemaCatalog(self.root)
            candidates, direct = {}, set()
            for path in model_paths(self.root, environment, directory):
                service_scope = path.relative_to(self.root / 'model').with_suffix('').as_posix()
                self.model(service_scope)
                for identity, resource in self.resources[service_scope].items():
                    if resource.get('cfn-logicalId'):
                        direct.add(resource['cfn-logicalId'])
                    if resource.get('resourceMode', 'CREATE') != 'CREATE' or not resource.get('logicalId') or resource.get('cfn-logicalId'):
                        continue
                    kind = catalog.cloudformation_type(resource['resourceType'])
                    if not kind:
                        continue
                    logical = resource['logicalId']
                    converted = ''.join(part[:1].upper() + part[1:] for part in re.split(r'[^A-Za-z0-9]+', logical) if part)
                    for key in {logical, converted}:
                        candidates.setdefault((kind, key), set()).add((service_scope, identity))
            stack_source = self.model(target_scope + '/cloudformation-stacks')
            proven = {}
            for _, stack in entries(stack_source.authoritative, 'desired.stack.'):
                template = self.root / 'infra/cloudformation/templates' / target.get('alias', '') / stack['template']
                parameters = self.root / 'infra/cloudformation/parameters' / environment / directory / stack['parameters']
                for path in (template, parameters):
                    safe(self.root, path)
                    if path.read_bytes() != (after / path.relative_to(self.root)).read_bytes():
                        raise ValueError('identity rewrite cannot change CFn inputs')
                document, _ = load_template_inputs(template, parameters)
                for key, definition in document.get('Resources', {}).items():
                    matches = candidates.get((definition.get('Type'), key), set())
                    if len(matches) == 1 and stack['name'] + '-' + key not in direct:
                        proven.setdefault(next(iter(matches)), []).append(stack['name'] + '-' + key)
            self.cfn[target_scope] = proven
        matches = self.cfn[target_scope].get((scope, rid), [])
        if len(matches) != 1:
            raise ValueError('identity rewrite cannot prove unique historical CFn mapping: ' + scope + '/' + rid)
        return matches[0]

    def resolve(self, scope, token):
        self.model(scope)
        if URI.fullmatch(token):
            from model.identity import parse_reference
            env, target, service, logical = parse_reference(token)
            producer = '/'.join((env, target, service))
            self.model(producer)
            matches = self.logical[producer].get(logical, [])
        elif self.legacy and (link := LINKS.fullmatch(token)):
            producer = link_scope(*scope.split('/'), link[2])
            self.model(producer)
            matches = self.anchors[producer].get(link[3], [])
        else:
            raise ValueError('unproven Resource reference: ' + token)
        if len(matches) != 1:
            raise ValueError('rewrite cannot prove reference target: ' + token)
        return producer + '/' + matches[0]

    def normalize(self, scope, key, raw):
        if key.startswith('observed.'):
            return ('observed', raw)
        value, structured = _json(key, raw)
        semantic = (key.startswith('desired.row.') and key.endswith(('.value', '.document')) or
                    key.startswith('desired.resource.') and key.endswith('.parentReference') or
                    key == 'desired.deployment.templateBucket' or
                    key.startswith('desired.artifact.') and key.endswith('.bucket') or
                    key.startswith('desired.note.') and key.endswith('.text'))
        def walk(item):
            if isinstance(item, list):
                return ('list', tuple(walk(child) for child in item))
            if isinstance(item, dict):
                return ('dict', {name: walk(child) for name, child in item.items()})
            if not isinstance(item, str) or not semantic:
                return (type(item).__name__, item)
            pattern = re.compile(URI.pattern + ('|' + LINKS.pattern if self.legacy else ''))
            spans, cursor = [], 0
            for match in pattern.finditer(item):
                token = match[0]
                if token.startswith('['):
                    link = LINKS.fullmatch(token)
                    if re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', link[2]):
                        continue
                    # Only old Markdown Resource links are interpreted, never JSON/ordinary URLs.
                    if link[2] and not link[2].endswith('.md'):
                        continue
                spans.extend((item[cursor:match.start()], ('resource', self.resolve(scope, token))))
                cursor = match.end()
            return ('str', tuple((*spans, item[cursor:])) if spans else item)
        return walk(value)


def verify(before, after, scopes):
    """Pair by immutable scope + entry number, including every reference position."""
    from model.operations import _same, preserve_layout
    old, new = BaselineIndex(before, legacy=True), BaselineIndex(after, legacy=False)
    if (before / 'project.json').read_bytes() != (after / 'project.json').read_bytes():
        raise ValueError('identity rewrite cannot change project.json')
    for scope in sorted(scopes):
        left, right = old.model(scope), new.model(scope)
        if {p.relative_to(before) for p in left.files} != {p.relative_to(after) for p in right.files}:
            raise ValueError('identity rewrite cannot change parts/file sets: ' + scope)
        if [p.relative_to(before) for p in left.parts] != [p.relative_to(after) for p in right.parts]:
            raise ValueError('identity rewrite cannot reorder parts: ' + scope)
        preserve_layout(left, right)
        a, b = dict(left.authoritative), dict(right.authoritative)
        if old.resources[scope].keys() != new.resources[scope].keys():
            raise ValueError('identity rewrite changed Resource composition: ' + scope)
        for rid, resource in old.resources[scope].items():
            current = new.resources[scope][rid]
            for field in resource.keys() | current.keys():
                if field == 'cfn-logicalId' and field not in resource and field in current:
                    if current[field] != old.cfn_mapping(scope, rid, after):
                        raise ValueError('identity rewrite CFn completion differs from proven baseline')
                    b.pop(f'desired.resource.{rid}.cfn-logicalId')
                    continue
                if field in {'logicalId', 'anchor', 'parentReference'}:
                    continue
                if resource.get(field) != current.get(field) or (field in resource) != (field in current):
                    raise ValueError('identity rewrite changed fixed Resource field: ' + scope + '/' + rid + '/' + field)
            a.pop(f'desired.resource.{rid}.logicalId', None)
            b.pop(f'desired.resource.{rid}.logicalId', None)
            a.pop(f'desired.resource.{rid}.anchor', None)
            if f'desired.resource.{rid}.anchor' in b:
                raise ValueError('identity rewrite must remove authoritative anchors')
        previous_state, current_state = counters(left.authoritative), counters(right.authoritative)
        if previous_state:
            if previous_state != current_state:
                raise ValueError('identity rewrite cannot change established allocation state')
            for rid, resource in old.resources[scope].items():
                if resource.get('logicalId') != new.resources[scope][rid]['logicalId']:
                    raise ValueError('identity rewrite cannot reallocate established identities')
        else:
            expected = {}
            for resource in new.resources[scope].values():
                kind = resource['resourceType']
                expected[kind] = max(expected.get(kind, 0), sequence(kind, resource['logicalId']))
            if current_state != expected:
                raise ValueError('identity rewrite must initialize exact allocation high watermarks')
        a.pop(COUNTERS, None)
        b.pop(COUNTERS, None)
        for refid, declaration in entries(a, 'desired.reference.'):
            if declaration['producerKind'] != 'resource':
                continue
            producer = declaration['producerScope']
            old.model(producer)
            fixed = declaration.get('producerId')
            if fixed is None:
                matches = old.logical[producer].get(declaration.get('producerLogicalId'), [])
                fixed = matches[0] if len(matches) == 1 else None
            new.model(producer)
            logical_key = f'desired.reference.{refid}.producerLogicalId'
            matches = new.logical[producer].get(b.get(logical_key), [])
            if fixed is None or fixed not in old.resources[producer] or matches != [fixed]:
                raise ValueError('identity rewrite retargeted reference declaration: ' + refid)
            a.pop(f'desired.reference.{refid}.producerId', None)
            a.pop(logical_key, None)
            b.pop(logical_key, None)
            text_key = f'desired.reference.{refid}.text'
            if declaration['format'] == 'link':
                if old.resolve(scope, a[text_key]) != new.resolve(scope, b[text_key]):
                    raise ValueError('identity rewrite changed declared link target')
                a.pop(text_key)
                b.pop(text_key)
        if a.keys() != b.keys():
            raise ValueError('identity rewrite changed authoritative field set: ' + scope)
        for key in a:
            if not _same(old.normalize(scope, key, a[key]), new.normalize(scope, key, b[key])):
                raise ValueError('identity rewrite changed value or reference target: ' + scope + '/' + key)
            if left.locations[key][0].relative_to(before) != right.locations[key][0].relative_to(after):
                raise ValueError('identity rewrite moved retained field: ' + key)
    # Unselected consumers must not retain references to identities removed by this batch.
    from model.sources import list_models
    from model.references import string_leaves
    for selected in list_models(before, old.reads):
        scope = '/'.join((selected.environment, selected.target, selected.service))
        if scope in scopes:
            continue
        snapshot = old.model(scope)
        for _, declaration in entries(snapshot.authoritative, 'desired.reference.'):
            producer = declaration.get('producerScope')
            if declaration.get('producerKind') == 'resource' and producer in scopes:
                old.model(producer)
                new.model(producer)
                logical = declaration.get('producerLogicalId')
                if logical is None or old.logical[producer].get(logical) != new.logical[producer].get(logical):
                    raise ValueError('identity rewrite requires incoming consumer in Task scope: ' + scope)
        for key, raw in snapshot.authoritative.items():
            if not (key.startswith('desired.row.') and key.endswith(('.value', '.document')) or
                    key.endswith('.parentReference') or key == 'desired.deployment.templateBucket' or
                    key.startswith('desired.artifact.') and key.endswith('.bucket') or
                    key.startswith('desired.note.') and key.endswith('.text')):
                continue
            value, _ = _json(key, raw)
            for _, text in string_leaves(value):
                for link in LINKS.finditer(text):
                    if link[2] and not link[2].endswith('.md') or re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', link[2]):
                        continue
                    producer = link_scope(*scope.split('/'), link[2])
                    if producer in scopes and old.resolve(scope, link[0]):
                        raise ValueError('identity rewrite requires incoming consumer in Task scope: ' + scope + '/' + key)
                for uri in reference_tokens(text):
                    producer = '/'.join(uri[0].removeprefix('resource://').split('/')[:3])
                    if producer in scopes and old.resolve(scope, uri[0]) != new.resolve(scope, uri[0]):
                        raise ValueError('identity rewrite retargeted an undeclared consumer: ' + scope)
    return ()
