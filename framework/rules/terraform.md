# Terraform Rules

対象environment/target/serviceに未解決issueがある間は通常taskを開始・継続しない。`framework/rules/loop-engineering.md`のUnresolved issue gateに従い、issue調査とhumanが明示したIssue remediationだけを許可する。

- Terraformは`infrastructure` taskでのみ作成・変更・実行する。
- infrastructure taskは承認済みの詳細設計とservice modelをinputとして読み取る。
- intended designの変更が必要な場合は値を補完せず停止し、別の`design` taskが必要であることを報告する。
- active projectと対象environment/target directoryがTerraformを選択した場合だけ使用する。
- 1 environment/AWS accountは1 IaC engineだけで管理し、同じAWS account IDを持つalias間でもengineを統一する。
- aliasなしの共通moduleは`infra/terraform/modules/`、alias別moduleは`infra/terraform/modules/<alias>/`に置く。同じaliasのmoduleをenvironment間で共用し、異なるaliasのmoduleを共用しない。
- target固有root、backend、state設定は`infra/terraform/environments/<environment>/<target-directory>/`に置く。target directoryはaliasがあればalias、なければAWS account IDとする。
- 未使用infrastructureを先回りして生成しない。
- API設計catalogの追加はTerraform実装の対応確認や導入許可を意味しない。CFn非対応を理由にengineを切り替えず、選択済みengineとactive taskの明示scopeを維持する。実装対応が未確認のresourceを黙って除外して完了扱いにしない。
- Terraform modelには`logicalId`も`cfn-logicalId`も要求しない。service内entry番号とanchorを内部identityに使用し、CFn用metadataは保存しない。既存logicalIdは読み取り互換性だけに維持する。
- CREATEを参照する詳細設計のidentifier参照はMarkdown linkのanchorからmodel resourceを解決し、対応するTerraform resource attribute参照を生成する。link表示textの`PENDING_DEPLOY`またはphysical IDをconfigurationへ直書きしない。
- 詳細設計の表を統合してもCREATEのKMS KeyとAliasは別resourceとして保持する。IMPORTは生成しない。grouped Aliasのmodelの`parentReference`から対象Keyを解決し、`parentProperty`に対応する`target_key_id`へKeyのattribute参照を設定する。S3からAliasへの参照は該当Aliasのnameを使用する。表示変更だけを理由に既存resource addressを変更しない。
- 後続resourceまたはroot moduleが必要とするCREATEのcatalog `IDENTIFIER_OUTPUT`はnon-sensitive `output`としてresource attributeから公開する。generated ARNはoutput収集またはobserved value永続化の対象にしない。

## Resource mode boundary

- 正本modelのresourceMode=CREATE（未指定を含む）だけをTerraform生成対象とする。IMPORTは詳細設計・propertiesに保持するがIaC生成対象外で、AWS resourceを変更しない。IMPORTをTerraform `resource`へ生成しない。Terraform import command／import blockの作成・実行やstateへの取り込みを行わない。
- IMPORTはframework上の設計管理区分であり、Terraformのimport機能ではない。値をframework命名へ修正せず、Name tagを追加・変更しない。
- 本ruleのresource実装・logical ID対応・identifier参照・Outputs／output生成はCREATEに限る。grouped childも独立identityがあれば自身のresourceModeで判定する。inline設定は包含resourceの区分に従う。
- CREATEからIMPORTへの参照は架空のresource参照を生成しない。既存の承認済み受渡し設計がなければ不足を報告して停止し、新しいexternal input mechanismを設計しない。IMPORTを所有する外部stack／stateへ変更を加えない。
- 既にIaC管理中のresourceをIMPORTへ切り替えることを、template／configurationからの自動削除や管理解除の許可と解釈しない。検出時は影響を報告して停止する。

## Validation and execution

- 対象targetの`awsProfile`があれば、Terraformのinit／plan／applyとAWS値取得で同じprofileを使用する。対象processと子processだけに`AWS_PROFILE`を渡し、global shellやAWS設定fileを書き換えない。AWS providerとAWS backendの両方でprofileを維持し、明示profileや直接credentialなどが選択を上書きする設定は実行前に矛盾として停止する。AWS CLIには同じ`--profile`、SDKにはprofileを明示する。未設定時は従来の明示profile／default credential chainを維持し、account／region検証を省略しない。
- `implement` phaseは`terraform fmt -check`、freshな`TF_DATA_DIR`を使った`terraform init -backend=false`、`terraform validate`を実行し、plan、apply、AWS APIを実行しない。
- `deploy` phaseはIaCを変更せず、`terraform fmt -check`、`terraform validate`、repository外へ保存する`terraform plan`を実行する。
- `update` phaseはhumanがtask開始前に手動修正したmodel propertiesを変更せずMarkdownを生成し、implement phaseのlocal validation後、repository外へ保存するplanを確認してapplyする。このphase内で生成した対象IaCのuncommitted diffだけをapply対象として許可する。
- deploy phaseでIaC修正が必要な場合は変更せず停止する。
- 全planを一律停止するhuman reviewは設けない。保存済みplanに未承認のdestroy/replacementがある場合だけ`framework/prompts/codex/04_deploy.md`に従って説明付きhuman確認待ちにする。
- applyはdeployまたはupdate phaseのactive promptが明示的に許可し、plan scopeがpromptと一致するときだけ保存済みplanを実行する。
- active promptが対象を限定している場合は、implement phaseでは指定environment/module/resourceだけを変更し、deployまたはupdate phaseでは指定対象だけをapplyして終了できる。
- 保存済みplanのresource change actionにdeleteを含む変更をdestroy/replacementの確認対象とする。未承認の場合はdeployment failureまたはtask完了として扱わず、applyせずにhuman確認待ちにする。
- human承認後は同じtaskで同じ保存済みplanを再確認し、承認対象のresource address、resource type、actionが一致する場合だけそのplan binaryをapplyする。plan binaryが失われた、再作成された、または内容が変わった場合は以前の承認を使用せず再確認する。
- 一部の変更だけが承認された場合は保存済みplanをapplyしない。configuration修正またはresource保持が必要な場合は現在のdeploy/update phaseでIaCを変更せず停止する。
- wrong workspace/account/region、missing input、sensitive output、plan failure、intended designの不足、またはdestroy/replacementのactionを確定できない場合は停止する。
- state fileとplan binaryをcommitしない。
- remote stateはaccess control、locking、encryption、backupを備える構成としてproject designに記録する。
- secretを出力せず、generated ARNをobserved valueとして保存しない。
- existing environmentのCloudFormation/Terraform切替はdedicated migration/import taskとし、normal updateで行わない。

apply後は`framework/rules/observed-values.md`の優先順位で必要なnon-ARN identifierをTerraform output、必要な場合だけstateから取得し、詳細設計のmodelのidentifier output／全参照元のobserved valueを先に更新してMarkdownを再生成する。local loop後にinfrastructure taskを終了し、次のmodule、environment、scenario-test taskへ自動的に進まず、scenario testまたはscenario evidenceを作成・更新しない。
