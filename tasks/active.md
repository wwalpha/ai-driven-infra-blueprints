# Codex Task: Verify active task completion deterministically

## Task contract

- Task type: `governance`
- Goal: 新taskへの契約切替、task別completion check、focused check実行、詳細設計からのLLM mirror生成をframeworkで強制する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 最新依頼とactive taskが異なる場合の契約切替と、chat-only設計からdesign taskへのhandoffを定義する。
- [R2] active taskの各requirementをmachine-readable acceptance checkへ対応付け、task type別completion checkをlocal loopで実行する。
- [R3] repositoryのfocused check scriptsをlocal loopから必ず実行し、未実行のcheckをPASSとして扱わない。
- [R4] human-readable詳細設計を正本としてLLM design mirrorを決定的に生成し、差分があればlocal loopをFAILさせる。

## Acceptance checks

- [R1] `check:framework.active-task-transition`
- [R1] `check:framework.design-handoff`
- [R2] `check:framework.task-completion-contract`
- [R2] `check:framework.task-type-dispatch`
- [R3] `check:framework.focused-check-runner`
- [R4] `check:framework.generated-design-mirror`

## Allowed paths

- `AGENTS.md`
- `README.md`
- `prompts/chatbot/initial-service-design.md`
- `prompts/codex/add-project-target.md`
- `prompts/codex/apply-design.md`
- `prompts/codex/implement-infrastructure.md`
- `prompts/codex/initialize-repository.md`
- `prompts/codex/run-scenario-test.md`
- `rules/detailed-design.md`
- `rules/llm-design-information.md`
- `rules/loop-engineering.md`
- `scripts/blueprint-loop.py`
- `scripts/sync-design-mirror.py`
- `scripts/sync-design-mirror.checks.py`
- `scripts/validate-blueprint.py`
- `scripts/validate-blueprint.checks.py`
- `tasks/active.md`

## Out of scope

- project topology、project固有design、actual、IaC、scenario、scenario result
- AWS API、deploy、apply
- `materials/**`
- 既存staged-target workflow変更の巻き戻しまたは内容変更
