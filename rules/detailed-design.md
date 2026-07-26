# Detailed Design Rules

## Grouping principle

詳細設計の grouping unit は human design resource group とする。CloudFormation resource type 単位でも AWS service namespace 単位でもない。

- 同じ resource group の複数 instance は同じ Markdown file に記載する。
- 関連 child resource は同じ file に置いてよいが、別 heading と別 table を使用できる。
- 同じ file にあることは、同じ table にまとめることを意味しない。

| Detailed-design file | Content grouping |
| --- | --- |
| `vpc.md` | VPC only |
| `internet-gateway.md` | Internet Gateway only |
| `elastic-ip.md` | Elastic IP only |
| `nat-gateway.md` | NAT Gateway only |
| `subnet.md` | Subnet only |
| `route-table.md` | Route Table, Route, and Subnet Route Table Association |
| `security-group.md` | Security Group plus its ingress/egress rules |
| `iam-role.md` | IAM Role and its policies/attachments |
| `instance-profile.md` | IAM Instance Profile |
| `ec2.md` | EC2 Instance, its UserData, and instance-local settings |
| `load-balancer.md` | Load Balancer, Target Group, and Listener; separate sections/tables as appropriate |
| `s3-bucket.md` | S3 Bucket and Bucket Policy; separate sections/tables as appropriate |

current sample で未使用の resource group に空 design file を作らない。

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

`docs/designs/naming-rules.md` は project-wide support document であり、reference table のすべてをこの4列に変換する必要はない。

## Links and anchors

- 関連 resource は `Value` column の Markdown link で表す。
- link は relative path を使う。
- renderer 自動生成だけに依存せず、resource heading の直前に explicit HTML anchor を置く。
- anchor は lower-case resource group と lower-case logical ID を `-` で結ぶ。例: `<a id="vpc-webnginxvpc"></a>`。
- 別 file の例: `[WEBNGINXVPC](vpc.md#vpc-webnginxvpc)`。
- 同じ file の例: `[TG01](#target-group-tg01)`。
- file と anchor の存在を local loop で検証する。

## Generated values and deployment state

- deploy 前の generated current value は `PENDING_DEPLOY` と表示する。
- desired resource があるが current environment を teardown 済みの場合は `DeploymentState` などの row を `NOT_DEPLOYED` とする。historical physical ID を current ID として残さない。
- deploy / apply 後は `PENDING_DEPLOY` を current value に置き換え、`Source / Comment` に task ID を記録する。
- destroy 後は current physical value を削除し、generated field を `PENDING_DEPLOY` に戻す。old value は historical evidence だけに残す。
- 全候補 field を並べた mandatory な別 actual-values table は作らない。必要な actual は該当 resource/component table に置く。
