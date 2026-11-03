#!/usr/bin/env python3
"""Markdown section boundaries used by static document validation."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pytest
from support.pytest_cli import run
from utils.markdown_format import markdown_prose, markdown_sections, rule_readings

if not __debug__:
    raise SystemExit("Focused checks require assertions; run without -O")


def check_rule_section_boundaries():
    text = "# Rules\r\n\r\n## Required\r\nkeep\r\n```md\r\n## Required\r\n```\r\n### Child\r\nchild\r\n## Unrelated\r\nomit\r\n"
    text = text.replace(
        "## Required\r\nkeep", '<a id="explicit"></a>\r\n\r\n## Required\r\nkeep'
    )
    sections = markdown_sections(text)
    assert sections["explicit"] == sections["required"]
    assert "child" in sections["required"] and "omit" not in sections["required"]
    for ambiguous in (
        "## Duplicate\nsame\n## Duplicate\nsame\n",
        '<a id="shared"></a>\n## One\nfirst\n<a id="shared"></a>\n## Two\nsecond\n',
    ):
        try:
            markdown_sections(ambiguous)
        except ValueError as error:
            assert "ambiguous rule section" in str(error)
        else:
            raise AssertionError("duplicate heading/anchor accepted")
    assert "same" in markdown_sections('<a id="same"></a>\n## Same\nrule\n')
    # Required child exceptions and stop conditions remain inside the selected range.
    nested = (
        "## Required\nrule\n### Exception\nstop on missing input\n## Optional\nomit\n"
    )
    assert (
        markdown_sections(nested)["required"]
        == "## Required\nrule\n### Exception\nstop on missing input\n"
    )


@pytest.mark.parametrize("target", ["missing.md#required", "rules.md#missing"])
def check_broken_rule_reference_rejected(tmp_path, target):
    root = tmp_path
    rules = root / "framework/rules"
    rules.mkdir(parents=True)
    (rules / "rules.md").write_text("## Required\nbody\n")
    source = root / "framework/prompts/codex/04_deploy.md"
    source.parent.mkdir(parents=True)
    with pytest.raises((OSError, ValueError)):
        rule_readings(root, source, f"[rule](../../rules/{target})")


pytestmark = pytest.mark.usefixtures("catalog_display_fixture")


# These are operation paths, not a recursive read of every linked method/exception.
ROOT = Path(__file__).resolve().parents[4]
ROUTER = "framework/prompts/codex/04_deploy.md"
RUNBOOK = "framework/prompts/codex/deploy/runbook.md"
CLOUDFORMATION = "framework/rules/cloudformation.md"
SKILL = ".agents/skills/deploy/SKILL.md"


def document_links(source, text):
    result = set()
    for _, line in markdown_prose(text):
        for raw in re.findall(r"\]\(([^)]+)\)", line):
            if "://" in raw or raw.startswith("mailto:"):
                continue
            path, _, anchor = raw.partition("#")
            target = (ROOT / source).parent / path if path else ROOT / source
            result.add((target.resolve().relative_to(ROOT).as_posix(), anchor))
    return result


def reading(node, documents):
    path, anchor = node
    text = documents[path]
    return markdown_sections(text)[anchor] if anchor else text


def require_path(nodes, documents):
    for source, target in zip(nodes, nodes[1:], strict=False):
        links = document_links(source[0], reading(source, documents))
        assert target in links or (target[0], "") in links, (
            source,
            target,
        )
    return reading(nodes[-1], documents)


# Each row requires a real entry-to-operation-to-rule path and its safety boundary.
ROUTES = [
    (
        "sdk-first",
        ["sdk-prepare", "sdk-stack", "c:explicit-operations"],
        ["current scoped DescribeStacks", "UNKNOWN"],
    ),
    (
        "sdk-continue",
        ["sdk-stack", "c:llm-controlled-short-operations"],
        ["reads current AWS first", "later Order"],
    ),
    (
        "sdk-multiple",
        ["sdk-stack", "c:llm-controlled-short-operations"],
        ["configured concurrency", "independent peers"],
    ),
    (
        "sdk-sync",
        ["sdk-stack", "observation-reads", "o:observation-publication"],
        ["observed"],
    ),
    (
        "sdk-final",
        ["verify-and-finish", "sdk-finish", "sdk-stack"],
        ["--action sync", "--sync-stack"],
    ),
    (
        "sdk-checkpoint",
        ["sdk-stack", "c:llm-controlled-short-operations"],
        ["checkpoint", "without a", "fresh observation"],
    ),
    (
        "sdk-git-retry",
        ["git-recovery", "c:managed-deploy-snapshot-and-git-publication"],
        ["deploy-publish --task-id", "no AWS call"],
    ),
    (
        "cli-first",
        ["prepare", "cli-prepare", "c:preflight-and-fixed-snapshot"],
        ["get-caller-identity", "Partition", "UNKNOWN is not ABSENT"],
    ),
    (
        "cli-s3",
        ["cli-stack", "cli-delivery", "c:order-dependencies-and-s3-delivery"],
        ["put-object", "checksum", "never an unconditional overwrite"],
    ),
    (
        "cli-create",
        ["cli-stack", "cli-changeset", "c:changeset-review-and-execution"],
        ["CREATE", "create-change-set", "client-token"],
    ),
    (
        "cli-update",
        ["cli-stack", "cli-changeset", "c:changeset-review-and-execution"],
        ["UPDATE", "pinned StackId", "full Changes"],
    ),
    (
        "cli-approval",
        [
            "confirm-unapproved-deletereplacement",
            "c:delete-and-replacement-confirmation",
        ],
        ["Replacement", "Human"],
    ),
    (
        "cli-execute",
        ["cli-stack", "cli-execute", "c:changeset-review-and-execution"],
        ["execute-change-set", "client-request-token", "describe-stack-events"],
    ),
    (
        "cli-save",
        [
            "cli-stack",
            "cli-observe-and-save",
            "c:observations-validation-and-publication",
        ],
        ["publish_observed_candidates", "ambiguous", "stale required Views"],
    ),
    (
        "cli-finish",
        [
            "verify-and-finish",
            "cli-finish",
            "c:observations-validation-and-publication",
        ],
        ["--complete", "finalize", "Active/uncertain requests"],
    ),
    (
        "failure",
        ["unfinished-aws-operation-recovery"],
        ["UNKNOWN", "REVIEW_IN_PROGRESS", "StackId"],
    ),
    (
        "lost-response",
        ["cli-recovery", "c:interruption-and-independent-recovery"],
        ["lost Execute response", "original token", "Never unconditionally reissue"],
    ),
    (
        "task-resume",
        [
            "prepare",
            "cli-prepare",
            "cli-recovery",
            "c:interruption-and-independent-recovery",
        ],
        ["fixed inputs", "On resume", "retains tracking"],
    ),
    (
        "contract-correction",
        [
            "correct-this-tasks-preparation-omissions",
            "c:managed-deploy-contract-correction",
        ],
        ["--correct-deploy-contract", "--approve-deferred-consumer"],
    ),
    (
        "repair",
        ["external-iac-repair-handoff", "c:controlled-deploy-repair"],
        ["separately authorized one-shot", "Unknown cause"],
    ),
    (
        "git-conflict",
        ["git-recovery", "c:managed-deploy-snapshot-and-git-publication"],
        ["Human conflict", "--publication-resolution", "Never automatically overwrite"],
    ),
    ("terraform", ["terraform", "t:validation-and-execution"], ["saved plan", "apply"]),
]


def route_nodes(anchors):
    files = {
        "c": CLOUDFORMATION,
        "o": "framework/rules/observed-values.md",
        "t": "framework/rules/terraform.md",
    }
    return [
        (SKILL, ""),
        (ROUTER, "read-before-changing-files"),
        *(([(RUNBOOK, "prepare")]) if anchors[0] == "sdk-prepare" else []),
        *[
            (files[anchor[0]], anchor[2:]) if anchor[1:2] == ":" else (RUNBOOK, anchor)
            for anchor in anchors
        ],
    ]


def deploy_documents():
    files = {
        SKILL,
        ROUTER,
        RUNBOOK,
        CLOUDFORMATION,
        "framework/rules/observed-values.md",
        "framework/rules/terraform.md",
    }
    return {path: (ROOT / path).read_text(encoding="utf-8") for path in files}


@pytest.mark.parametrize(
    "route,anchors,literals", ROUTES, ids=[row[0] for row in ROUTES]
)
def check_deploy_operation_routes(route, anchors, literals):
    documents = deploy_documents()
    matrix = markdown_sections(documents[RUNBOOK])["operation-routes"]
    row = next(line for line in matrix.splitlines() if line.startswith(f"| {route} |"))
    assert any((RUNBOOK, anchor) in document_links(RUNBOOK, row) for anchor in anchors)
    terminal = require_path(route_nodes(anchors), documents)
    for literal in literals:
        assert literal.lower() in terminal.lower(), (route, literal)


@pytest.mark.parametrize(
    "route,anchors,literals", ROUTES, ids=[row[0] for row in ROUTES]
)
def check_deploy_broken_route_is_rejected(route, anchors, literals):
    documents = deploy_documents()
    nodes = route_nodes(anchors)
    # Removing the required final edge must fail even if safety words still exist elsewhere.
    source, target = nodes[-2:]

    def remove_edge(match):
        raw = match[1]
        links = document_links(source[0], f"[edge]({raw})")
        if target in links or (target[0], "") in links:
            return "[removed required edge]"
        return match[0]

    documents[source[0]] = re.sub(
        r"\[[^\]]+\]\(([^)]+)\)", remove_edge, documents[source[0]]
    )
    with pytest.raises(AssertionError):
        require_path(nodes, documents)


def check_deploy_links_and_compatibility():
    documents = deploy_documents()
    for path in (SKILL, ROUTER, RUNBOOK):
        for target, anchor in document_links(path, documents[path]):
            text = (ROOT / target).read_text(encoding="utf-8")
            assert not anchor or anchor in markdown_sections(text), (
                path,
                target,
                anchor,
            )
    expected = {
        "normal-startup",
        "read-before-changing-files",
        "direct-aws-cli-method",
        "cli-entrypoints",
        "llm-controlled-stack-checkpoints",
        "correct-this-tasks-preparation-omissions",
        "confirm-unapproved-deletereplacement",
        "unfinished-aws-operation-recovery",
        "external-iac-repair-handoff",
        "terraform",
        "verify-and-finish",
        "最終保存",
        "deployorder-selection-and-synchronization-scope",
    }
    assert expected <= markdown_sections(documents[ROUTER]).keys()
    assert "status-before-advance" in markdown_sections(documents[RUNBOOK])["sdk-stack"]
    local_save = markdown_sections(documents[RUNBOOK])["cli-observe-and-save"]
    assert "original consumed-input path→bytes map" in local_save
    assert "There is no public observation-saving CLI" in local_save


def check_deploy_common_safety_reads():
    documents = deploy_documents()
    prepare = document_links(RUNBOOK, markdown_sections(documents[RUNBOOK])["prepare"])
    required = (
        {
            ("framework/rules/task-contract.md", anchor)
            for anchor in ("task-transition", "task-boundary", "acceptance-contract")
        }
        | {
            ("framework/rules/project-configuration.md", anchor)
            for anchor in ("topology", "credentials-and-account")
        }
        | {
            (CLOUDFORMATION, anchor)
            for anchor in (
                "common-rules",
                "aws-execution-context",
                "resource-mode-boundary",
                "deployment-validation-and-execution",
            )
        }
        | {
            ("framework/rules/model-information.md", anchor)
            for anchor in (
                "model-authority",
                "resource-management-mode",
                "cloudformation-deployment-policy",
                "properties-format",
            )
        }
    )
    assert required <= prepare
    observations = document_links(
        RUNBOOK, markdown_sections(documents[RUNBOOK])["observation-reads"]
    )
    assert {
        ("framework/rules/observed-values.md", anchor)
        for anchor in (
            "identifier-lifecycle",
            "collection-and-propagation",
            "observation-publication",
        )
    } <= observations
    finish = document_links(
        RUNBOOK, markdown_sections(documents[RUNBOOK])["verify-and-finish"]
    )
    assert {
        ("framework/rules/loop-engineering.md", anchor)
        for anchor in (
            "validation-policy",
            "validation-scope",
            "infrastructure-task-completion",
        )
    } <= finish
    skill = documents[SKILL]
    for boundary in (
        "never infer missing scope",
        "never blindly resend",
        "never switch",
        "current request evidence",
    ):
        assert boundary in skill


if __name__ == "__main__":
    raise SystemExit(run(__file__))
