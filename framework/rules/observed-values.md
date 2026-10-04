# Observed Values Rules

- observed valueはcurrent deploymentから取得した必要最小限のmachine-readable valueであり、scenario evidenceではない。
- observed valueはservice modelの`observed.*`を正本とし、詳細設計のcatalog `IDENTIFIER_OUTPUT` rowと全参照元を生成する。
- 成功した`infrastructure` taskのAWS mutation後、または`design` taskでhumanが選択した既存resourceをread-only取得した場合だけmodelのobserved valueを先に更新し、`framework/scripts/sync-model.py`でMarkdownを再生成する。
- `scenario-test` taskは`model/**`を読み取れるが変更しない。
- follow-up configuration、link、connection、operation、future task inputに必要なvalueだけを収集する。
- valid exampleは、実際に必要なVPC ID、Subnet ID、Route Table ID、Security Group ID、EC2 Instance ID、private/public IP、DNS name、endpoint address、hosted zone IDなど。
- generated ARNは詳細設計と`observed.*`の両方へ保存しない。
- AWS APIがARNを要求する場合はtransientに取得してよい。
- `Macie.ClassificationJob.jobId`もAPI catalogの`IDENTIFIER_OUTPUT`として扱う。既存Jobを取得する許可済みdesign taskでは`DescribeClassificationJob`から必要なjobIdを取得する。CFn Outputsやstack resourceへ探索を広げず、responseのjobArn、統計、実行状態を永続化しない。
- AWS managed-policy ARNなどのhuman-provided design ARNはobserved valueではなく、必要なdesign inputとして`desired.*`へ残してよい。
- current valueがまだ存在しないgenerated fieldは`PENDING_DEPLOY`とし、そのidentifierを参照する全propertyのMarkdown link表示textも`PENDING_DEPLOY`とする。
- `CidrBlock`、`DestinationCidrBlock`、`CidrIp`等のCIDR項目は、詳細表・リソース一覧とも`PENDING_DEPLOY`を禁止する。deploy前でも確定済みCIDRを表示し、未確定ならhumanへ確認する。参照linkの表示値や配列内も同じとし、catalogでidentifier outputとされるCIDRでも例外にしない。`VpcId`等の生成IDのPENDING_DEPLOY許容は維持する。
- 既存resource取得ではchatbotが選択したpropertyだけを詳細設計のdesired valueへ直接差分反映し、必要な非ARN generated identifierをobserved valueへ反映する。未選択propertyと未選択resourceは変更しない。
- current physical valueはresourceが現在存在する間だけ保持する。replacementでは新しい値だけをidentifier output rowと全参照元へ反映する。
- destroy後はidentifier output rowと全参照元を`PENDING_DEPLOY`へ戻し、Markdownを再生成する。
- obsoleteなphysical IDと過去valueはGit履歴、CloudFormation/Terraform、AWS側のdeployment historyで追跡する。
- 過去valueをscenario evidenceへ転記しない。
- old result fileだけを根拠にold IDがcurrentであると仮定しない。

IMPORTの設定取得・observed更新は明示許可されたdesign taskのread-only取得で行う。以下のCloudFormation／Terraformからの収集とoutput追加はCREATEだけを対象とし、IMPORTのためにStack／state管理へ移行したりAWS設定を変更したりしない。

## Collection and propagation

- identityなしで親modelのrowへ統合した子resourceは、`resource-layout.json`の親型・parentPropertyとtemplateの有効な親Refから対応を解決する。親のCREATE・正式型・直接IDまたは一意な旧ID・Validation scopeと子設定rowの存在を検証し、同じ親への同型子resourceの二重所有を拒否する。子へ独立したresource metadataやidentifier rowを要求せず、子のphysical IDを収集しない。親参照が未解決・不一致なら推測せず停止する。
- `CodeCommit.Repository.RepositoryId`などmodelに保存しない`HIDDEN_PROPERTIES`は、identifier row・Outputsの必須検証とobserved収集から除外する。他の識別子の検証は維持する。

- CloudFormationはstack詳細設計のStackNameと実行したtemplateのLogicalIdで対象resourceを特定し、service詳細設計と照合する。対応が曖昧なら推測せず停止する。必要なnon-ARN identifierをそのstackの`Outputs`から取得する。対象outputがない場合だけstack resourceの`PhysicalResourceId`を使用し、同じlogical resourceについて両方が取得できる場合は一致を確認する。複数stackで同じtemplate/LogicalIdを使う場合も、別の設計resource rowへ反映する。
- Terraformは必要なnon-sensitive identifierをroot module `output`から取得する。対象outputがない場合だけstateのresource attributeをread-onlyで参照し、同じresourceについて両方が取得できる場合は一致を確認する。
- IaCに必要なoutputが不足する場合、`deploy` phaseではIaCを変更せず停止する。`implement`または`update` phaseは必要なoutputだけを追加し、CloudFormationはlogical resource参照、Terraformはresource attribute参照を維持する。
- 取得したidentifierはcatalogの正式な`IDENTIFIER_OUTPUT` propertyへ対応付ける。対応が一意でなければ推測せず停止する。
- modelのidentifier outputに対応するobserved rowを更新した後、同じidentifierを参照する全model rowのobserved valueを同じ値へ更新する。Markdown link表示textは生成処理で更新する。参照元の`Source / Comment`、link先path、anchorは変更しない。
- 更新後にMarkdownを再生成し、validatorでidentifier outputと全参照元の一致を確認する。generated ARN、secret、old physical IDは保存しない。

CloudFormation controllerは`cloudformation_observed.py`のimplement/deploy共通検証で、各model resourceの`cfn-logicalId=<StackName>-<Resources key>`を直接照合する。別対応表は使用しない。旧logicalIdだけのmodelは正式型と旧IDの一意な従来照合を維持する。直接IDを持つresourceは名前検索から除外し、不正・欠落をfallbackで補わない。stack固有parameter/defaultとaccount/region/StackNameでConditionを評価し、falseのresourceを照合・identifier検証・所有判定から除外する。未解決・循環・非booleanの条件は停止する。対応先のCREATE区分・正式型・一意性、catalog row／Output／actualの不一致は`AMBIGUOUS_OBSERVED_MAPPING`で停止する。名前、file順、過去のphysical IDから対応を推測しない。

OutputのValueが対象logical resourceのRef（catalogの一意identifierがschema primaryIdentifierに対応する場合）または正式attributeのGetAttであることを確認する。PhysicalResourceId fallbackは一意なcatalog identifierがprimaryIdentifierに対応する場合だけ使用する。他のidentifierは正式GetAtt Outputを必要とし、generated ARNは拒否する。全更新と参照伝播を計画してtask scope／予約fileを検査してからobservedだけを書き、既存sync-modelでservice単位に生成・検証する。曖昧さがある場合はmodelへ書かない。生成失敗時はmodelを正本として保持し、同sessionで同期を再試行する。

observed同期はdeploy前に検証した同じ対応を使用し、再開時はimmutable input guardと共通検証で再確定する。Removeは新templateのConditionがfalseまたはresourceが存在しなくても、change setの正式型と対応先をexecution前に検証する。削除後の同期で新しい所有先を推測せず、Delete／Snapshotによる物理破棄を確認した場合だけidentifierと参照元をPENDING_DEPLOYへ戻す。Retain／不明policyでは保持し停止する。
