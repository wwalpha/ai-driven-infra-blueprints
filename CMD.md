下記前提と設定値で、この repo の方針に従って AWS インフラを構築してください。まず設計書 markdown を正本として更新し、その後に CloudFormation を実装し、最後に shell script / PowerShell script によるシナリオテストを追加してください。実装後はいきなり deploy せず、CloudFormation validate まで実施して、変更内容・想定 stack・想定 parameter・validate 結果・リスクを整理したうえで REVIEW_PENDING で止めてください。設定値は以下を固定値として扱ってください。:contentReference[oaicite:0]{index=0}

【今回のゴール】

- VPC + NAT Gateway + EC2 + ALB の構成を作る
- Multi-AZ 構成にする
- EC2 は private subnet に配置する
- public ALB 経由で NGINX の画面を表示できるようにする
- EC2 OS は Amazon Linux 2023 とする
- 管理接続は Session Manager を使い、SSH は使わない
- 初回は HTTP(80) のみで疎通確認する:contentReference[oaicite:1]{index=1}

【固定パラメータ】

- systemName: web-nginx
- env: dev
- region: ap-northeast-1
- az1: ap-northeast-1a
- az2: ap-northeast-1c
- ipAddressFamily: ipv4
- createHttpsNow: false

- vpcCidr: 10.0.0.0/16
- enableDnsSupport: true
- enableDnsHostnames: true

- publicSubnetAz1Cidr: 10.0.0.0/24
- publicSubnetAz2Cidr: 10.0.1.0/24
- privateAppSubnetAz1Cidr: 10.0.10.0/24
- privateAppSubnetAz2Cidr: 10.0.11.0/24
- mapPublicIpOnLaunchPublic: true
- mapPublicIpOnLaunchPrivate: false

- createInternetGateway: true
- natGatewayCount: 2
- eipCountForNat: 2
- publicRouteDefault: 0.0.0.0/0 -> IGW
- privateAz1RouteDefault: 0.0.0.0/0 -> NAT-A
- privateAz2RouteDefault: 0.0.0.0/0 -> NAT-C
- routeTablePublicCount: 1
- routeTablePrivateCount: 2

- albName: web-nginx-alb
- albScheme: internet-facing
- albType: application
- albIpAddressType: ipv4
- albSubnets: public-a, public-c
- listenerHttpPort: 80
- targetType: instance
- targetPort: 80
- healthCheckProtocol: HTTP
- healthCheckPath: /
- healthCheckMatcher: 200-399
- deregistrationDelaySeconds: 60
- albAccessLogsEnabled: false

- albSgIngress80Source: 0.0.0.0/0
- albSgEgress80Dest: ec2-sg
- ec2SgIngress80Source: alb-sg
- ec2SgIngress22Source: none
- ec2SgEgress443Dest: 0.0.0.0/0
- ec2SgEgress80Dest: 0.0.0.0/0

- ec2Count: 2
- instanceType: t3.small
- architecture: x86_64
- amiSsmParameter: /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64
- subnetPlacement: private-a, private-c
- associatePublicIpAddress: false
- rootVolumeType: gp3
- rootVolumeSizeGiB: 8
- iamInstanceProfile: AmazonSSMManagedInstanceCore
- keyPairName: none
- metadataHttpTokens: required

- userDataInstallNginx: true
- userDataIndexPage: hostname / az / instance-id を表示

- managementAccess: ssm-session-manager
- createSsmVpcEndpoints: false
- sshEnabled: false
- cloudWatchAgent: false
- detailedMonitoring: false
- terminationProtection: false

- outputVpcId: true
- outputPublicSubnetIds: true
- outputPrivateSubnetIds: true
- outputAlbDnsName: true
- outputAlbArn: true
- outputTargetGroupArn: true
- outputEc2InstanceIds: true
- outputSecurityGroupIds: true:contentReference[oaicite:2]{index=2}

【実装方針】

1. まず docs/designs 配下に、この構成の正本 markdown を追加または更新すること
2. 必要に応じて docs/designs/\_llm 側の properties も markdown と同じ値に同期すること
3. CloudFormation は nested stack を使わず、責務単位で分割すること
4. まずは以下 3 系統に分けること
   - network: VPC, IGW, subnets, route tables, NAT Gateway, EIP
   - security: security groups
   - app: ALB, target group, listener, IAM role/profile, EC2, UserData
5. cross-stack reference を使って必要な ID / ARN / subnet ID / security group ID を受け渡すこと
6. EC2 は各 AZ に 1 台ずつ配置すること
7. EC2 は private subnet に置き、public IP を付けないこと
8. EC2 の UserData で Amazon Linux 2023 に NGINX をインストールし、index.html に hostname / AZ / instance-id を表示すること
9. ALB は public subnet 2 本に配置し、HTTP:80 で受けて target group の instance:80 へ転送すること
10. health check は HTTP / とし、200-399 を healthy とすること
11. SSH 用の inbound は作らないこと
12. Session Manager 利用前提で IAM role / instance profile を作ること
13. Output は上記固定値どおり出力すること:contentReference[oaicite:3]{index=3}

【作成してほしい成果物】

- docs/designs 配下の設計 markdown
- 必要な docs/designs/\_llm/\*.properties
- infra/cloudformation 配下の CloudFormation templates
- tests/scenarios 配下の shell script
- tests/scenarios 配下の PowerShell script
- テスト結果を記録する markdown
- validate 実行結果のまとめ markdown

【CloudFormation 実装要件】

- Parameters は必要最小限にするが、今回の固定値はデフォルトまたは設計値として明示すること
- Tags は少なくとも Name, System, Env を付けること
- EC2 用 IAM Role には Session Manager 利用に必要な managed policy を付与すること
- EC2 AMI は固定 AMI ID 直書きではなく、SSM public parameter 参照で取得すること
- UserData は idempotent に近づけ、NGINX install / enable / start / index.html 作成を行うこと
- index.html には少なくとも systemName, env, hostname, instance-id, availability zone を出すこと
- NAT Gateway は各 AZ に 1 台ずつ作ること
- private route table は AZ ごとに分け、それぞれ同一 AZ の NAT Gateway をデフォルトルートにすること
- ALB の security group は 80/tcp を 0.0.0.0/0 から許可すること
- EC2 の security group は 80/tcp を ALB security group からのみ許可すること
- EC2 outbound は 80/443 を許可し、NAT 経由でパッケージ取得できること
- ALB access log は今回 disabled のままでよいこと:contentReference[oaicite:4]{index=4}

【シナリオテスト要件】
shell script と PowerShell script の両方を作成してください。設定確認だけではなく、実際の期待動作を確認するシナリオにしてください。少なくとも下記を含めてください。

1. CloudFormation stack の status 確認
2. Output から ALB DNS 名を取得
3. HTTP で ALB にアクセスし 200 が返ることを確認
4. 返却 HTML に NGINX 画面の想定文字列、または hostname / instance-id / availability zone の情報が含まれることを確認
5. target group の target が 2 台とも healthy であることを確認
6. EC2 に public IP が付いていないことを確認
7. 2 台の EC2 がそれぞれ別 AZ に配置されていることを確認
8. Session Manager 接続前提の IAM profile がアタッチされていることを確認
9. 失敗時は終了コード non-zero にすること
10. 実行手順と前提 AWS CLI 権限を markdown に記載すること

【レビュー観点として残す内容】
実装後、まだ deploy はしないでください。以下をまとめてください。

- 変更したファイル一覧
- 追加した stack 一覧
- stack 間依存関係
- 想定 deploy 順序
- 想定 parameter 一覧
- validate-template 実行結果
- リスクと未対応事項
- 次に人間がレビューすべき観点

【命名案】
必要に応じて下記のような命名で統一してください。

- VPC: web-nginx-dev-vpc
- Public Subnet AZ1: web-nginx-dev-public-subnet-a
- Public Subnet AZ2: web-nginx-dev-public-subnet-c
- Private Subnet AZ1: web-nginx-dev-private-app-subnet-a
- Private Subnet AZ2: web-nginx-dev-private-app-subnet-c
- IGW: web-nginx-dev-igw
- NAT Gateway AZ1: web-nginx-dev-nat-a
- NAT Gateway AZ2: web-nginx-dev-nat-c
- ALB: web-nginx-dev-alb
- Target Group: web-nginx-dev-tg
- ALB SG: web-nginx-dev-alb-sg
- EC2 SG: web-nginx-dev-ec2-sg
- EC2 AZ1: web-nginx-dev-ec2-a
- EC2 AZ2: web-nginx-dev-ec2-c
- IAM Role: web-nginx-dev-ec2-role
- Instance Profile: web-nginx-dev-ec2-profile

【期待する最終状態】

- ap-northeast-1 に VPC が 1 つある
- public subnet が 2 つ、private subnet が 2 つある
- IGW があり、public subnet は IGW へ出られる
- NAT Gateway が 2 台あり、private subnet は各 AZ の NAT を使う
- internet-facing ALB が public subnet 2AZ にある
- private subnet に Amazon Linux 2023 EC2 が 2 台ある
- 各 EC2 に NGINX が導入済み
- ALB DNS へ HTTP アクセスすると NGINX ページが見える
- target group は 2/2 healthy
- EC2 に public IP はない
- SSH inbound はない
- SSM 管理前提になっている

不足や矛盾があれば、実装を勝手に簡略化せず、今回のゴールを満たす最小構成として設計判断を markdown に明記したうえで実装してください。
