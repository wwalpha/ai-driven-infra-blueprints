# task-20260726-blueprint-governance-migration Result

## Objective

Migrate the repository from the superseded Copilot / legacy GitHub workflow / CloudFormation-only governance structure to the agreed ChatGPT + human + Codex blueprint without changing AWS implementation behavior. This task selected no IaC engine for execution and forbade every AWS mutation.

## Files read during preflight

### Root

- `AGENTS.md`
- `README.md`
- `CMD.md`

### Legacy GitHub workflow

- `.github/copilot-instructions.md`
- `.github/instructions/cloudformation.instructions.md`
- `.github/instructions/designs-llm.instructions.md`
- `.github/instructions/designs.instructions.md`
- `.github/instructions/scenario-tests.instructions.md`
- `.github/prompts/existing-stack-change.prompt.md`
- `.github/prompts/new-stack.prompt.md`
- `.github/prompts/scenario-test-only.prompt.md`
- `.github/prompts/standard-infra-change.prompt.md`

### Existing human and LLM design

- `docs/designs/alb.md`
- `docs/designs/ec2.md`
- `docs/designs/naming-rules.md`
- `docs/designs/post-deploy-actual-values.md`
- `docs/designs/security-group.md`
- `docs/designs/subnet.md`
- `docs/designs/vpc.md`
- every file formerly under `docs/designs/_llm/`

### Existing implementation, tests, and historical evidence

- all three files under `infra/cloudformation/templates/`
- all three files under `infra/cloudformation/parameters/`
- both files under `tests/scenarios/`
- `tests/results/web-nginx-review-pending.md`
- `tests/results/web-nginx-scenario.md`

The historical result confirms that the app, security, and network stacks all reached `DELETE_COMPLETE` on 2026-03-27. The old physical IDs, IPs, DNS names, state values, and generated ARNs in the former current-design documents were therefore treated as historical, not current.

### Materials catalog

- all 81 filenames under `materials/aws/` were inventoried
- representative and sample-relevant contents were read for Athena, S3, VPC, Internet Gateway, VPC attachment, EIP, NAT Gateway, Subnet, Route Table, Route, association, Security Group, ingress/egress, EC2 Instance, IAM Role, and IAM Instance Profile
- material syntax was observed as `<Namespace>.<ResourceType>.<PropertyPath>=`

## Baselines captured

Before substantive migration edits:

- `materials-baseline.sha256`: 81 files
- `cloudformation-templates-baseline.sha256`: 3 files
- `cloudformation-parameters-baseline.sha256`: 3 files
- `scenarios-baseline.sha256`: 2 files

The complete received task prompt was copied to `tasks/task-20260726-blueprint-governance-migration/prompt.md`. Its SHA-256 matched the received attachment:

```text
413c0ef084c9dfda4432bb3fed317566f7b267b1645872a4f79f3e98bb1d2eb8
```

## Files created

### Governance

- `rules/detailed-design.md`
- `rules/llm-design-information.md`
- `rules/cloudformation.md`
- `rules/terraform.md`
- `rules/post-deploy-actuals.md`
- `rules/loop-engineering.md`
- `tasks/task-20260726-blueprint-governance-migration/prompt.md`
- `infra/terraform/README.md`

### Human design groups

- `docs/designs/internet-gateway.md`
- `docs/designs/elastic-ip.md`
- `docs/designs/nat-gateway.md`
- `docs/designs/route-table.md`
- `docs/designs/iam-role.md`
- `docs/designs/instance-profile.md`
- `docs/designs/load-balancer.md`

### LLM information

- `llm/designs/naming-rules.properties`
- `llm/designs/vpc.properties`
- `llm/designs/internet-gateway.properties`
- `llm/designs/elastic-ip.properties`
- `llm/designs/nat-gateway.properties`
- `llm/designs/subnet.properties`
- `llm/designs/route-table.properties`
- `llm/designs/security-group.properties`
- `llm/designs/iam-role.properties`
- `llm/designs/instance-profile.properties`
- `llm/designs/ec2.properties`
- `llm/designs/load-balancer.properties`
- `llm/actuals/dev/deployment.properties`

### Loop and evidence

- `scripts/blueprint-loop.sh`
- `scripts/validate-blueprint.py`
- baseline and final SHA-256 manifests in this result directory
- this result file

## Files moved or renamed

- root `CMD.md` → `tasks/task-20260327-web-nginx/prompt.md`
  - historical body preserved
  - a separated metadata note states that the completed superseded task is not current AWS authorization
- design group `docs/designs/alb.md` → `docs/designs/load-balancer.md`
- the former combined VPC, subnet, and EC2 documents were split into the agreed human resource groups while preserving intended sample architecture

## Files deleted

- the complete `.github/` directory and its nine tracked workflow files
- the complete obsolete `docs/designs/_llm/` directory and its seven tracked helper files
- root `CMD.md` after historical migration
- `docs/designs/alb.md` after load-balancer regrouping
- `docs/designs/post-deploy-actual-values.md` after selective actual policy moved to `rules/post-deploy-actuals.md`

Historical `tests/results/*.md` files were intentionally retained without rewriting their old facts or terminology.

## Old rules retained

- read and update human design before IaC
- do not guess missing design values
- keep human and machine-readable design synchronized
- use scenario tests that verify behavior rather than only static configuration
- save Markdown evidence
- no nested CloudFormation stacks
- template boundaries based on change/rollback/dependency/deploy responsibility
- `1 template = 1 deploy responsibility`
- stable, minimal cross-stack references
- CloudFormation syntax/static validation and AWS CLI execution when authorized
- naming rules and the distinction between resource names and `Name` tags

## Old rules intentionally removed or replaced

- Copilot-specific execution wording
- active dependencies on the deleted GitHub workflow directory
- the old design-local LLM helper location
- CloudFormation-only project governance
- repository-level manual review gate after validate/plan
- old review-state commands and checkpoint flow
- obsolete `docs/test-results/` result path
- mandatory collect-everything post-deploy actual catalog
- generated ARN persistence as current actual information

## Design grouping migration

- `vpc.md`: VPC only
- `internet-gateway.md`: Internet Gateway only
- `elastic-ip.md`: both Elastic IPs
- `nat-gateway.md`: both NAT Gateways
- `subnet.md`: all four Subnets only
- `route-table.md`: all Route Tables, Routes, and associations
- `security-group.md`: both groups and separate ingress/egress rule tables
- `iam-role.md`: EC2 IAM Role and managed-policy attachment
- `instance-profile.md`: IAM Instance Profile
- `ec2.md`: both instances and UserData
- `load-balancer.md`: Load Balancer, Target Group, and Listener in separate sections/tables
- no unused S3 detailed-design file was created

Every resource-detail table now uses the exact `No. | Property | Value | Source / Comment` schema, sequential numbering per table, explicit stable anchors, and validated relative resource links.

Deleted sample current state was corrected to `NOT_DEPLOYED`; required generated fields are `PENDING_DEPLOY`. Old IDs, IPs, DNS values, runtime states, and generated ARNs remain only in historical result evidence. The AWS-managed `AmazonSSMManagedInstanceCore` ARN remains an intended design input.

## LLM migration

- intended design moved to `llm/designs/`
- group boundaries match the human detailed-design files
- related resources use logical references rather than physical IDs
- current dev state is recorded minimally under `llm/actuals/dev/deployment.properties`
- dev actual state contains `NOT_DEPLOYED`, region, evidence date, collection method, and historical evidence path
- no old physical ID or generated ARN is present in current LLM actual information

## Loop implementation and commands

The validator uses only Bash and the Python standard library. It checks task prompt presence, exact rule files, legacy directory removal, path scope, all four baselines, design grouping, table schema, numbering, explicit anchors, link resolution, LLM grouping/references, obsolete active dependencies, and generated ARN exclusion from actuals.

Commands executed:

```bash
bash -n scripts/blueprint-loop.sh
python3 -m py_compile scripts/validate-blueprint.py
bash scripts/blueprint-loop.sh \
  --task-id task-20260726-blueprint-governance-migration \
  --mode local
bash -n tests/scenarios/sh/web-nginx-scenario.sh
git diff --check
```

Observed check results:

- loop script syntax: PASS
- Python compile: PASS
- first local loop: PASS, 1,355 checks
- unchanged shell scenario syntax: PASS
- PowerShell runtime/parser check: NOT RUN because `pwsh` is unavailable
- CloudFormation validate/change set: NOT RUN because this governance task selected IaC engine `none`, required no AWS access, and forbade AWS mutation
- Terraform validation/plan: NOT RUN because no Terraform resource exists and this task selected IaC engine `none`
- deployed scenario runtime: NOT RUN because infrastructure behavior did not change and the sample environment is `NOT_DEPLOYED`

The final rerun results are recorded below after all evidence is complete.

## Targeted obsolete-dependency searches

Active governance, design, LLM, and Terraform guidance was searched for:

- legacy GitHub workflow paths
- obsolete design-local LLM helper paths
- `docs/test-results/`
- the old review-state workflow
- Copilot execution wording

Result: no active obsolete dependency found. Historical task/result evidence was excluded because it intentionally preserves historical facts. Validator source is also excluded from literal-path dependency searches because it must detect the forbidden legacy paths.

## Baseline/final comparison

Final manifests were regenerated deterministically and compared with `cmp`:

| Scope | Count | Result |
| --- | ---: | --- |
| `materials/aws/*` | 81 | MATCH |
| CloudFormation templates | 3 | MATCH |
| CloudFormation parameters | 3 | MATCH |
| scenario scripts | 2 | MATCH |

## AWS and Terraform execution

- no AWS CLI command was run in this migration
- no AWS API mutation was performed
- no CloudFormation deploy/update/execute/delete command was run
- no Terraform apply/destroy/import command was run

## Known catalog gaps

The current sample includes the following CloudFormation resource types without a corresponding `materials/aws/` file:

- `AWS::ElasticLoadBalancingV2::LoadBalancer`
- `AWS::ElasticLoadBalancingV2::TargetGroup`
- `AWS::ElasticLoadBalancingV2::Listener`

This gap was recorded only; `materials/aws/` was not modified.

## Risks and unresolved items

- `pwsh` is unavailable, so the unchanged PowerShell scenario was not re-parsed or run in this task.
- The migration validator is intentionally a local governance foundation, not an AWS deploy engine.
- No infrastructure is currently deployed, so runtime scenario behavior was not re-observed.
- unresolved design input: none for this governance migration.

## Final verification

- final `git diff --check`: PASS
- final loop script syntax: PASS
- final Python compile: PASS
- final local loop after evidence completion: PASS, 1,359 checks
- active obsolete-dependency search: PASS
- generated ARN actual search: PASS
- materials manifest comparison: PASS
- CloudFormation template manifest comparison: PASS
- CloudFormation parameter manifest comparison: PASS
- scenario script manifest comparison: PASS
- task result: PASS with the explicitly recorded non-applicable and unavailable checks above
