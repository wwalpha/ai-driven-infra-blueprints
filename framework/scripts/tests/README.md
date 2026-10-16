# Framework test layout

Production CLIs and reusable production modules remain directly under `framework/scripts/` (and its production packages). `model-test.py` generates human-run audit scripts; `model_test_runtime.py` supplies their embedded runtime. Both are production code.

All Framework regression entries and test-only helpers live here. Classification follows executed responsibilities, not filenames. Mixed suites remain intact in `unknown/`; this move does not split, merge, delete or optimize cases.

| Directory | Python files | Responsibility |
| --- | ---: | --- |
| `units/` | 3 | Isolated function/class behavior, with mocks or local input files. |
| `integrations/` | 18 | Connected Model, reference, staging, synchronization or comparison execution paths. |
| `unknown/` | 52 | Mixed unit/integration responsibilities; see reasons below. |
| `support/` | 15 | Existing shared test fixtures and validator check modules. |

`conftest.py` and `pytest.ini` are test configuration and are counted separately. `support/validation_checks/` is test-only; the production `validation/` package remains outside this tree. Production code has no imports of these test helpers.

## Execution

From the repository root (inside a managed worktree, prepend the `framework/scripts/run-python.py` wrapper as documented in the root README):

```console
python3 -m pytest --collect-only -q framework/scripts/tests
python3 -m pytest -q framework/scripts/tests
python3 -B framework/scripts/tests/units/test_issues_iac.py
python3 -B framework/scripts/tests/integrations/service-parameter-inputs.checks.py
python3 -B framework/scripts/tests/unknown/model_design.checks.py
python3 -B framework/scripts/blueprint-loop.py --mode full --task-file tasks/<task-name>.md
```

pytest collects only the existing pytest suites named in `pytest.ini`, plus `test_*.py`. Plain script suites retain their direct entrypoints and must not be imported as pytest suites. The previously standalone `test_issues_iac.py` is also discoverable by pytest. The loop retains its existing Full targets: every `*.checks.py` below this directory, ordered by filename. The standalone unittest is run directly or through pytest; it is not newly added to Full.

`--affected` retains exact dependency mappings at the new paths. Shared or unknown dependencies and unresolved deletion/rename sources still select all regression. Test bootstrap paths resolve only Framework scripts/helpers; fixtures continue to use synthetic temporary projects, without a new dependency on the executing repository's `model/` or `project.json`.

## File moves

Paths below are relative to `framework/scripts/`. Filenames and test function names are retained.

| Before | After |
| --- | --- |
| `array_display.checks.py` | `tests/unknown/array_display.checks.py` |
| `attribute-reference-resolution.checks.py` | `tests/integrations/attribute-reference-resolution.checks.py` |
| `auxiliary-model-dependencies.checks.py` | `tests/integrations/auxiliary-model-dependencies.checks.py` |
| `aws_mapping.checks.py` | `tests/unknown/aws_mapping.checks.py` |
| `aws_mapping_catalog.checks.py` | `tests/unknown/aws_mapping_catalog.checks.py` |
| `aws_mapping_compare.checks.py` | `tests/unknown/aws_mapping_compare.checks.py` |
| `aws_mapping_display.checks.py` | `tests/unknown/aws_mapping_display.checks.py` |
| `blueprint-loop.checks.py` | `tests/unknown/blueprint-loop.checks.py` |
| `bound-anchor-name-change.checks.py` | `tests/integrations/bound-anchor-name-change.checks.py` |
| `bound-stack-name-change.checks.py` | `tests/integrations/bound-stack-name-change.checks.py` |
| `check-deploy-context.checks.py` | `tests/unknown/check-deploy-context.checks.py` |
| `check-model-aws.checks.py` | `tests/unknown/check-model-aws.checks.py` |
| `cloudformation-deploy.checks.py` | `tests/unknown/cloudformation-deploy.checks.py` |
| `cloudformation-destroy.checks.py` | `tests/unknown/cloudformation-destroy.checks.py` |
| `cloudformation-naming.checks.py` | `tests/unknown/cloudformation-naming.checks.py` |
| `cloudformation_schema.checks.py` | `tests/unknown/cloudformation_schema.checks.py` |
| `cloudtrail-input-reference.checks.py` | `tests/integrations/cloudtrail-input-reference.checks.py` |
| `compact-model-sources.checks.py` | `tests/integrations/compact-model-sources.checks.py` |
| `compare-environments.checks.py` | `tests/unknown/compare-environments.checks.py` |
| `comparison_core.checks.py` | `tests/unknown/comparison_core.checks.py` |
| `deploy_preparation.checks.py` | `tests/unknown/deploy_preparation.checks.py` |
| `design_catalog.checks.py` | `tests/unknown/design_catalog.checks.py` |
| `design_document.checks.py` | `tests/unknown/design_document.checks.py` |
| `design_layout.checks.py` | `tests/unknown/design_layout.checks.py` |
| `eventbridge-producer-name-reference.checks.py` | `tests/integrations/eventbridge-producer-name-reference.checks.py` |
| `export-design-pdf.checks.py` | `tests/unknown/export-design-pdf.checks.py` |
| `framework-input-isolation.checks.py` | `tests/unknown/framework-input-isolation.checks.py` |
| `glue_datazone_catalog.checks.py` | `tests/unknown/glue_datazone_catalog.checks.py` |
| `group-03-input-references.checks.py` | `tests/integrations/group-03-input-references.checks.py` |
| `human-inputs-group-05.checks.py` | `tests/unknown/human-inputs-group-05.checks.py` |
| `import-model.checks.py` | `tests/unknown/import-model.checks.py` |
| `issue_gate.checks.py` | `tests/unknown/issue_gate.checks.py` |
| `issues_api_only.checks.py` | `tests/integrations/issues_api_only.checks.py` |
| `issues_failed_services.checks.py` | `tests/unknown/issues_failed_services.checks.py` |
| `issues_policy_equivalence.checks.py` | `tests/unknown/issues_policy_equivalence.checks.py` |
| `issues_ref_returns.checks.py` | `tests/integrations/issues_ref_returns.checks.py` |
| `issues_scan.checks.py` | `tests/unknown/issues_scan.checks.py` |
| `json-yaml-document-hash.checks.py` | `tests/unknown/json-yaml-document-hash.checks.py` |
| `lambda-input-reference.checks.py` | `tests/integrations/lambda-input-reference.checks.py` |
| `lambda_permission.checks.py` | `tests/unknown/lambda_permission.checks.py` |
| `legacy-lambda-dependencies.checks.py` | `tests/integrations/legacy-lambda-dependencies.checks.py` |
| `model-input-context-digest.checks.py` | `tests/unknown/model-input-context-digest.checks.py` |
| `model-test.checks.py` | `tests/unknown/model-test.checks.py` |
| `model_design.checks.py` | `tests/unknown/model_design.checks.py` |
| `model_files.checks.py` | `tests/unknown/model_files.checks.py` |
| `model_impact.checks.py` | `tests/unknown/model_impact.checks.py` |
| `model_parameter_inputs.checks.py` | `tests/unknown/model_parameter_inputs.checks.py` |
| `model_templates.checks.py` | `tests/unknown/model_templates.checks.py` |
| `policy_tables.checks.py` | `tests/unknown/policy_tables.checks.py` |
| `producer-identifier-reference.checks.py` | `tests/unknown/producer-identifier-reference.checks.py` |
| `producer-name-reference.checks.py` | `tests/integrations/producer-name-reference.checks.py` |
| `quicksight-display.checks.py` | `tests/unknown/quicksight-display.checks.py` |
| `raw-bucket-name-reference.checks.py` | `tests/unknown/raw-bucket-name-reference.checks.py` |
| `regression_guard.checks.py` | `tests/unknown/regression_guard.checks.py` |
| `resource_mode.checks.py` | `tests/unknown/resource_mode.checks.py` |
| `rotation_schedule.checks.py` | `tests/unknown/rotation_schedule.checks.py` |
| `runtime-model.checks.py` | `tests/integrations/runtime-model.checks.py` |
| `s3-bound-anchor.checks.py` | `tests/integrations/s3-bound-anchor.checks.py` |
| `script_loader.checks.py` | `tests/units/script_loader.checks.py` |
| `security-group-input-reference.checks.py` | `tests/integrations/security-group-input-reference.checks.py` |
| `security_group_tables.checks.py` | `tests/unknown/security_group_tables.checks.py` |
| `service-parameter-inputs.checks.py` | `tests/integrations/service-parameter-inputs.checks.py` |
| `sync-existing-files.checks.py` | `tests/integrations/sync-existing-files.checks.py` |
| `sync-model.checks.py` | `tests/unknown/sync-model.checks.py` |
| `task_contract.checks.py` | `tests/unknown/task_contract.checks.py` |
| `update-catalog-lock.checks.py` | `tests/units/update-catalog-lock.checks.py` |
| `used-definition-inputs.checks.py` | `tests/unknown/used-definition-inputs.checks.py` |
| `validate-blueprint.checks.py` | `tests/unknown/validate-blueprint.checks.py` |
| `validation_cache.checks.py` | `tests/unknown/validation_cache.checks.py` |
| `validation_scope.checks.py` | `tests/unknown/validation_scope.checks.py` |
| `worktree_python.checks.py` | `tests/unknown/worktree_python.checks.py` |
| `worktree_task.checks.py` | `tests/unknown/worktree_task.checks.py` |
| `test_issues_iac.py` | `tests/units/test_issues_iac.py` |
| `test_support/model_sources.py` | `tests/support/model_sources.py` |
| `test_support/parameter_cases.py` | `tests/support/parameter_cases.py` |
| `test_support/pytest_cli.py` | `tests/support/pytest_cli.py` |
| `test_support/service_contracts.py` | `tests/support/service_contracts.py` |
| `test_support/service_fixtures.py` | `tests/support/service_fixtures.py` |
| `test_support/validator.py` | `tests/support/validator.py` |
| `validation_checks/cloudformation.py` | `tests/support/validation_checks/cloudformation.py` |
| `validation_checks/contracts.py` | `tests/support/validation_checks/contracts.py` |
| `validation_checks/design.py` | `tests/support/validation_checks/design.py` |
| `validation_checks/references.py` | `tests/support/validation_checks/references.py` |
| `validation_checks/runner.py` | `tests/support/validation_checks/runner.py` |
| `validation_checks/scenario.py` | `tests/support/validation_checks/scenario.py` |
| `validation_checks/scope.py` | `tests/support/validation_checks/scope.py` |
| `validation_checks/task.py` | `tests/support/validation_checks/task.py` |
| `validation_checks/terraform.py` | `tests/support/validation_checks/terraform.py` |
| `conftest.py` | `tests/conftest.py` |
| `pytest.ini` | `tests/pytest.ini` |

## Unknown classification reasons

| File | Reason |
| --- | --- |
| `array_display.checks.py` | 配列行の境界値・例外と、全catalog/schemaを用いる表示往復検証が混在。 |
| `aws_mapping.checks.py` | Registry/cacheの単体検証と、取得・比較・表示・IMPORT展開の結合検証が混在。 |
| `aws_mapping_catalog.checks.py` | schema/SDK/cacheの個別契約と、catalog/Mapping全体の整合性検証が混在。 |
| `aws_mapping_compare.checks.py` | 値変換・不正定義の拒否と、SDK fixtureから比較結果までの結合検証が混在。 |
| `aws_mapping_display.checks.py` | 個別表示・選択値検証と、Model/Markdown投影・保存検証が混在。 |
| `blueprint-loop.checks.py` | 選択・診断・終了コードの単体検証と、子プロセス・Git snapshot・実Validatorの結合検証が混在。 |
| `check-deploy-context.checks.py` | target読込・mock応答の個別検証と、接続先・認証・deploy事前判定の連携検証が同じmainに集約。 |
| `check-model-aws.checks.py` | 正規化・比較・mask処理と、SDK/CLI/サービスadapter経路の結合検証が混在。 |
| `cloudformation-deploy.checks.py` | scheduler/helperの境界値と、session/repair/delivery/observedの結合検証が混在。 |
| `cloudformation-destroy.checks.py` | 依存順・事前判定と、controller/session/observedの結合検証が混在。 |
| `cloudformation-naming.checks.py` | 名前・式解決の個別検証と、合成stack/template/import経路の検証が混在。 |
| `cloudformation_schema.checks.py` | schema型・必須値・literal判定と、固定catalog/表示契約の整合性検証が混在。 |
| `compare-environments.checks.py` | parameter差分の境界値・例外と、CLI子プロセス検証が混在。 |
| `comparison_core.checks.py` | 純粋な比較・式評価と、複数モジュールの子プロセスimport順・同一性検証が混在。 |
| `deploy_preparation.checks.py` | rule section/hash/timingの個別検証と、準備・生成・controller連携検証が混在。 |
| `design_catalog.checks.py` | schema/表示の個別契約と、Markdown生成・Validator・子プロセス検証が混在。 |
| `design_document.checks.py` | snapshot/indexの個別検証と、参照fixture・投影・Validatorの結合検証が混在。 |
| `design_layout.checks.py` | 表示・anchor・属性の個別検証と、生成・Validator・参照の往復検証が混在。 |
| `export-design-pdf.checks.py` | bundle/linkの個別検証と、mock converterを使ったexport経路・出力保持検証が混在。 |
| `framework-input-isolation.checks.py` | Validation scope/Findings/cacheの個別検証と、実Validatorの入力隔離検証が混在。 |
| `glue_datazone_catalog.checks.py` | schema/literalの個別判定と、Model/Markdown同期・投影検証が混在。 |
| `human-inputs-group-05.checks.py` | 型・制約・丸めなどの入力境界値と、宣言・展開・保存・影響範囲の結合検証が混在。 |
| `import-model.checks.py` | 入力値・補助処理の単体検証と、mock AWSによる取得・保存・rollback・worktree経路が混在。 |
| `issue_gate.checks.py` | issue解析・scope判定と、契約・CLI・保存gateの結合検証が混在。 |
| `issues_failed_services.checks.py` | KMS形式・symbol比較の個別判定と、複数service/template/reportの結合検証が混在。 |
| `issues_policy_equivalence.checks.py` | Action/JSON比較の境界値と、local export/import・IAM/S3比較の結合検証が混在。 |
| `issues_scan.checks.py` | 比較・reference・reportの個別検証と、scan/save/reuse/concurrency・子プロセス経路が混在。 |
| `json-yaml-document-hash.checks.py` | canonical JSON/hashの単体検証と、展開・YAML更新・再実行・provenance検証が混在。 |
| `lambda_permission.checks.py` | Permission表示・引数拒否と、Model生成・参照・保存の結合検証が混在。 |
| `model-input-context-digest.checks.py` | digestの型・順序契約と、展開・入力依存・影響範囲の結合検証が混在。 |
| `model-test.checks.py` | mask/report等のruntime単体検証と、監査コード生成・合成CLI実行・結果検証が混在。 |
| `model_design.checks.py` | 命名・行変換・表示等の単体検証と、生成・保存・service rollback・Validatorが混在。 |
| `model_files.checks.py` | parts/境界値/読込例外と、CLI trace・同期・deploy選択の結合検証が混在。 |
| `model_impact.checks.py` | 依存・identity・削除判定と、Git差分・複数環境・Validator scopeの結合検証が混在。 |
| `model_parameter_inputs.checks.py` | schema/入力の単体検証と、複数serviceの展開・保存・同期・依存検証が混在。 |
| `model_templates.checks.py` | parser/cache等の個別検証と、展開・publish・rollback・環境伝播・Validatorが混在。 |
| `policy_tables.checks.py` | policy/statement行の個別検証と、生成・投影・grouping・Validatorが混在。 |
| `producer-identifier-reference.checks.py` | reference schemaの単体拒否検証と、producer選択・展開・依存更新の結合検証が混在。 |
| `quicksight-display.checks.py` | display_rowsのalias出力検証と、expanded_designを経由する往復検証が同じmainに混在。 |
| `raw-bucket-name-reference.checks.py` | reference schemaの型・format拒否と、producer JSON/link展開・依存更新が混在。 |
| `regression_guard.checks.py` | password/hash等の単体検証と、登録file・CLI・Full認証gateの検証が混在。 |
| `resource_mode.checks.py` | mode/naming判定と、IMPORT表示・生成・投影・Validator・同期検証が混在。 |
| `rotation_schedule.checks.py` | rotation表示・不正値と、Model往復・secret参照・同期検証が混在。 |
| `security_group_tables.checks.py` | port/表形式の個別検証と、生成・投影・複数Validator検証が混在。 |
| `sync-model.checks.py` | newline/選択/例外等の個別検証と、投影・publication・rollback・readback検証が混在。 |
| `task_contract.checks.py` | path/選択等の個別契約と、Git worktree・並行予約・Validator・保存検証が混在。 |
| `used-definition-inputs.checks.py` | 宣言・binding入力境界値と、expand/save/reload契約が単一checkに混在。 |
| `validate-blueprint.checks.py` | 補助check群にdispatch/collector単体契約と、design/CFn/Terraform/Taskの結合検証が混在。 |
| `validation_cache.checks.py` | cache key/load/saveの個別契約と、Model依存・catalog入力・scope更新検証が混在。 |
| `validation_scope.checks.py` | scope判定の個別検証と、共有template消費先・生成・cache・実Validator検証が混在。 |
| `worktree_python.checks.py` | 出力decode・runtime判定の単体検証と、Git worktree・Python setup・並行操作検証が混在。 |
| `worktree_task.checks.py` | base/path/metadata境界値と、実Git lifecycle・CLI・loopの結合検証が混在。 |
