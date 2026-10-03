# propertiesとAWS SDKの比較

## Task contract
- Task type: `governance`
- Target: 全serviceのproperties ↔ AWS SDK比較
- Goal: 1サービス1ファイルの取得・変換処理と共通比較処理を実装し、毎回AIを使わず設計値とAWS現在値の差を検出する。

## Validation scope
- `framework`

## Required changes
- [R1] 共通entrypoint、既存properties reader・catalog・target解決の再利用、比較、JSON結果を実装する。単一environment/target/serviceと明示--allを提供する。
- [R2] 全28serviceを1service1fileで実装する。全resource type、grouped child、選択keyのSDK取得・入力・応答箇所・意味に沿った正規化を明記する。
- [R3] 現在の全service/resource type/keyを対応済み、API仕様上取得不能、local metadataへ分類し、未実装は失敗させる。viewcard-code全target/modelは一覧とcoverageのread-only参照とする。
- [R4] 全serviceのSDK取得と一致・不一致・不存在・取得失敗、共通pagination/profile/account/分割model/参照/正規化/未実装/部分失敗を実AWSなしで回帰検証する。consumer modelをfixtureへコピーしない。
- [R5] issuesスキルへSDK比較の差分だけをAI調査・記録する運用を記載し、比較用boto3依存を明記する。

## Acceptance checks
- [R1] `exists:framework/scripts/check-model-aws.py`
- [R2] `exists:framework/scripts/aws-compare-services/athena.py`
- [R2] `exists:framework/scripts/aws-compare-services/cloudformation-stacks.py`
- [R2] `exists:framework/scripts/aws-compare-services/cloudtrail.py`
- [R2] `exists:framework/scripts/aws-compare-services/cloudwatch-logs.py`
- [R2] `exists:framework/scripts/aws-compare-services/codebuild.py`
- [R2] `exists:framework/scripts/aws-compare-services/codecommit.py`
- [R2] `exists:framework/scripts/aws-compare-services/codepipeline.py`
- [R2] `exists:framework/scripts/aws-compare-services/config.py`
- [R2] `exists:framework/scripts/aws-compare-services/data-firehose.py`
- [R2] `exists:framework/scripts/aws-compare-services/ec2.py`
- [R2] `exists:framework/scripts/aws-compare-services/eventbridge.py`
- [R2] `exists:framework/scripts/aws-compare-services/glue.py`
- [R2] `exists:framework/scripts/aws-compare-services/guardduty.py`
- [R2] `exists:framework/scripts/aws-compare-services/iam.py`
- [R2] `exists:framework/scripts/aws-compare-services/kms.py`
- [R2] `exists:framework/scripts/aws-compare-services/lambda.py`
- [R2] `exists:framework/scripts/aws-compare-services/macie.py`
- [R2] `exists:framework/scripts/aws-compare-services/mwaa.py`
- [R2] `exists:framework/scripts/aws-compare-services/quicksight.py`
- [R2] `exists:framework/scripts/aws-compare-services/route53.py`
- [R2] `exists:framework/scripts/aws-compare-services/s3.py`
- [R2] `exists:framework/scripts/aws-compare-services/secrets-manager.py`
- [R2] `exists:framework/scripts/aws-compare-services/security-hub.py`
- [R2] `exists:framework/scripts/aws-compare-services/security_group.py`
- [R2] `exists:framework/scripts/aws-compare-services/sqs.py`
- [R2] `exists:framework/scripts/aws-compare-services/transit-gateway.py`
- [R2] `exists:framework/scripts/aws-compare-services/vpc.py`
- [R2] `exists:framework/scripts/aws-compare-services/vpc-endpoint.py`
- [R3] `exists:framework/scripts/check-model-aws.checks.py`
- [R4] `exists:framework/scripts/check-model-aws.checks.py`
- [R5] `changed:.agents/skills/issues/SKILL.md`

## Allowed paths
- `tasks/active.md`
- `framework/scripts/check-model-aws.py`
- `framework/scripts/aws-compare-services/*.py`
- `framework/scripts/check-model-aws.checks.py`
- `framework/scripts/requirements-aws-compare.txt`
- `.agents/skills/issues/SKILL.md`

## Implementation contract
- desired.*が期待値。observed.*は確認済みidentifierの特定だけに使用する。CREATE/IMPORT、親子所属を維持する。
- 確定名称、確認済みidentifier、設計参照で特定し、推測しない。曖昧なidentifier、未確定値、取得失敗を一致にしない。
- 同一実行/接続先でAPI応答を再利用し、一覧は全ページ取得する。SDK paginatorがあれば使用する。
- account/region/target awsProfileを守り、profile不一致を接続前に拒否する。STS account一致確認後にservice APIを呼ぶ。read-only取得だけを実装し、secret値取得、mutation、AI呼出しを実装しない。
- 型/boolean/数値/JSON/default/省略/配列/tag/policy/参照を意味に沿って比較する。KMS同一resourceはSDK確認で正規化し、ARNをmodelへ保存しない。
- 結果はenvironment/target/service/resource/key/設計値/AWS値/model根拠/APIを含む。差分/不存在/取得失敗/未確定/取得不能を分け、一つの取得失敗を影響key一覧へ集約する。
- 一致/不一致/未完了を終了状態で区別する。取得不能/未実装があれば全体一致にしない。local metadataを明示する。
- stack存在/状態をSDKで確認し、template/parameters/deployOrder等はlocal metadataとする。旧properties↔CFn設定自動比較を再実装しない。

## Out of scope
- viewcard-code変更/同期、既存issue更新、model/設計/IaC/project変更、実AWS API、deploy/apply、push。
- 比較機能からAI調査・issue保存・修復へ進まない。
- 新しいworktreeで実施し、検証完了後に必要なローカルcommitを作成してmasterへmergeする。humanが明示的に許可済み。pushしない。

## Completion
- 回帰scriptで全service/resource type/keyの実対応を検証し、file存在だけで完了にしない。
- `python3 framework/scripts/blueprint-loop.py --mode task`をframework scopeで完了する。
- 完了報告にservice一覧、type/key対応件数、仕様上取得不能な項目、回帰結果を記載する。実AWS比較は未実行とし、properties/CFn/AWS一致を確認したと報告しない。
