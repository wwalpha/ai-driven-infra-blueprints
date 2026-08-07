# Post-Deploy Actuals Rules

- follow-up configuration、link、connection、operation、scenario test、future task input に必要な value だけを収集する。
- valid example は、実際に必要な VPC ID、Subnet ID、Route Table ID、Security Group ID、EC2 Instance ID、private/public IP、DNS name、endpoint address、hosted zone ID など。
- generated ARN は persistent actual-value record から除外する。
- AWS API が ARN を要求する場合は transient に取得してよいが、detailed design や `llm/actuals/` に書かない。
- AWS managed-policy ARN などの human-provided/design ARN は post-deploy actual ではなく、必要な design input として残してよい。
- current value がまだ存在しない generated field は `PENDING_DEPLOY` とする。
- current physical value は resource が現在存在する間だけ保持する。
- destroy 後は environment/resource を `NOT_DEPLOYED` とし、generated design field を `PENDING_DEPLOY` に戻す。historical value は task result evidence だけに残す。
- actuals は create だけでなく、成功した update/destroy の後にも更新する。
- LLM actual informationまたはaccompanying metadataにtask ID、environment、AWS account、region、collection method、observation date/timeを記録する。
- old result file だけを根拠に old ID が current であると仮定しない。
