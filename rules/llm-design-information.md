# LLM Design Information Rules

- human-readable current designは`docs/designs/<environment>/<aws-account-id>/`に置く。
- machine-readable intended-design mirrorは`llm/designs/<environment>/<aws-account-id>/`に置く。
- machine-readable current actual valuesは`llm/actuals/<environment>/<aws-account-id>/`に置く。
- 旧 design 配下の LLM helper directory は obsolete であり、再作成を禁止する。
- Markdown design が human-readable current-design source of truth である。
- `llm/designs/` は同期 mirror であり、design value を独自に発明・override しない。
- Markdown と LLM information の conflict は error とし、片方を黙って採用しない。
- Markdown と関連 LLM design information は同じ coherent logical change で更新する。
- Markdownの構造、service grouping、generated identifier rowは`rules/detailed-design.md`を正本とする。

## Format

UTF-8 の `.properties` file を使い、基本形は次とする。

対応するMarkdownと同じservice ownership metadataを正確に1件ずつ記載する。

```properties
designService.vpc.serviceId=vpc
designService.vpc.ownedCatalogResourceTypes=EC2.VPC,EC2.Subnet,EC2.FlowLog
```

```properties
<resourceGroup>.<logicalId>.<property>=<value>
```

resource reference は deploy 前の physical AWS ID ではなく stable logical reference を使う。

```properties
natGateway.NATA01.subnetRef=subnet.PUBLICAZ1
routeTable.PUBLICRT01.defaultRouteTargetRef=internetGateway.WEBNGINXIGW
```

policy JSONは本文を複製せず、対応するhuman design target rootからのrelative pathを保持する。

```properties
iamRole.VPCFLOWLOGROLE01.assumeRolePolicyDocumentPath=iam/vpcflowlogrole01-trust-policy.json
iamRole.VPCFLOWLOGROLE01.inlinePolicyName=VPCFlowLogsToCloudWatchLogs
iamRole.VPCFLOWLOGROLE01.inlinePolicyDocumentPath=iam/vpcflowlogrole01-vpc-flow-logs-to-cloud-watch-logs.json
vpcEndpoint.S3ENDPOINT01.policyDocumentPath=vpc/s3endpoint01-policy-document.json
```

IAM Roleのinline policyでは、同じstable prefixを持つ`<policy-key>PolicyName`と`<policy-key>PolicyDocumentPath`が同じpolicyを表す。`PolicyName`を明示し、その値を`rules/detailed-design.md`の規約でartifact名へ変換する。複数inline policyは重複しない`<policy-key>`で別々のpairとして記録し、`PolicyName`が未確定ならpathを推測しない。

## Grouping

- AWS service ownership boundaryごとにMarkdownとpropertiesを一対一対応させ、同じService ID、相対path、file stemを使う。
- `designService.<service-id>.serviceId`のkeyとvalueはfile stemと一致させる。
- `designService.<service-id>.ownedCatalogResourceTypes`はMarkdownと同じresource typeを同じ順序でcomma区切りにする。
- 同じAWS serviceのrelated child resourceだけを同じproperties fileに置いてよい。
- 別serviceのresource referenceは`<resourceGroup>.<logicalId>`形式のstable logical referenceを使用する。
- 別serviceのdesign valueを参照元properties fileへ複製しない。
- `*PolicyPath`と`*PolicyDocumentPath`は対応するservice directory内の有効なJSON design artifactを参照する。
- `llm/designs/**`はintended design、service ownership、stable logical referenceだけを保持する。Markdownのgenerated current identifier rowやcurrent physical valueは複製しない。
- current physical valueとtarget/collection metadataは`llm/actuals/**`へ分離する。
- generated ARN を `llm/actuals/` に保存しない。
- AWS managed-policy ARN のような既存／human-provided design input は必要な場合に `llm/designs/` へ残してよい。
- referenceは同じenvironment/AWS account内のstable logical referenceをdefaultとする。cross-account referenceは所有AWS accountと接続方式をhuman designに明示し、値を推測しない。
