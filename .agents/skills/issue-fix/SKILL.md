---
name: issue-fix
description: AWS Blueprintの明示指定された1 environment内のtarget・serviceについてissues skillでローカル調査し、その結果の表示関連の問題だけを修復するときに使用する。環境指定は必須とし、複数環境の実行は禁止する。
---

# 表示関連issueの修復

共通正本は`ai-driven-infra-blueprints`リポジトリで管理する。本skillの呼び出しは、依頼範囲の表示関連issueの調査と修復を許可する。設計値の変更、IaC修正、AWS API、deploy/apply、scenarioは含めない。

## 環境指定

- humanによるenvironment名の明示指定を必須とし、1回の実行は1 environmentだけに限定する。未指定なら環境名を確認し、回答までissuesの調査・契約登録・修復を開始しない。既存契約、path、唯一のenvironmentから推測・補完しない。
- 複数environmentや全環境の指定は禁止する。指定された場合は1 environmentの選択を求め、回答まで開始しない。先頭の環境だけを選ぶ、環境ごとのtaskへ自動分割する、順次実行することも行わない。
- 指定されたenvironmentが`project.json`に存在することを確認する。issuesの先行調査、修復、再生成、再検証、issues.md更新まで同じenvironmentを維持し、契約のValidation scope・Issue remediation・model／生成物／issuesのpathへ別environmentを混ぜない。

## issuesによる先行調査

1. 最初にissues skillの[対象の確認](../issues/SKILL.md#対象の確認)、[issue登録の判定](../issues/SKILL.md#issue登録の判定)、[命名規則の確認](../issues/SKILL.md#命名規則の確認)、[出力](../issues/SKILL.md#出力)を読み、同じenvironment・target・serviceについて呼び出す。この段階は読み取り専用のローカル調査とし、結果をチャットまたはrepository外の一時fileへ出す。issuesの調査方法・命名確認・未確認の扱いに従い、保存限定taskやissues.mdへの書き込みはまだ行わない。read-only調査ではrepository taskを登録しない。
2. `project.json`で対象を確認し、既存の`issues/<environment>/<target-directory>/issues.md`を読む。対象指定が不足している場合は確認し、別target・serviceへ広げない。`AGENTS.md`、[issue-gate](../../../framework/rules/issue-gate.md)、[Markdown structure](../../../framework/rules/detailed-design.md#markdown-structure)と対象resourceの表示・参照section、[Model authority](../../../framework/rules/model-information.md#model-authority)と[Properties format](../../../framework/rules/model-information.md#properties-format)を読む。
3. 調査結果を、表示だけで修復できる問題、設計判断・設定変更が必要な問題、未確認へ分ける。表示以外のissueが残っていても、明示された表示修復はIssue remediationとして扱える。表示修復対象がなければ調査結果を報告して終了する。

## 修復範囲

- 対象は、見出し・一覧・表の形式や番号、propertyの表示alias、説明文、リンクの表示text・anchor、正本modelと生成Markdown／JSONの表示不一致。resourceの所属、正式property、設定値、名称、tag、policy本文、参照先resource、resourceMode、logical ID、current identifierは維持する。
- 表示入力の修復は`display.*`や説明commentなど対応するmodel propertiesを先に変更する。説明は確定済み設計から根拠を確認できる内容だけとし、不明な用途・表示名を作らない。正式名称のrename、必須Name／tagの追加、欠落する設計値の補完を表示修復へ含めない。
- 設定値が正しく生成物だけが古い場合は、modelを変更せず再生成する。リンクは同じenvironment・targetの実resourceへの対応を確認し、既存の参照先を維持して表示を修復する。参照先が不明・複数候補・未設計なら未確認として残す。
- 生成Markdown／JSONを直接編集しない。`--import-markdown`で既存modelを上書きしない。generator／validator／共通表示ruleの不具合を検知した場合は、原因と必要なframework修正を報告し、consumerのmodelで回避しない。framework修正は本skillから別taskとして自動開始しない。

## 修復契約と生成

- 調査で特定した表示問題だけを対象に、`migration` taskを登録する。GoalとRequired changesへ対象issue、原因、表示修復scopeを記載し、既存issueの番号と根拠、または今回の調査結果を示す。この契約は保存限定taskの免除を使わず、`## Validation scope`とその部分集合の`## Issue remediation`へ具体的な`<environment>/<target-directory>/<service-id>`を列挙する。`all`／`framework`を修復例外にしない。
- 契約の`## Modified files`と`## Allowed paths`へ、自分の契約、変更するmodel入口・part、生成Markdown／JSON、対象issues.mdの具体的pathを列挙する。変更予定fileは実変更前に予約し、各Requirement IDへ`changed:`／`exists:`または登録済み`check:`を対応付ける。別taskの変更・未予約の生成先を取り込まない。
- repository外の候補から`task_contract.py --task-file tasks/<task-name>.md --source <候補file>`で登録し、以後は`BLUEPRINT_TASK_FILE`で同じ契約を選ぶ。重複時は新規taskを停止し、既存taskを変更しない。詳細は[task-contract](../../../framework/rules/task-contract.md)に従う。
- modelは入口indexと必要なpartを一つの論理serviceとして扱う。変更前後で設定値・resource identity・参照先が維持されていることを確認し、`framework/scripts/sync-model.py --write`で契約scopeのserviceを生成する。成功serviceの生成物を保存し、失敗serviceの保存済み生成物を保持する。

## 再検証と一覧更新

- 修復後に同じ範囲でissues skillの読み取り専用調査を再実行し、対象問題の解消と生成一致、リンク・anchor、表構造を確認する。検証失敗や比較不能を解消と扱わない。設定・名称・policy・参照先resource等の意味が変わった差分は表示修復として保存しない。
- issues.mdは同じ修復契約内で更新する。解消を確認できた対象issueだけを除去し、表示以外の問題、未確認、対象外serviceの既存issueを保持する。新たに確認した未解決問題はissues skillの形式で記載し、更新日時・確認範囲・未検証範囲を更新する。0件でもfileを残す。
- 最後に`python3 -B framework/scripts/blueprint-loop.py --mode local --task-file tasks/<task-name>.md`を実行する。成功後だけ今回の契約を`completed`にする。失敗時は今回の契約を`suspend`にし、失敗check・file・具体的errorと必要なrepository外logを記録する。再開時は`task_contract.py --task-file tasks/<task-name>.md --resume`で競合を確認する。
- チャットには修復内容、保存file、検証結果、残る設計問題・未確認を簡潔に報告して終了する。対象外の修復、次工程、別taskの作成・再開へ進まない。

読取規則はAGENTS.mdの「必要な規則の読み方」に従う。targetの確定・account／profile検証には[project-configuration](../../../framework/rules/project-configuration.md)、停止・調査／修復／保存の例外判定には[issue-gate](../../../framework/rules/issue-gate.md)を読む。repository変更時だけ[task-contract](../../../framework/rules/task-contract.md)と[Local loop](../../../framework/rules/loop-engineering.md#local-loop)と[Validation scope](../../../framework/rules/loop-engineering.md#validation-scope)、[Other task completion](../../../framework/rules/loop-engineering.md#other-task-completion)を追加する。

framework変更時だけ[Framework regression](../../../framework/rules/loop-engineering.md#framework-regression)を追加で読む。
