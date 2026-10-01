# framework検証と配布同期の堅牢化

## Task contract

- Task type: `governance`
- Target: framework共通 / local loop、target検証、framework配布同期
- Goal: 指定された改善点1、4、5、8、9、10と配布先必須化を修正する。

## Required changes

- [R1] clean repositoryに前taskのactive.mdが残ってもlocal loopをidleとして検証できるようにする。
- [R4] framework配布同期の途中失敗時に、それまでの配布先変更を復元する。
- [R5] 配布先に新規追加する場合もsource symlinkを拒否する。
- [R6] framework配布同期の固定default targetを削除し、--targetを必須にする。
- [R8] local loopとfocused checks単独実行をPython最適化によるassert無効化から守る。
- [R9] repository validatorが失敗してもfocused checksを全件実行し、全失敗を報告する。
- [R10] project.jsonのAWS regionに明らかに不正な形式を拒否する。

## Acceptance checks

- [R1] `changed:framework/scripts/validate-blueprint.py`
- [R1] `changed:framework/scripts/validate-blueprint.checks.py`
- [R4] `changed:framework/scripts/sync-existing-files.py`
- [R4] `changed:framework/scripts/sync-existing-files.checks.py`
- [R5] `changed:framework/scripts/sync-existing-files.checks.py`
- [R6] `changed:framework/scripts/sync-existing-files.py`
- [R8] `changed:framework/scripts/blueprint-loop.py`
- [R8] `changed:framework/scripts/blueprint-loop.checks.py`
- [R9] `changed:framework/scripts/blueprint-loop.checks.py`
- [R10] `changed:framework/scripts/validate-blueprint.py`
- [R10] `changed:framework/scripts/validate-blueprint.checks.py`
- [R10] `changed:framework/scripts/check-deploy-context.py`
- [R10] `changed:framework/scripts/check-deploy-context.checks.py`

## Allowed paths

- `tasks/active.md`
- `framework/rules/loop-engineering.md`
- `framework/scripts/blueprint-loop.py`
- `framework/scripts/*.checks.py`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/check-deploy-context.py`
- `framework/scripts/sync-existing-files.py`

## Out of scope

- catalog/schema snapshot、design/model、IaC、consumer repository、AWS API、deploy/apply、scenario、別taskの作成・実行は行わない。
- focused checks、governance local loop、git diff --checkを実行し、結果を報告する。
