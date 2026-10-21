"""Strict full-authority semantic comparison; no reference_equal relaxation."""
import hashlib
import json
from pathlib import Path
from model.format import strict_json, json_field
from model.sources import Scope, load_model, list_models, FileReads
from model.migration.convert import checked_export


def semantic(values):
    result = {}
    for key, raw in values.items():
        body, ticked = json_field(key, raw)
        if body is None:
            result[key] = {'text': raw}
        else:
            result[key] = {'backtickJSON' if ticked else 'document': strict_json(body[:-1] if ticked else body)}
    return json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def _order(values, prefix):
    return list(dict.fromkeys(key[len(prefix):].partition('.')[0] for key in values if key.startswith(prefix)))


def compare_export(value, candidate_root):
    value = checked_export(value)
    root = Path(candidate_root).absolute()
    reads = FileReads()
    if hashlib.sha256(reads.read(root / 'project.json')).hexdigest() != value['inputs']['project.json']:
        raise ValueError('migration must preserve project.json bytes')
    expected = {tuple(model['scope']): model for model in value['models']}
    if len(expected) != len(value['models']):
        raise ValueError('duplicate exported Model scope')
    discovered = {(scope.environment, scope.target, scope.service) for scope in list_models(root, reads)}
    if expected.keys() != discovered:
        raise ValueError('migration Model scope set differs: missing=' + str(expected.keys() - discovered) + '; extra=' + str(discovered - expected.keys()))
    for identity, model in expected.items():
        snapshot = load_model(Scope(root, *identity), reads)
        if semantic(snapshot.authoritative) != semantic(model['authoritative']):
            keys = snapshot.authoritative.keys() ^ model['authoritative'].keys()
            changed = [key for key in snapshot.authoritative.keys() & model['authoritative'].keys()
                       if semantic({key: snapshot.authoritative[key]}) != semantic({key: model['authoritative'][key]})]
            raise ValueError('migration authority differs at ' + '/'.join(identity) + ': ' + ', '.join(sorted([*keys, *changed])))
        for prefix, field in (('desired.resource.', 'resourceOrder'), ('desired.row.', 'rowOrder')):
            if _order(snapshot.authoritative, prefix) != model[field]:
                raise ValueError('migration display order differs: ' + '/'.join(identity) + '/' + field)
    reads.verify()
    return {'status': 'equivalent', 'modelFormat': 2, 'models': len(expected), 'designValidation': 'not-run'}
