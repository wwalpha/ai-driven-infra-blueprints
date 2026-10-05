# Project Configuration Rules

## Topology

- initialization後のmachine-readable source of truthは`project.json`。target directoryはaliasがあればalias、なければ`awsAccountId`とする。

- 未初期化の配布状態では`project.json`を置かない。
- `docs/system-overview.md`の作成・記入状態に関係なく、`framework/prompts/codex/01_initialize.md`を使用できる。Codexが必要な確定値を質問し、`project.json`とtarget pathを作成する。
- initializationでは現時点で必要値が確定しているtargetだけを登録する。未作成または必要値が未確定のtargetは推測やplaceholderで登録せず、確定後に`framework/prompts/codex/02_add-target.md`のmigrationで追加する。
- environment数、environment名、AWS account数を固定しない。
- 一つのenvironmentにtargetが一件だけならaliasを持たせない。複数targetがある場合は全targetにhuman-confirmed aliasを必須とし、同じAWS account IDを複数aliasへ設定してよい。aliasは同じenvironment内で一意なlower-kebab-caseとし、12桁の数字だけの値を禁止する。
- 1 environment/AWS accountの`IaC engine`は`cloudformation`または`terraform`のどちらか一つとし、同じAWS account IDを持つalias間で統一する。
- humanへ`project.json`の直接編集を要求しない。topology変更は明示されたinitializationまたはmigration taskでCodexが行う。
- `project.json`の各targetは任意の`suffix`を持てる。確定済みnon-empty lower-kebab-case文字列とし、environment/aliasごとに別値を設定してよい。命名patternに`{{suffix}}`がある場合だけ選択targetの値を使用し、ないpatternへ自動付加しない。初期化・target追加時に任意で確認し、既存targetへの追加・変更・解除はhumanが明示した`migration` taskで行う。既存名称は自動変更しない。

## Credentials and account

- `project.json`の各targetは任意の`awsProfile`を持てる。設定時はそのprofileを対象targetのAWS CLI／SDK、Terraformのprovider／AWS backendに使用する。未設定時は明示profile、それもなければdefault credential chainを維持する。設定値と異なる明示profileは実行前に拒否し、認証失敗時に別profileへfallbackしない。

- `awsProfile`は確定済みの空でない文字列とし、前後の空白、改行、NUL、`UNSET`を禁止する。指定しない場合はkey自体を省略し、credential値を保存しない。profileはtargetごとに設定でき、alias／account／region／IaC engineの制約を変更しない。
- `awsAccountId`はresource作成時の明示的なaccount ID設定・名称componentとtarget identityの正本とする。target directory、selector、task scopeは従来どおりalias、aliasなしは`awsAccountId`を使用する。
- policy内で同じtargetに作成するresourceの実際の所有account・source accountを照合する値は、resource作成時の名称・ID設定と区別し、`awsExecutionAccountId`（未設定時は`awsAccountId`）を使用する。VPC Flow Logsの信頼policyでは`aws:SourceAccount`と`aws:SourceArn`内のaccount部分の両方が該当する。権限policyの`Resource` ARNや`Principal`のaccountも参照先の実際の所有accountに合わせる。humanが明示したcross-account参照はそのaccountを維持し、policy内のaccountを一括置換しない。
- 各targetは任意の`awsExecutionAccountId`を持てる。指定時はASCII数字12桁の文字列とし、未指定時はkeyを省略して`awsAccountId`を実行accountとして使用する。AWS CLI／SDK、CloudFormation、Terraform、既存resource取得、observed値取得、model対AWS比較、scenarioのcaller account検証には実行accountを使用し、不一致・認証失敗ではAWS操作前に停止する。ID設定だけでcredentialは切り替わらず、既存の`awsProfile`／明示profile／default credential chainを使用し、AssumeRoleや別accountへのfallbackを自動追加しない。
- AWS APIの暗黙のaccount context／owner検証とCloudFormationの`AWS::AccountId`は実行accountを使用する。設計に明示したaccount propertyやcross-account参照は書き換えない。名前等に`awsAccountId`が必要で両IDが異なる場合は、`AWS::AccountId`へ置換せず独立した明示parameter／設定値として渡す。通常のresourceの所属accountは実際のAWS実行先で決まり、`awsAccountId`設定だけでは変更できない。
- 同じenvironment/実行accountを持つtargetでもIaC engineを統一する。初期化・target追加では任意の実行account IDを確認し、既存targetへの追加・変更・解除はhumanが明示した`migration` taskでCodexが行う。`awsAccountId`やalias、path、設計、IaCを暗黙に変更せず、AWS接続を行わずlocal validationする。
- `project.json`と一致しないpath/IaC implementationはlocal loopを通さない。
