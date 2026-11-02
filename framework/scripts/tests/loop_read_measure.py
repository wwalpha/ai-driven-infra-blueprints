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
old = subprocess.check_output(["git", "show", base + ":" + P], text=True)
new = Path(P).read_text()
enc = tiktoken.get_encoding("o200k_base")


def sec(s, title):
    m = re.search(r"^" + r"(#{2,3}) " + re.escape(title) + r"\s*$", s, re.M)
    assert m, title
    n = re.search(r"^#{1," + str(len(m[1])) + r"} ", s[m.end() :], re.M)
    return (m.start(), m.end() + n.start() if n else len(s))


def calc(s, names):
    spans = [sec(s, x) for x in names]
    pieces = [s[a:b] for a, b in spans]
    unique = []
    for i in range(len(s)):
        if any(a <= i < b for a, b in spans):
            unique.append(s[i])
    total = sum(len(enc.encode(p)) for p in pieces)
    unq = len(enc.encode("".join(unique)))
    return total, total - unq


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
    "Scenario | before total/duplicate | after total/duplicate | before sections | after sections"
)
for name, (a, b) in cases.items():
    print(name, calc(old, a), calc(new, b), "; ".join(a), "; ".join(b), sep=" | ")
print("Entire document tokens:", len(enc.encode(old)), len(enc.encode(new)))
