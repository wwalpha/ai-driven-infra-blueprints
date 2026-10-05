# ai-driven-infra-blueprints

human、chatbot、Codexが役割を分け、特定のsystem architectureに依存せずAWS infrastructureを設計・実装・検証するためのrepository blueprintです。配布状態ではprojectやIaC implementationを持ちません。

## Initial setup

1. `framework/prompts/codex/01_initialize.md`をCodexへ渡す。Codexが初期化に必要なproject、environment、必要な場合だけalias、AWS account、region、IaC engineを一問一答で順番に確認する。
2. 現時点で必要値が確定しているtargetだけを回答する。未作成または必要値が未確定のenvironment／logical targetは初期化対象に含めない。
3. Codexが回答から`project.json`と定義済みtarget pathを作成し、全targetで未選択のIaC engine directoryを削除する。
4. 未確定だったtargetは、必要値の確定後に`framework/prompts/codex/02_add-target.md`をCodexへ渡して追加する。
5. initializationまたはmigration taskの完了後は終了し、design taskを自動作成または自動実行しない。

`docs/system-overview.md`は初期化とは独立した任意の背景資料です。初期化前でも後でも、分かる範囲だけを記入できます。初期化後のproject topologyのmachine-readable source of truthは、Codexが生成する`project.json`です。humanがJSONを直接作成・編集する手順はありません。environment名、environment数、AWS account数はblueprintで固定しません。

`project.json`の各targetには任意の命名suffixを設定できます。たとえばtargetに`"suffix": "aaaaaa"`を指定すると、選択したenvironment/aliasの値を命名patternの`{{suffix}}`へ使用します。値は空でないlower-kebab-caseとし、一部targetだけを指定できます。`[-{{suffix}}]`は未設定なら区切りごと省略し、必須の`{{suffix}}`が未設定なら停止します。suffixのないpatternや既存名称は変更しません。初期化／target追加時に確認し、既存targetへの追加・変更・解除はCodexへ明示したmigration taskで行います。

`project.json`の各targetには任意の`awsProfile`と`awsExecutionAccountId`を設定できます。initialization／target追加時に確認済みの値を指定し、不要なら項目を省略します。既存targetへの実行account IDの登録・変更・解除は、対象targetと値を明示したmigration taskをCodexへ依頼します。

```json
{
  "environment": "dev",
  "awsAccountId": "123456789012",
  "awsExecutionAccountId": "210987654321",
  "awsRegion": "ap-northeast-1",
  "iacEngine": "cloudformation",
  "awsProfile": "dev-admin"
}
```

設定時はpreflightとCloudFormation controllerが自動使用し、直接のAWS CLIにも`--profile`を付けます（[AWS CLIのnamed profile](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html)）。SDKにはprofileを明示し、Terraformは対象processの`AWS_PROFILE`へ渡します（[AWS providerの認証設定](https://registry.terraform.io/providers/hashicorp/aws/latest/docs#authentication-and-configuration)）。profile未設定時は従来の明示profile／default credential chainを維持します。設定済みprofileと異なる明示profileは実行前に停止します。account／regionの確認も引き続き行います。

`awsAccountId`はresource作成時の明示的なaccount ID設定・名前とtargetの識別に使います。同じtargetに作成するresourceを認可するpolicyの所有account・source accountには`awsExecutionAccountId`を使います。`awsExecutionAccountId`はAWS操作の認証account照合にも使うASCII数字12桁の文字列です。省略時は`awsAccountId`を使い、設定と異なるcaller accountでは停止します。設定だけで認証は切り替わりません。上の例では、選択したprofileのcaller accountが`210987654321`である必要があります。

例えば、このtargetのVPC Flow Logsの信頼policyでは、`aws:SourceAccount`は`210987654321`、`aws:SourceArn`は`arn:aws:ec2:ap-northeast-1:210987654321:vpc-flow-log/*`です。両条件は実際のFlow Logの所有accountを照合します（[AWS公式のFlow Logs信頼policy仕様](https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs-iam-role.html)）。権限policyの`Resource` ARNや`Principal`も参照先の実際の所有accountに合わせ、明示したcross-account参照はそのaccountを維持します。

CFnの`AWS::AccountId`は実際のstack作成accountです（[AWS公式の擬似parameter仕様](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/pseudo-parameter-reference.html)）。両IDが異なる場合、名前などへ`awsAccountId`を含める実装は独立した明示parameterを使います。AWS APIの暗黙の所有者検証は実行accountを使い、設計に明示したaccount propertyやcross-account参照は維持します。

一つのenvironmentにtargetが一件だけならaliasを使用しません。複数の論理配置先がある場合は全targetへhuman-confirmed aliasを設定し、異なるaliasへ同じAWS account IDを設定できます。aliasは同じenvironment内で一意なlower-kebab-caseとし、12桁の数字だけの値は禁止します。target directoryはaliasがあればalias、なければ`awsAccountId`です。同じenvironment/実行accountのtargetでもIaC engineを統一します。

## Repository instructions

- `README.md`: repository全体の役割、情報優先順位、workflow
- `framework/`: project間で共通利用するprompt、rule、catalog、validation scriptの一括コピー単位
- `framework/prompts/README.md`: promptの説明、使用時期、使用方法、実行順をまとめたguide
- `framework/prompts/chatbot/*.md`: 初期設計などで都度使用するAsk指示
- `framework/prompts/codex/01_initialize.md`: 必要値をhumanへ確認し、topologyとrepositoryを初期化する指示
- `framework/prompts/codex/02_add-target.md`: 初期化後に確定したtargetを1件追加するmigration指示
- `framework/prompts/chatbot/service-design.md`: 詳細設計fileと、それをrepositoryへ作成する自己完結型Codex promptを出力するAsk指示
- `framework/prompts/codex/03_implement.md`: 承認済み詳細設計を選択済みIaCへ変換し、local static validationまでを行う指示
- `framework/prompts/codex/04_deploy.md`: 作成・検証済みIaCを変更せず、安全確認、deploy/apply、deploy完了確認を行う指示
- `framework/prompts/codex/05_update.md`: humanが手動修正した未commitの詳細設計をIaCへ反映し、deploy/applyまで行う指示
- `framework/prompts/codex/06_scenario-test.md`: deployとは別taskでapplication behaviorを検証する指示
- `framework/scripts/check-deploy-context.py`: topology、credential、deploy先account、region、IaC engine、必要commandを確認するpreflight
- `framework/scripts/sync-model.py`: 設計値の正本model propertiesからMarkdown／JSON artifactを決定的に生成・検証する
- `framework/scripts/model_files.py`: `<service.properties> --resource '<resource-number-or-logical-id-or-anchor>'`で対象resourceの正本と同じ表示group・共通注記だけを位置付きで読む。`--find '<key-or-logical-id>'`は値を表示せず対象fileと行を検索する。600行超のmodelの物理分割は明示design/migration taskで`--split`を実行する
- `docs/designs/<environment>/<target-directory>/cloudformation-stacks.md`: CloudFormation targetの管理対象stack、templateと個別parameterのファイル名を記す詳細設計
- `project.json`: Codexがinitialization時に生成するmachine-readable project topology
- `tasks/<task-name>.md`: taskごとの契約。`issues/`配下以外の変更予定fileが重複しない複数taskを同時進行できる

## Task transition

repository変更は[task契約](framework/rules/task-contract.md)に従って`tasks/<task-name>.md`を登録します。read-only調査・chat-only相談は契約不要です。各工程の手順は対応workflowを使用します。

## 未解決issueによるtask停止

停止条件・修復・保存限定taskの例外は[issue gate](framework/rules/issue-gate.md)を正本とします。

## Local issues scan

issuesは[対象限定scan・Python保存](framework/rules/issues-investigation.md)を使う。既存validator診断と全resourceの最小命名材料を確認し、通常issueは`issues.md`、非阻害model→IaC差分は`iac-issues.md`へ別保存する。`diff.md`は環境間比較用のまま。issue gateは`issues.md`だけを読む。

```console
python3 framework/scripts/issues_scan.py scan --environment <environment> --target-directory <alias-or-account-id> --service <service-id> --artifact /tmp/issues-scan.json
python3 framework/scripts/issues_scan.py --task-file tasks/<task-name>.md save --artifact /tmp/issues-scan.json --review /tmp/issues-review.json
python3 framework/scripts/blueprint-loop.py --mode local --task-file tasks/<task-name>.md
```

複数serviceは`--service`を繰り返す。保存済み結果だけは`save-results`を使い再調査しない。全名称・残判断のreview、保存限定契約、partial/error、CloudFormationの対応/未対応範囲はリンク先に従う。

## Context priority

実行時の入口と読取規則は[AGENTS.md](AGENTS.md)と使用skill／workflowのRead節です。READMEは人間向けguideで、毎taskの全文読込対象ではありません。target設定は[project configuration](framework/rules/project-configuration.md)、設計値と生成物の関係は[model information](framework/rules/model-information.md#model-authority)に従います。背景情報・外部情報は必要な範囲だけ参照します。

## Task contract and types

active promptの`## Task contract`には次を正確に1件記載します。

```md
- Task type: `<task-type>`
```

`infrastructure` taskでは、同じTask contractへ次も正確に1件記載します。

```md
- Infrastructure phase: `<implement-or-deploy-or-update>`
```

許可するtask type:

- `initialization`: 必要値をhumanへ確認し、project topologyとtarget pathを初期化する。
- `design`: 詳細設計と対応するservice modelを更新し、local validation後に終了する。
- `infrastructure`: `implement` phaseでIaCを作成・検証するか、`deploy` phaseで既存IaCをdeploy/applyするか、`update` phaseでhumanの未commit設計差分をIaCへ反映してdeploy/applyする。
- `scenario-test`: scenario、test implementation、実行、scenario-scoped current resultを更新して終了する。
- `governance`: repository ruleやworkflowを変更する。
- `catalog-maintenance`: materials catalogを明示scopeで保守する。
- `migration`: active promptで定義されたmigrationだけを実行する。

各taskは独立してhumanが明示的に開始します。task完了後に次taskを自動作成または自動実行しません。

各active taskは次のmachine-readable completion contractを持ちます。

```md
## Required changes

- [R1] 実施内容

## Acceptance checks

- [R1] `changed:path/to/file`
- [R1] `check:registered-check-id`
```

Acceptance checksの定義は[Acceptance contract](framework/rules/task-contract.md#acceptance-contract)に従います。

## Roles

### Human

- system overviewを必要に応じて記入する
- Ask形式の質問へ回答し、設計判断を承認する
- 実行するtask typeとscopeを決める
- deploy/apply許可を明示する
- 必要なscenario-test taskを別途開始する

### Codex

- active prompt、task type、repository ruleの範囲だけを実行する
- design taskでは詳細設計とservice modelまでで終了する。chatbotが既存resource取得を指定した場合だけread-only AWS APIで選択済みpropertyと必要な非ARN current identifierを反映できる
- infrastructure taskでは`implement`、`deploy`、`update`のいずれか一つだけを実行する
- scenario-test taskではscenarioとcurrent resultだけを変更する
- task完了後に次工程へ自動的に進まない

## Initial detailed design

初期設計はAsk workflowとし、実装は独立した`design` taskで行います。

1. system overview、既存設計、関連materialsを確認する。
2. 必須serviceの前提となる未設計serviceを優先する。
3. 通常5〜8個の設計判断を一つのbatchとして質問する。
4. humanが決める設計値だけで完成できる場合は、完成したmodel propertiesをfile単位で出力し、Markdown／JSON artifactの生成先を示す。
5. 既存AWS resourceの現在値を使用する場合は、chatbotが対象service、resource type、propertyを確定し、完成Markdownの代わりにread-only取得を含む自己完結型Codex promptを出力する。
6. Codexのdesign taskはtarget contextを検証し、resource候補をhumanが選択した後、選択済みpropertyを`model/**`へ直接差分反映してMarkdown／JSON artifactを生成する。

chatの完了報告と保存対象Markdownは分離します。chatとMarkdownの説明文は日本語とし、保存対象Markdownの正本形式は`framework/rules/detailed-design.md`に従います。policyなどJSON documentが必要な確定設計は、同ruleのservice-owned JSON artifactとしてMarkdownから参照します。model propertiesを先に更新してMarkdownとJSON artifactを生成し、design taskはCloudFormation/Terraform、AWS mutation、scenario、scenario resultを変更しません。既存resource取得では必要な非ARN current identifierだけをobserved valueへ反映できます。

resource単位の`desired.resource.<nnn>.resourceMode`は`CREATE`／`IMPORT`だけです。未指定はCREATE互換です。CREATEには既存の命名・必須Name tag policyを適用し、IaC生成対象にします。IMPORTは既存AWSのactual/current値を設計・modelへ保持し、framework命名不一致やName tag不存在を許容します。AWS変更・IaC生成・CloudFormation Resource Import・Terraform importは行いません。表示labelはAWS propertyから分離します。詳細は[model contract](framework/rules/model-information.md#resource-management-mode)を参照してください。

## Post-design SDD

新規設計では、`framework/prompts/chatbot/service-design.md`が出力したCodex promptでmodel propertiesを保存して詳細設計Markdownを生成し、`03_implement.md`でIaCを作成・検証し、別taskの`04_deploy.md`でdeploy/applyする。

既存詳細設計をhumanが直接変更し、未commit差分をIaCへ反映してdeploy/applyまで行う場合は、`framework/prompts/codex/05_update.md`だけを使用する。`03_implement.md`、`04_deploy.md`を個別に実行しない。

どちらのworkflowでもapplication behavior確認が必要な場合だけ、deploy完了後に別taskで`framework/prompts/codex/06_scenario-test.md`を使用する。詳細な使い分けは`framework/prompts/README.md`を参照する。

## Operating model

1. humanが独立したtaskのtypeと対象scopeを決める。
2. Codexはactive prompt、`AGENTS.md`、関連rulesを読み、同じtask type内だけで作業する。
3. `design` taskはintended designとservice modelを更新して終了する。既存resource取得が明示された場合だけ、read-only AWS APIによる現在値の直接差分反映を含める。
4. `infrastructure` taskの`implement` phaseはIaC作成とlocal static validationまでで終了する。
5. 別の`infrastructure` taskの`deploy` phaseは既存IaCを変更せず、CloudFormation change setまたはTerraform planを確認してdeploy/applyし、成功後のobserved value更新までで終了する。
6. `infrastructure` taskの`update` phaseはhumanの未commit model propertiesを変更せず、Markdown生成、IaC反映、deploy/apply、observed value更新までを一つのtaskで行う。
7. `scenario-test` taskは別途開始し、指定scenarioのtestとcurrent resultだけを更新する。
8. scenario testが失敗しても、同じtaskでdesign変更、IaC修正、redeploy、remediation task作成へ進まない。

non-scenario taskのverification outputはdefaultではrepositoryへ保存せず、Codexの完了報告に記載します。

## Framework distribution

`framework/`、`.agents/`、rootの`AGENTS.md`と`README.md`を共通資産の配布単位とします。既存repositoryへ同期する場合は、配布元repositoryのrootで次を実行します。

```console
python framework/scripts/sync-existing-files.py --target <target-repository>
```

このcommandは`<target-repository>/framework/**`、`<target-repository>/.agents/**`、rootの`AGENTS.md`と`README.md`を追加・更新します。projectごとに変わる`project.json`、`docs/`、`infra/`、`model/`、`tasks/`、`tests/`はコピーまたは変更しません。`--dry-run`で保存前の差分を確認できます。同期件数はコピー先との内容差分で数えるため、同期対象外の`tasks/<task-name>.md`などを含むローカル未commit件数とは一致しない場合があります。summaryに同期範囲と対象外のpathを表示します。

## Repository structure

```text
AGENTS.md
README.md
project.json  # initialization後にCodexが生成
framework/
  chatbot/
  prompts/
    README.md
    chatbot/
      service-design.md
    codex/
      01_initialize.md
      02_add-target.md
      03_implement.md
      04_deploy.md
      05_update.md
      06_scenario-test.md
  rules/
  materials/
    catalog.properties
    catalog.sha256
    aws/
    cloudformation-schema.properties
    cloudformation-schema.sha256
    cloudformation-schema/ap-northeast-1/
  scripts/
    blueprint-loop.py
    check-deploy-context.py
    sync-model.py
    sync-existing-files.py
    update-catalog-lock.py
    validate-blueprint.py
tasks/<task-name>.md  # taskごとの契約。idle状態では省略可
docs/
  system-overview.md
  designs/<environment>/<target-directory>/
model/
  <environment>/<target-directory>/<service-id>.properties
  <environment>/<target-directory>/cloudformation-stacks.properties  # stack設計がある場合
infra/
  cloudformation/  # CloudFormationを選択したtargetがある場合だけ
    templates/  # aliasなしの共通template
    templates/<alias>/  # alias別template
    parameters/<environment>/<target-directory>/
  terraform/  # Terraformを選択したtargetがある場合だけ
    modules/  # aliasなしの共通module
    modules/<alias>/  # alias別module
    environments/<environment>/<target-directory>/
tests/
  scenarios/<scenario-id>/
  results/<scenario-id>/<environment>/<target-directory>/
```

## Design information

設計値・分割model・生成手順は[model information](framework/rules/model-information.md)、設計Markdownの表示は[detailed design](framework/rules/detailed-design.md)、取得値は[observed values](framework/rules/observed-values.md)を正本とします。

## Scenario evidence

- scenarioは`tests/scenarios/<scenario-id>/`に置き、stableなlower-kebab-case IDを使う。
- current resultは`tests/results/<scenario-id>/<environment>/<target-directory>/`に置く。
- 同じscenario/environment/target directoryの再実行では同じ`result.md`とstable evidence fileを更新する。
- 実行別またはtimestamp別のresult directory/fileを作らない。
- scenario変更時は既存resultを再実行結果へ更新するか、`STALE`または`NOT_EXECUTED`へ更新する。
- scenario evidenceの過去版はGit履歴で追跡する。
- scenario resultはcurrent observed valueの正本ではない。

## CFn非対応resourceの詳細設計

詳細設計に記載できる対象と、選択済みIaC engineで作成できる対象を分離します。`Macie.ClassificationJob`は公式API仕様に基づいて設計し、CFn対応の`Macie.Session`と同じ`macie.md`へ通常のリソース一覧・詳細表で記載できます。両方を同じservice modelに保持します。

- APIの選択リストと固定schema: `framework/materials/api/Macie_ClassificationJob.properties`と同名`.json`
- schema内に公式仕様URL、API version、元SDK modelのhash、確認日、CFn非対応を保持します。clientTokenと生成jobArnは設計項目にしません。
- root propertyを一つのrowにし、nested設定はJSONで保持します。長いobjectはservice配下JSON artifactへ分けられます。型、必須、未知のnested field、単発／定期などの条件をoffline検証します。
- jobIdは`IDENTIFIER_OUTPUT`としてdesiredのlogical referenceとobservedのcurrent IDを分離します。未作成は既存の`PENDING_DEPLOY`を使用します。
- CFn型解決: `python framework/scripts/design_catalog.py --cloudformation-type Macie.Session`は成功し、`Macie.ClassificationJob`は非対応として失敗します。Jobを含む実装要求を、CFn部分だけの実装で完了扱いにしません。
- checksum確認: `python framework/scripts/design_catalog.py`。API catalog/schemaの保守は明示scopeの`governance` taskで行い、仕様・選択リスト・表示定義・focused checksを揃えた後、`python framework/scripts/design_catalog.py --write-lock`で`framework/materials/api-catalog.sha256`を更新します。通常taskでは変更せず、未知のresourceを自動登録しません。

この対応は詳細設計・検証・model生成までです。Job作成の自動化、Custom Resource、Terraformへの切替、consumerへの同期は別の明示依頼で扱います。

## Materials catalog

`framework/materials/aws/`はAWS CloudFormation Resource Specificationから作成したcurated partial catalogで、詳細設計へ載せる候補項目を選択します。廃止せず、provider schemaの全項目を設計書へ機械的に掲載する用途には使いません。

- provenanceと件数: `framework/materials/catalog.properties`
- file integrity: `framework/materials/catalog.sha256`
- check: `python framework/scripts/update-catalog-lock.py`
- authorized catalog maintenance後のlock更新: `python framework/scripts/update-catalog-lock.py --write`

通常のproject taskでは`framework/materials/aws/*.properties`を変更しません。不足resourceがある場合は、source specification versionと対象resourceを明示した専用catalog-maintenance taskで更新します。

resource追加・削除時は`framework/rules/resource-layout.json`の表示方針も同じtaskのAllowed pathsへ含めて更新します。全catalog resourceに独立表示または親への統合を明示し、未判定をlocal loopで拒否します。所属先、複数の子、共有・複数対象、外部参照を確認し、条件付き統合が必要ならその判定と検証を先にframeworkへ実装します。現在はS3 BucketPolicyとKMS Aliasを親の詳細表へ統合し、その他は独立表示を維持します。KMS Aliasの識別marker、参照とmodelは`framework/rules/detailed-design.md`と`framework/rules/model-information.md`に従います。

`framework/materials/cloudformation-schema/ap-northeast-1/`は、propertiesで選択したresource typeについて公式CloudFormation provider schemaのfull propertyと型・制約を保持します。対象件数は`framework/materials/cloudformation-schema.properties`を正本とします。設計値とCloudFormation templateのproperty名、`type`、`enum`、`pattern`、長さ、範囲、`required`の検証元です。

- provenance: `framework/materials/cloudformation-schema.properties`
- file integrity: `framework/materials/cloudformation-schema.sha256`
- offline check: `python framework/scripts/cloudformation_schema.py`
- 公式regional schemaからの明示的なrefresh: `python framework/scripts/cloudformation_schema.py --write`

通常のlocal loopはnetworkへ接続せずsnapshotとpropertiesの対応を検証します。refreshは公式schema更新を取り込む明示的なgovernanceまたはcatalog-maintenance taskだけで実行します。CloudFormation template自体は、target regionを指定した`cfn-lint`でprovider schema validationを行い、続けて`aws cloudformation validate-template`で構文を検証します。

## Validation

active promptには`Task type`と`## Allowed paths`を記載します。Allowed pathsはtask type boundaryを拡張できません。

```md
## Task contract

- Task type: `design`
- Task status: `running`

## Validation scope

- `<environment>/<target-directory>/<service-id>`

## Required changes

- [R1] 確定済み詳細設計を保存する。
- [R2] 正本model propertiesを先に更新し、Markdown／JSON artifactを生成する。

## Acceptance checks

- [R1] `changed:docs/designs/<environment>/<target-directory>/**`
- [R2] `changed:model/<environment>/<target-directory>/**`

## Modified files

- `tasks/network-design.md`
- `model/dev/cde/ec2.properties`
- `docs/designs/dev/cde/ec2.md`

## Allowed paths

- `docs/designs/**`
- `model/**`
- `tasks/network-design.md`
```

通常taskはValidation scopeに指定したserviceの設計/model、生成Markdown/JSON一致、ownership、stack、catalog/schema、命名、policy、reference/link、artifact、active task contractとtask固有checkを検証します。validatorからmodel照合まで指定serviceを引き継ぎます。共通の契約・変更範囲・project topology・catalog整合性チェックは維持します。参照先はlink解決に必要な情報だけを読み、参照先service全体は検証しません。unstaged/staged両方の`git diff --check`もloop内で実行します。CloudFormation/Terraformとdeployの既存必須手順は各phaseのrules/promptどおり別途維持します。

```console
python -X utf8 framework/scripts/blueprint-loop.py --mode task
```

frameworkが未変更なら`*.checks.py`のself-testを省略します。`framework/**`全体（scripts/rules/materials/schema/catalog/prompts等）、`.agents/**`、`AGENTS.md`、`README.md`のunstaged/staged/untracked変更がある場合は全self-testを自動追加します。framework変更taskやcommit済みframework変更の再検証は明示的に次を実行します。

```console
python -X utf8 framework/scripts/blueprint-loop.py --mode full
```

`full`は通常taskのvalidationに加え、全`framework/scripts/*.checks.py`を実行します。実設計の全体検証とframework regressionは別の責務です。framework未変更の`task`はValidation scopeが`all`でもself-testを実行しません。

Windowsでは全回帰を開始する前にパスワード入力が必要です。自動追加と`--affected`で選んだ結果が全件になる場合にも適用し、未登録・不一致・キャンセル時は検証を起動せず停止します。通常の対象限定検証と一部に絞った回帰には入力を求めません。Windowsのstaged検証では現行`blueprint-loop.py`／`regression_guard.py`もstageし、workspaceと異なる旧entrypointを実行しません。

人間がrepository rootで次を実行すると、repo直下の`.lock`一つだけへsalt付きpassword hashを保存します。管理者権限、ProgramDataへの設置、ACL設定は不要です。passwordは12文字以上とし、チャットやcommand引数へ渡さず、非表示の入力欄で入力します。

```console
python -I -B framework/scripts/regression_guard.py --install
```

既存の`.lock`は上書きしません。不一致・未登録・破損・非対話入力・キャンセル時は全回帰を開始しません。`.lock`はローカル設定としてtask変更範囲から除外し、staged検証にはその値を引き継ぎます。解除flagや再利用tokenは保存しません。repo内のfileを編集できる権限からの分離は行いません。Windows以外のガード有効化は今回の対象外です。

旧版で登録済みなら、repository rootで次を実行すると同じpasswordを再利用できます（既存のrepo `.lock`がある場合は上書きしないでください）。修正版はProgramDataを参照しません。

```powershell
Copy-Item 'C:\ProgramData\BlueprintRegressionGuard\.lock' '.\.lock'
```

生成と検証の対象はactive taskの`## Validation scope`で統一します。`task`／`local`／`full`はいずれもそのscopeを使用し、`full`単独では全serviceへ広げません。`local`を指定するskillも対象限定検証だけで完了できます。scope欠落時は停止します。全体検証は明示した`--all`またはscopeの`all`だけで実行します。`--all`と`local`のscope `all`は全self-testも実行します。日次の全体検証は別途設定済みのscheduleに任せ、対象限定検証の後に「念のため」の全体検証を追加しません。

command例はPython 3 launcherを`python`と表記する。WindowsでPython Launcherだけがある場合は`py -3`、Unix系OSで`python3`だけがある場合は`python3`へ、各command先頭の`python`を置き換える。

### 競合解消後の固定snapshot検証

競合解消したfileと今回の`tasks/<task-name>.md`をstageした後、比較元commitを明示して実行します。

```console
python -X utf8 framework/scripts/blueprint-loop.py --mode task --staged --base <比較元commit> --affected
```

stage内容をrepository外に固定し、その中のrunnerと契約を使います。元workspaceの未stage変更は含めず、元indexも変更しません。比較元との差分にはincoming変更も含まれます。終了時に元HEAD/indexが変わっていればstaleとして失敗し、古い結果を最新状態の成功とは扱いません。`snapshot.json`に検証したtreeと比較元が残ります。通常実行は従来どおり未stage変更も検証します。

`--affected`は、既存の回帰script自身の変更ならそのcheck、standalone loop runnerの変更ならloop checkを選びます。共通処理・rule・catalogなど対応不明の変更は全checkを実行します。選択理由と未実行checkを表示し、`full`／`--all`との併用は拒否します。framework開発taskの完了には`--mode full`を使います。

回帰は最大2並列で実行し、診断を名前順に表示します。直列比較は`--jobs 1`を指定します。起動時にUTF-8の事前確認を行い、通常のPython起動でも自動でUTF-8 modeへ切り替えます。

通常のtask/local検証は、catalogとserviceの入力内容が前回の成功時と一致すれば結果を再利用します。modelの入口/part、Markdown/JSON、参照先、project、frameworkのコード/rule/catalog/schemaのSHA-256とfile集合で判定し、mtimeだけでは省略しません。成功記録はrepository外のOS一時directory `blueprint-validation-cache`へ保存し、`BLUEPRINT_VALIDATION_CACHE_DIR`でrepository外の保存先を変更できます。破損・不明dependencyでは明示scope内を再検証します。契約、issue、変更範囲、Acceptance、scope全体のresource所有権/stack重複、IaC/deploy安全確認は毎回実行します。

同一targetの複数serviceも最大4並列で検証します。`--validation-jobs 1`で直列実行、`--fresh`で結果再利用を無効化できます。`--mode full`と`--all`はfresh検証です。再利用数と実行数を表示し、60秒を超えても未完了の検証をPASSにしません。

### Local loopの時間計測

追加指定なしでも、実行ごとにOS一時directoryの`blueprint-loop-*`へ計測ログを保存し、開始時に絶対pathを表示します。継続保存したい場合はrepository外の親directoryを指定します。

```console
python -X utf8 framework/scripts/blueprint-loop.py --mode task --log-dir /tmp/blueprint-loop-logs
```

`--profile`を追加すると、validatorと生成照合の子process、model_design／design_catalogの関数別内訳を計測します。初回相当の詳細計測は`--fresh --validation-jobs 1 --profile`を指定します。cProfileは主threadを計測するため、並列workerの関数別内訳は含まれません。計測overheadを含むため、通常の所要時間との直接比較は避けます。

Windowsでは保存先を例として`C:\Temp\blueprint-loop-logs`へ置き換えてください。一時directoryはOSが削除する場合があるため、長期保存にはrepository外の専用directoryを使用します。各実行は別directoryを作り、以前のログを上書きしません。

| File | 内容 |
| --- | --- |
| `snapshot.json`（`--staged`時） | 比較元commit、HEAD、index tree、元状態との一致、終了code |
| `*.checks.prof`（`--profile`時） | model_design／design_catalogの関数別cProfile計測。上位25件はcheck logにも出力 |
| `validate-blueprint.prof` / `sync-model-*.prof`（`--profile`時） | validatorと生成照合の子processのcProfile計測 |
| `timing.jsonl` | loopとcheckの開始・終了UTC時刻、経過秒数、PID、終了code、成否。30秒ごとの稼働記録も含む |
| `01-validate-blueprint.py.log`など | check別のstdout/stderr。実行中から直接fileへ保存し、check終了時にterminalにも表示 |

所要時間はmonotonic clockで計測します。terminalにはcheckの開始・終了と、30秒ごとのcheck名・経過秒数・PIDが表示されます。稼働表示は子プロセスの未終了を示し、処理の進捗率を示しません。強制終了やOS停止では`loop_end`を残せない場合があります。`loop_end`がなければ未完了として扱います。

2026-10-02にこのframework repository（Mac、未初期化template、既存の全15 focused check）で変更前のlocal loopを計測した結果は、全体38.6秒、repository validator 0.56秒でした。主な内訳は`design_catalog.checks.py`が14.2秒、`model_design.checks.py`が9.6秒、`policy_tables.checks.py`が5.0秒です。別のprofile実行では、`design_catalog.checks.py`の42ケースがmodel検証を子プロセスで繰り返し起動し、その待機が12.8秒を占めました。30〜60分の現象はこの環境では未再現です。consumer repositoryや別OSの時間とは区別してください。

同日の`viewcard-code`の読み取り計測では、全体202.2秒、repository validator 164.6秒、17 focused checkの合計37.7秒でした。設計Markdownは97 file、modelは99 fileあり、変更前は変更対象以外も含めて全targetを検証していました。この時点のvalidatorは既存1451件の診断でFAILし、focused checkも3件がFAILしました（consumer側の2 checkのassert guard不足、IAM fixture不整合、当該PythonのPyYAML不足）。性能調査でこれらは修正していません。計測前後のrepository file内容は一致しました。30〜60分の現象はこの計測でも未再現です。

`viewcard-code`のdev/cdeだけを別途read-onlyでprofileすると、`validate_views`が33回、`linked_resource`が6306回、`expanded_design`が1757回呼ばれ、参照先Markdownの再解析が繰り返されていました。`formal_property`は496495回呼ばれ、Pythonで全resource prefixを順番に調べる処理がprofile上で26.1秒を占めました（profileの計測負荷を含み、これらの時間は親子関係があるため合算できません）。このprefix判定だけを、起動時に構築したtupleに対する標準の`str.startswith(tuple)`へ変更しました。未知prefix・display alias・完全修飾propertyの扱いを維持し、全体の検証結果をcacheで省略しません。参照先の再解析を減らす変更は未実施です。

prefix判定の176入力×500回×3試行の比較では、中央値が0.517秒から0.028秒となり、この判定部分だけ約18.5倍速くなりました。loop全体の高速化倍率やconsumerへ同期後の所要時間を示す値ではありません。

Python checkの処理にはLLMのmodel/reasoning設定を渡していません。luna/maxで遅く見える場合も、まず`timing.jsonl`の実行時間とCopilot側のmodel request・tool待機・再実行の時間を分けて確認します。特定checkだけが遅ければ、例えば次のように標準のprofilerでそのcheckを計測できます。check名とrepository外の保存先は実測結果に合わせて置き換えます。元のloopが終了してから実行してください。

```console
python -B -m cProfile -o /tmp/design-catalog.prof framework/scripts/design_catalog.checks.py
python -m pstats /tmp/design-catalog.prof
```

### VS Code GitHub Copilot Autopilotで待機が止まる場合

1. **実行中のloopを増やさない。** 起動時のログdirectoryを控え、同じ実行の`timing.jsonl`とcheck別`.log`を確認します。toolのtimeoutだけではPythonの停止と断定しません。PIDを確認する際はcommandと開始時刻も照合します。実行中は検証inputを編集しません。
2. **コマンド追跡の終了を切り分ける。** VS Codeの`chat.tools.terminal.enforceTimeoutFromModel`（Experimental）は、agent指定timeoutでコマンドの追跡を終了し、それまでの出力を返す設定です。利用中の版にこの設定があれば、追跡timeoutが原因と確認できた場合に限りworkspace単位で`false`を比較検証し、確認後は元へ戻します。session切断を直す設定ではありません。[公式設定一覧](https://code.visualstudio.com/docs/agents/reference/ai-settings#agent-tools)
3. **通常のterminalから実行する。** 長時間checkはhumanがVS Codeの通常terminalまたはOSのterminalで上記commandを実行し、Copilotには表示されたログpathの確認を依頼します。これでagentのtool待機への依存を減らします。OSのsleepやterminal終了に対する存続は別途確認が必要です。
4. **session停止の証拠を確認する。** `Developer: Set Log Level`でGitHub Copilot / GitHub Copilot Chatを一時的にTraceにし、`Output: Show Output Channels`から同じ時刻のerrorを確認します。Agent Debug Logsがある版ではmodel requestとtool callも照合し、request limit、通信error、extension/terminal異常を分けます。`chat.agent.maxRequests`はrequest回数の上限であり、実行時間の上限ではありません。回数上限が実際に報告された場合だけ設定を見直します。[公式診断手順](https://code.visualstudio.com/docs/agents/agent-troubleshooting/troubleshooting)、[request設定](https://code.visualstudio.com/docs/agents/reference/ai-settings#agent-behavior)
5. **同じtaskで結果を確認する。** 切断後は今回の`tasks/<task-name>.md`と保存済みログを読み直します。`loop_end`と全checkの終了があり、検証inputも変わっていないことを確認して成否を報告します。`loop_end`欠落で実プロセスも終了済みの場合は全loopを再実行します。途中ログだけでPASSにせず、別taskへ進みません。

local loopはtask type、infrastructure phase、task scope、project topology、catalog/schema integrity、IaC engine selectionの共通checkと、Validation scope内のdesign value・service model・observed ARNを検証します。IaC内容とscenario/resultのrepository整合性も全体検証に含み、実IaC/deploymentの必須validationは各phaseで別途実行します。System Overviewの`UNSET`は検証失敗にしません。通常はIaC作成とdeploy/applyを別taskにし、humanがmodel propertiesへ手動修正した設計の反映だけは専用`update` phaseで一つのtaskとして実行します。

設計更新の順序は「catalog選択項目と命名ルールを確認 → model propertiesを更新 → 全対象のMarkdown／JSONを一時生成・検証 → 全件成功後に保存」です。生成失敗時は保存済み表示を変更せず、propertiesを正本として修正・再実行します。通常のsyncでMarkdownからmodelを上書きしません。旧形式の採用は明示されたmigration taskの`sync-model.py --import-markdown --write`だけに限定し、既存modelを上書きしません。

### CloudFormationのtemplateとローカル成果物のS3配置

controllerは、送信するtemplateが51,200 bytes以下なら従来どおり直接渡し、超過〜1 MiBなら指定bucketへ配置してS3 URLから変更セットを作成します。1 MiB超は停止します。小さいtemplateには配置bucket設定は不要です。

配置先はtargetの`cloudformation-stacks.properties`へ次のように指定します。以下は形式例で、bucket名・StackName・sourceは実際の設計で確定します。bucketの名前・設定はS3 modelが正本で、ここでは参照だけを保持します。

```properties
desired.deployment.templateBucket=[app-dev-assets](s3.md#s3-app-dev-assets)
desired.deployment.templateKeyPrefix=cloudformation/templates/
desired.artifact.001.stack=cfn-stack-app-dev-job
desired.artifact.001.resource=FunctionA
desired.artifact.001.property=Code
desired.artifact.001.source=infra/cloudformation/artifacts/function-a.zip
desired.artifact.001.bucket=[app-dev-assets](s3.md#s3-app-dev-assets)
desired.artifact.001.keyPrefix=lambda/functions/
```

Lambdaごとの使用fileはresource／propertyとsourceの対応で判定します。複数Lambdaが同じZIPを使う場合も各対応を明記します。配置先が異なる場合は各entryのbucketを指定します。元templateのS3 bucketとkey prefixが一致しなければ停止します。宣言のない既存S3参照は維持します。

ローカル成果物を配置した後、宣言済みS3 key/versionだけを内容hashへ置換した実行用copyをrepository外に生成します。Lambda ZIPの配置とCFn templateのS3送信は独立しており、ZIPを配置して小さいtemplateを直接送信できます。ビルド、bucket作成、権限追加、過去成果物削除はdeploy中に自動実行しません。初回のbucket作成は小さいtemplateから行い、成功後に利用stackを実行します。

全scopeをローカル検証し、各stackの順番でupload／checksum確認、AWS template検証、変更セット作成・実行を行います。sessionと隣接する`.files` directoryは同じtaskの再開まで保持してください。入力file、実行用copy、配置済みobjectが変わっていれば再開・実行を停止します。対応property、権限、保持方針の詳細は[CloudFormation rules](framework/rules/cloudformation.md#s3-deployment-artifacts)、正本形式は[model rules](framework/rules/model-information.md#cloudformation-s3配置)を参照してください。
