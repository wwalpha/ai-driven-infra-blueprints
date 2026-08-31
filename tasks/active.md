# Agent Skill wrappers for prompt workflows

## Task contract

- Task type: `governance`
- Goal: 既存のCodex promptを正文のまま維持し、CodexとGitHub Copilotから共通利用できるrepository-scoped Agent Skillsを追加する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] 6件のCodex prompt workflowへ対応する共通Agent Skill entrypointを`.agents/skills/`へ追加する。
- [R2] 各Skillは対応する既存promptだけを正文として参照し、prompt本文を複製しない。

## Acceptance checks

- [R1] `changed:.agents/skills/**/SKILL.md`
- [R2] `exists:.agents/skills/initialize/SKILL.md`
- [R2] `exists:.agents/skills/add-target/SKILL.md`
- [R2] `exists:.agents/skills/implement/SKILL.md`
- [R2] `exists:.agents/skills/deploy/SKILL.md`
- [R2] `exists:.agents/skills/update/SKILL.md`
- [R2] `exists:.agents/skills/scenario-test/SKILL.md`

## Allowed paths

- `.agents/skills/**`
- `tasks/active.md`

## Out of scope

- `framework/prompts/**`の変更
- prompt本文のSkillへの複製
- framework rules、scripts、materialsの変更
- initialization、migration、infrastructure、scenario-test workflowの実行
- AWS API、deploy、applyの実行
