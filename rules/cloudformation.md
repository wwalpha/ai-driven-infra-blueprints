# CloudFormation Rules

- active task/project が CloudFormation を選択した場合だけ使用する。
- detailed design、LLM design information、CloudFormation の順に変更する。
- nested stack は使用しない。
- stack/template boundary は AWS service 単位ではなく、change unit、rollback unit、dependency direction、deploy responsibility で決める。
- `1 template = 1 deploy responsibility` を default とする。
- cross-stack reference は downstream が必要とする stable value だけを公開し、不要な coupling を避ける。
- authorized operation は AWS CLI で行う。

## Validation and execution

1. syntax/static check と `aws cloudformation validate-template` を実行する。
2. change set または同等の change summary を作成して scope、delete、replacement を確認する。
3. repository-level の mandatory human stop は設けない。
4. active task prompt が deploy/update を許可し、change scope が prompt と一致する場合は execution へ進む。

次の場合は停止する。

- validation failure
- required input missing
- AWS account または region mismatch
- task prompt が許可していない delete/replacement

deploy/update 後は必要な非 ARN actual だけを収集し、design と LLM actuals を更新し、scenario test と evidence 記録まで行う。design-only または governance task では、CloudFormation file が存在するだけの理由で AWS API を呼ばない。
