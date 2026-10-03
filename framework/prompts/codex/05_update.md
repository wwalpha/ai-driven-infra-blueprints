# Manual Design Update and Deployment Prompt

契約は`tasks/<task-name>.md`へtaskごとに登録する。Task statusを`running`とし、`## Modified files`へ今回変更する具体的なfile path（契約自身、新規file、生成artifact、model part、削除対象を含む）を列挙する。Allowed pathsのglobは予約fileの代わりにしない。repository外の候補から`task_contract.py --task-file tasks/<task-name>.md --source <候補file>`で登録し、進行中taskとのfile重複があれば新規taskを停止する。既存taskの契約を上書きしない。以後のcommandは`BLUEPRINT_TASK_FILE`で同じ契約を選択し、local loopには`--task-file`を指定する。成功後に今回のstatusだけを`completed`へ変更する。詳細は`framework/rules/loop-engineering.md`に従う。

このpromptは、人間が既存のmodel propertiesを手動修正し、まだcommitしていない差分を確定済みdesignとして受け取り、Markdown生成、選択済みIaCへの反映、deploy/apply、完了確認までを一つの`infrastructure` taskで行うために使用する。新規詳細設計の作成には使用しない。

## Check applicability and finish point first

最初に依頼の対象environment／target／service、property、修復対象issueと、終了地点（model修復まで、IaCまで、AWS反映まで）を確定する。依頼に明記された範囲を再質問せず、不足する判断だけを確認する。

- humanの手動model差分をAWSへ反映する依頼だけを、以下の通常update手順で扱う。IaCまでの依頼へpreflight、change set／plan、deploy/applyを追加しない。
- humanが明示したissue修復は手動model差分を前提とするupdateと区別する。修復値を対象modelと既存IaC・parameterへ変更前に照合し、既存IaCが一致していれば確認対象とする。model修復と生成設計書・該当issueの解消だけが必要なら、design boundaryの修復contractへ対象serviceのValidation scopeとIssue remediationを記載する。手動model差分がないことを理由に修復を止めたり、IaCの同値書換えを要求しない。
- 実際にIaC変更が必要なら既存のinfrastructure boundaryに従う。model修復とIaC変更を混ぜてupdateのimmutable input制約を解除せず、別taskを自動作成・実行しない。

契約のRequired changesとAllowed pathsは必要な変更だけに絞り、既存IaCの確認対象と区別する。以下の通常updateの適用条件を満たさない依頼に、その契約・AWS許可を流用しない。明示issue修復は対象serviceの生成、依頼された対象IaCの静的検証、local loopを各一回実行して指定の終了地点で終える。task type固有checkとissue gateは省略しない。

## Unresolved issue gate

対象environment／target／serviceを確定した時点で、通常taskの開始前と再開時に`issues/<environment>/<target-directory>/issues.md`を確認し、`framework/rules/loop-engineering.md`のUnresolved issue gateを適用する。関係する全serviceについて`python framework/scripts/issue_gate.py --environment <environment> --target-directory <alias-or-account-id> --service <service-id>`を実行する。未解決issueがあれば設計質問、設計保存、IaC変更、deploy/apply、scenarioなど他taskへ進まず、対象issueと停止理由を示す。issue調査とhumanが明示した修復だけを許可し、修復taskには対象serviceだけのValidation scopeとIssue remediationを記載する。AWS mutation直前にも再確認し、既存のtask boundaryとAWS execution許可は維持する。

## Optional user input

- Authorized delete/replacement: 省略時は`none`
- AWS profile: 任意。省略時はtargetの`awsProfile`、未設定ならdefault credential chain。設定と異なる明示profileは拒否する

通常はどちらも入力不要とする。delete/replacementは対象resourceと理由が明記されている場合だけ事前承認済みとして扱う。事前承認がなくてもchange setまたはplanは作成し、未承認のdelete/replacementを検出した場合だけ`04_deploy.md`のhuman確認待ちへ進む。

## Resolve target and scope from repository state

fileを変更する前に、次の順序でtargetとscopeを特定する。

1. `git status --short`と`git diff --name-only HEAD -- model/`を確認する。
2. humanが変更した既存model propertiesのpathが`model/<environment>/<target-directory>/<service-id>.properties`に一致することを確認し、pathからenvironmentとtarget directoryを取得する。
3. 取得したenvironment／target directoryの組み合わせが正確に1件で、`project.json`のtargetと一致することを確認し、aliasがある場合はalias、常に実際のAWS account IDを取得する。手動修正済みmodel propertiesがない場合、複数targetの差分が混在する場合、または未登録targetの場合はfileを変更せず停止する。
4. 同じtargetでhumanが変更した既存model propertiesをすべてDesign scopeとする。policy／設定JSON本文はmodel rowのdocumentをinputとし、Markdown／JSON artifactの手動diffを設計値として採用しない。
5. 対応する正本service modelと、CloudFormationでは同じtargetの`cloudformation-stacks.properties`と生成済み`cloudformation-stacks.md`を確認し、`03_implement.md`の既存IaC照合とimplementation unit解決に従って変更が必要なStackName、template／parameter fileまたはTerraform root／resourceを特定する。一致するpropertyは変更しない。CloudFormationの変更済みdesignが同じaccount・regionの別stack所有resourceを参照する場合は、そのproducer stackも必要なOutput/Export追加の候補とする。
6. `04_deploy.md`のdeployment unit解決に従い、stack詳細設計からStackName、parameter file、Terraform root、resource、dependency順を特定し、Deployment scopeとする。CloudFormationでは順序と並列設定をDeployOrder、MaxConcurrentStacksから解決し、DeployOrderが未設定なら推測・migrationせず停止する。Terraformでは既存のscope・dependency解決を維持する。同じtemplateを使う別StackNameは別unitとし、変更された設計resourceを所有するstackだけをscopeへ含める。cross-stack exportが必要なproducerとconsumerを同じtaskで扱う場合は両stackをscopeへ含める。

scope外のuncommitted changeがある場合は取り込まず停止する。repository内の情報からdeployment unitを一意に特定できない場合だけ、stack名など不足している項目を一回の応答につき一つ質問する。repositoryから特定できるtarget、file path、scope全体をuserへ再入力させず、値を推測しない。
既存StackNameの削除・改名をstack詳細設計の差分から自動的にstack削除と解釈しない。対象stackの管理終了または削除が必要なら、現在のupdate phaseで実行せず対象と影響を報告して停止する。

## Read before changing files

1. `AGENTS.md`
2. `README.md`
3. 存在する場合は`tasks/<task-name>.md`。ない場合はidle状態として扱い、Create active task contractで最初に作成する。
4. `project.json`
5. `git status --short`と、repository差分から特定したDesign scopeのdiff
6. 対象の`docs/designs/<environment>/<target-directory>/*.md`と関連するJSON artifact
7. 対応する`model/<environment>/<target-directory>/*.properties`
8. `framework/prompts/codex/03_implement.md`
9. `framework/prompts/codex/04_deploy.md`
10. `framework/rules/detailed-design.md`
11. `framework/rules/model-information.md`
12. 選択済みengineに対応する`framework/rules/cloudformation.md`または`framework/rules/terraform.md`
13. `framework/rules/observed-values.md`
14. `framework/rules/loop-engineering.md`
15. 対象resourceに関係する`framework/materials/aws/*.properties`と`framework/materials/api/*.properties`および同名API設計schema
16. CloudFormationの場合は対象resourceのprovider schema

読取対象はDesign scopeのresource/propertyと参照解決に必要な箇所へ絞る。分割modelは入口indexから必要なpartだけを読む。同じtaskで確認済みの資料は、内容変更・検証失敗・未解決の依存がなければ再読しない。

`<target-directory>`は、選択targetにaliasがあればalias、なければAWS account IDとする。

## Validate human design diff

- 特定したDesign scopeは、対象environment／target directory配下でhumanが変更した既存model propertiesだけとする。
- Design scopeのmodel propertiesにhumanが作成したuncommitted diffが存在しなければ停止する。
- 特定したDesign scope外のuncommitted changeがある場合は、今回のtaskへ取り込まず停止する。
- IaCまたは生成物Markdown／JSONにtask開始前からuncommitted changeがある場合は停止する。正本model propertiesのhuman diffは許可する。
- humanが変更したintended designをこのtaskで修正、補完、巻き戻ししない。
- 詳細設計の不足、矛盾、placeholder、schema violation、未確定のhuman decisionがあれば停止する。
- 変更対象にCFn非対応の`Macie.ClassificationJob`が含まれる場合は、`03_implement.md`の実装対応確認に従い、Jobの未反映を報告する。Jobを黙って除外してupdate完了とせず、CFnへの誤変換、API実行、Custom Resource追加、旧Jobのキャンセルを行わない。

task開始時のDesign scope diffを保持し、deploy成功後のgenerated current value更新を除いて完了時まで同じであることを確認する。

## Create active task contract

Codexによる最初のrepository changeとして`tasks/<task-name>.md`を今回の対象だけを許可する内容へ新規登録する。

- Task typeは`infrastructure`とする。
- Infrastructure phaseは`update`とする。
- goalにtarget environment、aliasがある場合はalias、AWS account、自動特定したDesign scopeとDeployment scope、選択済みIaC engineを記載する。
- `Validation scope`はDesign scopeと実装・deploymentに関係するserviceを`<environment>/<target-directory>/<service-id>`で明記する。target全体へ広げない。
- AWS API executionとdeploy/applyは自動特定したDeployment scopeに限り`allowed`とする。
- Authorized delete/replacementは明示された値、入力がなければ`none`を記載する。change setまたはplan作成後にhumanが承認した場合は、同じtaskのまま対象resource、action、確認済み理由へ更新する。
- `Required changes`は一意なRequirement ID付きで、human design diffの検証、Markdown生成、IaC implementation、deployment、必要なobserved value更新を分けて記載する。
- `Acceptance checks`はDesign scope、対応するmodel、対象IaCへ`changed:`を対応付け、deployment unitへ`exists:`を対応付ける。deploy未実行や失敗をrepository fileで完了扱いにしない。
- Allowed pathsはDesign scopeのmodel properties、生成先Markdown／JSON artifact、対象IaC、`tasks/<task-name>.md`だけに限定する。別targetと`tests/**`は変更禁止とする。

## Generate Markdown and implement IaC

1. aliasがあるtargetは`framework/scripts/sync-model.py --write --environment <environment> --alias <alias> --service <service-id>`、aliasがないtargetは`framework/scripts/sync-model.py --write --environment <environment> --aws-account-id <aws-account-id> --service <service-id>`を実行し、human design diffを入力としてMarkdown／JSON artifactを生成する。同じtargetの複数対象serviceは`--service`を繰り返して一回で指定し、modelのintended designを変更しない。
2. Markdown／JSON生成失敗またはvalidation failureではdesignを修正せず停止する。
3. `03_implement.md`のimplementation unit解決とengine別local static validationに従い、自動特定したDeployment scopeに必要なIaCだけを最小変更する。CloudFormationのcross-stack参照はpreflight後にdeploy済みexportを調べるまでproducer Output/Exportとconsumer `!ImportValue`の変更を保留する。
4. IaC implementation errorは確定済みdesign内で修正可能な場合だけ最大3 iterationまで修正する。human decisionまたはdesign変更が必要なら停止する。

## Preflight and deploy

credential、deploy先account、AWS region、IaC engine、必要commandをLLMの推論で判定せず、repository rootから次を実行する。追加inputがなければ`--profile`を省略してよい。scriptはtargetの`awsProfile`を自動使用する。

aliasがあるtargetでは次を実行する。

```text
python framework/scripts/check-deploy-context.py --environment <environment> --alias <alias> [--profile <profile>]
```

aliasがないtargetでは次を実行する。

```text
python framework/scripts/check-deploy-context.py --environment <environment> --aws-account-id <12-digit-account-id> [--profile <profile>]
```

scriptが終了code 0を返した場合だけ、出力されたprofile（設定時）をすべての後続AWS実行で使用して続行する。CLI／SDKにはprofileを明示し、Terraformのprovider／AWS backendには`terraform.md`に従いprocess単位で同じ`AWS_PROFILE`を渡す。失敗時はcredential切替、account変更、check bypassを行わず停止する。secretやcredential値を表示または保存しない。

CloudFormationのcross-stack参照を同じtaskで扱う場合は、preflight後に`describe-stacks`と`list-exports`でproducer stackのOutputsとdeploy済みexportsをread-onlyで照合する。既存exportがあればその名前・値を確認してconsumer templateの参照と文字列中の該当箇所を`!ImportValue`へ変更し、static validation、change set確認、consumer deployへ進む。exportがなければproducer templateに必要なOutput/Exportだけを追加し、static validation、change set確認、producer deploy、terminal successと実際のexport確認を先に行う。その後に初めて未着手NOT_STARTEDのconsumer templateを`!ImportValue`へ変更し、`--pause-after-group`で停止した同じcontroller sessionのresumeでstatic validation、change set確認、consumer deployへ進む。controllerは準備済み・実行済みunitのIaC変更を拒否する。両stackがDeployment scopeに含まれない場合はscopeを推測で広げず停止する。

このtaskでDesign scopeから生成した対象IaCのuncommitted diffだけはdeploy対象として許可する。task開始前から存在したIaC diffまたはDeployment scope外のdiffは許可しない。

CloudFormationの宣言済み成果物配置とtemplateサイズ別送信は`cloudformation.md`のS3 deployment artifactsに従い、controllerに集約する。配置先・sourceの対応はhuman-changed stack modelをimmutable inputとして扱い、ZIPなどは事前ビルド済みfileだけを使う。元IaCを変更しない実行用copyと配置objectのhash／versionは同じrepository外sessionに固定する。未着手unitの変更だけを再検証し、準備済み／実行済みunitのsource変更は拒否する。

`04_deploy.md`のdeployment unit解決、engine別validation、change set／plan確認、未承認delete/replacementの説明付きhuman確認待ち、承認後の同じtaskと同じchange setまたは保存済みplanによる再開、CloudFormation controllerのDeployOrder group barrier・MaxConcurrentStacks queue・完了確認・failure stop ruleに従う。同じtemplateの別StackNameを統合しない。CloudFormationのchange set作成・実行をcontroller外へ分散せず、通常はcontroller内でobserved値更新とsync-modelを行い全DeployOrderを継続する。producer成功後に未着手consumerのIaC変更が必要な明示update用途だけ`--pause-after-group`で同期後にGROUP_COMPLETEを返し、IaC変更後に同じsessionをresumeする。最終groupは追加resumeなしでCOMPLETEとなる。scope超過、account/region不一致、credential/permission不足、またはdeployment failureでは新たなunitを起動せず、実行中のCloudFormation stackの終状態を確認して停止する。未承認のdelete/replacementだけはfailureとして終了せずhuman確認待ちにする。

deploy/applyが成功した場合:

1. terminal successとresource存在を確認する。
2. 必要な非ARN generated current valueだけをmodelのobserved namespaceへ反映し、humanが変更したintended designは変更しない。
3. 上記のservice指定付き`sync-model.py --write`を、observed valueを更新したserviceだけに実行する。

deploy完了status、resource存在、observed value収集をapplication behaviorの検証またはscenario PASSとして扱わない。

## Verify and finish

1. task開始時のhuman design diffと比較し、generated current value以外のintended designをCodexが変更していないことを確認する。
2. 選択済みIaCのsyntax/static validation結果を確認する。成功後に対象IaC・parameter・依存入力が変わっていなければ再実行しない。deploy phaseの必須validation・AWS安全確認は維持する。
3. `python framework/scripts/blueprint-loop.py --mode task`を一回実行する。差分checkもこのloopに含まれる。

成功した対象検証の後に追加の全体検証を行わない。生成・検証の再実行は入力変更、新しい失敗、未解決の懸念がある場合だけとし、tool待機timeoutでは同じ実行を追跡する。

target、Design scope、表示生成、IaC変更、deployment unitとdependency順、plan/change set summary、human確認待ちと承認結果、deploy完了status、observed value更新、blockerを完了報告に記載する。verification outputをrepositoryへ保存しない。

scenario、scenario result、別target、次taskを変更、作成、実行しない。application behaviorの検証が必要な場合は、humanが別taskとして`framework/prompts/codex/06_scenario-test.md`を使用する。
