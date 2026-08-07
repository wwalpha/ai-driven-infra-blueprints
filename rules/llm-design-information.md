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

```properties
<resourceGroup>.<logicalId>.<property>=<value>
```

resource reference は deploy 前の physical AWS ID ではなく stable logical reference を使う。

```properties
natGateway.NATA01.subnetRef=subnet.PUBLICAZ1
routeTable.PUBLICRT01.defaultRouteTargetRef=internetGateway.WEBNGINXIGW
```

## Grouping

- detailed-design file と LLM file の group を一致させる。
- human design resource group ごとに同じ stem の Markdown と properties file を一つずつ置く。
- related child resource は親と同じ resource group file に置いてよい。
- intended design と current actual value を分離する。
- generated ARN を `llm/actuals/` に保存しない。
- AWS managed-policy ARN のような既存／human-provided design input は必要な場合に `llm/designs/` へ残してよい。
- referenceは同じenvironment/AWS account内のstable logical referenceをdefaultとする。cross-account referenceは所有AWS accountと接続方式をhuman designに明示し、値を推測しない。
