# Terraform Rules

- Terraformは`infrastructure` taskでのみ作成・変更・実行する。
- infrastructure taskは承認済みの詳細設計とservice modelをinputとして読み取る。
- intended designの変更が必要な場合は値を補完せず停止し、別の`design` taskが必要であることを報告する。
- active projectと対象environment/AWS accountがTerraformを選択した場合だけ使用する。
- 1 environment/AWS accountは1 IaC engineだけで管理する。
- reusable moduleは`infra/terraform/modules/`、AWS account compositionは`infra/terraform/environments/<environment>/<aws-account-id>/`に置く。
- 未使用infrastructureを先回りして生成しない。
- 詳細設計のidentifier参照はMarkdown linkのanchorからlogical IDを解決し、対応するTerraform resource attribute参照を生成する。link表示textの`PENDING_DEPLOY`またはphysical IDをconfigurationへ直書きしない。
- 後続resourceまたはroot moduleが必要とするcatalog `IDENTIFIER_OUTPUT`はnon-sensitive `output`としてresource attributeから公開する。generated ARNはoutput収集またはobserved value永続化の対象にしない。

## Validation and execution

- `implement` phaseは`terraform fmt -check`、freshな`TF_DATA_DIR`を使った`terraform init -backend=false`、`terraform validate`を実行し、plan、apply、AWS APIを実行しない。
- `deploy` phaseはIaCを変更せず、`terraform fmt -check`、`terraform validate`、repository外へ保存する`terraform plan`を実行する。
- `update` phaseはhumanがtask開始前に手動修正した詳細設計を変更せずmodelを同期し、implement phaseのlocal validation後、repository外へ保存するplanを確認してapplyする。このphase内で生成した対象IaCのuncommitted diffだけをapply対象として許可する。
- deploy phaseでIaC修正が必要な場合は変更せず停止する。
- plan後にrepository-levelのmandatory human stopは設けない。
- applyはdeployまたはupdate phaseのactive promptが明示的に許可し、plan scopeがpromptと一致するときだけ保存済みplanを実行する。
- active promptが対象を限定している場合は、implement phaseでは指定environment/module/resourceだけを変更し、deployまたはupdate phaseでは指定対象だけをapplyして終了できる。
- unauthorized delete/replacement、wrong workspace/account/region、missing input、sensitive output、plan failure、intended designの不足で停止する。
- state fileとplan binaryをcommitしない。
- remote stateはaccess control、locking、encryption、backupを備える構成としてproject designに記録する。
- secretを出力せず、generated ARNをobserved valueとして保存しない。
- existing environmentのCloudFormation/Terraform切替はdedicated migration/import taskとし、normal updateで行わない。

apply後は`framework/rules/observed-values.md`の優先順位で必要なnon-ARN identifierをTerraform output、必要な場合だけstateから取得し、詳細設計の正式なidentifier output rowと全参照元を更新してservice modelを再生成する。local loop後にinfrastructure taskを終了し、次のmodule、environment、scenario-test taskへ自動的に進まず、scenario testまたはscenario evidenceを作成・更新しない。
