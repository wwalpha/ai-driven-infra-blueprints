#!/usr/bin/env python3
"""Measure representative section reads against a Git baseline.

Install tiktoken==0.12.0 outside the shared environment, then run from the
repository root: PYTHONPATH=<install-dir> python3 framework/scripts/tests/loop_read_measure.py [base-commit]
The scenario selections are explicit; this estimates only loop-engineering.md,
not the full prompt or actual model billing. Tokenization uses o200k_base.
"""

import re
import subprocess
import sys
from pathlib import Path

import tiktoken

P = "framework/rules/loop-engineering.md"
base = sys.argv[1] if len(sys.argv) > 1 else "edf4d0018b70eb4ff65bdca6bc7f6d67f9326569"
old = subprocess.check_output(
    ["git", "show", base + ":" + P], text=True, encoding="utf-8"
)
new = Path(P).read_text(encoding="utf-8")
enc = tiktoken.get_encoding("o200k_base")


def sec(s, title):
    m = re.search(r"^" + r"(#{2,3}) " + re.escape(title) + r"\s*$", s, re.M)
    assert m, title
    n = re.search(r"^#{1," + str(len(m[1])) + r"} ", s[m.end() :], re.M)
    return (m.start(), m.end() + n.start() if n else len(s))


def calc(s, names):
    spans = sorted(sec(s, x) for x in names)
    total = sum(len(enc.encode(s[a:b])) for a, b in spans)
    merged = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    unique = sum(len(enc.encode(s[a:b])) for a, b in merged)
    selected = []
    for match in re.finditer(r"^#{2,3} (.+?)\s*$", s, re.M):
        if any(a <= match.start() < b for a, b in merged):
            selected.append(match.group(1))
    return total, unique, total - unique, selected


P1 = "Validation policy"
L = "Local loop"
E = "Local loop execution"
C = "Change Validation and Full Model Validation"
F = "Framework regression"
W = "Windows full regression input guard"
cases = {
    "Markdown-only": ([P1], [P1]),
    "Model Change": ([P1, L], [P1, L, E, C]),
    "Framework bounded": ([P1, L], [P1, L, E]),
    "Framework regression non-Windows": ([P1, L, F], [P1, L, E, F]),
    "Framework regression Windows Full": ([P1, L, F], [P1, L, E, F, W]),
    "IaC": ([P1, L], [P1, L, E]),
    "Deploy": ([P1, L], [P1, L, E]),
    "Unknown impact": ([P1], [P1]),
}
print(
    "Scenario | before sum/unique/overlap/actual sections | after sum/unique/overlap/actual sections | requested before | requested after"
)
for name, (a, b) in cases.items():
    print(name, calc(old, a), calc(new, b), "; ".join(a), "; ".join(b), sep=" | ")
print("Entire document tokens:", len(enc.encode(old)), len(enc.encode(new)))

print(
    "Scope: only explicitly modeled loop-engineering.md reads, not total prompt or billing."
)
print(
    "Full-document references in cloudformation.md and terraform.md are excluded; when applicable they independently require the entire file."
)
print(
    "Other mandatory rules, prompts, Skills and any repeated reads are excluded; sums model rereading, unique counts do not assume it."
)
