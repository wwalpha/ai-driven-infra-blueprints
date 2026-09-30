# 共通ファイル同期のコピー漏れ修正

## Task contract

- Task type: `governance`
- Target: framework共通 / sync-existing-files.py
- Goal: rootのAGENTS.mdとREADME.mdも共通資産として同期できるようにし、repository固有のtaskや設計をコピーしない。未commit件数と同期件数の差を説明できる同期scopeを表示する。

## Required changes

- [R1] 共通rootファイルAGENTS.mdとREADME.mdを既存の差分コピー対象へ追加する。
- [R2] task、project設定、設計、model、IaC、scenarioを同期対象外に維持する。
- [R3] 同期範囲の説明と回帰チェックを更新し、local loopと実targetのdry-runで確認する。

## Acceptance checks

- [R1] `changed:framework/scripts/sync-existing-files.py`
- [R2] `changed:framework/scripts/sync-existing-files.checks.py`
- [R3] `changed:README.md`

## Allowed paths

- `tasks/active.md`
- `README.md`
- `framework/scripts/sync-existing-files.py`
- `framework/scripts/sync-existing-files.checks.py`
- `AGENTS.md`
- `framework/rules/*.md`
- `framework/prompts/README.md`
- `framework/prompts/chatbot/service-design.md`
- `framework/prompts/codex/*.md`
- `framework/scripts/model_design.py`
- `framework/scripts/design_layout.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/sync-model.py`
- `framework/scripts/*.checks.py`
- `framework/materials/catalog.sha256`

## Out of scope

- 前taskのstage済み変更は維持し、今回必要な同期script、回帰、README、task contract以外は編集しない。
- 別repositoryはdry-runだけとし、ファイルのコピーやtask変更を行わない。
- project設定、target設計、target model、IaC、AWS操作、scenario、catalog本文は変更しない。
