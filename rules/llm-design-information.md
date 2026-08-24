# LLM Design Information Rules

- human-readable current designは`docs/designs/<environment>/<aws-account-id>/`に置く。
- machine-readable intended-design mirrorは`llm/designs/<environment>/<aws-account-id>/`に置く。
- machine-readable current actual valuesは`llm/actuals/<environment>/<aws-account-id>/`に置く。
- 旧 design 配下の LLM helper directory は obsolete であり、再作成を禁止する。
- Markdown design が human-readable current-design source of truth である。
- `llm/designs/` は同期 mirror であり、design value を独自に発明・override しない。
- Markdown と LLM information の conflict は error とし、片方を黙って採用しない。
- Markdown と関連 LLM design information は同じ coherent logical change で更新する。

## Format

UTF-8 の `.properties` file を使い、基本形は次とする。

file先頭に対応するMarkdownと同じservice metadataを正確に1件ずつ記載する。

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

## Grouping

- AWS service boundaryごとにMarkdownとpropertiesを一対一対応させ、同じService ID、相対path、file stemを使う。
- `designService.<service-id>.serviceId`のkeyとvalueはfile stemと一致させる。
- `designService.<service-id>.ownedCatalogResourceTypes`はMarkdownと同じresource typeを同じ順序でcomma区切りにする。
- 同じAWS serviceのrelated child resourceだけを同じproperties fileに置いてよい。
- 別serviceのresource referenceは`<resourceGroup>.<logicalId>`形式のstable logical referenceを使用する。
- 別serviceのdesign valueを参照元properties fileへ複製しない。
- intended design と current actual value を分離する。
- generated ARN を `llm/actuals/` に保存しない。
- AWS managed-policy ARN のような既存／human-provided design input は必要な場合に `llm/designs/` へ残してよい。
- referenceは同じenvironment/AWS account内のstable logical referenceをdefaultとする。cross-account referenceは所有AWS accountと接続方式をhuman designに明示し、値を推測しない。
