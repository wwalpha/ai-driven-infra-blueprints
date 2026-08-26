# Observed Values Rules

- observed valueはcurrent deploymentから取得した必要最小限のmachine-readable valueであり、scenario evidenceではない。
- observed valueは詳細設計のgenerated identifier rowと、同じservice modelの`observed.*`へ保持する。
- 成功した`infrastructure` taskのAWS mutation後にだけ詳細設計を更新し、`framework/scripts/sync-model.py`でmodelを再生成する。
- `scenario-test` taskは`model/**`を読み取れるが変更しない。
- follow-up configuration、link、connection、operation、future task inputに必要なvalueだけを収集する。
- valid exampleは、実際に必要なVPC ID、Subnet ID、Route Table ID、Security Group ID、EC2 Instance ID、private/public IP、DNS name、endpoint address、hosted zone IDなど。
- generated ARNは詳細設計と`observed.*`の両方へ保存しない。
- AWS APIがARNを要求する場合はtransientに取得してよい。
- AWS managed-policy ARNなどのhuman-provided design ARNはobserved valueではなく、必要なdesign inputとして`desired.*`へ残してよい。
- current valueがまだ存在しないgenerated fieldは`PENDING_DEPLOY`とする。
- current physical valueはresourceが現在存在する間だけ保持する。
- destroy後はgenerated identifier rowを`PENDING_DEPLOY`へ戻し、modelを再生成する。
- obsoleteなphysical IDと過去valueはGit履歴、CloudFormation/Terraform、AWS側のdeployment historyで追跡する。
- 過去valueをscenario evidenceへ転記しない。
- old result fileだけを根拠にold IDがcurrentであると仮定しない。
