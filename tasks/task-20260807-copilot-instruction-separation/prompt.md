# Codex Task: Separate Microsoft Copilot instructions and reusable prompts

## Task contract

- Task ID: `task-20260807-copilot-instruction-separation`
- Goal: separate Microsoft Copilot personal context instructions, repository-wide guidance, and per-use chatbot prompts
- AWS mutation: forbidden
- CloudFormation/Terraform mutation: forbidden
- Deploy/apply: forbidden

## Required changes

1. Add copy-ready Microsoft Copilot personal custom instructions that only establish the fixed SharePoint folder context and README-first behavior.
2. Update `README.md` as the repository-wide source for roles, context priority, initial design, and later SDD.
3. Add the reusable initial service-design Ask prompt used in Microsoft Copilot.
4. Add `docs/system-overview.md` as the user-maintained global premise template.
5. Do not add questionnaire Markdown, conversation logs, or session-state files.
6. Keep Microsoft Copilot-specific rules out of `README.md`; the README contains only repository-wide guidance.
7. Do not reuse the former requirement-to-basic-design SharePoint path or wording in the personal custom instructions.
8. Do not encode repository content, architecture, workflow, or Codex rules in the personal custom instructions.

## Allowed paths

- `README.md`
- `copilot/**`
- `prompts/**`
- `docs/system-overview.md`
- `scripts/validate-blueprint.py`
- `tasks/**`
- `tests/results/**`

## Verification

- Run the generic local loop.
- Run Python and shell syntax checks.
- Run `git diff --check`.
