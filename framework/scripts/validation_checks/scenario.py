"""Scenario/Result metadata and state handoff without running scenarios."""
from test_support.validator import MODULE, project, write
from validation.scenario import is_rfc3339


def check_records():
    with project() as root:
        scenario = root / 'tests/scenarios/fixture/scenario.md'
        scenario.parent.mkdir(parents=True)
        result = root / 'tests/results/fixture/dev/123456789012/result.md'
        result.parent.mkdir(parents=True)
        good = ('- Scenario ID: `fixture`\n- Environment: `dev`\n- AWS account ID: `123456789012`\n'
                '- AWS region: `ap-northeast-1`\n- Status: `FAIL`\n- Executed at: `2026-01-01T12:00:00+09:00`\n')
        cases = [
            ('- Scenario ID: `fixture`\n', good, 35, []),
            ('- Scenario ID: `wrong`\n- Scenario ID: `fixture`\n', good + '- Status: `PASS`\n', 35,
             ['Scenario ID must appear exactly once: tests/scenarios/fixture/scenario.md',
              'Scenario ID does not match directory: tests/scenarios/fixture/scenario.md',
              'Status must appear exactly once: tests/results/fixture/dev/123456789012/result.md']),
            ('- Scenario ID: `fixture`\n', good.replace('2026-01-01T12:00:00+09:00', 'NOT_EXECUTED'), 35,
             ['FAIL result must have execution timestamp: tests/results/fixture/dev/123456789012/result.md']),
            ('- Scenario ID: fixture\n', good.replace('`FAIL`', '`NOT_EXECUTED`'), 34,
             ['invalid Scenario ID metadata format: tests/scenarios/fixture/scenario.md',
              'NOT_EXECUTED result must use NOT_EXECUTED timestamp: tests/results/fixture/dev/123456789012/result.md']),
        ]
        for definition, record, checks, errors in cases:
            write(scenario, definition)
            write(result, record)
            validator = MODULE.Validator(root)
            validator.accounts[('dev', '123456789012')] = {'account': '123456789012', 'region': 'ap-northeast-1'}
            validator.template_mode = False
            validator.check_scenarios()
            validator.check_results()
            validator.check_scenario_changes()
            assert (validator.errors, validator.checks) == (errors, checks), (validator.errors, validator.checks)
            assert validator.scenario_ids == {'fixture'} and validator.result_files == {'fixture': [result]}
            validator.changed_paths.add('tests/scenarios/fixture/scenario.md')
            validator.check_scenario_changes()
            assert validator.errors[-1] == 'scenario changed without updating existing result: tests/results/fixture/dev/123456789012/result.md'
            validator.changed_paths.add('tests/results/fixture/dev/123456789012/result.md')
            before = list(validator.errors)
            validator.check_scenario_changes()
            assert validator.errors == before
        # Preserve permissive datetime parsing; FAIL is a valid record status.
        assert is_rfc3339('2026-01-01 12:00:00+09:00') and is_rfc3339('NOT_EXECUTED')
        assert not is_rfc3339('2026-01-01T12:00:00') and not is_rfc3339('invalid')
        scenario.unlink()
        write(result, good)
        validator = MODULE.Validator(root)
        validator.check_results()
        assert validator.errors[:3] == ['orphan result without scenario: tests/results/fixture',
            'result target is not defined in project.json: tests/results/fixture/dev/123456789012',
            'template mode cannot contain scenario results: tests/results/fixture/dev/123456789012']
