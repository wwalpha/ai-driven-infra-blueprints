#!/usr/bin/env python3
"""Shared issue/notice classification on synthetic Markdown only."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from issue_gate import issue_errors, unresolved_services
from issue_markdown import markdown_matches, split_notices
from issues.materials import existing_materials
from issues.publication import save
from issues.reports import attach_notices, normal_merge, notice_report
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

REFERENCE = "## 参照警告（非ブロッキング）\n\n"
PREAMBLE = "# 問題一覧\n\n## dev／team\n\n"
SCOPE = {("dev", "team", "s3")}


@pytest.mark.parametrize(
    "body",
    [
        "1. Reference warning, not an Issue\n",
        "- S3 unresolved refs\n\n### s3\n\n1. Reference A details\n",
    ],
)
@pytest.mark.parametrize("preamble", ["", PREAMBLE, PREAMBLE + "未解決issueなし\n\n"])
def check_reference_lists(tmp_path, body, preamble):
    path = tmp_path / "issues/dev/team/issues.md"
    path.parent.mkdir(parents=True)
    original = preamble + REFERENCE + body
    path.write_text(original, encoding="utf-8")
    for _ in range(2):
        assert (
            unresolved_services(tmp_path, path) == issue_errors(tmp_path, SCOPE) == []
        )
        assert existing_materials(tmp_path, "dev", "team", ["s3"])[0] == []
        with patch("issues.publication.save_authority", return_value=[path]):
            save(tmp_path, "dev", "team", ["s3"])
        assert path.read_text(encoding="utf-8").endswith(REFERENCE + body)


@pytest.mark.parametrize(
    "issue",
    [
        "### s3\n\n<!-- issue-service: s3 -->\n\n1. Actual s3 problem <!-- issue-id: s3-fixed -->\n",
        "### s3\n\n1. Actual s3 problem <!-- issue-id: s3-fixed -->\n",
        "<!-- issue-service: s3 -->\n\n1. Actual s3 problem <!-- issue-id: s3-fixed -->\n",
        "## dev／team\n\n### s3\n\n1. Actual s3 problem\n",
        "### s3\n\n1. Actual s3 problem <!-- issue-service: s3 -->\n",
    ],
)
def check_explicit_issue_boundary(tmp_path, issue):
    path = tmp_path / "issues/dev/team/issues.md"
    path.parent.mkdir(parents=True)
    reference = REFERENCE + "- Reference Warning A\n\n### s3\n\n1. Reference details\n"
    path.write_text(PREAMBLE + issue, encoding="utf-8")
    materials = existing_materials(tmp_path, "dev", "team", ["s3"])[0]
    owners = unresolved_services(tmp_path, path)
    path.write_text(PREAMBLE + reference + "\n" + issue, encoding="utf-8")
    for _ in range(3):
        assert existing_materials(tmp_path, "dev", "team", ["s3"])[0] == materials
        assert unresolved_services(tmp_path, path) == owners == [("1", {"s3"})]
        assert len(issue_errors(tmp_path, SCOPE)) == 1
        merged = normal_merge(tmp_path, path, "dev", "team", ["s3"], [], [], [])
        merged = notice_report(
            merged,
            "dev",
            "team",
            ["s3"],
            {"information": ["info"], "warnings": ["warning"]},
        )
        assert merged.endswith(reference) and merged.index(
            "Actual s3 problem"
        ) < merged.index("## 情報") < merged.index(REFERENCE)
        path.write_text(merged, encoding="utf-8")


@pytest.mark.parametrize("fence", ["````", "~~~~"])
def check_fenced_classification(fence):
    block = "<!-- issues-notices:scope:start -->\n## Warning\n- valid\n<!-- issues-notices:scope:end -->"
    ordinary, notices = split_notices("before\n" + block + "\nafter\n")
    assert ordinary == "before\n\nafter\n" and notices == [("scope", block)]
    assert split_notices(attach_notices(ordinary, notices))[1] == notices
    example = (
        f"{fence}text\n{fence[:3]}\n" + block + "\n### s3\n<!-- issue-service: s3 -->\n"
        "1. example <!-- issue-id: fake -->\n## dev／team\n" + fence + "\n"
    )
    assert split_notices(example) == (example, [])
    assert split_notices(REFERENCE + example) == (
        "",
        [(None, (REFERENCE + example).rstrip())],
    )
    assert markdown_matches(example, r"^(.*)$") == []


@pytest.mark.parametrize(
    "body",
    [
        "<!-- issues-notices:one:start -->\n- incomplete\n",
        "<!-- issues-notices:one:start -->\n<!-- issues-notices:two:end -->\n",
        "<!-- issues-notices:one:end -->\n",
        "<!-- issues-notices:one:start -->\n<!-- issues-notices:two:start -->\n",
        "<!-- issues-notices:one:start -->\n### s3\n<!-- issue-service: s3 -->\n1. actual\n<!-- issues-notices:one:end -->\n",
        "<!-- issues-notices:one:start -->\n### s3\n1. actual <!-- issue-id: actual -->\n<!-- issues-notices:one:end -->\n",
        REFERENCE + "1. actual <!-- issue-id: actual -->\n",
        REFERENCE + "### s3\n1. warning\n2. actual <!-- issue-id: actual -->\n",
    ],
)
def check_ambiguous_input_stops_save(tmp_path, body):
    path = tmp_path / "issues/dev/team/issues.md"
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    for read in [
        lambda: split_notices(body),
        lambda: issue_errors(tmp_path, SCOPE),
        lambda: existing_materials(tmp_path, "dev", "team", ["s3"]),
    ]:
        with pytest.raises(ValueError, match="ambiguous"):
            read()
    with (
        patch("issues.publication.save_authority", return_value=[path]),
        patch("issues.publication.atomic_files") as publish,
    ):
        with pytest.raises(ValueError, match="ambiguous"):
            save(tmp_path, "dev", "team", ["s3"])
        publish.assert_not_called()
    assert path.read_text(encoding="utf-8") == body


@pytest.mark.parametrize("heading", ["##", "###"])
def check_warning_sections(heading):
    first = heading + " 警告（非ブロッキング）\n\n1. warning\n"
    second = (
        heading + " 参照警告（非ブロッキング）\n\n" + heading + "# s3\n1. reference\n"
    )
    ordinary, notices = split_notices(first + second)
    assert ordinary == "" and notices == [
        (None, first.rstrip()),
        (None, second.rstrip()),
    ]
    assert split_notices(attach_notices(ordinary, notices)) == ("\n\n", notices)


def check_fenced_owner_does_not_override_issue(tmp_path):
    path = tmp_path / "issues/dev/team/issues.md"
    path.parent.mkdir(parents=True)
    issue = (
        "### s3\n\n1. actual <!-- issue-id: stable -->\n"
        "````text\n```\n<!-- issue-service: sqs -->\n1. fake\n````\n"
    )
    path.write_text(PREAMBLE + issue, encoding="utf-8")
    before = existing_materials(tmp_path, "dev", "team", ["s3"])[0]
    assert (
        len(before) == 1
        and before[0]["service"] == "s3"
        and "<!-- issue-id: stable -->" in before[0]["message"]
    )
    merged = normal_merge(tmp_path, path, "dev", "team", ["s3"], [], [], [])
    path.write_text(merged, encoding="utf-8")
    assert existing_materials(tmp_path, "dev", "team", ["s3"])[0] == before
    assert unresolved_services(tmp_path, path) == [("1", {"s3"})]


if __name__ == "__main__":
    raise SystemExit(run(__file__))
