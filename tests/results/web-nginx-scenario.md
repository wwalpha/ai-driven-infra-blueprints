# web-nginx Scenario Result

## Scenario Scripts

- shell: tests/scenarios/sh/web-nginx-scenario.sh
- powershell: tests/scenarios/ps1/web-nginx-scenario.ps1

## Execution Preconditions

- `AWS_REGION` が未設定でも ap-northeast-1 を既定で使う
- 対象 stack が deploy 済みで `CREATE_COMPLETE` または `UPDATE_COMPLETE` であること
- 実行者は少なくとも次の AWS CLI 権限を持つこと
  - `cloudformation:DescribeStacks`
  - `ec2:DescribeInstances`
  - `elasticloadbalancing:DescribeTargetHealth`
- shell script 実行時は `aws`, `curl`, `grep`, `bash` が利用可能であること
- PowerShell script 実行時は `aws` と `pwsh` または PowerShell 7 が利用可能であること

## Expected Execution Commands

### Shell

```bash
bash tests/scenarios/sh/web-nginx-scenario.sh \
  cfn-stack-dev-webnginx-network01 \
  cfn-stack-dev-webnginx-security01 \
  cfn-stack-dev-webnginx-app01
```

### PowerShell

```powershell
pwsh -NoLogo -NoProfile -File tests/scenarios/ps1/web-nginx-scenario.ps1 -NetworkStackName cfn-stack-dev-webnginx-network01 -SecurityStackName cfn-stack-dev-webnginx-security01 -AppStackName cfn-stack-dev-webnginx-app01
```

## Test Steps

1. Describe stack status for network/security/app
   Execution Command: `describe-stacks`
   Expected Value: 3 stack とも `CREATE_COMPLETE` または `UPDATE_COMPLETE`
   Actual Value: network=`CREATE_COMPLETE`, security=`CREATE_COMPLETE`, app=`CREATE_COMPLETE`
   Pass / Fail: PASS
2. Read `AlbDnsName` from app stack output
   Execution Command: `describe-stacks`
   Expected Value: DNS 名が取得できる
   Actual Value: `alb-dev-web01-1082823635.ap-northeast-1.elb.amazonaws.com`
   Pass / Fail: PASS
3. HTTP GET to `http://<AlbDnsName>/`
   Execution Command: `curl`
   Expected Value: HTTP 200 が返る
   Actual Value: `200`
   Pass / Fail: PASS
4. Inspect HTML body
   Execution Command: `curl`
   Expected Value: `web-nginx` または `instance-id=` または `availability-zone=` を含む
   Actual Value: response body に `web-nginx` と instance metadata を確認
   Pass / Fail: PASS
5. Check target health
   Execution Command: `describe-target-health`
   Expected Value: healthy target が 2 台
   Actual Value: `2`
   Pass / Fail: PASS
6. Check EC2 public IP
   Execution Command: `describe-instances`
   Expected Value: public IP count が 0
   Actual Value: `0`
   Pass / Fail: PASS
7. Check AZ distribution
   Execution Command: `describe-instances`
   Expected Value: distinct AZ count が 2
   Actual Value: `2`
   Pass / Fail: PASS
8. Check IAM instance profile attachment
   Execution Command: `describe-instances`
   Expected Value: IAM instance profile count が 2
   Actual Value: `2`
   Pass / Fail: PASS

## Current Status

- `REVIEW APPROVED` 後に 3 stack を deploy した
- shell scenario test は実行済みで全項目 PASS
- PowerShell script はこの macOS 環境で `pwsh` 未導入のため runtime 実行は未実施
- 2026-03-27 に app -> security -> network の順で stack を削除済みのため、この結果は teardown 前の実行証跡として保持する

## Executed Command

```bash
bash tests/scenarios/sh/web-nginx-scenario.sh \
  cfn-stack-dev-webnginx-network01 \
  cfn-stack-dev-webnginx-security01 \
  cfn-stack-dev-webnginx-app01
```

## Notes

- shell script は失敗時に non-zero を返す
- PowerShell script は例外送出で non-zero 終了となる
- HTTP 応答待ちは ALB と NGINX bootstrap の立ち上がりを考慮して最大 30 回まで retry する
