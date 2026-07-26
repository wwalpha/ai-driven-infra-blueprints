# LLM Design Information Rules

- human-readable current design は `docs/designs/` に置く。
- machine-readable intended-design mirror は `llm/designs/` に置く。
- machine-readable current actual values は `llm/actuals/<environment>/` に置く。
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
- Load Balancer、Target Group、Listener は `load-balancer.properties` に置く。
- Route Table、Route、association は `route-table.properties` に置く。
- S3 Bucket と Bucket Policy は `s3-bucket.properties` に置く。
- intended design と current actual value を分離する。
- generated ARN を `llm/actuals/` に保存しない。
- AWS managed-policy ARN のような既存／human-provided design input は必要な場合に `llm/designs/` へ残してよい。
