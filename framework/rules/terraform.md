# Terraform Rules

- Terraformは`infrastructure` taskでのみ作成・変更・実行する。
- infrastructure taskは承認済みの詳細設計とservice modelをinputとして読み取る。
- intended designの変更が必要な場合は値を補完せず停止し、別の`design` taskが必要であることを報告する。
- active projectと対象environment/AWS accountがTerraformを選択した場合だけ使用する。
- 1 environment/AWS accountは1 IaC engineだけで管理する。
- reusable moduleは`infra/terraform/modules/`、AWS account compositionは`infra/terraform/environments/<environment>/<aws-account-id>/`に置く。
- 未使用infrastructureを先回りして生成しない。

## Validation and execution

- `implement` phaseは`terraform fmt -check`、freshな`TF_DATA_DIR`を使った`terraform init -backend=false`、`terraform validate`を実行し、plan、apply、AWS APIを実行しない。
- `deploy` phaseはIaCを変更せず、`terraform fmt -check`、`terraform validate`、repository外へ保存する`terraform plan`を実行する。
- deploy phaseでIaC修正が必要な場合は変更せず停止する。
- plan後にrepository-levelのmandatory human stopは設けない。
- applyはdeploy phaseのactive promptが明示的に許可し、plan scopeがpromptと一致するときだけ保存済みplanを実行する。
- active promptが対象を限定している場合は、implement phaseでは指定environment/module/resourceだけを変更し、deploy phaseでは指定対象だけをapplyして終了できる。
- unauthorized delete/replacement、wrong workspace/account/region、missing input、sensitive output、plan failure、intended designの不足で停止する。
- state fileとplan binaryをcommitしない。
- remote stateはaccess control、locking、encryption、backupを備える構成としてproject designに記録する。
- secretを出力せず、generated ARNをobserved valueとして保存しない。
- existing environmentのCloudFormation/Terraform切替はdedicated migration/import taskとし、normal updateで行わない。

apply後は詳細設計内のgenerated current valueを更新してservice modelを再生成し、local loop後にinfrastructure taskを終了する。次のmodule、environment、scenario-test taskへ自動的に進まず、scenario testまたはscenario evidenceを作成・更新しない。
