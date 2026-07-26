# Terraform Rules

- active task/project が Terraform を選択した場合だけ使用する。
- 1 environment は 1 IaC engine だけで管理する。
- detailed design、LLM design information、Terraform の順に変更する。
- reusable module は `infra/terraform/modules/`、environment composition は `infra/terraform/environments/<environment>/` に置く。
- 未使用 infrastructure を先回りして生成しない。

## Validation and execution

- `terraform fmt -check`、`terraform validate`、`terraform plan` を必須とする。
- plan 後に repository-level の mandatory human stop は設けない。
- apply は active ChatGPT task prompt が明示的に許可し、plan scope が prompt と一致するときだけ実行する。
- unauthorized delete/replacement、wrong workspace/account/region、missing input、sensitive output、plan failure で停止する。
- state file と plan binary を commit しない。
- remote state は access control、locking、encryption、backup を備える構成として project design に記録する。
- secret を出力せず、generated ARN を post-deploy actual として保存しない。
- existing environment の CloudFormation/Terraform 切替は dedicated migration/import task とし、normal update で行わない。

apply 後は必要な非 ARN actual を更新し、scenario test を実行して evidence を記録する。
