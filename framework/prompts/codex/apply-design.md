# Apply Confirmed Detailed Design

chatで確定した詳細設計をrepositoryへ保存し、generated service modelを同期するために使用する。

## User input

- Design target: `<確定済みの機能またはservice>`
- Target environment: `<project.jsonのenvironment>`
- Target AWS account: `<project.jsonの12桁AWS account ID>`
- Confirmed design files: `<保存するMarkdownとJSON artifactのpathおよび完成内容>`

## Read before changing files

1. `AGENTS.md`
2. `README.md`
3. `tasks/active.md`
4. `project.json`
5. 対象の既存`docs/designs/<environment>/<aws-account-id>/**`
6. `framework/rules/detailed-design.md`
7. `framework/rules/model-information.md`
8. `framework/rules/loop-engineering.md`
9. 対象resourceに関係する`framework/materials/aws/*.properties`

## Validate input

- environmentとAWS accountが`project.json`の同じtargetに存在する。
- Confirmed design filesのpathが対象target配下にある。
- 必須設計値が未確定、矛盾、placeholderではない。
- MarkdownとJSON artifactが`framework/rules/detailed-design.md`に従う。
- humanが確定していないresource、property、値を追加しない。

不足または矛盾がある場合はrepositoryを変更せず、該当項目だけをblockerとして報告する。

## Create active task contract

最新依頼のtask type、target、Goalを現在の`tasks/active.md`と比較する。異なる場合は新しいtaskとして扱い、最初のrepository changeで`tasks/active.md`を今回の内容へ上書きする。完了済みの前taskが残っていること自体はblockerにしない。

- Task typeは`design`とする。
- GoalにDesign target、environment、AWS account、保存対象serviceを記載する。
- AWS mutation、AWS API、CloudFormation/Terraform execution、deploy/applyは禁止する。
- `Required changes`は一意なRequirement ID付きで、確定設計の保存とservice model生成をfile単位に記載する。
- `Acceptance checks`は各Markdown／JSON／propertiesへ`changed:`または`exists:`を対応付ける。
- Allowed pathsは対象の`docs/designs/<environment>/<aws-account-id>/**`、`model/<environment>/<aws-account-id>/**`、`tasks/active.md`だけに限定する。
- IaC、observed value、scenario、scenario result、別targetは対象外とする。

## Save source design

Confirmed design filesのMarkdownとJSON artifactだけを`docs/designs/<environment>/<aws-account-id>/`へ保存する。chatの完了報告、質問履歴、判断経緯、verification evidenceは保存しない。

`model/**`を手動編集しない。

## Generate service model

対象targetだけを指定して実行する。

```console
python framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id>
```

generated modelを手修正しない。生成失敗、orphan model、Markdown validation failureは値の推測やcheck bypassで解消しない。

## Verify and finish

1. `python framework/scripts/blueprint-loop.py --mode local`
2. `git diff --check`

target、保存したsource design、生成したmodel、Requirement ID別check結果、blockerを完了報告に記載する。IaC、observed value、scenario、次taskを作成または実行せず終了する。
