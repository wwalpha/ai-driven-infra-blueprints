#!/usr/bin/env python3
"""Shared issue/notice classification on synthetic Markdown only."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from issue_markdown import markdown_matches, split_notices
from support.pytest_cli import run

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")

REFERENCE = "## 参照警告（非ブロッキング）\n\n"
PREAMBLE = "# 問題一覧\n\n## dev／team\n\n"


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
        ordinary, notices = split_notices(path.read_text(encoding="utf-8"))
        assert not markdown_matches(ordinary, r"^ {0,3}(\d+)[.)] +")
        assert notices
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
    ordinary = split_notices(path.read_text(encoding="utf-8"))[0]
    path.write_text(PREAMBLE + reference + "\n" + issue, encoding="utf-8")
    for _ in range(3):
        current = split_notices(path.read_text(encoding="utf-8"))[0]
        assert (
            [item[2] for item in markdown_matches(current, r"^ {0,3}(\d+)[.)] +")]
            == [item[2] for item in markdown_matches(ordinary, r"^ {0,3}(\d+)[.)] +")]
            == ["1"]
        )


@pytest.mark.parametrize("fence", ["````", "~~~~"])
def check_fenced_classification(fence):
    block = "<!-- issues-notices:scope:start -->\n## Warning\n- valid\n<!-- issues-notices:scope:end -->"
    ordinary, notices = split_notices("before\n" + block + "\nafter\n")
    assert ordinary == "before\n\nafter\n" and notices == [("scope", block)]
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
def check_ambiguous_notice_input(tmp_path, body):
    path = tmp_path / "issues/dev/team/issues.md"
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="ambiguous"):
        split_notices(body)
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


def check_fenced_owner_does_not_override_issue(tmp_path):
    path = tmp_path / "issues/dev/team/issues.md"
    path.parent.mkdir(parents=True)
    issue = (
        "### s3\n\n1. actual <!-- issue-id: stable -->\n"
        "````text\n```\n<!-- issue-service: sqs -->\n1. fake\n````\n"
    )
    path.write_text(PREAMBLE + issue, encoding="utf-8")
    assert [
        item[2]
        for item in markdown_matches(
            split_notices(path.read_text())[0], r"^ {0,3}(\d+)[.)] +"
        )
    ] == ["1"]


if __name__ == "__main__":
    raise SystemExit(run(__file__))
