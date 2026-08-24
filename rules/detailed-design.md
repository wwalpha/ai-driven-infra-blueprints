# Detailed Design Rules

## Task boundary

- `design` taskはintended designと対応するLLM design mirrorを更新し、local validation後に終了する。IaC、actuals、scenarioへ自動的に進まない。
- `infrastructure` taskはintended designを変更しない。deploy/apply成功後のgenerated current valueだけを詳細設計へ反映できる。
- designの不足または変更が必要な場合、infrastructure taskは停止して別のdesign taskを要求する。

## AWS service ownership boundary

詳細設計のfile grouping unitは、security boundaryやIAM Permissions Boundaryではなく、人間が認識するAWS serviceごとの責務を表すAWS service ownership boundaryとする。一つのdesign fileは一つのAWS serviceだけを所有する。

- fileは`docs/designs/<environment>/<aws-account-id>/<service-id>.md`に置く。
- Service IDはlower-kebab-caseとし、file stemおよび対応する`llm/designs/<environment>/<aws-account-id>/<service-id>.properties`と一致させる。
- 同じAWS serviceに属する複数resource typeとinstanceは同じfileに置いてよい。
- 運用上関連するだけの別AWS serviceを同じfileへ入れない。CloudFormation resource namespaceだけでgroupingを決めない。
- child componentは親resourceと同じAWS serviceに属する場合だけ同じfileに置いてよい。別AWS serviceのresourceはchild componentとして扱わない。
- IAM RoleとPolicyは利用先service専用でもIAM service fileへ置く。
- CloudWatch Logs resourceは利用元serviceではなくCloudWatch Logs service fileへ置く。
- VPC Flow LogはAmazon VPCのservice fileへ置き、IAM RoleとLog Groupをcross-file referenceで参照する。
- service間dependencyはfile統合ではなく、relative Markdown linkとLLM stable logical referenceで表す。
- 未使用serviceの空design fileを作らない。
- design file boundaryとCloudFormation stack/template boundaryは別概念とする。

generic validatorがservice ownershipを判断するため、各Markdownには次のmachine-readable service metadataだけを正確に1件ずつ記載する。

```md
- Design service ID: `vpc`
- Owned catalog resource types: `EC2.VPC`, `EC2.Subnet`, `EC2.FlowLog`
```

- Owned catalog resource typesには`materials/aws/*.properties`に存在し、このservice fileが所有するresource typeだけを記載する。
- 同じenvironment/AWS account内で同じcatalog resource typeを複数service fileが所有してはいけない。

## Markdown structure

保存対象Markdownは、原則としてH1 title、service metadata、resourceごとのexplicit anchor、resource heading、resource-detail tableだけで構成する。tableだけでは表現できない場合に限り、必要最小限のimplementation noteを追加してよい。

- catalog-backed resource headingは`## <catalog-resource-type>: <logical-id>`とする。
- `Environment`、`AWS account ID`、`AWS region`、`Purpose`、`Deployment state`をfile metadataとして記載しない。これらは`project-topology.json`、`docs/system-overview.md`、active task、`llm/actuals/**`の該当する正本を参照する。
- `Design decisions`、`Out of scope`、`Generated values`または同義の日本語sectionを作らない。
- 確定済みの設計値は該当resource/component tableへ記載する。
- 対象外事項はactive taskまたはchatの完了報告だけに記載する。

## Resource-detail table

すべての resource-detail table は次の header と alignment row を正確に使う。

```md
| No. | Property | Value | Source / Comment |
| ---: | --- | --- | --- |
```

- 各 table の row は 1 から連番にする。
- 1 file に複数 resource heading と table を置いてよい。
- Listener、Route、association、UserData、Bucket Policy などの child component は独立 table にしてよい。
- configurable AWS property で `materials/aws/` との mapping が明確な場合、`Property` は catalog と同じ spelling を使う。
- generated value や derived documentation field は、catalog にない明確な human-readable name を使ってよい。
- catalog の全 field を掲載せず、選択済みで必要な design field だけを載せる。
- IaC template path を AWS resource property のように table に入れない。implementation note は table 外の prose section に書く。

## Links and anchors

- 関連 resource は `Value` column の Markdown link で表す。
- link は relative path を使う。
- renderer 自動生成だけに依存せず、resource heading の直前に explicit HTML anchor を置く。
- anchorはlower-case Service IDとlower-case logical IDを`-`で結ぶ。
- 別fileの例: `[FLOWLOGROLE01](iam.md#iam-flowlogrole01)`。
- 同じfileの例: `[FLOWLOG01](#vpc-flowlog01)`。
- file と anchor の存在を local loop で検証する。

## Generated values and deployment state

- 必要なnon-ARN generated current identifierは独立sectionではなく、該当resource tableの個別行にhuman-readableなresource固有名で記載する。例は`VPC ID`、`Subnet ID`、`Flow Log ID`とする。
- deploy前は値を`PENDING_DEPLOY`、`Source / Comment`を`Generated current value`とする。
- infrastructure taskのdeploy/apply成功後だけ`PENDING_DEPLOY`をcurrent valueへ更新し、`Source / Comment`の`Generated current value`に続けて更新根拠を記録する。
- destroy後はcurrent physical valueを削除し、generated identifier rowを`PENDING_DEPLOY`へ戻す。
- human-selected nameなど既存propertyがそのままcurrent identifierになる場合は、重複するgenerated identifier rowを作らない。
- local validatorはcatalog propertyのleaf名が`<resource-name>Name`または`<resource-name>Identifier`で確定値を持つ場合をhuman-selected current identifierとして扱う。例は`RoleName`と`LogGroupName`とする。
- generated ARNは詳細設計にも`llm/actuals/**`にも永続化しない。
- old physical valueはGit履歴とAWS/IaC deployment historyで追跡し、詳細設計やscenario evidenceへ保存しない。
- `llm/designs/**`はintended designとstable referenceだけを保持し、必要なmachine-readable current IDは`llm/actuals/**`へ置く。
