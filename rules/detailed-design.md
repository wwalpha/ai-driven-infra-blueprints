# Detailed Design Rules

## Task boundary

- `design` taskはintended designと対応するLLM design mirrorを更新し、local validation後に終了する。IaC、actuals、scenarioへ自動的に進まない。
- `infrastructure` taskはintended designを変更しない。deploy/apply成功後のgenerated current valueだけを詳細設計へ反映できる。
- designの不足または変更が必要な場合、infrastructure taskは停止して別のdesign taskを要求する。

## Grouping principle

詳細設計の grouping unit は human design resource group とする。CloudFormation resource type 単位でも AWS service namespace 単位でもない。

- 同じ resource group の複数 instance は同じ Markdown file に記載する。
- 関連 child resource は同じ file に置いてよいが、別 heading と別 table を使用できる。
- 同じ file にあることは、同じ table にまとめることを意味しない。
- fileは`docs/designs/<environment>/<aws-account-id>/<resource-group>.md`に置く。
- file nameはresource groupを表すlower-kebab-caseとし、対応する`llm/designs/<environment>/<aws-account-id>/<resource-group>.properties`と相対path及びstemを一致させる。
- resource group は active task で選択した resource と運用上のまとまりから決め、validator や blueprint が固定一覧を要求しない。
- 未使用 resource group の空 design file を作らない。
- 同じresource groupでもenvironment/AWS accountが異なる場合は別fileとして明示する。

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
- anchor は lower-case resource group と lower-case logical ID を `-` で結ぶ。
- 別 file の例: `[RESOURCE01](resource-group.md#resource-group-resource01)`。
- 同じ file の例: `[CHILD01](#child-group-child01)`。
- file と anchor の存在を local loop で検証する。

## Generated values and deployment state

- deploy 前の generated current value は `PENDING_DEPLOY` と表示する。
- desired resource があるが current environment を teardown 済みの場合は `DeploymentState` などの row を `NOT_DEPLOYED` とする。historical physical ID を current ID として残さない。
- deploy / apply 後は `PENDING_DEPLOY` を current value に置き換え、`Source / Comment` に task ID を記録する。
- destroy後はcurrent physical valueを削除し、generated fieldを`PENDING_DEPLOY`に戻す。
- old physical valueはGit履歴とAWS/IaC deployment historyで追跡し、詳細設計やscenario evidenceへ保存しない。
- 全候補 field を並べた mandatory な別 actual-values table は作らない。必要な actual は該当 resource/component table に置く。
