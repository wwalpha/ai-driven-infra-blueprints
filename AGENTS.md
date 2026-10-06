# AGENTS.md

このリポジトリはrepository rootを作業ディレクトリとしてCodexで運用する。

## 常時適用ルール

- active promptのscopeだけを実行し、次工程・別taskへ自動で進まない。未確定のresource・parameter・対応付けを推測しない。
- repository変更前に今回の契約を登録する。他taskの契約・予約・未commit変更を維持する。
- 未解決issueの停止判定と明示修復・保存限定taskの例外を適用する。
- AWS mutationとdeploy/applyは、infrastructure契約が明示した許可範囲だけで行う。designのAWS APIは明示した既存resourceのread-only取得だけに限定する。
- `framework/materials/aws/`は通常taskで変更しない不変カタログ。`docs/system-overview.md`は背景referenceで、`UNSET`を一律blockerにしない。
- `model/**/*.properties`を設計値の正本とし、Markdown／JSONは生成する。generated ARNを永続化しない。
- 変更後はtask typeに対応するlocal loopを実行し、成功後だけcompletedにする。
- Humanのactive task instructionが実行modeとして明示的に`debug`を指定したtaskだけ、開始時から[Debug read reporting](framework/rules/debug-read-reporting.md)を適用する。通常taskではこのruleの追加read・tracking・report生成・保存を行わず、modeを保存・次taskへ継承しない。

## Task transition

変更時は[task契約](framework/rules/task-contract.md)に従い`tasks/<task-name>.md`を登録する。read-only調査とchat-only相談は契約不要。[issue gate](framework/rules/issue-gate.md)の適用条件は別途確認する。

## 必要な規則の読み方

以下は正本への案内で、全fileの全文読込リストではない。使用skill／workflowのRead節が指定する必須sectionと、その工程・resourceに適用される条件付きsectionだけを読む。指定sectionは見出しから次の同階層以上の見出し直前まで（子sectionを含む）。fileだけ指定された場合は全文を読む。固有規則・例外・必要な参照先を省略せず、不足・参照不明なら停止する。本文を読まないことを理由に必須checkやValidation scopeを縮小しない。

- [task-contract](framework/rules/task-contract.md): repository変更の契約・Task boundary・Acceptance contract
- [issue-gate](framework/rules/issue-gate.md): service対象taskの開始・再開・保存・AWS mutationと調査／修復／保存の例外
- [project-configuration](framework/rules/project-configuration.md): target directory、topology、profile、accountの確定・検証
- [model-information](framework/rules/model-information.md): 正本model・形式・生成
- [detailed-design](framework/rules/detailed-design.md): 対象resourceの設計・表示
- [observed-values](framework/rules/observed-values.md): current identifierの取得・保存・伝播
- [cloudformation](framework/rules/cloudformation.md)／[terraform](framework/rules/terraform.md): 選択済みengineの固有手順
- [scenario-testing](framework/rules/scenario-testing.md): scenario固有手順
- [loop-engineering](framework/rules/loop-engineering.md): 検証scope・check・regression・完了条件
