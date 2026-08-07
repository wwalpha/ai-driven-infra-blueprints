# Repository Initialization Prompt

この prompt は、human が `docs/system-overview.md` を完成させた後、Codex が repository を project 用に初期化するために使用する。

## Input

- Task ID: `{{task-id}}`

## Preconditions

1. repository root を作業directoryとする。
2. `docs/system-overview.md` の `Project name` が `UNSET` ではないこと。
3. `Environment topology` table が1行以上あり、各行の全fieldが確定していること。
4. environment数、environment名、AWS account数を推測しないこと。
5. `Environment topology` にないtargetを作成しないこと。

preconditionを満たさない場合はfileを変更せず、不足fieldを列挙して停止する。

## Initialization contract

変更前に、次を含むactive task promptを `tasks/{{task-id}}/prompt.md` に作成する。

```md
- Task type: `initialization`
```

- goalはSystem Overviewに定義済みのproject topologyの初期化だけとする
- AWS mutation、deploy、applyは禁止する
- allowed pathsは、作成対象の`docs/designs/**`、`llm/**`、選択済みIaCの初期化path、activeな`tasks/{{task-id}}/**`に限定する
- resource設計、IaC implementation、AWS接続確認は対象外とする
- `tests/scenarios/**`と`tests/results/**`を変更しない

## Read

次を順に読む。

1. `AGENTS.md`
2. `README.md`
3. `docs/system-overview.md`
4. `rules/detailed-design.md`
5. `rules/llm-design-information.md`
6. 選択されたIaC engineに対応するrule
7. `rules/loop-engineering.md`

## Validate topology

`Environment topology` の各行について次を確認する。

- `Environment ID`はlower-kebab-case
- AWS account IDは12桁
- 同じenvironment内でAWS account IDが重複していない
- 同じEnvironment IDのEnvironment nameとPurposeが一致している
- AWS account IDは12桁
- AWS regionが設定済み
- IaC engineは`cloudformation`または`terraform`

AWS account IDはenvironment間で共有される場合があるため、repository全体での一意性は要求しない。

## Create target paths

各`Environment ID`と`AWS account ID`の組み合わせについて、存在しないpathだけを作成する。空directoryをGit管理するため、各pathに`.gitkeep`を置く。

```text
docs/designs/<environment>/<aws-account-id>/.gitkeep
llm/designs/<environment>/<aws-account-id>/.gitkeep
llm/actuals/<environment>/<aws-account-id>/.gitkeep
```

IaC engineが`cloudformation`の場合:

```text
infra/cloudformation/parameters/<environment>/<aws-account-id>/.gitkeep
```

IaC engineが`terraform`の場合:

```text
infra/terraform/environments/<environment>/<aws-account-id>/.gitkeep
```

## Do not create

- 空の詳細設計Markdown
- 空のLLM design properties
- CloudFormation template
- Terraform module、resource、provider、state設定
- questionnaire、回答履歴、session state
- System Overviewにないsample environmentやsample AWS account

## Existing repository handling

- 既存のdesign、actual、IaC implementationを上書きしない。
- 同じpathが存在する場合は再利用し、`.gitkeep`のためだけに内容を変更しない。
- System Overviewから削除されたtargetのpathが残っている場合は削除せず、専用migration taskが必要なことを報告して停止する。
- System Overviewと既存pathのIaC engineが矛盾する場合は停止する。

## Verify

1. `bash scripts/blueprint-loop.sh --task-id {{task-id}} --mode local`
2. `python3 -m py_compile scripts/validate-blueprint.py`
3. `bash -n scripts/blueprint-loop.sh`
4. `git diff --check`

validation結果、初期化したenvironment/AWS account、作成path、既存のため変更しなかったpath、blockerはCodexの完了報告だけに記載する。repositoryへverification resultを保存しない。初期化完了後にdesign taskまたはinfrastructure taskへ進まない。
