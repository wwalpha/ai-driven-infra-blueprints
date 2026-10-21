#!/usr/bin/env python3
"""Separated checks; case provenance is recorded in ../CASES.md."""
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[1])]
if not __debug__:
    raise SystemExit('Focused checks require assertions; run without -O')

from support.it_case_receipt import it_case

from support.design_catalog_fixtures import *
from macie_bucket_tables import job_bucket_tables, write_job_bucket_definitions


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

    schema = DesignSchemaCatalog(ROOT)
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
    assert len(bad_values) == len(expected_errors) == 23
    job_schema = schema.schema(MACIE_JOB)
    # Root schema covers required/unknown keys; property paths also check sentinels.
    assert not schema.api_value_errors(MACIE_JOB, job_schema, VALUES, "")
    assert not schema.job_errors(VALUES)
    for values, expected in zip(bad_values, expected_errors, strict=True):
        errors = schema.api_value_errors(MACIE_JOB, job_schema, values, "")
        for key, value in values.items():
            if key in job_schema["properties"]:
                errors.extend(schema.api_value_errors(MACIE_JOB, job_schema["properties"][key], value, key))
        errors.extend(schema.job_errors(values))
        assert all(any(message in error for error in errors) for message in expected), (values, expected, errors)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        design = root / "docs/designs/dev/123456789012/macie.md"
        artifact = design.with_suffix("") / "job-scope.json"
        artifact.parent.mkdir(parents=True)
        text = markdown(VALUES)
        design.write_text(text, encoding="utf-8")
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
        design.write_text(text, encoding="utf-8")
        artifact.write_text(json.dumps({"bucketCriteria": {}}), encoding="utf-8")
        try:
            write_job_bucket_definitions(design)
        except ValueError as error:
            assert "conflicts with bucketCriteria" in str(error)
        else:
            raise AssertionError("bucketCriteria accepted with a fixed bucket table")
    print("design-catalog: PASS (QuickSight display, current Macie schema, 23 invalid inputs, bucket link and JSON conflict guards)")


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

