# Terraform Rules

- Terraformは`infrastructure` taskでのみ作成・変更・実行する。
- infrastructure taskは承認済みの詳細設計とservice modelをinputとして読み取る。
- intended designの変更が必要な場合は値を補完せず停止し、別の`design` taskが必要であることを報告する。
- active projectと対象environment/target directoryがTerraformを選択した場合だけ使用する。
- 1 environment/AWS accountは1 IaC engineだけで管理し、同じAWS account IDを持つalias間でもengineを統一する。
- aliasなしの共通moduleは`infra/terraform/modules/`、alias別moduleは`infra/terraform/modules/<alias>/`に置く。同じaliasのmoduleをenvironment間で共用し、異なるaliasのmoduleを共用しない。
- target固有root、backend、state設定は`infra/terraform/environments/<environment>/<target-directory>/`に置く。target directoryはaliasがあればalias、なければAWS account IDとする。
- 未使用infrastructureを先回りして生成しない。
- 詳細設計のidentifier参照はMarkdown linkのanchorからlogical IDを解決し、対応するTerraform resource attribute参照を生成する。link表示textの`PENDING_DEPLOY`またはphysical IDをconfigurationへ直書きしない。
- 後続resourceまたはroot moduleが必要とするcatalog `IDENTIFIER_OUTPUT`はnon-sensitive `output`としてresource attributeから公開する。generated ARNはoutput収集またはobserved value永続化の対象にしない。

## Validation and execution

- `implement` phaseは`terraform fmt -check`、freshな`TF_DATA_DIR`を使った`terraform init -backend=false`、`terraform validate`を実行し、plan、apply、AWS APIを実行しない。
- `deploy` phaseはIaCを変更せず、`terraform fmt -check`、`terraform validate`、repository外へ保存する`terraform plan`を実行する。
- `update` phaseはhumanがtask開始前に手動修正した詳細設計を変更せずmodelを同期し、implement phaseのlocal validation後、repository外へ保存するplanを確認してapplyする。このphase内で生成した対象IaCのuncommitted diffだけをapply対象として許可する。
- deploy phaseでIaC修正が必要な場合は変更せず停止する。
- 全planを一律停止するhuman reviewは設けない。保存済みplanに未承認のdestroy/replacementがある場合だけ`framework/prompts/codex/04_deploy.md`に従って説明付きhuman確認待ちにする。
- applyはdeployまたはupdate phaseのactive promptが明示的に許可し、plan scopeがpromptと一致するときだけ保存済みplanを実行する。
- active promptが対象を限定している場合は、implement phaseでは指定environment/module/resourceだけを変更し、deployまたはupdate phaseでは指定対象だけをapplyして終了できる。
- 保存済みplanのresource change actionにdeleteを含む変更をdestroy/replacementの確認対象とする。未承認の場合はdeployment failureまたはtask完了として扱わず、applyせずにhuman確認待ちにする。
- human承認後は同じtaskで同じ保存済みplanを再確認し、承認対象のresource address、resource type、actionが一致する場合だけそのplan binaryをapplyする。plan binaryが失われた、再作成された、または内容が変わった場合は以前の承認を使用せず再確認する。
- 一部の変更だけが承認された場合は保存済みplanをapplyしない。configuration修正またはresource保持が必要な場合は現在のdeploy/update phaseでIaCを変更せず停止する。
- wrong workspace/account/region、missing input、sensitive output、plan failure、intended designの不足、またはdestroy/replacementのactionを確定できない場合は停止する。
- state fileとplan binaryをcommitしない。
- remote stateはaccess control、locking、encryption、backupを備える構成としてproject designに記録する。
- secretを出力せず、generated ARNをobserved valueとして保存しない。
- existing environmentのCloudFormation/Terraform切替はdedicated migration/import taskとし、normal updateで行わない。

apply後は`framework/rules/observed-values.md`の優先順位で必要なnon-ARN identifierをTerraform output、必要な場合だけstateから取得し、詳細設計の正式なidentifier output rowと全参照元を更新してservice modelを再生成する。local loop後にinfrastructure taskを終了し、次のmodule、environment、scenario-test taskへ自動的に進まず、scenario testまたはscenario evidenceを作成・更新しない。
