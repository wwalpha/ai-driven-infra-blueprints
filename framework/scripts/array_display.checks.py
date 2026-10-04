#!/usr/bin/env python3
"""Array display coverage, nested element ownership and lossless sources."""

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

from pathlib import Path

from array_display import indexed_rows, restored_rows
from design_catalog import DesignSchemaCatalog, design_material_files


ROOT = Path(__file__).resolve().parents[2]


def rows(fields):
    return [[str(number), prop, value, "設定値"] for number, (prop, value) in enumerate(fields, 1)]


def rejected(shown, kind):
    try:
        restored_rows(shown, kind)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid array display accepted")


def main():
    source = rows([
        ("LifecycleConfiguration.Rules[].Id", "`first`"),
        ("LifecycleConfiguration.Rules[].Transitions[].StorageClass", "`STANDARD_IA`"),
        ("LifecycleConfiguration.Rules[].Transitions[].TransitionInDays", "`30`"),
        ("LifecycleConfiguration.Rules[].Transitions[].StorageClass", "`GLACIER`"),
        ("LifecycleConfiguration.Rules[].Transitions[].TransitionInDays", "`60`"),
        ("LifecycleConfiguration.Rules[].Status", "`Enabled`"),
        ("LifecycleConfiguration.Rules[].Id", "`second`"),
        ("LifecycleConfiguration.Rules[].Transitions[].StorageClass", "`GLACIER`"),
        ("LifecycleConfiguration.Rules[].Status", "`Enabled`"),
        ("Tags[].Key", "`one`"), ("Tags[].Value", "`value-one`"),
        ("Tags[].Key", "`two`"), ("Tags[].Value", "`value-two`"),
    ])
    shown = indexed_rows(source, "S3.Bucket")
    assert restored_rows(shown, "S3.Bucket") == source
    fields = [row[1] for row in shown]
    assert fields[1:5] == ["LifecycleConfiguration.Rules[1].Transitions[1].StorageClass", "LifecycleConfiguration.Rules[1].Transitions[1].TransitionInDays", "LifecycleConfiguration.Rules[1].Transitions[2].StorageClass", "LifecycleConfiguration.Rules[1].Transitions[2].TransitionInDays"]
    assert fields[7] == "LifecycleConfiguration.Rules[2].Transitions[1].StorageClass"
    assert fields[-4:] == ["Tags[1].Key", "Tags[1].Value", "Tags[2].Key", "Tags[2].Value"]
    for token in ("[0]", "[2]", "[01]", "[]", "[x]"):
        bad = [row.copy() for row in shown]
        bad[0][1] = bad[0][1].replace("[1]", token)
        rejected(bad, "S3.Bucket")
    bad = [row.copy() for row in shown]
    bad[2][2] = "`999`"
    rejected(bad, "S3.Bucket")
    for value, count in (('`[ "sg-one", "sg-two" ]`', 2), ('`["sg-one"]`', 1), ('`[]`', 1)):
        original = rows([("SecurityGroupIds", value)])
        output = indexed_rows(original, "EC2.Instance")
        assert len(output) == count and restored_rows(output, "EC2.Instance") == original
        if value != "`[]`":
            assert output[0][1] == "SecurityGroupIds[1]"
    # An indexed parent scopes a nested array and preserves existing link markers.
    original = rows([("Stages[1].Actions.InputArtifacts[].Name", "`one`"), ("Stages[1].Actions.InputArtifacts[].Name", "`two`"), ("Stages[2].Actions.Name", "`build`")])
    output = indexed_rows(original, "CodePipeline.Pipeline")
    assert [row[1] for row in output] == ["Stages[1].Actions[1].InputArtifacts[1].Name", "Stages[1].Actions[1].InputArtifacts[2].Name", "Stages[2].Actions[1].Name"]
    assert restored_rows(output, "CodePipeline.Pipeline") == original
    original = rows([("Tasks[].Name", "`first`"), ("Tasks[].Subnets[1]", "[one](#one)"), ("Tasks[].Subnets[2]", "[two](#two)"), ("Tasks[].Name", "`second`"), ("Tasks[].Subnets[3]", "[three](#three)")])
    output = indexed_rows(original, "Example.Resource")
    assert [row[1] for row in output] == ["Tasks[1].Name", "Tasks[1].Subnets[1]", "Tasks[1].Subnets[2]", "Tasks[2].Name", "Tasks[2].Subnets[1]"]
    assert restored_rows(output, "Example.Resource") == original
    for kind, fields, expected in (
        ("GuardDuty.Detector", [("Features.ONE", "`ENABLED`"), ("Features[].AdditionalConfiguration[].Name", "`nested`"), ("Features[].AdditionalConfiguration[].Status", "`ENABLED`"), ("Features.TWO", "`DISABLED`")], ["Features[1].ONE", "Features[1].AdditionalConfiguration[1].Name", "Features[1].AdditionalConfiguration[1].Status", "Features[2].TWO"]),
        ("CloudTrail.Trail", [("EventSelectors.DataResources[1].S3", "[one](#one)"), ("EventSelectors.DataResources[2].Lambda", "[two](#two)"), ("EventSelectors.IncludeManagementEvents", "`true`"), ("EventSelectors.IncludeManagementEvents", "`false`"), ("EventSelectors.DataResources[3].S3", "[three](#three)")], ["EventSelectors[1].DataResources[1].S3", "EventSelectors[1].DataResources[2].Lambda", "EventSelectors[1].IncludeManagementEvents", "EventSelectors[2].IncludeManagementEvents", "EventSelectors[2].DataResources[1].S3"]),
    ):
        original = rows(fields)
        output = indexed_rows(original, kind)
        assert [row[1] for row in output] == expected
        assert restored_rows(output, kind) == original
    # Aliases retain the array index even when they hide a formal ancestor.
    for kind, prop, expected in (("CloudTrail.Trail", "EventSelectors.IncludeManagementEvents", "EventSelectors[1].IncludeManagementEvents"), ("S3.Bucket", "BucketEncryption.BucketKeyEnabled", "BucketEncryption[1].BucketKeyEnabled")):
        original = rows([(prop, "`true`")])
        output = indexed_rows(original, kind)
        assert output[0][1] == expected
        assert restored_rows(output, kind) == original
    covered = scalar_covered = 0
    catalog = DesignSchemaCatalog(ROOT)
    for path in design_material_files(ROOT):
        kind = path.stem.replace("_", ".", 1)
        for line in path.read_text().splitlines():
            prop = line.partition("=")[0].removeprefix(kind + ".")
            if "[]" not in prop:
                if catalog.property_schema(kind, prop).get("type") == "array":
                    original = rows([(prop, '`["one","two"]`')])
                    output = indexed_rows(original, kind)
                    assert len(output) == 2 and output[0][1].endswith("[1]") and output[1][1].endswith("[2]"), (kind, prop)
                    assert restored_rows(output, kind) == original
                    scalar_covered += 1
                continue
            original = rows([(prop, "`selected`")])
            output = indexed_rows(original, kind)
            assert "[]" not in output[0][1] and "[1]" in output[0][1], (kind, prop)
            assert restored_rows(output, kind) == original, (kind, prop)
            covered += 1
    print(f"Array display: PASS ({covered} catalog paths, {scalar_covered} schema array containers; nested, scalar, aliases, single actions, invalid displays)")


if __name__ == "__main__":
    main()
