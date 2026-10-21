#!/usr/bin/env python3
"""Explicit per-Resource values and guarded source saves; no input expansion."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')
from unittest.mock import patch
import tempfile
from support.it_case_receipt import it_case
from support.producer_identifier_reference_fixtures import *
from support.worktree_task_fixtures import fixture as worktree_fixture, git, start
from model import prepare_edit, publish_edit
from model.adapters.task import edit_write_context
from model.format import patch as patch_properties


@it_case
def check(root):
    with worktree_fixture() as primary:
        setup(primary, ['security-group'], ['EC2.SecurityGroup'])
        path = primary / 'model/preview/team/security-group.properties'
        values = {}
        for rid, value in [('1', '`fixed`'), ('2', '`10.0.0.0/24`'), ('3', '`10.0.0.0/24`')]:
            item = resource(rid, 'EC2.SecurityGroup', 'security-group-' + rid, [('GroupDescription', value)])
            item[f'desired.resource.{rid}.resourceMode'] = 'CREATE'
            values.update(item)
        write_model(path, values)
        git(primary, 'add', 'model', 'project.json', 'framework'); git(primary, 'commit', '-qm', 'explicit synthetic values')
        relative = path.relative_to(primary).as_posix()
        target, state = start(primary, files=(relative,))
        name = state['task_file']
        listed = ''.join('- `' + item + '`\n' for item in (relative, name))
        contract = ('## Task contract\n- Task type: `design`\n- Task status: `running`\n'
                    '- AWS API execution: `forbidden`\n- deploy/apply: `forbidden`\n'
                    '## Required changes\n- [R1] Explicit Resource values\n'
                    '## Acceptance checks\n- [R1] `exists:project.json`\n'
                    '## Validation scope\n- `preview/team/security-group`\n')
        for heading in ('Modified files', 'Allowed paths'):
            contract += '## ' + heading + '\n' + listed
        (target / name).write_text(contract)
        model = target / relative
        baseline = model.read_bytes()
        candidate = {**values, 'desired.row.2-001.value': '`10.1.0.0/24`'}
        text = serialize(candidate)
        with edit_write_context(target, {('preview', 'team', 'security-group')}, name) as context:
            before = load_model(model, context.snapshot)
            plan = prepare_edit(before, {model: text}, context)
            with patch('model.validation.validate_required_properties', side_effect=AssertionError('intermediate save must not run final design validation')):
                assert publish_edit(plan, context) == (model,)
            rejected(lambda: publish_edit(plan, context), 'consumed')
        current = load_model(model)
        assert current.authoritative == candidate
        assert current.authoritative['desired.row.1-001.value'] == '`fixed`'
        assert current.authoritative['desired.row.3-001.value'] == '`10.0.0.0/24`', 'equal values have no implicit shared input'
        raw = model.read_bytes()
        with edit_write_context(target, {('preview', 'team', 'security-group')}, name) as context:
            assert publish_edit(prepare_edit(load_model(model, context.snapshot), {model: text}, context), context) == ()
        assert model.read_bytes() == raw
        for changed, phrase in [
            ({**candidate, 'desired.row.2-001.unknown': 'old'}, 'unknown Model field'),
            ({**candidate, 'desired.row.2-001.value': '`{bad}`'}, 'property name')]:
            with edit_write_context(target, {('preview', 'team', 'security-group')}, name) as context:
                before = load_model(model, context.snapshot)
                rejected(lambda: prepare_edit(before, {model: serialize(changed)}, context), phrase)
            assert model.read_bytes() == raw
        rejected(lambda: serialize({**candidate, 'desired.row.2-001.value': 3}), 'strings')
        assert (primary / relative).read_bytes() == baseline


with tempfile.TemporaryDirectory(prefix='explicit-model-values-') as directory:
    check(Path(directory))
print('Explicit Model values: PASS (independent equal values; canonical fields; managed one-use save; no-op bytes; syntax/identity retention; no final-validation at intermediate save)')
