# Manual Design Update and Deployment Prompt

このpromptは、人間が既存の詳細設計Markdownを手動修正し、まだcommitしていない差分を確定済みdesignとして受け取り、service model同期、選択済みIaCへの反映、deploy/apply、完了確認までを一つの`infrastructure` taskで行うために使用する。新規詳細設計の作成には使用しない。

## User input

- Target environment: `{{project.jsonのenvironment}}`
- Target AWS account: `{{project.jsonの12桁AWS account ID}}`
- Design scope: `{{人間が手動修正した詳細設計Markdown。複数可}}`
- Deployment scope: `{{対象のtemplate/stackまたはTerraform root/resource。複数可}}`
- Authorized delete/replacement: `none`
- AWS profile: `{{使用するprofile名。default credential chainの場合は空}}`

## Resolve missing input

fileまたはAWSを変更する前にUser inputを確認する。placeholder、空、不明な値はmissingとして扱い、次の順序で一回の応答につき一つだけ質問する。

1. Target environment
2. Target AWS account
3. Design scope
4. Deployment scope

environmentとAWS accountは`project.json`に存在する候補だけを提示し、自動選択しない。delete/replacementは、対象resourceと理由がUser inputに明記されていない限り許可しない。AWS profileがplaceholderまたは空の場合はdefault credential chainを使用し、profile名を質問しない。

## Read before changing files

1. `AGENTS.md`
2. `README.md`
3. `tasks/active.md`
4. `project.json`
5. `git status --short`とDesign scopeのdiff
6. 対象の`docs/designs/<environment>/<aws-account-id>/*.md`とJSON artifact
7. 対応する`model/<environment>/<aws-account-id>/*.properties`
8. `framework/prompts/codex/04_implement.md`
9. `framework/prompts/codex/05_deploy.md`
10. `framework/rules/detailed-design.md`
11. `framework/rules/model-information.md`
12. 選択済みengineに対応する`framework/rules/cloudformation.md`または`framework/rules/terraform.md`
13. `framework/rules/observed-values.md`
14. `framework/rules/loop-engineering.md`
15. 対象resourceに関係する`framework/materials/aws/*.properties`
16. CloudFormationの場合は対象resourceのprovider schema

## Validate human design diff

- Design scopeは対象environment／AWS account配下の既存詳細設計Markdownだけとする。
- Design scopeのMarkdownにhumanが作成したuncommitted diffが存在しなければ停止する。
- Design scope外のuncommitted changeがある場合は、今回のtaskへ取り込まず停止する。
- 対応するmodelまたはIaCにtask開始前からuncommitted changeがある場合は停止する。
- humanが変更したintended designをこのtaskで修正、補完、巻き戻ししない。
- 詳細設計の不足、矛盾、placeholder、schema violation、未確定のhuman decisionがあれば停止する。

task開始時のDesign scope diffを保持し、deploy成功後のgenerated current value更新を除いて完了時まで同じであることを確認する。

## Create active task contract

Codexによる最初のrepository changeとして`tasks/active.md`を今回の対象だけを許可する内容へ上書きする。

- Task typeは`infrastructure`とする。
- Infrastructure phaseは`update`とする。
- goalにtarget environment、AWS account、Design scope、Deployment scope、選択済みIaC engineを記載する。
- AWS API executionとdeploy/applyは今回のDeployment scopeに限り`allowed`とする。
- Authorized delete/replacementは確認済みUser inputの値をそのまま記載する。
- `Required changes`は一意なRequirement ID付きで、human design diffの検証、service model同期、IaC implementation、deployment、必要なobserved value更新を分けて記載する。
- `Acceptance checks`はDesign scope、対応するmodel、対象IaCへ`changed:`を対応付け、deployment unitへ`exists:`を対応付ける。deploy未実行や失敗をrepository fileで完了扱いにしない。
- Allowed pathsはDesign scope、対応するJSON artifactとmodel、対象IaC、`tasks/active.md`だけに限定する。別targetと`tests/**`は変更禁止とする。

## Sync model and implement IaC

1. `framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id>`を実行し、human design diffを対応するservice modelへ反映する。
2. model生成失敗またはMarkdown validation failureではdesignを修正せず停止する。
3. `04_implement.md`のimplementation unit解決とengine別local static validationに従い、Deployment scopeに必要なIaCだけを最小変更する。
4. IaC implementation errorは確定済みdesign内で修正可能な場合だけ最大3 iterationまで修正する。human decisionまたはdesign変更が必要なら停止する。

## Preflight and deploy

credential、deploy先account、AWS region、IaC engine、必要commandをLLMの推論で判定せず、repository rootから次を実行する。AWS profileが空の場合は`--profile`を省略する。

```text
python framework/scripts/check-deploy-context.py --environment <environment> --aws-account-id <12-digit-account-id> [--profile <profile>]
```

scriptが終了code 0を返した場合だけ続行する。失敗時はcredential切替、account変更、check bypassを行わず停止する。secretやcredential値を表示または保存しない。

このtaskでDesign scopeから生成した対象IaCのuncommitted diffだけはdeploy対象として許可する。task開始前から存在したIaC diffまたはDeployment scope外のdiffは許可しない。

`05_deploy.md`のdeployment unit解決、engine別validation、change set／plan確認、実行、完了確認、failure stop ruleに従う。scope超過、account/region不一致、未許可のdelete/replacement、credential/permission不足、またはdeployment failureでは後続unitを実行せず停止する。

deploy/applyが成功した場合:

1. terminal successとresource存在を確認する。
2. 必要な非ARN generated current valueだけを詳細設計へ反映し、humanが変更したintended designは変更しない。
3. `framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id>`を再実行する。

deploy完了status、resource存在、observed value収集をapplication behaviorの検証またはscenario PASSとして扱わない。

## Verify and finish

1. task開始時のhuman design diffと比較し、generated current value以外のintended designをCodexが変更していないことを確認する。
2. 選択済みIaCのsyntax/static validationを再確認する。
3. `python framework/scripts/blueprint-loop.py --mode local`
4. `git diff --check`

target、Design scope、model同期、IaC変更、deployment unitとdependency順、plan/change set summary、deploy完了status、observed value更新、blockerを完了報告に記載する。verification outputをrepositoryへ保存しない。

scenario、scenario result、別target、次taskを変更、作成、実行しない。application behaviorの検証が必要な場合は、humanが別taskとして`framework/prompts/codex/07_scenario-test.md`を使用する。
