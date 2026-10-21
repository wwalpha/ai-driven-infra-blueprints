#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.design_catalog_fixtures import *
from validation_cache import input_scope, memo_table

from support.it_workspace import copy_framework

@it_case
def main():
    with tempfile.TemporaryDirectory() as directory:
        group_path = Path(directory) / "quicksight.md"
        group_path.write_text(quicksight_group_markdown(), encoding="utf-8")
        from design_layout import expanded_display_rows
        group_model = "\n".join(expanded_display_rows(group_path.read_text().splitlines()))
        assert '### QuickSight.Group: reader-group' in group_model
        assert '| QuickSight.Group.PrincipalId | `PENDING_DEPLOY` |' in group_model
        assert 'QuickSight.Group.Arn' not in group_model and 'arn:' not in group_model

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        copy_framework(root / 'framework')
        design = root / "docs/designs/dev/123456789012/macie.md"
        # Real sync reads the fixture's actual Mapping.
        import yaml
        mapping = root / 'framework/mappings/aws/macie.yaml'
        definition = yaml.safe_load(mapping.read_text(encoding='utf-8'))
        for resource in definition['resourceTypes'].values():
            for prop in resource['properties'].values():
                prop['model']['include'] = prop['display']['show'] = True
        mapping.write_text(yaml.safe_dump(definition, sort_keys=False), encoding='utf-8')
        model = root / "model/dev/123456789012/macie.properties"
        design.parent.mkdir(parents=True)
        model.parent.mkdir(parents=True)
        schema = DesignSchemaCatalog(root)
        (root / "project.json").write_text(json.dumps({"projectName": "test", "targets": [{"environment": "dev", "awsAccountId": "123456789012", "awsRegion": "ap-northeast-1", "iacEngine": "cloudformation"}]}) + "\n", encoding="utf-8")
        # Isolated fixture rule: production intentionally rejects the unregistered Job name.
        naming = root / "framework/rules/aws-resource-naming.md"
        naming.write_text(naming.read_text(encoding="utf-8") + "\n| Fixture | Job | `Macie.ClassificationJob` | `name` | `{{purpose}}` |\n", encoding="utf-8")

        write_model(model.with_name('cloudformation-stacks.properties'), {
            'desired.stack.001.name': 'fixture', 'desired.stack.001.placementName': 'fixture',
            'desired.stack.001.template': 'fixture.yaml', 'desired.stack.001.parameters': 'fixture.json',
            'desired.stack.001.deployOrder': '1', 'display.stack.001.comment': '合成Stack'})
        @input_scope
        def check(values=VALUES, text=None):
            artifact = design.with_suffix("") / "job-scope.json"
            if text is None and isinstance(values.get("s3JobDefinition"), dict) and values["s3JobDefinition"].get("bucketDefinitions"):
                artifact.parent.mkdir(exist_ok=True)
                artifact.write_text(json.dumps(values["s3JobDefinition"], indent=2) + "\n", encoding="utf-8")
            elif text is None and artifact.is_file():
                artifact.unlink()
            design.write_text(text if text is not None else markdown(values), encoding="utf-8")
            model_values = {
                'desired.service.macie.serviceId': 'macie',
                'desired.service.macie.ownedCatalogResourceTypes': 'Macie.Session,Macie.ClassificationJob',
                'desired.resource.001.resourceType': 'Macie.Session',
                'desired.resource.001.logicalId': 'Macie_Session_001',
                'desired.resource.001.anchor': 'macie-session',
                'desired.resource.001.cfn-logicalId': 'fixture-Session',
                'desired.service.identity.lastAllocated': '{"Macie.Session":1,"Macie.ClassificationJob":1}',
                'desired.resource.002.resourceType': MACIE_JOB,
                'desired.resource.002.logicalId': 'Macie_ClassificationJob_001',
                'desired.resource.002.anchor': 'macie-daily-data-scan',
                'desired.row.001-001.property': 'Macie.Session.AwsAccountId',
                'desired.row.001-001.value': '`123456789012`',
                'desired.row.001-001.comment': 'Macieを使用するAWS accountのID',
                'desired.row.001-002.property': 'Macie.Session.Status',
                'desired.row.001-002.value': '`ENABLED`',
                'desired.row.001-002.comment': 'Macieの有効状態',
            }
            order = [line.partition('=')[0].removeprefix(MACIE_JOB + '.') for line in
                     (ROOT / 'framework/materials/api/Macie_ClassificationJob.properties').read_text().splitlines()]
            for number, key in enumerate(sorted(values, key=lambda key: order.index(key) if key in order else len(order)), 1):
                value = values[key]
                raw = value if isinstance(value, str) else json.dumps(value)
                cell = '[対象条件](macie/job-scope.json)' if key == 's3JobDefinition' and isinstance(value, dict) and value.get('bucketDefinitions') else '`' + raw + '`'
                prefix = f'desired.row.002-{number:03d}.'
                model_values.update({prefix + 'property': MACIE_JOB + '.' + key,
                                     prefix + 'value': '[Job](#macie-daily-data-scan)' if key == 'jobId' else cell,
                                     prefix + 'comment': f'Jobの{key}を設定する項目'})
                if key == 'jobId':
                    model_values.update({prefix.replace('desired.', 'observed.') + field: content for field, content in
                                         [('property', MACIE_JOB + '.jobId'), ('value', cell), ('comment', f'Jobの{key}を設定する項目')]})
            model_values.update({'display.service.title': '# Macie 詳細設計',
                                 'display.resource.001.comment': '機密データ検出を有効にするsession',
                                 'display.resource.001.label': 'session',
                                 'display.resource.002.comment': '対象データを検査するjob'})
            if artifact.is_file():
                for key, value in list(model_values.items()):
                    if key.endswith('.value') and value == '[対象条件](macie/job-scope.json)':
                        model_values[key.removesuffix('.value')+'.document'] = model_projection.json.dumps(json.loads(artifact.read_text()), ensure_ascii=False, separators=(',', ':'))
            write_model(model, model_values)
            # Fixture writes end the previous immutable input snapshot.
            memo_table().clear()
            # Real generation and mismatch detection are exercised independently below.
            validator = VALIDATOR.Validator(root, model_check=lambda scope: [])
            validator.schema_catalog = schema
            validator.accounts = {("dev", "123456789012"): {"engine": "cloudformation", "account": "123456789012", "region": "ap-northeast-1"}}
            validator.check_designs()
            return validator.errors

        assert not check(), check()
        pending = read_model(model)
        assert f"desired.resource.002.resourceType={MACIE_JOB}" in pending
        assert "desired.row.002-002.value=[Job](#macie-daily-data-scan)" in pending
        assert "observed.row.002-002.value=`PENDING_DEPLOY`" in pending
        assert "desired.row.002-004.value=" in pending
        assert "observed.row.002-004" not in pending
        assert not check({**VALUES, "jobId": "0123456789abcdef0123456789abcdef"})
        assert "observed.row.002-002.value=`0123456789abcdef0123456789abcdef`" in read_model(model)
        assert "desired.row.002-002.value=[Job](#macie-daily-data-scan)" in read_model(model)
        single = {key: value for key, value in VALUES.items() if key not in {"scheduleFrequency", "initialRun"}}
        assert not check({**single, "jobType": "ONE_TIME"})
        assert not check({**VALUES, "scheduleFrequency": {"weeklySchedule": {"dayOfWeek": "MONDAY"}}})
        assert not check({**VALUES, "scheduleFrequency": {"monthlySchedule": {"dayOfMonth": 31}}})
        assert not (errors := check({**VALUES, "managedDataIdentifierSelector": "NONE", "customDataIdentifierIds": ["custom-id"]})), errors
        assert not check({**VALUES, "s3JobDefinition": {"bucketCriteria": {}}}), check({**VALUES, "s3JobDefinition": {"bucketCriteria": {}}})

        bad_values = [
            {key: value for key, value in VALUES.items() if key != "name"},
            {key: value for key, value in VALUES.items() if key != "scheduleFrequency"},
            {**VALUES, "jobType": "ONE_TIME"},
            {**VALUES, "jobType": "OTHER"},
            {**VALUES, "name": "x" * 501},
            {**VALUES, "name": "UNSET"},
            {**VALUES, "samplingPercentage": 101},
            {**VALUES, "samplingPercentage": True},
            {**VALUES, "initialRun": "yes"},
            {**VALUES, "scheduleFrequency": {}},
            {**VALUES, "scheduleFrequency": {"dailySchedule": {}, "weeklySchedule": {"dayOfWeek": "MONDAY"}}},
            {**VALUES, "scheduleFrequency": {"monthlySchedule": {"dayOfMonth": 32}}},
            {**VALUES, "s3JobDefinition": {}},
            {**VALUES, "s3JobDefinition": {"bucketDefinitions": [], "bucketCriteria": {}}},
            {**VALUES, "s3JobDefinition": {"bucketDefinitions": [{"accountId": "bad", "buckets": [1]}]}},
            {**VALUES, "s3JobDefinition": {"bucketDefinitions": [{"accountId": "123456789012"}]}},
            {**VALUES, "s3JobDefinition": {"bucketCriteria": {"typo": True}}},
            {**VALUES, "managedDataIdentifierSelector": "NONE"},
            {**VALUES, "managedDataIdentifierSelector": "INCLUDE"},
            {**VALUES, "managedDataIdentifierIds": ["id"]},
            {**VALUES, "tags": {"team": 3}},
            {**VALUES, "clientToken": "runtime-token"},
            {**VALUES, "jobArn": "arn:aws:macie2:ap-northeast-1:123456789012:classification-job/example"},
            {**VALUES, "jobId": "arn:aws:macie2:ap-northeast-1:123456789012:classification-job/example"},
        ]
        expected_errors = [
            (".name: required property missing",),
            ("SCHEDULED requires scheduleFrequency",),
            ("ONE_TIME must omit scheduleFrequency", "ONE_TIME must omit initialRun"),
            ("jobType: must be one of",),
            ("name: maxLength must be <= 500",),
            ("name: omit unused optional properties",),
            ("samplingPercentage: maximum must be <= 100",),
            ("samplingPercentage: must be integer",),
            ("initialRun: must be boolean",),
            ("scheduleFrequency: minProperties must be >= 1",),
            ("scheduleFrequency: maxProperties must be <= 1",),
            ("scheduleFrequency.monthlySchedule.dayOfMonth: maximum must be <= 31",),
            ("s3JobDefinition: must satisfy exactly one alternative",),
            ("s3JobDefinition: must satisfy exactly one alternative", "s3JobDefinition.bucketDefinitions: minItems must be >= 1"),
            ("s3JobDefinition.bucketDefinitions[0].accountId: must match", "s3JobDefinition.bucketDefinitions[0].buckets[0]: must be string"),
            ("s3JobDefinition.bucketDefinitions[0].buckets: required property missing",),
            ("s3JobDefinition.bucketCriteria.typo: unknown property",),
            ("NONE requires customDataIdentifierIds",),
            ("INCLUDE requires managedDataIdentifierIds",),
            ("RECOMMENDED must omit managedDataIdentifierIds",),
            ("tags.team: must be string",),
            (".clientToken: unknown property",),
            (".jobArn: unknown property",),
        ]
        assert len(bad_values) == 24 and len(expected_errors) == 23
        job_schema = schema.schema(MACIE_JOB)
        # Root schema covers required/unknown keys; property paths also check sentinels.
        assert not schema.api_value_errors(MACIE_JOB, job_schema, VALUES, "")
        assert not schema.job_errors(VALUES)
        for values, expected in zip(bad_values[:-1], expected_errors, strict=True):
            errors = schema.api_value_errors(MACIE_JOB, job_schema, values, "")
            for key, value in values.items():
                if key in job_schema["properties"]:
                    errors.extend(schema.api_value_errors(MACIE_JOB, job_schema["properties"][key], value, key))
            errors.extend(schema.job_errors(values))
            assert all(any(message in error for error in errors) for message in expected), (values, expected, errors)
        assert any("ARN" in error and "jobId" in error for error in check(bad_values[-1]))
        original_row = next(line for line in markdown(VALUES).splitlines() if "| name |" in line)
        duplicate = markdown(VALUES).replace(original_row, original_row + "\n" + original_row, 1)
        assert any("duplicate API" in error for error in check(text=duplicate))
        assert any("display Mapping resource type missing" in error for error in check(text=markdown(VALUES).replace(MACIE_JOB, "Macie.Unknown")))

        # Model document owns fixed bucket mappings; rendered tables must match it.
        artifact = design.with_suffix("") / "job-scope.json"
        text = markdown(VALUES)
        assert not check(text=text), check(text=text)
        assert "desired.row.002-006.artifactSha256=" in read_model(model)
        artifact.write_text(json.dumps({"bucketDefinitions": [{"accountId": "123456789012", "buckets": ["wrong-bucket"]}]}), encoding="utf-8")
        assert any("bucket mapping differs from JSON artifact" in error for error in check(text=text))
        artifact.write_text(json.dumps(VALUES["s3JobDefinition"]), encoding="utf-8")
        assert any("requires a Markdown mapping table" in error for error in check(text=text.split("#### 対象S3 bucket")[0]))
        assert any("missing or duplicate Macie bucket" in error for error in check(text=text.replace("`app-data` |", "`app-data` |\n| [daily-data-scan](#macie-daily-data-scan) | `123456789012` | `app-data` |")))
        assert any("invalid Macie Job/account mapping row" in error for error in check(text=text.replace("[daily-data-scan](#macie-daily-data-scan) | `123456789012`", "[Other](#macie-other) | `123456789012`")))
        s3 = design.with_name("s3.md")
        s3.write_text('<a id="s3-app-data"></a>\n\n### S3.Bucket: app-data\n', encoding="utf-8")
        design.write_text(text.replace("`app-data` |", "[wrong](s3.md#s3-app-data) |"), encoding="utf-8")
        try:
            job_bucket_tables(design)
        except ValueError as error:
            assert "label must match its S3 Bucket" in str(error)
        else:
            raise AssertionError("wrong S3 link label accepted")
        s3.unlink()
        noncontiguous = text.replace("`app-data` |", "`app-data` |\n| [daily-data-scan](#macie-daily-data-scan) | `000000000000` | `other-bucket` |\n| [daily-data-scan](#macie-daily-data-scan) | `123456789012` | `third-bucket` |")
        assert any("account rows must be contiguous" in error for error in check(text=noncontiguous))
        assert not check()
        from model.sources import load_model
        authoritative = "".join(key + "=" + value + "\n" for key, value in load_model(model).authoritative.items())
        doc_key = next(line.split("=", 1)[0] for line in authoritative.splitlines() if line.startswith("desired.row.") and ".document=" in line)
        definition = {**VALUES["s3JobDefinition"], "bucketDefinitions": [{"accountId": "123456789012", "buckets": ["new-bucket"]}], "scoping": {}}
        lines = [doc_key + "=" + json.dumps(definition) if line.startswith(doc_key + "=") else line for line in authoritative.splitlines()]
        write_model(model, "\n".join(lines) + "\n")
        assert sync_runtime.sync(root, True, "dev", "123456789012") == 0
        assert json.loads(artifact.read_text(encoding="utf-8"))["bucketDefinitions"][0]["buckets"] == ["new-bucket"]
        assert "scoping" in json.loads(artifact.read_text(encoding="utf-8"))
        assert "`new-bucket`" in design.read_text(encoding="utf-8")
        artifact.write_text(json.dumps({"bucketCriteria": {}}), encoding="utf-8")
        try:
            write_job_bucket_definitions(design)
        except ValueError as error:
            assert "conflicts with bucketCriteria" in str(error)
        else:
            raise AssertionError("bucketCriteria accepted with a fixed bucket table")
        artifact.write_text('{"unknown":true}', encoding="utf-8")
        assert any("API schema violation" in error for error in check(text=text))
        artifact.unlink()
        assert not (errors := check()), errors
        from model.sources import model_parts
        data_file = model_parts(model)[-1]
        data_file.write_bytes(data_file.read_bytes() + b"desired.extra=stale\n")
        try:
            sync_runtime.sync(root, False, "dev", "123456789012")
        except ValueError as error:
            assert "invalid Model key: desired.extra" in str(error), error
        else:
            raise AssertionError("stale desired.extra accepted by real sync")
        group_snapshot = root / "framework/materials/api/QuickSight_Group.json"
        group_original = group_snapshot.read_text(encoding="utf-8")
        group_schema = json.loads(group_original)
        group_schema["identityProperties"] = ["Namespace", "GroupName"]
        group_snapshot.write_text(json.dumps(group_schema, indent=2) + "\n", encoding="utf-8")
        api_files = sorted((root / "framework/materials/api").glob("*"))
        (root / "framework/materials/api-catalog.sha256").write_text(manifest_text(root, api_files), encoding="utf-8")
        assert any("identity must be AwsAccountId + Namespace + GroupName" in error for error in api_snapshot_errors(root))
        group_snapshot.write_text(group_original, encoding="utf-8")
        (root / "framework/materials/api-catalog.sha256").write_text(manifest_text(root, api_files), encoding="utf-8")
        snapshot = root / "framework/materials/api/Macie_ClassificationJob.json"
        snapshot.write_text(snapshot.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        assert api_snapshot_errors(root)
    print("design-catalog: PASS (Macie and QuickSight API designs, identities, outputs, real sync, 24 invalid inputs, snapshot integrity)")


if __name__ == "__main__":
    from support.model_sources import catalog_display
    with catalog_display():
        if directory := os.environ.get("BLUEPRINT_PROFILE_DIR"):
            import cProfile
            import pstats
            profile = cProfile.Profile()
            try:
                profile.runcall(main)
            finally:
                profile.dump_stats(str(Path(directory) / (Path(__file__).stem + ".prof")))
                pstats.Stats(profile).strip_dirs().sort_stats("cumulative").print_stats(25)
        else:
            main()

