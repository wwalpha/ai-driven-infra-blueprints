# Observed Values Rules

- observed valueはcurrent deploymentから取得した必要最小限のmachine-readable valueであり、scenario evidenceではない。
- observed valueは詳細設計のcatalog `IDENTIFIER_OUTPUT` rowとそのidentifierを参照する全property、および同じservice modelの`observed.*`へ保持する。
- 成功した`infrastructure` taskのAWS mutation後、または`design` taskでhumanが選択した既存resourceをread-only取得した場合だけ詳細設計を更新し、`framework/scripts/sync-model.py`でmodelを再生成する。
- `scenario-test` taskは`model/**`を読み取れるが変更しない。
- follow-up configuration、link、connection、operation、future task inputに必要なvalueだけを収集する。
- valid exampleは、実際に必要なVPC ID、Subnet ID、Route Table ID、Security Group ID、EC2 Instance ID、private/public IP、DNS name、endpoint address、hosted zone IDなど。
- generated ARNは詳細設計と`observed.*`の両方へ保存しない。
- AWS APIがARNを要求する場合はtransientに取得してよい。
- AWS managed-policy ARNなどのhuman-provided design ARNはobserved valueではなく、必要なdesign inputとして`desired.*`へ残してよい。
- current valueがまだ存在しないgenerated fieldは`PENDING_DEPLOY`とし、そのidentifierを参照する全propertyのMarkdown link表示textも`PENDING_DEPLOY`とする。
- 既存resource取得ではchatbotが選択したpropertyだけを詳細設計のdesired valueへ直接差分反映し、必要な非ARN generated identifierをobserved valueへ反映する。未選択propertyと未選択resourceは変更しない。
- current physical valueはresourceが現在存在する間だけ保持する。replacementでは新しい値だけをidentifier output rowと全参照元へ反映する。
- destroy後はidentifier output rowと全参照元を`PENDING_DEPLOY`へ戻し、modelを再生成する。
- obsoleteなphysical IDと過去valueはGit履歴、CloudFormation/Terraform、AWS側のdeployment historyで追跡する。
- 過去valueをscenario evidenceへ転記しない。
- old result fileだけを根拠にold IDがcurrentであると仮定しない。

## Collection and propagation

- CloudFormationは必要なnon-ARN identifierをstack `Outputs`から取得する。対象outputがない場合だけstack resourceの`PhysicalResourceId`を使用し、同じlogical resourceについて両方が取得できる場合は一致を確認する。
- Terraformは必要なnon-sensitive identifierをroot module `output`から取得する。対象outputがない場合だけstateのresource attributeをread-onlyで参照し、同じresourceについて両方が取得できる場合は一致を確認する。
- IaCに必要なoutputが不足する場合、`deploy` phaseではIaCを変更せず停止する。`implement`または`update` phaseは必要なoutputだけを追加し、CloudFormationはlogical resource参照、Terraformはresource attribute参照を維持する。
- 取得したidentifierはcatalogの正式な`IDENTIFIER_OUTPUT` propertyへ対応付ける。対応が一意でなければ推測せず停止する。
- identifier output rowを更新した後、同じanchorを参照する全propertyのMarkdown link表示textを同じ値へ更新する。参照元の`Source / Comment`、link先path、anchorは変更しない。
- 更新後にservice modelを再生成し、validatorでidentifier outputと全参照元の一致を確認する。generated ARN、secret、old physical IDは保存しない。
