# Prompt Guide

This directory holds prompts for designing, implementing, deploying, and validating AWS infrastructure. Each prompt body is authoritative at execution; use this README as an index for selecting prompts, usage order, and start conditions.

## Basic usage

1. Select one prompt matching the work to execute.
2. Pass the prompt to the target chatbot or Codex and include confirmed `User input` values in the request.
3. If values are missing, answer one question at a time according to the prompt. Do not let it infer values.
4. After one prompt completes, confirm results and finish. Explicitly start the next prompt as a separate task only when needed.

Do not use aliases when an environment has only 1 target. For environments with multiple targets, specify each target's human-defined alias and use it as the target directory for designs, models, parameters/Terraform roots, and scenario results. Pass Target alias and the corresponding actual AWS account ID to prompts executing aliased targets.

In Codex, specify the target prompt and values as follows.

```text
framework/prompts/codex/03_implement.mdを使ってください。
Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Implementation scope: docs/designs/dev/cde/vpc.md
```

## Choose the workflow

| Situation | Use |
| --- | --- |
| Create new detailed designs through chatbot design | `chatbot/service-design.md` → Codex prompt output by chatbot → `03_implement.md` → `04_deploy.md` |
| Reflect current values of existing AWS resources selected by the chatbot into detailed design | `chatbot/service-design.md` → read-only retrieval Codex prompt output by chatbot |
| The human directly edits existing model properties, then reflects them in IaC and deploys while uncommitted | `05_update.md` |
| Confirm application behavior after deploy | `06_scenario-test.md` only when needed in either workflow |

For new designs, `service-design.md` outputs completed model properties, destination Markdown/JSON, and a self-contained Codex prompt to create them in the repository. When using current values of existing AWS resources, it does not output completed Markdown; it outputs a read-only retrieval Codex prompt including target services, resource types, and properties. After the human selects resource candidates, Codex directly reflects current-value differences into detailed design. Neither uses a fixed design-save-only prompt.

When managing stacks in CloudFormation targets, save target-specific `cloudformation-stacks.md` with service detailed designs in the design task. `03_implement.md` implements templates and individual parameter files for each StackName listed there; `04_deploy.md` matches actual AWS resources and deploys per StackName. The same template may be assigned to multiple StackNames.

For manual edits, do not split implement and deploy. `05_update.md` receives human design diffs as immutable input and performs Markdown generation, IaC reflection, and deploy/apply in one task.

## Workflow order

| Order | Prompt | Use when | Result |
| ---: | --- | --- | --- |
| 1 | [`codex/01_initialize.md`](codex/01_initialize.md) | Initialize a repository without `project.json` | Create project topology and target paths |
| 2 | [`codex/02_add-target.md`](codex/02_add-target.md) | Add 1 environment/logical target after initialization | Update `project.json` and added target paths |
| Design | [`chatbot/service-design.md`](chatbot/service-design.md) | Confirm detailed design values for new systems, features, or services with the human | Output completed model properties and destination Markdown/JSON, or a self-contained Codex prompt for existing-resource retrieval |
| 3 | [`codex/03_implement.md`](codex/03_implement.md) | Reflect detailed designs already created in the repository into CloudFormation/Terraform | Create/change IaC through local static validation |
| 4 | [`codex/04_deploy.md`](codex/04_deploy.md) | Deploy/apply created/validated IaC to AWS | Execute, perform uniquely determined CloudFormation controlled repair, and update necessary observed values |
| 5 | [`codex/05_update.md`](codex/05_update.md) | The human manually edits existing detailed designs, then reflects them in IaC and deploys while uncommitted | Perform Markdown generation, IaC changes, deploy/apply, and observed value updates in one task |
| 7 | [`codex/07_destroy.md`](codex/07_destroy.md) | Explicit CloudFormation Stack deletion requested | Independent destroy; observed consistency and scoped local loop |
| 6 | [`codex/06_scenario-test.md`](codex/06_scenario-test.md) | Application behavior confirmation is needed after deploy | Update scenarios and current results for the same target |

Use `02_add-target.md`, `05_update.md`, and `06_scenario-test.md` only when applicable. `05_update.md` is a separate branch from the ordinary new-design workflow.

## Prompt details

### `chatbot/service-design.md`

- Description: Confirm human decisions needed for new detailed design, or resource types/properties to retrieve from existing AWS resources, in chat per AWS service ownership boundary.
- Timing: When designing a new system, feature, or service before Markdown/JSON artifacts to save are confirmed.
- How to use: Pass Design target, environment, and AWS account and answer question batches. State when using current existing-resource values. After completion, execute the chatbot's `Codex反映依頼` unchanged in Codex. For existing-resource retrieval, Codex validates read-only AWS context and presents candidates; after human resource selection, directly reflect differences only for selected properties into detailed design.

Usage example:

```text
framework/prompts/chatbot/service-design.mdを使ってください。

Design target: 社内向けWeb APIのnetwork構成
Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Candidate AWS services: 未定
Expected design files: 未定
```

When reflecting current existing-VPC values into detailed design:

```text
framework/prompts/chatbot/service-design.mdを使ってください。

Design target: 既存VPCの設定を詳細設計書へ反映
Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Candidate AWS services: vpc
Expected design files: docs/designs/dev/cde/vpc.md
Existing AWS values: EC2.VPCの現在値を使用
```

### `codex/01_initialize.md`

- Description: Confirm project, environments, target aliases when needed, AWS accounts, regions, and IaC engines one question at a time, then initialize repository topology.
- Timing: Only the first time, when `project.json` does not exist. Do not use when already initialized.
- How to use: Pass the prompt to Codex and answer starting with Project name. The repository is unchanged until explicit agreement to final confirmation of all values.

Usage example:

```text
framework/prompts/codex/01_initialize.mdを使ってください。
```

Codex asks one question at a time for Project name, Environment ID, logical target count within the environment, Target alias when needed, AWS account ID, AWS region, IaC engine, and optional AWS profile; answer in order.

### `codex/02_add-target.md`

- Description: Add 1 confirmed environment/alias (when needed)/AWS account target to an initialized repository.
- Timing: `project.json` exists but the necessary target is not registered yet.
- How to use: Pass the prompt to Codex and answer Environment ID, Target alias if the existing environment uses aliases, AWS account ID, region, IaC engine, and optional AWS profile in order. Add only 1 target per execution.

Usage example:

```text
framework/prompts/codex/02_add-target.mdを使ってください。

Environment ID: dev
Target alias: cde
AWS account ID: 123456789012
AWS region: ap-northeast-1
IaC engine: cloudformation
```

### `codex/03_implement.md`

- Description: Create/change selected CloudFormation/Terraform from approved detailed designs and service models.
- Timing: Design reflection by the chatbot's Codex prompt is complete and design diffs need reflection in IaC.
- How to use: Pass environment, alias when present, AWS account, and implementation scope. Run `cfn-lint` for CloudFormation or local validation without backends for Terraform; do not run AWS APIs or deploy/apply.

Usage example:

```text
framework/prompts/codex/03_implement.mdを使ってください。

Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Implementation scope:
- docs/designs/dev/cde/vpc.md
- docs/designs/dev/cde/cloudwatch-logs.md
```

### `codex/04_deploy.md`

- Description: Deploy/apply created/validated IaC to target AWS accounts without changing it.
- Timing: IaC from `03_implement.md` is confirmed and target IaC has no uncommitted changes.
- How to use: Pass environment, alias when present, AWS account, deployment scope, permitted delete/replacement, and AWS profile if needed. Perform preflight, change set/plan checks, execution, completion confirmation, and necessary observed value updates.

Usage example:

```text
framework/prompts/codex/04_deploy.mdを使ってください。

Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Deployment scope:
- CloudFormation template: infra/cloudformation/templates/vpc.yaml
- Parameter file: infra/cloudformation/parameters/dev/cde/vpc.json
- Stack name: example-dev-cde-vpc
Authorized delete/replacement: none
AWS profile:
```

### `codex/05_update.md`

- Description: Receive uncommitted diffs created by the human in existing model properties as confirmed design; perform Markdown generation, IaC reflection, and deploy/apply.
- Timing: The human directly edits existing detailed design and reflects diffs into CloudFormation/Terraform and AWS resources before commit.
- How to use: Instruct only use of the prompt. Codex obtains environment, AWS account, and Design scope from changed detailed design paths and determines Deployment scope from corresponding existing IaC. Omitted delete/replacement authorization is `none`; omitted AWS profile uses target `awsProfile`, or default credential chain if unset. Reject explicit profiles differing from settings before execution. If design diffs mix multiple targets, stop without changes; ask only for missing deployment-unit items as needed.

Usage example:

```text
framework/prompts/codex/05_update.mdを使ってください。
```

### `codex/06_scenario-test.md`

- Description: Validate application behavior in a task separate from deploy and update current results/evidence.
- Timing: After deploy, when validating behavior that resource existence cannot confirm.
- How to use: Pass Scenario ID, environment, alias when present, AWS account, and expected behavior. Even on failure, do not proceed to design changes, IaC repair, or redeploy in the same task.

Usage example:

```text
framework/prompts/codex/06_scenario-test.mdを使ってください。

Scenario ID: private-api-connectivity
Target environment: dev
Target alias: cde
Target AWS account: 123456789012
Expected behavior: 社内networkからprivate APIへ接続し、HTTP 200が返ること
AWS mutation: forbidden
Destructive operation: forbidden
```

## SDD iteration

When creating new designs with the chatbot:

```text
chatbot/service-design.md
  -> chatbotが出力したCodex prompt（詳細設計とmodelを作成）
  -> 03_implement.md
  -> 04_deploy.md
  -> 06_scenario-test.md（behavior確認が必要な場合だけ）
```

When the human directly edits existing detailed design:

```text
humanがdocs/designs/**/*.mdを修正（未commit）
  -> 05_update.md
  -> 06_scenario-test.md（behavior確認が必要な場合だけ）
```

If design changes need new human decisions, confirm them in chat before repository changes. Do not pass unconfirmed values, placeholders, or guesses to Codex.

## Task boundaries

- Codex prompts output by `service-design.md` change only detailed designs and models.
- `03_implement.md` changes only IaC and does not run AWS APIs.
- `04_deploy.md` leaves IaC unchanged and executes only authorized deploy/apply.
- `05_update.md` leaves human detailed design diffs unchanged and updates only models, IaC, and generated current values, then deploys/applies.
- `06_scenario-test.md` changes only scenarios/results, without repairing designs or IaC.
- Do not treat deploy success as application behavior PASS.

### `codex/07_destroy.md`

Independent infrastructure phase `destroy`, invoked by `/destroy <StackName> [<StackName> ...]`. Resolve one explicit target and local JSON ownership/reservation plan, register the contract, then run cloudformation-destroy.py with external resumable state. Destroy checks context/StackId/protection/nested/export-import dependencies, deletes reverse DeployOrder with bounded concurrency, and batches proven-success observed updates. No deploy preparation, IaC validation, change sets, force delete, retained-resource cleanup, or scenarios. Complete with one scoped task loop.
