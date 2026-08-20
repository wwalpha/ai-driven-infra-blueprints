# Post-Deploy Actuals Rules

- actualsはcurrent deployment stateのmachine-readable情報であり、scenario evidenceではない。
- actualsは成功した`infrastructure` taskのAWS mutation後にだけ更新する。
- `scenario-test` taskは`llm/actuals/**`を読み取れるが変更しない。
- follow-up configuration、link、connection、operation、future task inputに必要なvalueだけを収集する。
- valid exampleは、実際に必要なVPC ID、Subnet ID、Route Table ID、Security Group ID、EC2 Instance ID、private/public IP、DNS name、endpoint address、hosted zone IDなど。
- generated ARNはpersistent actual-value recordから除外する。
- AWS APIがARNを要求する場合はtransientに取得してよいが、detailed designや`llm/actuals/`に書かない。
- AWS managed-policy ARNなどのhuman-provided/design ARNはpost-deploy actualではなく、必要なdesign inputとして残してよい。
- current valueがまだ存在しないgenerated fieldは`PENDING_DEPLOY`とする。
- current physical valueはresourceが現在存在する間だけ保持する。
- destroy後はenvironment/resourceを`NOT_DEPLOYED`とし、generated design fieldを`PENDING_DEPLOY`に戻す。
- actualsはcreateだけでなく、成功したupdate/destroyの後にも更新する。
- LLM actual informationまたはaccompanying metadataにenvironment、AWS account、region、collection method、observation date/timeを記録してよい。
- obsoleteなphysical IDと過去actualはGit履歴、CloudFormation/Terraform、AWS側のdeployment historyで追跡する。
- 過去actualをscenario evidenceへ転記しない。
- old result fileだけを根拠にold IDがcurrentであると仮定しない。
