# ResourceNameの明示display label検証

## Task contract

- Task type: `governance`
- Target: framework共通
- Goal: 名称propertyがないresourceで、human-confirmedな明示display labelが内部logical IDと同じ文字列でもResourceNameとして許可し、label欠落による内部ID流用を拒否する。

## Required changes

- [R1] 詳細設計・modelルールへ、対応するresource type・logical ID・display labelの照合条件を明記する。
- [R2] Validator.check_resource_namesで正本modelの明示labelを照合し、hidden logical ID、anchor、desired/observedの分離を維持する。
- [R3] 既存model_design.checks.pyへ同一文字列labelの成功とlabel欠落・identity不一致の失敗の回帰検証を追加する。

## Acceptance checks

- [R1] `changed:framework/rules/detailed-design.md`
- [R1] `changed:framework/rules/model-information.md`
- [R2] `changed:framework/scripts/validate-blueprint.py`
- [R2] `check:framework.generated-service-model`
- [R3] `changed:framework/scripts/model_design.checks.py`
- [R3] `check:framework.schema-backed-design-validation`

## Allowed paths

- `tasks/active.md`
- `framework/rules/detailed-design.md`
- `framework/rules/model-information.md`
- `framework/scripts/validate-blueprint.py`
- `framework/scripts/model_design.checks.py`
- `framework/prompts/chatbot/service-design.md`
- `framework/rules/detailed-design-samples.md`
- `framework/rules/loop-engineering.md`
- `framework/scripts/model_design.py`
- `framework/scripts/policy_tables.checks.py`

## Out of scope

- 名称のハードコード、Name tag・catalog propertyの追加、実targetのdesign/model/IaC、AWS API・mutation、deploy/apply、project.json、consumer repository、scenario、別taskは変更・実行しない。
- 今回の編集はRequired changesの4 framework fileと本contractに限定する。その他のAllowed pathsは開始時点の未commit変更を保持してlocal loopで検証するためだけに列挙し、追加編集しない。
- focused check、governance local loop、git diff --checkを実行し、既存failureと今回の結果を分けて報告する。
