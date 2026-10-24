# UT / IT 全ケース台帳

## Python structure and callback compatibility

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `python-structure::module` | `test_module_imports_and_methods` | UT | [units/python_structure-unit.checks.py](units/python_structure-unit.checks.py) | unittest / 1 | モジュールImportと通常メソッドを許可 | Python品質 |
| `python-structure::nested` | `test_function_import_and_nested_definition` | UT | [units/python_structure-unit.checks.py](units/python_structure-unit.checks.py) | unittest / 1 | 関数内Importとネスト関数の位置を検出 | Python品質 |
| `python-structure::async` | `test_async_and_method_bodies` | UT | [units/python_structure-unit.checks.py](units/python_structure-unit.checks.py) | unittest / 1 | asyncとメソッド内違反を検出 | Python品質 |
| `python-structure::cli` | `test_cli_reports_location_and_failure` | UT | [units/python_structure-unit.checks.py](units/python_structure-unit.checks.py) | unittest / 1 | パス・行番号・終了コードと正常終了 | Python品質 |
| `function-wrapper::metadata` | `check_wrapper` | UT | [units/function_wrapper-unit.checks.py](units/function_wrapper-unit.checks.py) | pytest / 1 | 呼出結果・署名・メタデータ保持 | Python品質 |
| `function-wrapper::method` | `check_method_binding` | UT | [units/function_wrapper-unit.checks.py](units/function_wrapper-unit.checks.py) | pytest / 1 | instance/class経由のメソッド束縛 | Python品質 |

| `model-cli::entrypoints` | `check_cli_entrypoints` | UT | [units/model_files-unit.checks.py](units/model_files-unit.checks.py) | pytest / 1 | 直接起動と公開mainのhelp一致・既存Module起動結果保持 | Python品質 |

## Issues package, artifact v2 and isolated cfn-lint

既存deploy lint廃止は復元しない。旧workerの設定/schema/custom rule状態隔離とscope回収契約をutils入口で検証する。Framework定義は読取専用、一時HOME/config/rule/schemaは独立fixtureとする。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `issues-v2::check_classification` | `check_classification` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 9 | severity・E0000 provenance・特殊Error分類 | Issues v2 |
| `issues-v2::check_explicit_plan` | `check_explicit_plan` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | Stack parametersと独立した対象・共有dedup・owner・対象外 | Issues v2 |
| `issues-v2::check_v2_index_and_status` | `check_v2_index_and_status` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | 一次集計・page先行・未対応形式拒否・status・bounded notice・review照合 | Issues v2 |
| `issues-v2::check_dependency_guards` | `check_dependency_guards` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | 外部config追加/変更・rule集合・runtime/HOME照合 | Issues v2 |
| `issues-v2::check_deferred_cache_finalization` | `check_deferred_cache_finalization` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | 最終入力確認まで候補保留・変更時不採用 | Issues v2 |
| `issues-v2::check_scan_cache_guard_order` | `check_scan_cache_guard_order` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | 集計→live guard→cache確定・stale/例外/中断時の不採用 | Issues v2 |
| `issues-v2::check_worker_protocol_and_fatal` | `check_worker_protocol_and_fatal` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | protocol拒否・共通runtime失敗後not_run | Issues v2 |
| `issues-v2::check_cli_equivalence` | `check_cli_equivalence` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py) | pytest / 4 | 固定版CLIのRule/Severity/Path/位置/Message同等性 | Issues v2 |
| `issues-v2::check_config_exclusion_and_outputs` | `check_config_exclusion_and_outputs` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py) | pytest / 1 | config除外・抑制時coverage・output_file非書込・競合 | Issues v2 |
| `issues-v2::check_noecho_and_dependencies` | `check_noecho_and_dependencies` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py) | pytest / 1 | NoEcho mask・HOME/cwd config存在と内容変更 | Issues v2 |
| `issues-v2::check_rule_schema_state_and_reaping` | `check_rule_schema_state_and_reaping` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py) | pytest / 1 | custom rule/schema状態隔離・child異常後継続・回収 | Issues v2 |
| `issues-v2::check_legacy_worker_scope` | `check_legacy_worker_scope` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py) | pytest / 1 | 従来Worker/scope・CLI応答・例外回収 | Issues v2 |
| `issues-v2::check_offline_schema` | `check_offline_schema` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py) | pytest / 2 | provider/schema欠落・offline阻止・not_run | Issues v2 |
| `issues-v2::check_timeout` | `check_timeout` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py) | pytest / 1 | timeoutとhelper/child回収 | Issues v2 |
| `issues-v2::check_scan_publication_and_missing_view` | `check_scan_publication_and_missing_view` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py) | pytest / 2 | scan→review→atomic save・guard/cache順序・共有dedup・stale・欠落/不正UTF-8 Viewと独立lint | Issues v2 |

| `issues-v2::check_plan_without_stack` | `check_plan_without_stack` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 4 | IMPORT/API-only先行分類・混在CREATE未検証・Stack loader回数 | Issues v2 |
| `issues-v2::check_processing_coverage_keeps_matches` | `check_processing_coverage_keeps_matches` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 1 | schema障害時の未完了coverageと通常/未知type診断保持・exit 2 | Issues v2 |
| `issues-v2::check_failed_model_input_guards` | `check_failed_model_input_guards` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 5 | 欠落入口/part/参照先/不正UTF-8/読取不能の初回観測と保存前guard | Issues v2 |
| `issues-v2::check_first_model_observation_is_not_replaced` | `check_first_model_observation_is_not_replaced` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | 失敗中のpart追加・矛盾するhashを後追いsnapshotで隠せない | Issues v2 |
| `issues-v2::check_notice_resolution_and_update_series` | `check_notice_resolution_and_update_series` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | T1〜T4日時/scope・ordinary解消ID・legacy/別scope/Human保全・save-results非再実行 | Issues v2 |
| `issues-v2::check_view_read_failure_policy` | `check_view_read_failure_policy` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | issues局所View障害・独立service/source診断・実チェック件数・非cache・raw guard・通常Validator伝播 | Issues v2 |
| `issues-v2::check_corrupt_provider_schema` | `check_corrupt_provider_schema` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py) | pytest / 2 | 隔離cacheのJSON/Schema構築障害・通常文字列のresource_typeによる実worker間の診断返却・診断0件/混在保持・未知type/override非誤分類・回収 | Issues v2 |
| `issues-v4::check_child_builtin_packets_preserve_progress` | `check_child_builtin_packets_preserve_progress` | UT | [units/issues-lint-unit.checks.py](units/issues-lint-unit.checks.py) | pytest / 2 | JSON組込み型へのIPC正規化・途中例外でも取得済み全channel/dependencies保持 | Issues residual repair |
| `issues-v4::check_scan_dependency_view_failure` | `check_scan_dependency_view_failure` | IT | [integrations/issues-lint.checks.py](integrations/issues-lint.checks.py) | pytest / 3 | scope外S3のUTF-8/欠落/permission障害・SQS未検証・独立Logs差分と実lint・非cache・raw変更guard・通常Validator伝播 | Issues residual repair |
| `issues-v4::check_notice_fenced_roundtrip` | `check_notice_fenced_roundtrip` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 2 | headerless owner/ID/Gate・backtick/tildeコード例・legacy/別scope・normal/notice/save-results解消往復 | Issues residual repair |
| `issues-v4::check_notice_marker_boundaries` | `check_notice_marker_boundaries` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py) | pytest / 1 | scope不一致/未完marker/HTML保持・長いfence・正常notice再接続 | Issues residual repair |


## Ordinary receiving-property reference contracts

既存の `units/model-markdown-reference.checks.py::main` に、Glue.Connection 001/002の2要素配列、各位置のS3型違反、不在・曖昧警告、明示契約なし、document除外、Name/observedとIMPORT契約、通常配列と明示JSON禁止の境界、保存・生成・再読取の値と順序不変を追加。入口数は変更しない。

## JSON Resource ARN projection

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `json-resource-arn::confirmed` | `check_confirmed_identifiers` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 12 | KeyId UUID/mrk・BucketNameのみ、実行account優先/fallback、3 partition、複数参照、表示・hash、既存属性、Modelバイト不変、AWS client禁止 | JSON projection |
| `json-resource-arn::generation` | `check_generation_and_snapshot_boundary` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 1 | confirmed observed、generate_files/generate_views成果物、anchor保持、正本不変、producer project最終比較 | JSON projection |
| `json-resource-arn::invalid` | `check_invalid_identifiers` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 35 | 欠落、placeholder、未解決link、不正KeyId/BucketName、Alias ARN、予約名・非Bucket拒否 | JSON projection |
| `json-resource-arn::ambiguous` | `check_ambiguous_identifiers` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 6 | 同値/異値/UNSETを含む複数候補拒否 | JSON projection |
| `json-resource-arn::duplicate-bucket` | `check_duplicate_bucket_resource` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 1 | producer内の複数Bucketで同一BucketNameを拒否 | JSON projection |
| `json-resource-arn::observations` | `check_unconfirmed_observations` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 10 | 未確定/不正observed、観測元link不在・非論理値、producer不在の拒否 | JSON projection |
| `json-resource-arn::target` | `check_unconfirmed_target` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 20 | producer Region/accountの欠落・不正、SDKにないRegion/partition拒否 | JSON projection |
| `json-resource-arn::unsupported` | `check_unsupported_references` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 6 | 不在・曖昧anchor、非対応属性/ObjectArn、KMS Alias/他TypeのARN導出拒否 | JSON projection |

## Independent AWS JSON

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `standalone-json::expressions` | `check_standalone_expressions` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 15 | 設計intrinsic/文字列化式は保持またはローカル解決、未解決WARNINGとPointer escape、AWS JSON/hashは拒否、裸pseudo/dynamicはERROR、入力不変 | JSON projection |
| `standalone-json::generation` | `check_standalone_generation` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 1 | 正常IAM変数・JSON/表示/hash一致、後続JSONの不正GetAtt構造で先行成果物を保存せず既存成果物/Model保持 | JSON projection |
| `standalone-json::cfn-boundary` | `check_standalone_and_cfn_boundaries` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 1 | 通常値/型とIAM変数保持、CFn YAMLタグと既存式評価維持 | JSON projection |
| `design-json::pending-intrinsics` | `check_pending_intrinsic_generation` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 17 | Ref/Fn全般とネスト、未対応関数はWARNING、Model保存/生成/表示成功、原式保持、AWS直接適用拒否 | Synthetic Model JSON |
| `design-json::api-intrinsics` | `check_api_json_intrinsics` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 1 | API設定JSONでも式だけ保留、リテラルの型・制約と不正構造のERRORを維持 | Synthetic JSON |
| `design-json::policy-siblings` | `check_pending_policy_siblings` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 1 | 未解決Sid/Resourceを保留し、隣接Effect/Resource/Sidの不正とAWS適用拒否を維持 | Synthetic policy |
| `design-json::invalid-intrinsics` | `check_invalid_intrinsic_structure` | UT | [units/json-resource-arn-unit.checks.py](units/json-resource-arn-unit.checks.py) | pytest / 9 | 既存intrinsic構造契約と評価器で証明された不正構造、JSON構文不正はERROR | Synthetic Model JSON |
| `issues-iac::intrinsic-warnings` | `IntrinsicWarningTests.test_unresolved_leaves_keep_other_comparisons_and_report_counts` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | 未解決式は未比較と警告、同じ式でもMATCH禁止、隣接確定値の一致/差分、未比較集計とAWS境界 | Synthetic CFn |
| `issues-iac::intrinsic-local` | `IntrinsicWarningTests.test_local_functions_resolve_with_proven_stack_inputs` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | Ref/Sub/Join/Split/Select/If/FindInMapは確定入力だけで評価、構造不正はERROR | Synthetic CFn |
| `standalone-json::resource-types` | `check_resource_types` | UT | [units/policy_tables-unit.checks.py](units/policy_tables-unit.checks.py) | pytest / 12 | Resource/NotResourceのobject・混合配列・非string scalar拒否 | Policy |
| `standalone-json::valid-resources` | `check_valid_resource_types` | UT | [units/policy_tables-unit.checks.py](units/policy_tables-unit.checks.py) | pytest / 4 | string/string配列、Statement object、Principal/NotAction/Condition、IAM変数を維持 | Policy |

## Framework定義不変による削除

定義ファイルはコピー先も含めて変更・追加・削除しない。現行定義の共有参照、メモリ上の入力辞書・既存Mockによるコード検証、独立した読取例外は維持する。同期処理の仮txt・Frameworkコードは固定Framework定義に含めない。

| 全体削除 | 関数 |
|---|---|
| `integrations/model_design.checks.py` | `check_design_naming_preflight` |
| `units/aws_definitions.checks.py` | `check_lazy_parallel_and_mutation` |
| `units/aws_mapping-unit.checks.py` | `check_ownership_errors` |
| `units/aws_mapping_compare-unit.checks.py` | `check_missing_catalog_field` |
| `units/aws_mapping_display-unit.checks.py` | `check_group_projection` |
| `units/aws_mapping_display-unit.checks.py` | `check_mapping_display_rows` |
| `units/aws_mapping_display-unit.checks.py` | `check_validation_projection_semantics` |
| `units/validation_checks/design.py` | `check_catalog_display_order` |

| 部分削除 | 残す責務 |
|---|---|
| sync-model `check_publication_boundary[mapping]` | source/project/part/consumer/extra/contractの6条件 |
| design_catalog `main` のMapping・命名規則・Schema書換え依存経路 | 現行QuickSight表示・Macie Schema正常値と異常値23件、S3リンクlabel・bucketCriteria/JSON競合 |
| design_layout `check_workflow` の架空Resource/Layout変更 | 現行layout、正常/異常文書、group child・参照・親移動 |
| blueprint-loop のRule変更・移動シナリオ | Model/Task/IaCのscope、空白検証、Frameworkコード変更の回帰選択 |
| deploy_preparation `check_stale_and_conflicts[input]` | issue/runtime/契約候補/Model/生成物の変更・削除 |
| cloudformation-deploy `check_session_cli` のRule変更条件 | IaC/Model/契約/コード・project変更、resume・保存保護 |
| aws_mapping `check_runtime_cache`、`check_runtime_failures[parse]` | root/scopeの再利用、独立したread/runtime/control例外 |
| aws_mapping `check_readonly_defaults` のMapping default差替え | Field.copy_defaultのstandalone埋込互換性 |
| aws_mapping_catalog `schema_checks` のファイル作成・変更 | メモリ上の不正Mapping入力と現行Mappingの正常性 |
| aws_definitions の定義編集・架空Schema/Catalog | SDK lifetime、現行定義の読取例外・依存分離・stage生存 |
| validation_cache のFramework定義編集 | Cache破損・fresh・README/Model/Taskの変更・権限・最終比較 |
| validation_checks/design のCatalog/Schema破損・架空Catalog | 現行定義の整合性、通常の設計値と行順・名前・CIDR検証 |
| validation_checks/contracts のRule/Prompt編集 | 現行のPrompt/Rule/リンク・節・回帰選択 |
| model_design `check_service_scoped_naming` の仮Rule | 現行service限定の読取と命名検証 |
| deploy_preparation `check_rule_section_boundaries` の仮Ruleファイル | 文字列による節・anchor・重複・境界検証 |
| policy_tables `mapping_cache_checks` の改名・破損Mapping | 同一定義のroot別cache分離と再利用 |
| update-catalog-lock `main` のCatalogファイル生成・改変 | POSIX/Windowsのcatalogファイル順序 |

IMPORTのLogGroup限定ケースは既存の `resource_types=['Logs.LogGroup']` を明示し、Mappingを縮小せずに従来の取得対象・assertionを維持する。

Fixture整理：`aws_mapping_display_fixtures.change`、`aws_definitions.write/fixture`、各削除経路内の専用helperを削除。所有一覧の絞込み、Logs Mapping縮小、仮の命名Rule・縮小Catalog作成を削除し、通常検証に必要な既存定義は実Frameworkを共有参照する。

台帳登録/展開数：UT 260/590 → 255/585（削除分）→ 397/959（未登録142件の補完・既存parameter件数1件訂正後）→ 398/960（CodeCommit返却属性1件追加）、IT 371/590 → 370/588。直接実行内部の部分削除は入口1件のままとし、検証地点・内部パターンを更新した。

## IMPORT optional-name display

The existing `units/design_layout-unit.checks.py::check_resource_display_names` excludes catalog IDENTIFIER_OUTPUT fields from confirmed-value checks and configured-name selection, using Glue self-references, PENDING_DEPLOY and physical names in short/formal rows. CREATE missing names, IMPORT labels and UNSET configured names retain their checks. Existing `integrations/model_design.checks.py::check_naming_exclusions` also checks Glue identifier observations and Markdown rows without changing desired references, plus identifier-specific validation. Definitions and entrypoint counts remain unchanged.

The existing `units/design_layout-unit.checks.py::check_resource_display_names` also checks shared selection for optional IMPORT names, CREATE rejection, missing labels, unconfirmed selected names, schema-required names and IAM/CodeBuild exceptions. Framework definitions remain unchanged.
The existing type-display constraint cases accept the shared selection error for missing required names; the anchor/reference unit isolates presentation at its current boundary without mocking the moved naming validator. Expansion counts remain unchanged.
Existing Import publication cases retain selected self-reference names and resolve only their own saved observations for presentation. Existing anchor-tampering cases retain warning severity. The CREATE Security Group heading fixture now selects its formal GroupName; no Framework definitions are changed.
The Security Group table IT also selects an independent formal GroupName for its second CREATE resource, retaining tag-scalar cases introduced on the latest base.

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `import-display::optional-name` | `check_import_optional_name_label` | IT | [integrations/model_design.checks.py](integrations/model_design.checks.py) | pytest / 1 | Config IMPORT任意Name未選択の生成・表示検証・同期、正式名優先、CREATE/不正値/欠落必須/ID不一致/別ラベル拒否、正本とanchor不変 | Display |

## Static fixture cases

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `fixture-cases::loading` | `check_loading_and_independence` | UT | [units/fixture_cases-unit.checks.py](units/fixture_cases-unit.checks.py) | pytest / 1 | base浅い上書き、複数ケース、独立性、cache保護と再読込一致 | Fixture |
| `fixture-cases::schema` | `check_invalid_schema` | UT | [units/fixture_cases-unit.checks.py](units/fixture_cases-unit.checks.py) | pytest / 1 | 重複キー、schema/version/ID/値型/再帰データ拒否 | Fixture |
| `fixture-cases::files` | `check_materialize_files` | UT | [units/fixture_cases-unit.checks.py](units/fixture_cases-unit.checks.py) | pytest / 1 | 複数ファイル、UTF-8/空白/改行保持、逸脱/symlink/衝突拒否 | Fixture |
| `fixture-cases::authored` | `check_authored_suite` | UT | [units/fixture_cases-unit.checks.py](units/fixture_cases-unit.checks.py) | pytest / 1 | issues_scanの2ケース読込、service順序、malformed末尾改行 | Fixture |

## SecurityGroup tag scalar / Markdown metadata

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `sg-tags-scalar` | `check_tag_scalars` | UT | [units/security_group_tables-unit.checks.py](units/security_group_tables-unit.checks.py#check_tag_scalars) | pytest / 1 | YAML 7条件のscalar/引用符/backslash/日本語/JSON風/数値風/コメント境界/backtick、複数タグの順序・ペア・SG所有、GroupName分離、選択状態、既存IaC比較との一致 | 新規 |
| `sg-tags-invalid` | `check_invalid_tag_metadata` | UT | [units/security_group_tables-unit.checks.py](units/security_group_tables-unit.checks.py#check_invalid_tag_metadata) | pytest / 1 | YAML 10条件の不正JSON、配列/ペア/string型違反、生コメント境界を拒否 | 新規 |

既存IT `integrations/security_group_tables.checks.py::main` 内で、同じ7条件をproperties v2で保存・読取し、正式rendererでMarkdown生成・検証用展開する。Model authorityの不変を確認し、通常scalarの引用符期待値を訂正する。既存の正常系・不正metadata・配置・ルール・所有関係チェックは保持。静的データは `fixtures/security_group_tables.yaml` のみ、Framework定義は変更しない。入口は既存direct_group / 1のまま。

## Generation-local resource row reuse

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `resource-row-reuse::edits` | `check_resource_row_reuse_and_edits` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py) | pytest / 1 | 遅延解析、mapping分離、変更・追加・削除・順序、空入力、返却list保護、次回scope | sync |
| `resource-row-reuse::legacy` | `check_resource_row_legacy_and_invalid_entries` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py) | pytest / 1 | legacy prefix重複、不正rowの例外と評価タイミング | sync |
| `resource-row-reuse::lifetime` | `check_resource_row_scope_restoration` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py) | pytest / 1 | 入れ子scopeと実generate_viewsの正常・例外終了時復元 | sync |

## Limited Route53 ImportValue expressions

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `route53-import-expression::syntax` | `check_limited_import_expression` | UT | [units/route53-import-expression.checks.py](units/route53-import-expression.checks.py) | pytest / 1 | 限定式・file-level linkの形式、境界、通常literal制約 | Route53 |
| `route53-import-expression::validation` | `check_route53_import_expression_validation` | IT | [integrations/route53-import-expression.checks.py](integrations/route53-import-expression.checks.py) | pytest / 1 | 合成Model入力と生成Markdownの正常・異常判定一致 | Route53 |

## Import conversational consent and integrity

`units/import-approval-unit.checks.py` uses synthetic data only. The LLM owns explicit
final consent in chat; Python validates Review/candidate/receipt integrity without Host
mocks. The Import IT exercises the normal unpatched CLI publisher across processes,
source transactions, rollback, receipt guards and display generation. These fixtures do
not establish actual agent conversation quality or Human identity authentication.
Display structure failures reject before saving; display I/O failures and recovery
remain separate. Dry-run/incomplete/display-failed sessions are retained.

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `import-approval::typed-review` | `check_complete_typed_before_after_and_digest` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | Before/After・型・論理参照・物理値・digest | Import Review |
| `import-approval::inventory` | `check_full_inventory_required` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 3 | 全取得レコード・リスク・取得Typeの欠落拒否 | Import Review |
| `import-approval::changed-review` | `check_changed_review_needs_new_review` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 10 | 反映先・操作・値・参照・リスク・基準・Scope・Task・Worktree・型の変更 | Import Review |
| `import-approval::duplicate-risk` | `check_unknown_identity_risk_is_bound` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 既存ID不明の重複リスク | Import Review |
| `import-approval::type-status` | `check_inventory_status_and_exclusions_remain_visible` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 5 | 取得失敗・権限・filter・empty・completeの区別 | Import Review |
| `import-approval::native-values` | `check_array_boolean_name_and_unreflected_values` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 配列・Boolean・Name tag・未反映値 | Import Review |
| `import-approval::composite-secret` | `check_composite_identity_and_secret_omission` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 複合識別子・機密値非出力 | Import Review |
| `import-approval::observed` | `check_configuration_is_not_observed` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 3 | 通常設定のobserved保存拒否 | Pre-save |
| `import-approval::warning` | `check_valid_observation_and_nonblocking_reference_warning` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 識別子observed許可・Reference warning非ブロック・無関係既存行保持 | Pre-save |
| `import-approval::no-trusted-approval` | `check_local_claim_cannot_replace_review_binding` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 6 | 自己申告JSON・flag・HMACはReview bindingの代替にならない、証跡保持 | Fail-closed |
| `import-approval::alternate-writer` | `check_alternate_source_guard_rejects_legacy_receipt` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 既存receipt経由のModel保存拒否 | Fail-closed |
| `import-approval::expiry` | `check_expiry_and_digest_tampering` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 7日有効期限・digest改ざん拒否 | Import Review |
| `import-approval::unselected` | `check_unselected_reference_changes_are_not_reviewed_as_selected` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 非選択Resourceの変更拒否 | Import Review |
| `import-approval::review-command` | `check_review_command_is_read_only` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 4 | Review出力・baseline競合・承認flag・機密候補拒否、Model未変更 | Import Review |
| `import-approval::display` | `check_preflight_before_any_save` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 8 | Review一致・値/反映先/baseline/provenance不一致拒否、表示用展開・メモリ生成と構造エラー時のModel/証跡保持 | Pre-save |
| `import-approval::required-review` | `check_missing_review_rejected_before_candidate_load` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | Reviewなしの通常Publishは候補読込前に拒否 | Pre-save |
| `import-approval::reference-meaning` | `check_same_value_reference_meaning_is_bound` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 6 | 同一展開値でもselector・Definition参照宣言・Service・Property・Definition・input名変更でReview不一致 | Import Review |
| `import-approval::reference-metadata` | `check_reference_location_and_description_are_not_meaning` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 位置・説明文と派生observed traceはReference意味から除外 | Import Review |
| `import-approval::reference-schema` | `check_reference_proposal_uses_existing_contract` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 5 | 参照提案は既存宣言/type/fixed-target契約と正規化形式で検証 | Import Review |
| `import-approval::unselected-selector` | `check_unselected_reference_selector_is_rejected` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 未選択Resourceのselector変更を拒否 | Import Review |
| `import-approval::loader-provenance` | `check_real_loader_retains_unresolved_reference_declaration` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 実loaderが未解決参照のService/type/Property/selectorを保持、Review構造検証は非ブロック | Import Review |

| `import-approval::publication-transaction` | `check_publication_transaction_without_host` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L974) | pytest / 10 | Hostなしの正常保存、lock前Review/draft/candidate/acquisition/baseline変更・期限切れ拒否、実rollbackと表示保存失敗時のModel/証跡保持 | Publication |
| `import-approval::display-recovery` | `check_saved_display_recovery_needs_no_new_approval` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L982) | pytest / 1 | sync-modelの既存回復workerで保存済みModelを保持して表示のみ保存、取得/承認呼出なし | Recovery |
| `import-approval::unapproved-candidate` | `check_candidate_review_mismatch_rejected_without_host` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L988) | pytest / 4 | HostなしでもProperty・反映先・追加Resource・selector不一致を保存前拒否 | Publication |

| `import-chat::check_explicit_bind_preserves_identity` | `check_explicit_bind_preserves_identity` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 12 | bind正常、既知ID・stale・CREATE・型・重複・無効ID・Anchor/Row/未取得変更拒否 | Chat approval |
| `import-chat::check_subnet_answers_correction_and_resume` | `check_subnet_answers_correction_and_resume` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 複数SUBNET回答保持・訂正・session再開・baseline変更拒否。LLM判断品質の評価ではない | Chat approval |
| `import-chat::check_checkpoint_rejects_stale_or_competing_answers` | `check_checkpoint_rejects_stale_or_competing_answers` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 8 | 期限・基準・Task/Worktree/scope・取得差替え・競合回答拒否 | Chat approval |
| `import-chat::check_review_binding_integrity_without_host` | `check_review_binding_integrity_without_host` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 19 | HostなしのReview binding構造・全digest・期限と不要な認証fields拒否 | Chat approval |
| `import-chat::check_unanswered_review_cannot_be_approved` | `check_unanswered_review_cannot_be_approved` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 未回答を含むReviewは最終承認に渡せない | Chat approval |

| `import-chat::consent-contract` | `check_conversational_consent_contract` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 全件Review・明示同意・訂正/取消・曖昧回答・再確認・merge後確認の規約 | Chat consent |
| `import-chat::save-guard` | `check_approval_bound_save_guard` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L936) | pytest / 6 | 保存後の別候補・source hash・Task/Worktree・risk・旧証跡改ざんを保存guardで拒否（Human認証ではない） | Publication |

元パスは分離前の `framework/scripts/tests/` 相対。現在のリンクはこのファイルからの相対。分類は検証責務による。変更不要のケースも掲載。

共通参照target選択の診断は、欠落ID・型不一致・複数候補を区別して関連ITで検証する。model_filesのcache検証はtype/name/linkの各解決を1回に限定し、出力・終了コード一致と入力準備・parse再利用のassertを維持する。

## 数え方

| Case ID | Entry | Level | Suite | Runner / cases | Coverage | Boundary |
| --- | --- | --- | --- | --- | --- | --- |
| `s3-kms-reference::authority` | `check_authority_display_and_references` | UT | [units/s3-kms-reference-unit.checks.py](units/s3-kms-reference-unit.checks.py) | pytest / 2 | Alias/明示Key Arnの保存再読込、schema、Markdown/表示検証、incoming、IMPORT、stale、正本バイト不変・生成ARN非保存 | Synthetic Models |
| `s3-kms-reference::invalid` | `check_invalid_scalar` | UT | [units/s3-kms-reference-unit.checks.py](units/s3-kms-reference-unit.checks.py) | pytest / 11 | 不正属性/構造、Alias/他Type、不在/曖昧anchor、別targetを解決・最終候補guardで拒否 | Scalar contract |
| `s3-kms-reference::pending` | `check_pending_key_projection` | UT | [units/s3-kms-reference-unit.checks.py](units/s3-kms-reference-unit.checks.py) | pytest / 1 | 未作成KeyIdのまま既存Key表示名で投影し、ARN導出・AWSを要求しない | Display only |
| `s3-kms-reference::iac` | `check_iac_matrix` | UT | [units/s3-kms-reference-unit.checks.py](units/s3-kms-reference-unit.checks.py) | pytest / 11 | KeyArn一致、KeyId/別Key/AliasName/AliasArn不一致、未証明式・literal ARN uncompared、従来形式維持 | Synthetic CFn |
| `issues-iac::codecommit-name` | `ImportValueResolutionTests.test_codecommit_name_uses_only_explicit_repository_name` | UT | [units/test_issues_iac.py](units/test_issues_iac.py) | pytest / 1 | Name→RepositoryName、Ref RepositoryId区別、文字列一致/差分、未解決/非文字列/欠落、Condition/Transform/型/Resource・Stack曖昧性を保留、ネットワーク禁止 | Synthetic CFn |

CodeBuild PLAINTEXTの属性参照比較は `units/test_issues_iac.py::ImportValueResolutionTests.test_codebuild_plaintext_resource_attributes`
（UT / unittest 1 case）で検証する。合成Model identityとCFn定義を使用し、Key ARN/GetAtt、Alias ARN/Subと両Export値の一致、Key/Alias・別対象・別属性の不一致、未確定参照・不正selector、Export名literalの非一致、既存S3 BucketName参照を確認する。実行中repoのproject/Model入力・AWSは使用しない。

同UTに非S3属性不足の専用診断、非文字列返却属性、Secret/Typeコンテキスト、IMPORT受け渡し不足と具体値未証明の保留を追加。既存IT `issues_scan::check_reference_property_contract` はCodeCommit名literalのmatched/difference/uncompared、`check_aws_standard_comparison` はS3・Secret・明示Key ARN・Alias ARNの混在と異なる属性/Resource/未証明literal、親Environment JSONの属性不足/不正属性/非文字列を検証する。IT入口数は変更しない。

`units/validation_checks/design.py::check_cidr_pending_deploy` は既存VPC fixtureで識別情報失敗の回帰も検証する。`resource_logical_ids` のValueError、`design_model_values` のOSErrorを単独ファイル／後続正常サービスありの各条件で注入し、元診断・ファイルパスの完全一致、当該ファイルの後続展開停止、正常サービスのName検証到達、集約結果FAILを確認する。CREATE正常／Name欠落、IMPORTのName省略と両展開関数へのmodes伝達も確認する。実Model・AWS・ITは使用しない。

ケース数は実行入口の関数（unittestはメソッド）を数える。pytestは設定から静的に算出し、decoratorの直積を展開した数も併記する。直接実行の関数、callback、main/module内の検証地点は別欄。mainは複数シナリオを含むため、検証地点の明細を別表で網羅し、関数数へ水増し加算しない。ヘルパーのassertは共通検証として保持し、テストケース数に加算しない。動的ループは入力式を記載し、実行しないと決まらない件数を推測しない。

pytest件数はテスト定義・aliasと設定から算出する。直接実行入口で選択されるcallbackとpytestラッパーは重ねて合計しない。

## Lambda依存IT統合のassertion対応

下表の旧行・template/parameters/bindings という語は旧版での検証目的の記録です。properties v2 での現在の検査対象・意味変更は末尾の「Properties v2 reference and Import assertion mapping」を優先します。

旧独立Lambda依存ITの全検証地点（削除前行番号）。完全重複は既存ITへ委譲し、部分重複の環境別byte snapshotと未カバーのPassCache依存を `validation_cache.check_producer_inputs` に統合。旧2構成の全体コピー・独立fixture生成ヘルパーの移植なし。

| 旧行 / assertion・拒否目的 | 重複判定 | 継続する検証 |
|---|---|---|
| 54 / 分割Templateのpartが解析入力に含まれる | 部分 | validation_cache.mainのpart変更キー、check_producer_inputsの`part in inputs` |
| 77 / Producer source_inputsがConsumerに包含 | 完全 | attribute-reference-resolution.check_pairの`loaded.files`、eventbridge-producer-name-reference.checkの`load_model(producer).files <= files`。統合fixtureでも同じ包含を確認 |
| 84 / 全Producer入力の空白変更で共有両環境・固有環境だけdigest変化 | 部分 | check_producer_inputsの入力全件×preview/release×依存/無関係サービスdigest比較。check_fixed_labelは値不変のdigestを既存検証 |
| 85 / 同条件でConsumer service_key変化 | 未カバー | check_producer_inputs。共有index/partとpreviewのparameters/bindings/observedを順に変更し、releaseと無関係sqsの非影響もassert |
| 86 / 入力空白変更中のConsumer値完全一致 | 部分 | check_producer_inputsの各入力変更中のvalues全体一致（JSONの型・配列順も含む） |
| 91 / affectedが共有両環境・固有環境のProducer/Consumerのみ | 完全 | model_impact.check_shared_environmentsの共有/環境固有分離、check_precisionのLambda含む変更伝播・値不変snapshot、check_selectionの無関係サービス除外。attribute-reference-resolution.check_fixed_labelの値不変入力でもConsumer包含。baseline無しの保守的集合とbaseline有りの精密集合は区別 |
| 93 / 復元後Consumer値一致 | 完全 | attribute-reference-resolution.check_pairのdigest/values復元一致。統合caseは全キー復元も確認 |
| 101 / 相互参照でもConsumer filesをProducer source_inputsが包含 | 完全 | attribute-reference-resolution.check_pairの相互fixtureとProducer files追跡、eventbridge-producer-name-reference.checkのLambda.Permission→Rule逆リンクとfiles包含 |
| 102 / 相互リンクがあっても値再帰しない | 完全 | attribute-reference-resolution.check_pairのLambda/EventBridge相互参照値解決と真の属性cycle拒否、eventbridge-producer-name-reference.checkの逆リンク付きLambda値解決 |
| 110–112 / Producer parameters欠落の拒否 | 完全 | attribute-reference-resolution.check_preparation_cacheのparameters.yaml欠落拒否、eventbridge-producer-name-reference.checkのProducer欠落拒否 |
| 120–122 / Producer型破損の拒否 | 完全 | eventbridge-producer-name-reference.checkのLambda型不一致拒否、attribute-reference-resolution.checkのresourceType不一致拒否 |
| 128–130 / Producer parameters欠落の再検証 | 完全（旧内でも重複） | 同上のProducer欠落拒否 |

実行入口単位：新規1 case、旧module case 1削除、独立suiteは1減。旧module内のflat/parts 2 fixture構築を廃止し、既存cache suiteに最小2環境fixture 1構築を追加。既存のwrite_modelで合成入力だけを作成する。run_itの共有seed bundle生成は1回のまま、suite processは1減。run_it.pyとFramework IT workflowは変更不要（自動発見と本台帳の照合を継続）。

## design_catalog の検証経路

現行定義を読み取るQuickSight表示とMacie Schema正常系、異常値23件を維持する。定義変更に依存しないS3リンクlabelとbucketCriteria/JSON競合の直接検証も維持する。
Mappingのinclude/show、命名規則、Schema snapshotの書き換えに依存した生成・保存経路は削除した。
不正定義のメモリ上での検証は維持し、ファイル変更テストを別方式へ移植しない。

## blueprint-loop サービスCLI責務対応

入力は独立した合成repository。初期Model/Markdown生成後にGit commitし、保持期間30→14をTaskの変更対象とする。全実CLIは本物のValidator/Generatorを使用する。下記番号は変更前の実行順（16回）。共通runのValidator起動・Git diff起動・回帰非選択は残す各実CLIで確認する。個別Validator診断のCLI経由繰返しを減らし、停止・scope・Git結合は残す。

| 番号 | 入力条件（Model / Markdown / Task / Git） | 期待結果・成果物 | 責務 | 判断と同等assertの所在 |
|---:|---|---|---|---|
| 1 | 正常14 / 一致 / logs / 変更あり | PASS・回帰0 | orchestration | 維持：check_task_service_validation |
| 2 | 1と同じ、ローカル.lock追加 | PASS・0 executed, 1 reused | cache / Git | 維持 |
| 3 | 1と同じ、fresh/profile/jobs=1 | PASS・1 executed, 0 reused・両prof実ファイル | orchestration | 維持 |
| 4 | 正常 / 一致 / logsに未解決Issue | FAIL・suspend・原因保存 | orchestration | 維持 |
| 5 | 保持7 / 14のまま / logs | FAIL・generated Markdown is stale | Validator | 重複削除：12の同一変更・診断に集約。12で非書込もassert |
| 6 | LogGroupName空 / 変更なし / logs | FAIL・confirmed resource display label is missing | Generator | 移管：[model_design.check_service_failure_protection](integrations/model_design.checks.py#L1368)の既存logs fixtureに空Name・診断・全view非書込assert追加 |
| 7 | 保持31 / 31 / logs | FAIL・schema | Validator / Generator | 移管：同専門関数でRetentionInDays=31のenum違反、生成とMarkdown検証の診断、非書込をassert |
| 8 | 正常 / 存在しないmdへのリンク / logs | FAIL・broken design link | Validator | 既存保証：[design_document.check_links](integrations/design_document.checks.py#L61)でabsent.md#absentに対する完全一致診断配列。CLI失敗伝播は12で維持 |
| 9 | 正常 / 一致 / 未定義account | FAIL・validation target is not defined | scope | 移管：[validation_scope.main](integrations/validation_scope.checks.py#L156)の不正selectorループに同accountと診断assert追加 |
| 10 | logs変更 / logs変更 / ec2指定 | FAIL・changed design path is outside validation scope | scope / Git | 維持：Git変更の実CLI伝播は専門関数のchanged_paths代入だけでは代替しない |
| 11 | 正常logs＋commit済み不正ec2 / logs | PASS・対象外無視 | orchestration | 維持 |
| 12 | 保持7＋不正ec2 / 14 / logs | FAIL・stale | orchestration | 維持・Markdown非書込assert追加 |
| 13 | 正常logs＋不正ec2 / all | FAIL・ec2・Validation all・回帰skip | orchestration | 維持（contractのall指定。CLI --allは他の既存ケースで検証） |
| 14 | mismatchをcommit後Modelだけ修復 / 正しい14 / ModelのみAcceptance | PASS・Markdown Git diffなし・内容不変 | orchestration / Git | 維持：専門Generator単独ではGit結合を代替できない |
| 15 | 正常14 / 不正7 / logs | FAIL・stale | Validator | 重複削除：12と[model_design.check_service_failure_protection](integrations/model_design.checks.py#L1368)のread-only stale検出＋全view byte不変 |
| 16 | 正常 / Markdown削除 / logs | FAIL・validation input missing | scope | 移管：validation_scope.mainにMarkdown削除・同診断・非再生成assert追加 |

16→9回。7回への削減よりscope変更・Modelのみ修復の実CLI結合保証を優先する。fixture構造・初期化回数は変更しない。既存の小型CLI fixtureに不足していたworktree_task.py/worktree_python.pyのコピーだけ補完する。Name/Schema/scope専門検証は既存fixture内に追加し、別ファイルへCLI処理を移していない。

`-O` は既存 `run_it.check_assertion_guards()` の全 `.checks.py` AST検証を再利用する（不明構造はFAIL）。現baseでは全ファイル個別起動は既に廃止済みであり、その削減を今回の成果に含めない。`service-parameter-inputs.checks.py` にも直接ガードが既にある。

`check_workflow` に実UT/IT代表2本の `python -O` 非ゼロ・専用診断を追加。通常モードのfixtureはAssertionErrorで検証本体到達を確認し、ガード除去fixtureは静的検査で拒否する。既存の `-O` loop→ガードなし子チェックもassert失敗・後続継続を確認する。全ファイルの動的起動保証は全ファイル静的＋代表動的へ縮小しており、同一保証とは扱わない。代表2本分の起動は現baseより2回増える。

## 配置と入口の件数

| 種別 | Pythonファイル数 | 台帳登録pytest関数 / 展開数 | 直接関数 |
|---|---:|---:|---:|
| UT | 68 | 371 / 933 | 28 |
| IT | 78 | 234 / 452 | 117 |
| support | 44 | 0 / 0 | 0 |

supportファイル数は共通fixture/補助のみ。main/moduleの地点数は下表を参照。

## IT統合と到達性

公式入口は `run_it.py`。`.checks.py` は68スイートを自動検出する。上表のファイル数には補助Pythonモジュールも含む。
ケース台帳を実行時に読み、pytestの収集・成功した検証本体のパラメータ件数、直接実行関数の呼出記録と照合する。未登録の `check_*`、消えた関数、未実行・skip・パターン不足はFAIL。ケース名だけの存在確認でPASSにしない。

現在のIT台帳は370登録・588入口パターン（pytest 234/452、direct 117、direct_group 13、module 6）。内部動的ループは下表の詳細どおりで、入口パターン数には加算しない。

- `check_quicksight_group_principal_reference` 1パターンと `check_incoming_reference_models` のFalse/Trueを通常pytest収集へ復帰。各ITの手書き選択リストも廃止した。
- 全量逆変換の検証は廃止。`design_document.check_snapshot` は局所的な表・リンクsnapshotと正本からの表示・生成物比較を検証する。`validate-blueprint` の `design_document.check_links` 呼出も削除。両検証本体はdesign_documentの通常入口に存在し、同じ実装モジュールを渡して実行するため完全重複。
- sync-performanceの7関数には完全重複と証明できるものはなく、全21パターンを保持。小規模な権限/選択/進捗の検証のみ既存UTに移管し、実際の生成・保存・CLI・ロック待機はITに保持する。
- 他ITへの16ロードは0。issues、Model、layout、worktree、blueprint-loopは既存supportを直接再利用。RotationScheduleのデータ生成だけをsupportへ抽出し、検証本体を他ITから呼ばない。
- runnerがframework・入力テンプレート・typed services・生成済みIAM policyを各1回初期化。生成イベントを実測し、共通bundleは書込禁止かつ前後の内容/modeハッシュで検査する。ケースは独立コピーを変更し、入力テンプレートの参照元のみ読み取り専用で共有する。
- `check_it_fixture_isolation` は通常/逆順で独立コピーを変更し、隣接ケースと原本の不変、書込禁止、後片付け、強制汚染時のFAILを検証する。
- assert無効化ガードは全UT/ITのAST配置・厳密な式・最適化コンパイル時のSystemExitで確認し、runner自体も実際の `python -O` で拒否を検証する。毎スイートの `python -O` 起動は不要。

## UT 全ケース

| 元ファイル : 行 | Test Case名 | 分類 | 現在の配置 | 入口 / パターン数 | 分類理由 | 変更 |
|---|---|---|---|---|---|---|
| `sync-model runner` | `check_internal_sync_isolation` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#check_internal_sync_isolation) | pytest / 4 | 複数・全体、直列・並列のContext分離と入力再読込、失敗後復元 | 新規 |
| `sync-model runner` | `check_internal_sync_real_diagnostics` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#check_internal_sync_real_diagnostics) | pytest / 1 | consumer不足と生成差分の実診断をValidatorへ伝達 | 新規 |
| `sync-model runner` | `check_internal_sync_concurrent_output` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#check_internal_sync_concurrent_output) | pytest / 1 | 並行呼び出しのmemo・診断・heartbeat分離と後片付け | 新規 |
| `sync-model runner` | `check_internal_sync_arguments` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#check_internal_sync_arguments) | pytest / 4 | help・usage・引数エラーと終了状態、出力漏れ防止 | 新規 |
| `Validator runner` | `check_internal_generation_dispatch` | UT | [units/validation_scope-unit.checks.py](units/validation_scope-unit.checks.py#check_internal_generation_dispatch) | pytest / 4 | 比較APIへのscope・workers・definitions_root引継ぎ、エラー伝達・重複防止・空scope・hook優先・subprocess禁止 | 新規 |
| `unknown/aws_mapping.checks.py:274` | `check_payload_selection` | UT | [units/aws_mapping-unit.checks.py:18](units/aws_mapping-unit.checks.py#L18) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/aws_mapping.checks.py:54` | `check_v3_registry` | UT | [units/aws_mapping-unit.checks.py:56](units/aws_mapping-unit.checks.py#L56) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/aws_mapping.checks.py:97` | `check_registry_cache` | UT | [units/aws_mapping-unit.checks.py:126](units/aws_mapping-unit.checks.py#L126) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/aws_mapping.checks.py:121` | `check_baseline` | UT | [units/aws_mapping-unit.checks.py:151](units/aws_mapping-unit.checks.py#L151) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/aws_mapping_catalog.checks.py:73` | `initialization_checks` | UT | [units/aws_mapping_catalog.checks.py:73](units/aws_mapping_catalog.checks.py#L76) | direct / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/aws_mapping_catalog.checks.py:120` | `schema_checks` | UT | [units/aws_mapping_catalog.checks.py:120](units/aws_mapping_catalog.checks.py#L121) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:847` | `check_utf8_restart` | UT | [units/blueprint-loop-unit.checks.py:11](units/blueprint-loop-unit.checks.py#L11) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/model_design.checks.py:303` | `check_changed_paths_error` | UT | [units/blueprint-loop-unit.checks.py:24](units/blueprint-loop-unit.checks.py#L24) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/blueprint-loop.checks.py:68` | `check_process_interruption` | UT | [units/blueprint-loop-unit.checks.py:32](units/blueprint-loop-unit.checks.py#L32) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/blueprint-loop.checks.py:413` | `check_parallel_interruption` | UT | [units/blueprint-loop-unit.checks.py:56](units/blueprint-loop-unit.checks.py#L56) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/blueprint-loop.checks.py:464` | `check_fixture_independence` | UT | [units/blueprint-loop-unit.checks.py:131](units/blueprint-loop-unit.checks.py#L131) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:1000` | `check_regression_discovery` | UT | [units/blueprint-loop-unit.checks.py:154](units/blueprint-loop-unit.checks.py#L154) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `units/check-model-aws-unit.checks.py:11` | `check_summary_exit_codes` | UT | [units/check-model-aws-unit.checks.py:11](units/check-model-aws-unit.checks.py#L11) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `units/check-model-aws-unit.checks.py:19` | `check_value_normalization` | UT | [units/check-model-aws-unit.checks.py:19](units/check-model-aws-unit.checks.py#L19) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `units/check-model-aws-unit.checks.py:29` | `check_secret_redaction` | UT | [units/check-model-aws-unit.checks.py:29](units/check-model-aws-unit.checks.py#L29) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/cloudformation-deploy.checks.py:98` | `check_scheduler` | UT | [units/cloudformation-deploy-unit.checks.py:11](units/cloudformation-deploy-unit.checks.py#L11) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:334` | `check_workflow_contract` | UT | [units/deploy_preparation-unit.checks.py:11](units/deploy_preparation-unit.checks.py#L11) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:344` | `check_dependencies_and_timing` | UT | [units/deploy_preparation-unit.checks.py:21](units/deploy_preparation-unit.checks.py#L21) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:382` | `check_rule_section_boundaries` | UT | [units/deploy_preparation-unit.checks.py:59](units/deploy_preparation-unit.checks.py#L59) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/design_catalog.checks.py:138` | `check_api_schema` | UT | [units/design_catalog-unit.checks.py:11](units/design_catalog-unit.checks.py#L11) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/design_document.checks.py:50` | `check_snapshots` | UT | [units/design_document-unit.checks.py:11](units/design_document-unit.checks.py#L11) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:926` | `check_resource_display_names` | UT | [units/design_layout-unit.checks.py:11](units/design_layout-unit.checks.py#L11) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/design_layout.checks.py:530` | `check_cloudtrail_expansion` | UT | [units/design_layout-unit.checks.py:20](units/design_layout-unit.checks.py#L20) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/design_layout.checks.py:621` | `check_pipeline_expansion` | UT | [units/design_layout-unit.checks.py:29](units/design_layout-unit.checks.py#L29) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/framework-input-isolation.checks.py:41` | `check_framework_input_guards` | UT | [units/framework-input-isolation-unit.checks.py:15](units/framework-input-isolation-unit.checks.py#L15) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/glue_datazone_catalog.checks.py:102` | `check_catalog_schema` | UT | [units/glue_datazone_catalog-unit.checks.py:11](units/glue_datazone_catalog-unit.checks.py#L11) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `import-agent-sources::check_null_parameter` | `check_null_parameter` | UT | [units/import-model-unit.checks.py:64](units/import-model-unit.checks.py#L64) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_yaml_edits` | `check_yaml_edits` | UT | [units/import-model-unit.checks.py:70](units/import-model-unit.checks.py#L70) | pytest / 7 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_yaml_empty_and_order` | `check_yaml_empty_and_order` | UT | [units/import-model-unit.checks.py:84](units/import-model-unit.checks.py#L84) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_physical_identity_wins_over_mutable_settings` | `check_physical_identity_wins_over_mutable_settings` | UT | [units/import-model-unit.checks.py:94](units/import-model-unit.checks.py#L94) | pytest / 2 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_invalid_candidates` | `check_invalid_candidates` | UT | [units/import-model-unit.checks.py:123](units/import-model-unit.checks.py#L123) | pytest / 12 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_unacquired_and_create_protection` | `check_unacquired_and_create_protection` | UT | [units/import-model-unit.checks.py:130](units/import-model-unit.checks.py#L130) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_duplicate_add_uses_baseline` | `check_duplicate_add_uses_baseline` | UT | [units/import-model-unit.checks.py:148](units/import-model-unit.checks.py#L148) | pytest / 8 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_selection_identity_duplicate` | `check_selection_identity_duplicate` | UT | [units/import-model-unit.checks.py:164](units/import-model-unit.checks.py#L164) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_existing_identity_ambiguity_is_local` | `check_existing_identity_ambiguity_is_local` | UT | [units/import-model-unit.checks.py:174](units/import-model-unit.checks.py#L174) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_unknown_identity_does_not_block_add` | `check_unknown_identity_does_not_block_add` | UT | [units/import-model-unit.checks.py:190](units/import-model-unit.checks.py#L190) | pytest / 4 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_new_resource_and_explicit_dispositions` | `check_new_resource_and_explicit_dispositions` | UT | [units/import-model-unit.checks.py:198](units/import-model-unit.checks.py#L198) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_binding_identity_and_addition` | `check_binding_identity_and_addition` | UT | [units/import-model-unit.checks.py:218](units/import-model-unit.checks.py#L218) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_shared_property_typed_preservation` | `check_shared_property_typed_preservation` | UT | [units/import-model-unit.checks.py:231](units/import-model-unit.checks.py#L231) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_shared_reference_is_symbolic` | `check_shared_reference_is_symbolic` | UT | [units/import-model-unit.checks.py:290](units/import-model-unit.checks.py#L290) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_typed_property_values` | `check_typed_property_values` | UT | [units/import-model-unit.checks.py:298](units/import-model-unit.checks.py#L298) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_candidate_scope_and_changed_files` | `check_candidate_scope_and_changed_files` | UT | [units/import-model-unit.checks.py:305](units/import-model-unit.checks.py#L305) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_sealed_evidence_tamper` | `check_sealed_evidence_tamper` | UT | [units/import-model-unit.checks.py:323](units/import-model-unit.checks.py#L323) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_cli_never_falls_back` | `check_cli_never_falls_back` | UT | [units/import-model-unit.checks.py:339](units/import-model-unit.checks.py#L339) | pytest / 4 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_cli_phase_dispatch` | `check_cli_phase_dispatch` | UT | [units/import-model-unit.checks.py:345](units/import-model-unit.checks.py#L345) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_native_equality_and_singleton` | `check_native_equality_and_singleton` | UT | [units/import-model-unit.checks.py:361](units/import-model-unit.checks.py#L361) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_adapter_inventory_normalization` | `check_adapter_inventory_normalization` | UT | [units/import-model-unit.checks.py:372](units/import-model-unit.checks.py#L372) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_shared_source_preservation_boundary` | `check_shared_source_preservation_boundary` | UT | [units/import-model-unit.checks.py:392](units/import-model-unit.checks.py#L392) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_existing_resource_action_rejected` | `check_existing_resource_action_rejected` | UT | [units/import-model-unit.checks.py:421](units/import-model-unit.checks.py#L421) | pytest / 4 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_new_anchor_and_reference_preservation` | `check_new_anchor_and_reference_preservation` | UT | [units/import-model-unit.checks.py:428](units/import-model-unit.checks.py#L428) | pytest / 1 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_authored_vpc_append_candidate` | `check_authored_vpc_append_candidate` | UT | [units/import-model-unit.checks.py:442](units/import-model-unit.checks.py#L442) | pytest / 2 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `import-agent-sources::check_foreign_candidate_scope` | `check_foreign_candidate_scope` | UT | [units/import-model-unit.checks.py:487](units/import-model-unit.checks.py#L487) | pytest / 5 | 取得・追加候補・不変性の単体判定 | Append-only Import |
| `unknown/issue_gate.checks.py:27` | `check_inventory_parser` | UT | [units/issue_gate-unit.checks.py:11](units/issue_gate-unit.checks.py#L11) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `integrations/issues_api_only.checks.py:62` | `check_api_type_rejection` | UT | [units/issues_api_only-unit.checks.py:11](units/issues_api_only-unit.checks.py#L11) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/issues_scan.checks.py:1622` | `check_mismatch_rendering` | UT | [units/issues_scan-unit.checks.py:11](units/issues_scan-unit.checks.py#L11) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/issues_scan.checks.py:1823` | `check_summary_scale` | UT | [units/issues_scan-unit.checks.py:167](units/issues_scan-unit.checks.py#L167) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/json-yaml-document-hash.checks.py:48` | `check_json_hash_types` | UT | [units/json-yaml-document-hash-unit.checks.py:11](units/json-yaml-document-hash-unit.checks.py#L11) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/lambda_permission.checks.py:93` | `check_permission_catalog` | UT | [units/lambda_permission-unit.checks.py:11](units/lambda_permission-unit.checks.py#L11) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/model_design.checks.py:1208` | `check_design_naming_rules` | UT | [units/model_design-unit.checks.py:11](units/model_design-unit.checks.py#L11) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/model_design.checks.py:530` | `check_subnet_list_display` | UT | [units/model_design-unit.checks.py:21](units/model_design-unit.checks.py#L21) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1170` | `check_security_naming` | UT | [units/model_design-unit.checks.py:74](units/model_design-unit.checks.py#L74) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1204` | `check_service_scoped_naming` | UT | [units/model_design-unit.checks.py:108](units/model_design-unit.checks.py#L108) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1235` | `check_naming_target_paths` | UT | [units/model_design-unit.checks.py:139](units/model_design-unit.checks.py#L128) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1332` | `check_security_group_and_glue_catalog_naming` | UT | [units/model_design-unit.checks.py:158](units/model_design-unit.checks.py#L147) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1635` | `check_naming_coverage` | UT | [units/model_design-unit.checks.py:183](units/model_design-unit.checks.py#L172) | pytest / 5 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1639` | `check_naming_edges` | UT | [units/model_design-unit.checks.py:187](units/model_design-unit.checks.py#L176) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1651` | `check_invalid_model` | UT | [units/model_design-unit.checks.py:199](units/model_design-unit.checks.py#L188) | pytest / 2 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:2062` | `check_temporary_roots` | UT | [units/model_design-unit.checks.py:204](units/model_design-unit.checks.py#L193) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:2081` | `check_cli_result` | UT | [units/model_design-unit.checks.py:222](units/model_design-unit.checks.py#L211) | pytest / 3 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `unknown/model_files.checks.py:198` | `check_cfn_selector` | UT | [units/model_files-unit.checks.py:11](units/model_files-unit.checks.py#L11) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:276` | `check_yaml_schema` | UT | [units/model_parameter_inputs-unit.checks.py:11](units/model_parameter_inputs-unit.checks.py#L11) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `units/model_parameter_inputs-unit.checks.py:18` | `check_embedded_parameter_type` | UT | [units/model_parameter_inputs-unit.checks.py:18](units/model_parameter_inputs-unit.checks.py#L18) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/policy_tables.checks.py:42` | `check_iam_artifact_names` | UT | [units/policy_tables-unit.checks.py:19](units/policy_tables-unit.checks.py#L19) | pytest / 6 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/policy_tables.checks.py:480` | `check_statement_metadata` | UT | [units/policy_tables-unit.checks.py:26](units/policy_tables-unit.checks.py#L26) | pytest / 4 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `unknown/policy_tables.checks.py:493` | `check_lossless_generation` | UT | [units/policy_tables-unit.checks.py:39](units/policy_tables-unit.checks.py#L39) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `units/producer-identifier-reference-unit.checks.py:11` | `check_identifier_schema` | UT | [units/producer-identifier-reference-unit.checks.py:11](units/producer-identifier-reference-unit.checks.py#L11) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/quicksight-display.checks.py:25` | `check_alias_catalog` | UT | [units/quicksight-display-unit.checks.py:11](units/quicksight-display-unit.checks.py#L11) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/quicksight-display.checks.py:30` | `check_alias_rows` | UT | [units/quicksight-display-unit.checks.py:20](units/quicksight-display-unit.checks.py#L20) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `units/raw-bucket-name-reference-unit.checks.py:11` | `check_reference_schema` | UT | [units/raw-bucket-name-reference-unit.checks.py:11](units/raw-bucket-name-reference-unit.checks.py#L11) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/regression_guard.checks.py:47` | `check_password_input_diagnostics` | UT | [units/regression_guard-unit.checks.py:11](units/regression_guard-unit.checks.py#L11) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/resource_mode.checks.py:158` | `check_default_mode` | UT | [units/resource_mode-unit.checks.py:11](units/resource_mode-unit.checks.py#L11) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/resource_mode.checks.py:182` | `check_import_naming_exemption` | UT | [units/resource_mode-unit.checks.py:16](units/resource_mode-unit.checks.py#L16) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/resource_mode.checks.py:121` | `check_required_name_modes` | UT | [units/resource_mode-unit.checks.py:26](units/resource_mode-unit.checks.py#L26) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/security_group_tables.checks.py:104` | `check_rule_catalog` | UT | [units/security_group_tables-unit.checks.py:11](units/security_group_tables-unit.checks.py#L11) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 関数内抽出 |
| `unknown/security_group_tables.checks.py:154` | `check_service_filenames` | UT | [units/security_group_tables-unit.checks.py:28](units/security_group_tables-unit.checks.py#L28) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/sync-model.checks.py:487` | `check_property_path_parents` | UT | [units/sync-model-unit.checks.py:11](units/sync-model-unit.checks.py#L11) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/sync-model.checks.py:265` | `check_markdown_newlines` | UT | [units/sync-model-unit.checks.py:23](units/sync-model-unit.checks.py#L23) | pytest / 4 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `units/test_issues_iac.py:14` | `ImportValueResolutionTests.test_formal_pipeline_membership_and_configuration_context` | UT | [units/test_issues_iac.py:14](units/test_issues_iac.py#L14) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 変更不要 |
| `units/test_issues_iac.py:63` | `ImportValueResolutionTests.test_api_managed_resource_remains_unverified_in_cloudformation_comparison` | UT | [units/test_issues_iac.py:63](units/test_issues_iac.py#L63) | pytest / 1 | Framework内部定義・入力制約の単体判定 | 変更不要 |
| `units/test_issues_iac.py:81` | `ImportValueResolutionTests.test_import_value_ignores_unrelated_incomplete_stack` | UT | [units/test_issues_iac.py:81](units/test_issues_iac.py#L81) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 変更不要 |
| `units/test_issues_iac.py:109` | `ImportValueResolutionTests.test_kms_alias_retains_identity_even_with_the_same_parent_key` | UT | [units/test_issues_iac.py:109](units/test_issues_iac.py#L109) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 変更不要 |
| `unknown/validation_cache.checks.py:30` | `check_cache_inputs` | UT | [units/validation_cache-unit.checks.py:11](units/validation_cache-unit.checks.py#L11) | pytest / 1 | Cache破損・fresh・bytecode除外・README可変入力・Model row再評価 | 関数内抽出 |
| `unknown/validation_cache.checks.py:104` | `check_cache_location` | UT | [units/validation_cache-unit.checks.py:55](units/validation_cache-unit.checks.py#L55) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `support/validation_checks/cloudformation.py:8` | `check_cloudformation_yaml_rules` | UT | [units/validation_checks/cloudformation.py:13](units/validation_checks/cloudformation.py#L13) | direct / 1 | 変換・比較・入力検証。合成fixture内で完結 | 配置/共有fixture分離 |
| `support/validation_checks/cloudformation.py:167` | `check_cloudformation_environment_parameters` | UT | [units/validation_checks/cloudformation.py:172](units/validation_checks/cloudformation.py#L172) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/contracts.py:9` | `check_optional_alias_contract` | UT | [units/validation_checks/contracts.py:16](units/validation_checks/contracts.py#L16) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/contracts.py:26` | `check_implementation_preflight_prompt` | UT | [units/validation_checks/contracts.py:33](units/validation_checks/contracts.py#L33) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/contracts.py:67` | `check_update_flow_prompt` | UT | [units/validation_checks/contracts.py:74](units/validation_checks/contracts.py#L74) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/contracts.py:165` | `check_design_handoff_prompt` | UT | [units/validation_checks/contracts.py:172](units/validation_checks/contracts.py#L172) | direct / 1 | 現行handoff Promptの必須記述とFramework検証 | 配置/共有fixture分離 |
| `support/validation_checks/contracts.py:240` | `check_rule_reading_contract` | UT | [units/validation_checks/contracts.py:247](units/validation_checks/contracts.py#L184) | direct / 1 | 現行Rule参照・節の存在と回帰選択を読み取り専用で検証 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:9` | `check_catalog_inputs` | UT | [units/validation_checks/design.py:16](units/validation_checks/design.py#L13) | direct / 1 | 現在のCatalog/Schema/Mapping整合性を読み取り専用で検証 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:84` | `check_schema_backed_design_rows` | UT | [units/validation_checks/design.py:91](units/validation_checks/design.py#L20) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:221` | `check_name_tag_and_identifier_order_contract` | UT | [units/validation_checks/design.py:137](units/validation_checks/design.py#L65) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:277` | `check_cidr_pending_deploy` | UT | [units/validation_checks/design.py:193](units/validation_checks/design.py#L121) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:353` | `check_event_rule_row_order` | UT | [units/validation_checks/design.py:269](units/validation_checks/design.py#L224) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:397` | `check_artifact_naming` | UT | [units/validation_checks/references.py:24](units/validation_checks/references.py#L24) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/runner.py:13` | `check_dispatch` | UT | [units/validation_checks/runner.py:31](units/validation_checks/runner.py#L31) | direct / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `support/validation_checks/runner.py:48` | `check_boundaries` | UT | [units/validation_checks/runner.py:66](units/validation_checks/runner.py#L66) | direct / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `support/validation_checks/runner.py:121` | `check_module_keys` | UT | [units/validation_checks/runner.py:132](units/validation_checks/runner.py#L132) | direct / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `support/validation_checks/scenario.py:45` | `check_timestamp` | UT | [units/validation_checks/scenario.py:10](units/validation_checks/scenario.py#L10) | direct / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `support/validation_checks/task.py:226` | `check_optional_alias_targets` | UT | [units/validation_checks/task.py:25](units/validation_checks/task.py#L25) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:389` | `check_model_task_boundaries` | UT | [units/validation_checks/task.py:188](units/validation_checks/task.py#L188) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `support/validation_checks/terraform.py:13` | `check_configuration` | UT | [units/validation_checks/terraform.py:28](units/validation_checks/terraform.py#L28) | direct / 1 | Framework内部定義・入力制約の単体判定 | 配置/共有fixture分離 |
| `unknown/validation_scope.checks.py:196` | `check_active_scope` | UT | [units/validation_scope-unit.checks.py:11](units/validation_scope-unit.checks.py#L11) | pytest / 1 | 変換・比較・入力検証。合成fixture内で完結 | 関数内抽出 |
| `unknown/worktree_python.checks.py:87` | `check_environment` | UT | [units/worktree_python-unit.checks.py:11](units/worktree_python-unit.checks.py#L11) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 関数内抽出 |
| `unknown/worktree_python.checks.py:279` | `check_pdf_native_optional` | UT | [units/worktree_python-unit.checks.py:19](units/worktree_python-unit.checks.py#L19) | pytest / 1 | 単一責務を既存Fake/Mockまたは合成入力で確認 | 配置/共有fixture分離 |
| `units/task-contract-unit.checks.py:196` | `check_allowed_paths` | UT | [units/task-contract-unit.checks.py:28](units/task-contract-unit.checks.py#L28) | pytest / 4 | sync-performance: exact/glob/rejection and symlink checks | 検証本体・assertを保持 |
| `units/task-contract-unit.checks.py:214` | `check_live_selection` | UT | [units/task-contract-unit.checks.py:47](units/task-contract-unit.checks.py#L47) | pytest / 1 | sync-performance: live selection and invalidation | 検証本体・assertを保持 |
| `units/sync-model-unit.checks.py:91` | `check_progress_heartbeat_and_waits` | UT | [units/sync-model-unit.checks.py:91](units/sync-model-unit.checks.py#L91) | pytest / 1 | sync-performance: heartbeat and lock/stage diagnostics | 検証本体・assertを保持 |
| `units/blueprint-loop-unit.checks.py:250` | `check_it_reachability` | UT | [units/blueprint-loop-unit.checks.py:253](units/blueprint-loop-unit.checks.py#L253) | pytest / 1 | runner: discovery, execution receipts, assertion guard or immutable fixture isolation | 検証本体・assertを保持 |
| `units/blueprint-loop-unit.checks.py:282` | `check_it_assertion_guards` | UT | [units/blueprint-loop-unit.checks.py:331](units/blueprint-loop-unit.checks.py#L331) | pytest / 1 | runner: discovery, execution receipts, assertion guard or immutable fixture isolation | 検証本体・assertを保持 |
| `units/blueprint-loop-unit.checks.py:297` | `check_it_fixture_isolation` | UT | [units/blueprint-loop-unit.checks.py:348](units/blueprint-loop-unit.checks.py#L348) | pytest / 1 | runner: discovery, execution receipts, assertion guard or immutable fixture isolation | 検証本体・assertを保持 |
| `units/blueprint-loop-unit.checks.py:330` | `check_it_inventory` | UT | [units/blueprint-loop-unit.checks.py:409](units/blueprint-loop-unit.checks.py#L409) | pytest / 1 | runner: discovery, execution receipts, assertion guard or immutable fixture isolation | 固定総数・種別別件数・展開件数・suite総数のassertを削除。登録整合性・重複/未登録/欠落・到達性検証を保持 |
| `units/blueprint-loop-unit.checks.py` | `check_it_run_lifecycle` | UT | [units/blueprint-loop-unit.checks.py:442](units/blueprint-loop-unit.checks.py#L442) | pytest / 1 | runner lifecycle: one initialization, measured events and environment restoration | 新規UT |

### UT 内部パターン

| ファイル / ケース | ループ地点・パターン数・入力 |
|---|---|
| `units/aws_mapping-unit.checks.py::check_payload_selection` | L40: 動的 (mapping.properties.items())<br>L48: 動的 (mapping.properties.items())<br>L51: 動的 (mapping.properties.items()) |
| `units/aws_mapping-unit.checks.py::check_v3_registry` | L61: 動的 (paths)<br>L73: 動的 (document['resourceTypes'].items())<br>L75: 動的 (mapping.getters.items())<br>L76: 動的 (adapter_getters.values())<br>L76: 動的 (resources)<br>L81: 3 (('RESOURCE_TYPES', 'IDENTITIES', 'GETTERS'))<br>L83: 動的 (mapping.identities.items())<br>L92: 3 (('RESOURCE_TYPES', 'IDENTITIES', 'GETTERS'))<br>L108: 動的 (tgw_properties.items())<br>L110: 動的 (actual.items())<br>L111: 動的 (actual.items())<br>L112: 動的 (selected)<br>L119: 動的 ([(baseline_properties, '011c38a46feabd4a28eb4619a3963a3c145f207266dfd757f4a0bbc25a02a463'), (definitions, '345c0f5691eeaf636a27f902e04831de58cd96f5506d1936c67f43edb156944b'), (metadata, '6ddf2190bf6c29c9615b5fad44deb27f8b33007f9fd8b4596be89630da10869b')]) |
| `units/aws_mapping-unit.checks.py::check_registry_cache` | L134: 動的 ((lambda: setattr(first.identities[RECORDER], 'id_path', 'other'), lambda: first.identities.__setitem__(RECORDER, None), lambda: first.getters['recorder'].__setitem__('resources', ()), lambda: setattr(first, 'service', 'other'))) |
| `units/aws_mapping-unit.checks.py::check_baseline` | L153: 動的 (BASELINE.items())<br>L153: 動的 (props.items())<br>L155: 動的 (aws_mapping.registry(ROOT, 'config').fields.items())<br>L161: 動的 (BASELINE.items())<br>L162: 動的 (enumerate(props, 1))<br>L164: 動的 (props)<br>L164: 動的 (shown)<br>L165: 動的 (rows)<br>L165: 動的 (shown) |
| `units/aws_mapping_catalog.checks.py::initialization_checks` | 1（内部パラメータ化なし） |
| `units/aws_mapping_catalog.checks.py::schema_checks` | L129: 4 ([('SNS.Topic', 'getter', 'sdk-sns-topicpolicy'), ('SNS.Topic', 'idPath', 'Unknown'), ('SNS.Topic', 'nameProperty', 'Unknown'), ('SNS.TopicPolicy', 'idPath', 'attributes')])<br>L163: 動的 (mutations)<br>L201: 動的 (invalid)<br>L210: 4 (('getter', 'default', 'source', 'transform')) |
| `units/blueprint-loop-unit.checks.py::check_utf8_restart` | L13: 4 ((0, 2, 7, 130)) |
| `units/blueprint-loop-unit.checks.py::check_changed_paths_error` | 1（内部パラメータ化なし） |
| `units/blueprint-loop-unit.checks.py::check_process_interruption` | 1（内部パラメータ化なし） |
| `units/blueprint-loop-unit.checks.py::check_parallel_interruption` | 1（内部パラメータ化なし） |
| `units/blueprint-loop-unit.checks.py::check_fixture_independence` | L144: 2 (('AGENTS.md', 'README.md'))<br>L146: 5 (('issues/dev/other/issues.md', 'model/dev/other/ec2.properties', 'docs/designs/dev/other/ec2.md', 'tasks/example.md', 'project.json')) |
| `units/blueprint-loop-unit.checks.py::check_regression_discovery` | 全UTの検出、IT除外、空集合拒否 |
| `units/check-model-aws-unit.checks.py::check_summary_exit_codes` | 1（内部パラメータ化なし） |
| `units/check-model-aws-unit.checks.py::check_value_normalization` | 1（内部パラメータ化なし） |
| `units/check-model-aws-unit.checks.py::check_secret_redaction` | 1（内部パラメータ化なし） |
| `units/cloudformation-deploy-unit.checks.py::check_scheduler` | L17: 2 ((('A', 'B'), ('B', 'C')))<br>L71: 3 (('intent', 'submitted', 'response'))<br>L?: 動的 (state.values())<br>L?: 動的 (state.values())<br>L?: 動的 (state.values())<br>L?: 動的 (enumerate(fake.events))<br>L?: 動的 (enumerate(fake.events))<br>L?: 動的 (results)<br>L?: 動的 (enumerate(fake.events)) |
| `units/deploy_preparation-unit.checks.py::check_workflow_contract` | L15: 2 (('cloudformation', 'terraform'))<br>L15: 動的 ((prompt, *((ROOT / 'framework/rules' / (engine + '.md')).read_text(encoding='utf-8') for engine in ('cloudformation', 'terraform'))))<br>L16: 9 (('authoritative model properties', 'desired.row.*.document', 'desired.resource.*', 'observed.*', 'existence verification', 'hash', 'local loop', 'fallback', 'stop'))<br>L18: 5 (('generatedViews', 'inputs', 'unread sections', 'load_units()', 'Do not newly reregister already registered tasks')) |
| `units/deploy_preparation-unit.checks.py::check_dependencies_and_timing` | L26: 6 (('boto3', 'botocore', 'PyYAML', 'git')) |
| `units/deploy_preparation-unit.checks.py::check_rule_section_boundaries` | L65: 2 (('## Duplicate\\nsame\\n## Duplicate\\nsame\\n', '<a id="shared"></a>\\n## One\\nfirst\\n<a id="shared"></a>\\n## Two\\nsecond\\n')) |
| `units/design_catalog-unit.checks.py::check_api_schema` | L22: 3 ((MACIE_JOB, QUICKSIGHT_GROUP, 'Macie.Unknown')) |
| `units/design_document-unit.checks.py::check_snapshots` | L?: 動的 (results)<br>L?: 動的 (reads.call_args_list)<br>L?: 動的 (reads.call_args_list) |
| `units/design_layout-unit.checks.py::check_resource_display_names` | 1（内部パラメータ化なし） |
| `units/design_layout-unit.checks.py::check_cloudtrail_expansion` | 1（内部パラメータ化なし） |
| `units/design_layout-unit.checks.py::check_pipeline_expansion` | L?: 動的 (expanded.splitlines())<br>L?: 動的 (pipeline_rows(formal_rows))<br>L?: 動的 (enumerate(rows, 1))<br>L?: 動的 (line.strip('\|').split('\|')) |
| `units/framework-input-isolation-unit.checks.py::check_framework_input_guards` | L?: 動的 (consumer.errors) |
| `units/glue_datazone_catalog-unit.checks.py::check_catalog_schema` | L14: 4 (('Glue.Catalog', 'DataZone.Domain', 'DataZone.Project', 'DataZone.DataSource')) |
| `units/issue_gate-unit.checks.py::check_inventory_parser` | L42: 3 (('### ec2\n1. 差分\n', 'invalid inventory; 999 differences', '')) |
| `units/issues_api_only-unit.checks.py::check_api_type_rejection` | L13: 動的 (catalog.api_schemas) |
| `units/issues_scan-unit.checks.py::check_mismatch_rendering` | L27: 4 ([(None, False, 'null', 'false'), (True, 1, 'true', '1'), (1, '1', '1', '"1"'), (False, 'false', 'false', '"false"')])<br>L?: 動的 (fields({'a': 1, 'b': 2}, {'a': 3, 'b': 4}))<br>L?: 動的 (records)<br>L?: 5 (range(5))<br>L?: 動的 (duplicates)<br>L?: 動的 (entries)<br>L?: 動的 (original)<br>L?: 動的 (entries)<br>L?: 動的 (original) |
| `units/issues_scan-unit.checks.py::check_summary_scale` | L157: 4 (('first', 'second', 'confidential', 'arn:aws:'))<br>L159: 4 ([('matched', 'complete match'), ('uncompared', 'partial'), ('excluded', 'no compared records'), ('error', 'error')])<br>L117: 動的 (stats['categories'].items())<br>L122: 2 (('naming', 'judgments'))<br>L?: 動的 (actions)<br>L?: 動的 (actions)<br>L?: 動的 (entries)<br>L?: 動的 (records)<br>L?: 動的 (stats['groups'])<br>L?: 動的 (stats['categories'].items())<br>L?: 動的 (again_actions)<br>L?: 動的 (actions)<br>L?: 動的 (again_actions)<br>L?: 動的 (actions)<br>L?: 動的 (actions)<br>L?: 動的 (actions)<br>L?: 動的 (action['members'])<br>L?: 動的 (range(0, total, 50))<br>L?: 動的 (detail_payload(artifact, section, offset, 50)['items'])<br>L?: 動的 (group['members'])<br>L?: 動的 (group['members'])<br>L?: 動的 (group['members'])<br>L?: 動的 (group['members']) |
| `units/json-yaml-document-hash-unit.checks.py::check_json_hash_types` | 1（内部パラメータ化なし） |
| `units/lambda_permission-unit.checks.py::check_permission_catalog` | 1（内部パラメータ化なし） |
| `units/model_design-unit.checks.py::check_design_naming_rules` | L12: 10 (('S3.Bucket', 'EC2.Instance', 'EC2.VPCEndpoint', 'EC2.VPC', 'IAM.Role', 'SecurityHub.Hub', 'SecretsManager.Secret', 'Macie.ClassificationJob', 'SSM.Association', 'CloudFormation.Stack')) |
| `units/model_design-unit.checks.py::check_subnet_list_display` | L23: 動的 ((ROOT / 'framework/materials/aws').glob('*.properties'))<br>L24: 動的 (path.read_text(encoding='utf-8').splitlines())<br>L25: 動的 (catalog)<br>L28: 動的 (sorted(subnet_lists))<br>L32: 動的 (links)<br>L40: 動的 (inputs)<br>L42: 動的 (shown)<br>L45: 動的 (restored)<br>L46: 動的 (enumerate(rows, 1))<br>L48: 動的 ((document[:-1], [line.replace(field + '[2]', field + '[3]') for line in document], [line.replace(field + '[2]', field + '[1]') for line in document], [line.replace(field + '[1]', field + '[0]') for line in document], [line.replace(field + '[1]', field) for line in document]))<br>L50: 動的 (document)<br>L51: 動的 (document)<br>L52: 動的 (document)<br>L53: 動的 (document)<br>L61: 動的 (([line.replace('\| ' + shown[0][2] + ' \|', '\| `subnet-other` \|') for line in document], [*document[:-1], document[-1].replace(shown[-1][3], '別の説明')]))<br>L62: 動的 (document)<br>L69: 動的 (bad_values) |
| `units/model_design-unit.checks.py::check_security_naming` | L77: 動的 (naming_rule_files(ROOT))<br>L79: 動的 (text.splitlines())<br>L80: 動的 (line.strip('\|').split('\|'))<br>L84: 動的 (patterns.items())<br>L87: 動的 ((False, True) if kind == 'Organizations.Policy' else (False,))<br>L89: 3 ((('application', 'app'), ('environment', 'dev'), ('purpose', 'patching')))<br>L93: 動的 (enumerate(fields, 1))<br>L95: 動的 (rows)<br>L96: 動的 (fields)<br>L100: 3 (('EC2.TransitGateway', 'EC2.TransitGatewayVpcAttachment', 'EC2.TransitGatewayRouteTable')) |
| `units/model_design-unit.checks.py::check_service_scoped_naming` | L110: 3 (('DataZone.Domain', 'DataZone.Project', 'DataZone.DataSource'))<br>L114: 動的 (selected) |
| `units/model_design-unit.checks.py::check_naming_target_paths` | L135: 3 (('Stages[].Name', 'Stages[].Actions[].Name', 'Variables[].Name')) |
| `units/model_design-unit.checks.py::check_security_group_and_glue_catalog_naming` | L148: 動的 (naming_rule_files(ROOT))<br>L153: 5 ((('EC2.SecurityGroup', [('GroupName', 'app-dev-glue-data-sg')]), ('EC2.SecurityGroup', [('GroupName', 'app-dev-glue-data-01-sg')]), ('EC2.SecurityGroup', [('Tags[].Key', 'Name'), ('Tags[].Value', 'app-dev-glue-data-sg')]), ('EC2.SecurityGroup', [('Tags[].Key', 'Name'), ('Tags[].Value', 'app-dev-glue-data-01-sg')]), ('Glue.Catalog', [('Name', 'glct-app-dev-data')])))<br>L160: 動的 (('', kind + '.'))<br>L162: 動的 (enumerate(fields, 1)) |
| `units/model_design-unit.checks.py::check_naming_coverage` | 1（内部パラメータ化なし） |
| `units/model_design-unit.checks.py::check_naming_edges` | 1（内部パラメータ化なし） |
| `units/model_design-unit.checks.py::check_invalid_model` | 1（内部パラメータ化なし） |
| `units/model_design-unit.checks.py::check_temporary_roots` | L196: 動的 (range(2))<br>L198: 動的 (configs)<br>L200: 動的 (configs)<br>L201: 動的 (paths)<br>L203: 動的 (cleanup) |
| `units/model_design-unit.checks.py::check_cli_result` | 1（内部パラメータ化なし） |
| `units/model_files-unit.checks.py::check_cfn_selector` | 1（内部パラメータ化なし） |
| `units/model_parameter_inputs-unit.checks.py::check_yaml_schema` | L13: 4 (['a: 1\na: 2', 'a: {b: 1, b: 2}', 'a: !!python/object:bad {}', 'a: &x {b: 1}\nc: {<<: *x}']) |
| `units/model_parameter_inputs-unit.checks.py::check_embedded_parameter_type` | 1（内部パラメータ化なし） |
| `units/policy_tables-unit.checks.py::check_iam_artifact_names` | 1（内部パラメータ化なし） |
| `units/policy_tables-unit.checks.py::check_statement_metadata` | 1（内部パラメータ化なし） |
| `units/policy_tables-unit.checks.py::check_lossless_generation` | 1（内部パラメータ化なし） |
| `units/producer-identifier-reference-unit.checks.py::check_identifier_schema` | L13: 4 ([{k: v for k, v in ref.items() if k != 'property'}, {**ref, 'property': 'EC2.VPC.Arn'}, {**ref, 'property': 'EC2.Subnet.SubnetId'}, {'instance': 'main', 'resourceType': 'EC2.VPC', 'format': 'identifier', 'property': 'EC2.VPC.VpcId'}])<br>L?: 動的 (ref.items()) |
| `units/quicksight-display-unit.checks.py::check_alias_catalog` | L?: 動的 ((ROOT / 'framework/materials/aws/QuickSight_DataSource.properties').read_text(encoding='utf-8').splitlines()) |
| `units/quicksight-display-unit.checks.py::check_alias_rows` | L?: 動的 ((ROOT / 'framework/materials/aws/QuickSight_DataSource.properties').read_text(encoding='utf-8').splitlines())<br>L?: 動的 (enumerate(fields, 1))<br>L?: 動的 (source) |
| `units/raw-bucket-name-reference-unit.checks.py::check_reference_schema` | L13: 3 ([{**ref, 'format': 'unknown'}, {**ref, 'format': {}}, {'instance': 'first', 'resourceType': 'S3.Bucket', 'format': 'name'}]) |
| `units/regression_guard-unit.checks.py::check_password_input_diagnostics` | L19: 2 (((guard.GuardError('repo .lock already exists'), 'repo .lock already exists'), (ValueError('fixture-private-password-and-hash'), 'Check repo .lock'))) |
| `units/resource_mode-unit.checks.py::check_default_mode` | 1（内部パラメータ化なし） |
| `units/resource_mode-unit.checks.py::check_import_naming_exemption` | 1（内部パラメータ化なし） |
| `units/resource_mode-unit.checks.py::check_required_name_modes` | L30: 4 (('EC2.VPC', 'EC2.Subnet', 'EC2.RouteTable', 'EC2.FlowLog'))<br>L31: 2 (('CREATE', 'IMPORT'))<br>L32: 2 (([], [['1', kind + '.Name', 'PRIVATE_SUBNET_01', 'Nameタグ']])) |
| `units/security_group_tables-unit.checks.py::check_rule_catalog` | L15: 動的 (DIRECTIONS.values())<br>L20: 動的 (selected - {'GroupId', 'Id'})<br>L?: 動的 (catalog[1].items()) |
| `units/security_group_tables-unit.checks.py::check_service_filenames` | L31: 7 ((('ec2.md', 'ec2', ('EC2.SecurityGroup',)), ('ec2.properties', 'ec2', ('EC2.SecurityGroupIngress',)), ('security-group.md', 'security-group', ('EC2.Instance',)), ('security-group.md', 'security-group', ('EC2.SecurityGroup', 'EC2.VPC')), ('security_group.md', 'security_group', ('EC2.SecurityGroup',)), ('security_group.properties', 'security_group', ('EC2.SecurityGroup',)), ('other_service.md', 'other_service', ('S3.Bucket',)))) |
| `units/sync-model-unit.checks.py::check_property_path_parents` | 1（内部パラメータ化なし） |
| `units/sync-model-unit.checks.py::check_markdown_newlines` | 1（内部パラメータ化なし） |
| `units/test_issues_iac.py::ImportValueResolutionTests.test_formal_pipeline_membership_and_configuration_context` | L?: 動的 (enumerate(fields)) |
| `units/test_issues_iac.py::ImportValueResolutionTests.test_api_managed_resource_remains_unverified_in_cloudformation_comparison` | 1（内部パラメータ化なし） |
| `units/test_issues_iac.py::ImportValueResolutionTests.test_import_value_ignores_unrelated_incomplete_stack` | 1（内部パラメータ化なし） |
| `units/test_issues_iac.py::ImportValueResolutionTests.test_kms_alias_retains_identity_even_with_the_same_parent_key` | 1（内部パラメータ化なし） |
| `units/validation_cache-unit.checks.py::check_cache_inputs` | L21: 4 (('{', 'null', '[]', '{"version":1,"checks":true}'))<br>L31: 1 (('README.md',)) |
| `units/validation_cache-unit.checks.py::check_cache_location` | 1（内部パラメータ化なし） |
| `units/validation_checks/cloudformation.py::check_cloudformation_yaml_rules` | L59: 4 (('OtherSuffix', 'ExportVersion', 'NamePart', 'namePart2'))<br>L64: 10 (("Imported:\n        Fn::ImportValue: !Sub 'VpcId${Suffix}'", 'Imported:\n        Fn::ImportValue: !Sub "SubnetId${OtherSuffix}"', "Imported:\n        Fn::ImportValue:\n          # Import name\n          !Sub 'VpcId${NamePart}'", "Imported:\n        'Fn::ImportValue': !Sub 'VpcId${Suffix}'", 'Imported: {"Fn::ImportValue": !Sub "VpcId${Suffix}"}', "Imported: !ImportValue {Fn::Sub: 'VpcId${Suffix}'}", 'Imported: !ImportValue {Fn::Sub: "SubnetId${OtherSuffix}"}', "Imported: !ImportValue {'Fn::Sub': 'VpcId${NamePart}'}", 'Imported: !ImportValue {"Fn::Sub": "VpcId${Suffix}"}', "Imported: !ImportValue {Fn::Sub: ['VpcId${Part}', {Part: !Ref Suffix}]}"))<br>L82: 動的 ((valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", 'JobId:\n        Fn::Select:\n          - 0\n          - Ref: GlueJob'), valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", 'JobId: {Fn::Select: [0, {Ref: GlueJob}]}'), valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {'Fn::Select': [0, !Ref GlueJob]}"), valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {Fn::Join: ['-', [a, b]]}"), valid.replace("JobId: !Select [0, !Split ['|', !Ref GlueJob]]", "JobId: {Fn::Sub: '${AWS::Region}'}"), valid.replace('Imported: !ImportValue fixed-export', 'Imported:\n        Fn::ImportValue: fixed-export'), valid.replace('Imported: !ImportValue fixed-export', "Imported:\n        Fn::ImportValue: {Fn::Sub: 'VpcId${Suffix}'}"), valid.replace('Imported: !ImportValue fixed-export', "Imported:\n        Fn::ImportValue:\n        Description: !Sub 'VpcId${Suffix}'"), valid.replace('Imported: !ImportValue fixed-export', 'Imported:\n        Fn::ImportValue:\n          Ref: Suffix'), valid.replace('Imported: !ImportValue fixed-export', "Imported: !ImportValue fixed-export # Fn::ImportValue: !Sub 'text'\n      ExtraImport: {Fn::Sub: text}"), valid.replace('Imported: !ImportValue fixed-export', "Imported: 'Fn::ImportValue: !Sub text'\n      ExtraImport: {Fn::Sub: text}"), valid.replace('Imported: !ImportValue fixed-export', "Imported: !ImportValue {Fn::Sub: ['VpcId${Part}', {Part: {Ref: Suffix}}]}"), valid.replace('Imported: !ImportValue fixed-export', "Imported: !ImportValue {Fn::Sub: 'VpcId${Suffix}'}\n      ExtraImport: {Fn::Sub: text}"), valid.replace('Imported: !ImportValue fixed-export', "Imported: '!ImportValue {Fn::Sub: text}'\n      ExtraImport: {Fn::Sub: text}"), valid.replace('Imported: !ImportValue fixed-export', 'Imported: !ImportValue fixed-export # !ImportValue {Fn::Sub: text}\n      ExtraImport: {Fn::Sub: text}')))<br>L112: 動的 ((valid.replace('AssumeRolePolicyDocument:\n', 'AssumeRolePolicyDocument: &sharedTrustPolicy\n', 1), valid.replace('AssumeRolePolicyDocument:\n' + trust_body, 'AssumeRolePolicyDocument: *sharedTrustPolicy\n', 1), valid.replace('AssumeRolePolicyDocument:\n' + trust_body, 'AssumeRolePolicyDocument:\n        <<: {}\n', 1)))<br>L161: 3 (('AWS::EC2::SecurityGroup', 'AWS::Logs::LogGroup', 'AWS::IAM::Role'))<br>L?: 動的 (errors(suffix_import.replace('!Ref Suffix', '{Ref: Suffix}')))<br>L?: 動的 (errors(export_suffix_import.replace('!Ref ExportSuffix', '{Ref: ExportSuffix}')))<br>L?: 動的 (errors(suffix_import.replace('!Ref Suffix', '!Ref Invalid_Name')))<br>L?: 動的 (errors(suffix_import.replace("['',", "['-',")))<br>L?: 動的 (errors(valid.replace('\n  RoleB:', '  RoleB:', 1)))<br>L?: 動的 (errors(block_array))<br>L?: 動的 (errors(join_block_array))<br>L?: 動的 (errors(valid.replace(consumer, '')))<br>L?: 動的 (errors(role_only))<br>L?: 動的 (errors(marker + valid))<br>L?: 動的 (errors('Resources:\n  Logs:\n    Type: AWS::Logs::LogGroup\n'))<br>L?: 動的 (errors('Resources:\n  Role:\n    Type: AWS::IAM::Role\n\n  Logs:\n    Type: AWS::Logs::LogGroup\n'))<br>L?: 動的 (errors('Resources:\n  Filter:\n    Type: AWS::Logs::SubscriptionFilter\n'))<br>L?: 動的 (errors('Resources:\n  Role:\n    Type: AWS::IAM::Role\n\n  Profile:\n    Type: AWS::IAM::InstanceProfile\n'))<br>L?: 動的 (errors('Resources:\n  Group:\n    Type: AWS::EC2::SecurityGroup\n  Ingress:\n    Type: AWS::EC2::SecurityGroupIngress\n'))<br>L?: 動的 (errors(marker + ingress))<br>L?: 動的 (errors(bad))<br>L?: 動的 (errors(forbidden))<br>L?: 動的 (errors(ingress + egress + f'\n  Support:\n    Type: {support}\n')) |
| `units/validation_checks/cloudformation.py::check_cloudformation_environment_parameters` | L236: 動的 (conditions)<br>L259: 動的 (selectors)<br>L285: 動的 (permitted)<br>L?: 動的 (errors(valid_template.replace('  Environment:\n    Type: String\n', ''), valid_values))<br>L?: 動的 (errors(valid_template, valid_values[1:]))<br>L?: 動的 (errors(valid_template, [{**valid_values[0], 'ParameterValue': 'prod'}, valid_values[1]]))<br>L?: 動的 (errors(valid_template, [valid_values[0], {**valid_values[1], 'ParameterValue': 'app-dev'}]))<br>L?: 動的 (errors(valid_template.replace("!Sub '${NamePrefix}-${Environment}-${AWS::AccountId}-role'", '!Ref NamePrefix'), [{'ParameterKey': 'NamePrefix', 'ParameterValue': 'app-dev-role'}]))<br>L?: 動的 (errors(yaml, valid_values))<br>L?: 動的 (errors(valid_template + loop, valid_values))<br>L?: 動的 (failures)<br>L?: 動的 (validator.errors)<br>L?: 動的 (errors('Resources: [', valid_values))<br>L?: 動的 (failures)<br>L?: 動的 (failures) |
| `units/validation_checks/contracts.py::check_optional_alias_contract` | L26: 動的 (required.items()) |
| `units/validation_checks/contracts.py::check_implementation_preflight_prompt` | L37: 17 (('before active contract creation or IaC generation', 'Do not execute AWS APIs, IaC generation, or deploy', 'model.validation.validate_required_properties', 'DesignSchemaCatalog.literal_errors', 'necessary dependency properties', 'authoritative stack registration', 'template/parameter mappings', 'dependency cycle', '対象file \| resource（logical ID）/stack \| property/parameter \| 不足・違反理由', 'together in one response', 'do not end the report at the first deficiency', 'If deficiencies exist, do not implement', 'without requiring additional approval', 'Do not automatically expand change scope or all-service validation', 'Japanese display Comments', 'do not automatically translate/replace invalid values', 'Do not repair designs/models/IaC here or automatically create/execute another task'))<br>L48: 18 (('Implement design inputs are only authoritative model properties', 'Do not require the Agent to compare properties and generated Markdown twice in advance', 'Do not read generated `docs/designs/<environment>/<target-directory>/*.md` bodies (including `cloudformation-stacks.md`) at Implement start, IaC generation, or reference resolution', 'Retain Markdown/JSON generation/saving and local loop consistency validation as before', 'treat them as scope selectors', 'Without reading bodies', 'path/file stem', 'If corresponding models cannot be uniquely identified, stop without guessing', 'python3 -B framework/scripts/run-python.py -B framework/scripts/model/cli.py resource model/<environment>/<target-directory>/<service>.properties <resource-selector>', 'resource number', 'Selectors require exact matches for resource number (fixed entry, such as `001`) or immutable typed logicalId', 'single files and split entry indexes', 'parents, children, and siblings in the same group required by existing specifications, and service metadata/notes', 'Service-wide scope may use entire service properties', '対象accountの承認済み設計すべて', 'Reading all target Markdown as fallback is prohibited', 'desired values, resources, references, stack assignments, or human decisions', 'stop because a design task is required'))<br>L58: 動的 (reading.splitlines())<br>L61: 8 (("read only the target's runtime Model through the logical `model/<environment>/<target-directory>/cloudformation-stacks.properties`", 'desired.stack.*.name', '`.template`', '`.parameters`', '`.deployOrder`', 'desired.deployment.maxConcurrentStacks', 'effective MaxConcurrentStacks remains 1 under the existing contract', 'do not read it as Implement input'))<br>L65: 9 (('Use only authoritative model properties', '`desired.row.*`', '`.document`', 'saved Markdown Resource links', 'common parser/resolver', 'referenced Model groups', 'parentReference', 'Resolve through producer Model saved anchors, never names, cfn-logicalId or generated Markdown', 'never emit an unresolved Resource link, PENDING_DEPLOY or an inferred physical value to IaC'))<br>L69: 7 (('blueprint-loop.py --mode task', 'read-only `sync-model.py`', 'mismatches are FAIL', 'check_design_tables', 'check_design_links', 'check_stack_designs', 'do not omit/weaken these validations')) |
| `units/validation_checks/contracts.py::check_update_flow_prompt` | L85: 動的 (re.findall('(?:^\|`)(python\\\\s+framework/scripts/[^`\\\\n]+)', body, re.M))<br>L85: 動的 (shlex.split(line))<br>L89: 7 (('authoritative model properties', 'desired.row.*.document', 'Do not read generated Markdown bodies or generated JSON artifacts as input', 'model/cli.py resource', 'parentReference', 'saved Markdown Resource links', 'required parts'))<br>L92: 動的 (reading.splitlines())<br>L95: 動的 (instructions)<br>L99: 8 (('desired.stack.*.name', '.template', '.parameters', '.deployOrder', 'desired.deployment.maxConcurrentStacks', 'workspace', 'backend', 'variable input'))<br>L109: 7 (('--read-only', 'describe-stacks', 'list-exports', 'ExportingStackId', 'NOT_STARTED', '--pause-after-group', 'do not run it in ordinary CloudFormation update'))<br>L115: 5 (('--environment', '--alias', '--stack', '--state', '--profile'))<br>L117: 10 (('responsible for final preflight', 'account', 'region', 'issue gate', 'immutable input', 'SDK', 'validate-template', 'MaxConcurrentStacks', 'COMPLETE', '--resume'))<br>L122: 動的 (tf_commands)<br>L125: 7 (('terraform fmt -check', 'terraform validate', 'terraform plan -out=', 'terraform apply', 'saved plan binary', 'partial apply', 'AWS_PROFILE'))<br>L132: 7 (('owned by the controller', 'model.adapters.observed', 'IDENTIFIER_OUTPUT', 'PhysicalResourceId', 'all references', 'must not rerun', 'AMBIGUOUS_OBSERVED_MAPPING'))<br>L135: 動的 (cfn_post.splitlines())<br>L137: 7 (('Terraform output', 'state', 'non-sensitive', 'IDENTIFIER_OUTPUT', 'all references', 'PENDING_DEPLOY', 'sync-model.py --write'))<br>L141: 7 (('unexecuted', 'wait for human confirmation', '--approve-change-set', 'CREATE_COMPLETE/AVAILABLE', 'fingerprint', 'Do not execute with only partial approval', 'Do not reuse prior approval'))<br>L149: 7 (('Validation scope', 'Acceptance checks', 'read-only', 'mismatches are FAIL', 'validation cache', 'service parallelism', 'do not add all framework regression'))<br>L162: 動的 (enumerate(regressions, 1)) |
| `units/validation_checks/contracts.py::check_design_handoff_prompt` | 1（内部パラメータ化なし） |
| `units/validation_checks/contracts.py::check_rule_reading_contract` | L196: 動的 (sources)<br>L198: 動的 (markdown_prose(text))<br>L199: 動的 (re.findall('(?<!!)\\\\[[^\\\\]]+\\\\]\\\\(([^)]+)\\\\)', prose))<br>L212: 6 (('framework/scripts/deploy_preparation.py', 'framework/scripts/validation_cache.py', 'framework/scripts/validation/framework_contracts.py', 'README.md', '.agents/skills/worktree/SKILL.md', 'framework/rules/loop-engineering.md')) |
| `units/validation_checks/design.py::check_catalog_inputs` | 1（内部パラメータ化なし） |
| `units/validation_checks/design.py::check_schema_backed_design_rows` | L46: 動的 (validator.errors)<br>L47: 動的 (validator.errors) |
| `units/validation_checks/design.py::check_name_tag_and_identifier_order_contract` | L74: 動的 (MODULE.REQUIRED_NAME_PROPERTIES.items())<br>L96: 動的 (name_cases)<br>L102: 動的 (validator.errors)<br>L112: 動的 (identifier_cases)<br>L118: 動的 (validator.errors) |
| `units/validation_checks/design.py::check_cidr_pending_deploy` | L167: 動的 ((('CREATE', valid, None), ('CREATE', without_name, 'required Name property'), ('IMPORT', without_name, None)))<br>L183: 動的 (diagnostics)<br>L190: 動的 ((('resource_logical_ids', ValueError('識別情報が曖昧')), ('design_model_values', OSError('Model読み込み失敗'))))<br>L195: 動的 (([failed], [failed, path]))<br>L208: 動的 (names.call_args_list)<br>L211: 3 (('PENDING_DEPLOY', '`PENDING_DEPLOY`', '[PENDING_DEPLOY](#vpc-saved-original)'))<br>L213: 動的 (errors(valid.replace('`10.0.0.0/16`', pending, 1)))<br>L214: 動的 (errors(valid.replace('CidrBlock \| `10.0.0.0/16`', 'CidrBlock \| ' + pending)))<br>L215: 5 (('EC2.Subnet.CidrBlock', 'EC2.Route.CidrBlock', 'EC2.Route.DestinationCidrBlock', 'EC2.SecurityGroupIngress.CidrIp', 'EC2.TransitGateway.TransitGatewayCidrBlocks')) |
| `units/validation_checks/design.py::check_event_rule_row_order` | L254: 動的 (enumerate(selected, 1))<br>L262: 動的 ((rows[2:3] + rows[:2] + rows[3:], [rows[1], rows[0], *rows[2:]]))<br>L263: 動的 (errors(selected))<br>L264: 2 ((0, 1))<br>L265: 動的 ((rows[:index] + rows[index + 1:], rows + [rows[index]]))<br>L266: 動的 (errors(selected))<br>L267: 3 (('', 'UNSET', 'PENDING_DEPLOY'))<br>L270: 動的 (errors(selected)) |
| `units/validation_checks/references.py::check_artifact_naming` | 1（内部パラメータ化なし） |
| `units/validation_checks/runner.py::check_dispatch` | L50: 動的 (cases)<br>L?: 動的 (cases)<br>L?: 動的 (tail)<br>L60: 動的 (methods) |
| `units/validation_checks/runner.py::check_boundaries` | 1（内部パラメータ化なし） |
| `units/validation_checks/runner.py::check_module_keys` | L154: 動的 (names)<br>L136: 動的 ((root, runtime))<br>L139: 動的 (names)<br>L144: 動的 ((root, runtime))<br>L145: 動的 (names) |
| `units/validation_checks/scenario.py::check_timestamp` | 1（内部パラメータ化なし） |
| `units/validation_checks/task.py::check_optional_alias_targets` | alias/path/restrict・suffix 14入力・Region・engine整合性・共通Profile判定のfindings伝播。Profile 8入力とexecution account 9入力、account不正1入力は共通Identity UTへ移管。 |
| `units/validation_checks/task.py::check_model_task_boundaries` | L190: 動的 ({'design': {'docs/designs/dev/cde/vpc.md', 'model/parameters/dev/cde/vpc/parameters.yaml'}, 'infrastructure': {'infra/cloudformation/templates/vpc.yaml', 'docs/designs/dev/cde/vpc.md', 'model/parameters/dev/cde/vpc/parameters.yaml'}}.items()) |
| `units/validation_checks/terraform.py::check_configuration` | L273: 2 (('cloudformation', 'terraform'))<br>L35: 動的 (accounts)<br>L115: 3 (('infra/cloudformation/parameters/preview/ops', 'docs/designs/preview/ops', 'model/preview/ops'))<br>L128: 動的 (saved_module.items())<br>L143: 動的 (range(2))<br>L148: 2 (('01_initialize.md', '02_add-target.md'))<br>L167: 2 (('../modules/iam/../iam', '../modules/./iam'))<br>L170: 7 (('../modules', '../modules/iam/../../stg', './copied', '../modules/iam/../../../non-cde/terraform/modules/iam', 'registry.example/module', '${var.source}', '../modules/iam${var.suffix}'))<br>L191: 7 (('infra/cde/terraform/qa/main.tf', 'infra/cde/terraform/dev/copied/main.tf', 'infra/cde/terraform/modules/main.tf', 'infra/cde/terraform/main.tf', 'infra/cde/main.tf', 'infra/terraform/modules/cde/main.tf', 'infra/unknown/terraform/modules/iam/main.tf'))<br>L223: 4 (('/* unterminated', 'locals { text = <<EOF\nunterminated\n', 'locals { text = "unfinished', 'module "application" { source = "../modules/iam"'))<br>L229: 4 ((({'resource': {'aws_iam_role': {'bad': {}}}}, True), ({'resource': {'terraform_data': {'valid': {}}}}, False), ({'module': {'extra': {'source': '../modules/missing'}}}, True), ({'module': {'extra': {'source': '../modules/iam'}}}, False)))<br>L264: 3 (('cde', 'non-cde', '123456789012'))<br>L266: 動的 (accounts.values())<br>L269: 動的 (accounts.values())<br>L36: 動的 ((f'docs/designs/{env}/{target}', f'model/{env}/{target}', f'infra/{target}/terraform/{env}', f'infra/{target}/terraform/modules/iam'))<br>L144: 動的 (accounts)<br>L?: 2 (('dev', 'stg'))<br>L?: 2 (('cde', 'non-cde'))<br>L?: 動的 (shared.parent.iterdir())<br>L?: 動的 (root.rglob('*'))<br>L?: 動的 (range(1, 18))<br>L?: 動的 (bad.errors)<br>L?: 動的 (validate().errors)<br>L?: 動的 (validate(set(), changed=module_changes, task='governance').errors)<br>L?: 動的 (root.rglob('*'))<br>L?: 動的 (blocks(path))<br>L?: 動的 (validate().errors)<br>L?: 動的 (validate().errors) |
| `units/validation_scope-unit.checks.py::check_active_scope` | L15: 3 (('', '## Validation scope\n- `dev/cde`\n', '## Validation scope\n- `ec2`\n'))<br>L?: 2 (('dev', 'stg'))<br>L?: 2 (('cde', 'non-cde'))<br>L?: 動的 (sorted(scope)) |
| `units/worktree_python-unit.checks.py::check_environment` | L?: 3 (('VIRTUAL_ENV', 'PYTHONHOME', 'PYTHONPATH')) |
| `units/worktree_python-unit.checks.py::check_pdf_native_optional` | L?: 動的 (imports.call_args_list)<br>L?: 動的 (versions.call_args_list) |

## IT 全ケース

| 元ファイル : 行 | Test Case名 | 分類 | 現在の配置 | 入口 / パターン数 | 分類理由 | 変更 |
|---|---|---|---|---|---|---|
| `integrations/attribute-reference-resolution.checks.py:73` | `check_pair` | IT | [integrations/attribute-reference-resolution.checks.py:73](integrations/attribute-reference-resolution.checks.py#L73) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/attribute-reference-resolution.checks.py:123` | `check_fixed_label` | IT | [integrations/attribute-reference-resolution.checks.py:123](integrations/attribute-reference-resolution.checks.py#L123) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/attribute-reference-resolution.checks.py:186` | `check_stack` | IT | [integrations/attribute-reference-resolution.checks.py:186](integrations/attribute-reference-resolution.checks.py#L186) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/attribute-reference-resolution.checks.py:237` | `check_preparation_cache` | IT | [integrations/attribute-reference-resolution.checks.py:237](integrations/attribute-reference-resolution.checks.py#L237) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 変更不要 |
| `integrations/attribute-reference-resolution.checks.py:285` | `check` | IT | [integrations/attribute-reference-resolution.checks.py:285](integrations/attribute-reference-resolution.checks.py#L285) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/auxiliary-model-dependencies.checks.py:76` | `check` | IT | [integrations/auxiliary-model-dependencies.checks.py:75](integrations/auxiliary-model-dependencies.checks.py#L75) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `unknown/aws_mapping.checks.py:141` | `check_config` | IT | [integrations/aws_mapping.checks.py:14](integrations/aws_mapping.checks.py#L14) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/aws_mapping_compare.checks.py:32` | `mapping_checks` | IT | [integrations/aws_mapping_compare.checks.py:12](integrations/aws_mapping_compare.checks.py#L12) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/aws_mapping_display.checks.py:50` | `check` | IT | [integrations/aws_mapping_display.checks.py:15](integrations/aws_mapping_display.checks.py#L15) | direct / 1 | 現行Logsの生成・再生成一致・検証・Model不変、CodeCommit非表示IDの正本保持 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:41` | `check_running_and_interruption` | IT | [integrations/blueprint-loop.checks.py:11](integrations/blueprint-loop.checks.py#L11) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:108` | `check_deploy_scope_isolation` | IT | [integrations/blueprint-loop.checks.py:52](integrations/blueprint-loop.checks.py#L52) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 別タスク差分の除外期待を廃止。既存のScope・JSON・空白検証を保持 |
| `unknown/blueprint-loop.checks.py:235` | `check_task_service_validation` | IT | [integrations/blueprint-loop.checks.py:147](integrations/blueprint-loop.checks.py#L147) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:382` | `check_parallel_and_selection` | IT | [integrations/blueprint-loop.checks.py:292](integrations/blueprint-loop.checks.py#L292) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:493` | `check_staged_snapshot` | IT | [integrations/blueprint-loop.checks.py:320](integrations/blueprint-loop.checks.py#L320) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:602` | `check_regression_authorization` | IT | [integrations/blueprint-loop.checks.py:423](integrations/blueprint-loop.checks.py#L423) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:651` | `check_failure_suspension` | IT | [integrations/blueprint-loop.checks.py:471](integrations/blueprint-loop.checks.py#L471) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 予約由来の未登録変更preflightだけ削除。失敗時suspendと他契約不変を保持 |
| `unknown/blueprint-loop.checks.py:723` | `check_startup_diagnostics` | IT | [integrations/blueprint-loop.checks.py:531](integrations/blueprint-loop.checks.py#L531) | pytest / 11 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:831` | `check_windows_exit_propagation` | UT | [units/worktree_python-unit.checks.py](units/worktree_python-unit.checks.py) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:853` | `check_workflow` | IT | [integrations/blueprint-loop.checks.py:648](integrations/blueprint-loop.checks.py#L648) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `integrations/bound-anchor-name-change.checks.py:86` | `check` | IT | [integrations/bound-anchor-name-change.checks.py:86](integrations/bound-anchor-name-change.checks.py#L86) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/bound-stack-name-change.checks.py:33` | `check` | IT | [integrations/bound-stack-name-change.checks.py:28](integrations/bound-stack-name-change.checks.py#L28) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `unknown/check-model-aws.checks.py:272` | `service_checks` | IT | [integrations/check-model-aws.checks.py:14](integrations/check-model-aws.checks.py#L14) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:345` | `cli_checks` | IT | [integrations/check-model-aws.checks.py:81](integrations/check-model-aws.checks.py#L81) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:439` | `check_cli_service_names` | IT | [integrations/check-model-aws.checks.py:175](integrations/check-model-aws.checks.py#L175) | pytest / 8 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:449` | `batch_checks` | IT | [integrations/check-model-aws.checks.py:186](integrations/check-model-aws.checks.py#L186) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:582` | `common_checks` | IT | [integrations/check-model-aws.checks.py:326](integrations/check-model-aws.checks.py#L326) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:716` | `association_checks` | IT | [integrations/check-model-aws.checks.py:453](integrations/check-model-aws.checks.py#L453) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:812` | `stack_checks` | IT | [integrations/check-model-aws.checks.py:550](integrations/check-model-aws.checks.py#L550) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:841` | `cfn_identity_checks` | IT | [integrations/check-model-aws.checks.py:580](integrations/check-model-aws.checks.py#L580) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:865` | `identity_registry_checks` | IT | [integrations/check-model-aws.checks.py:605](integrations/check-model-aws.checks.py#L605) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:893` | `fixture_coverage` | IT | [integrations/check-model-aws.checks.py:634](integrations/check-model-aws.checks.py#L634) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/check-model-aws.checks.py:934` | `check_consumer_coverage` | IT | [integrations/check-model-aws.checks.py:676](integrations/check-model-aws.checks.py#L676) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:229` | `check_sdk_execution` | UT | [units/deploy-runtime-unit.checks.py:14](units/deploy-runtime-unit.checks.py#L14) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:331` | `check_empty_rollback_recreation` | UT | [units/deploy-runtime-unit.checks.py:116](units/deploy-runtime-unit.checks.py#L116) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:443` | `check_template_validation` | UT | [units/deploy-runtime-unit.checks.py:232](units/deploy-runtime-unit.checks.py#L232) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:469` | `check_inputs` | IT | [integrations/cloudformation-deploy.checks.py:254](integrations/cloudformation-deploy.checks.py#L254) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:657` | `check_delivery` | UT | [units/deploy-runtime-unit.checks.py:246](units/deploy-runtime-unit.checks.py#L246) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:919` | `check_delivery_encryption` | UT | [units/deploy-runtime-unit.checks.py:506](units/deploy-runtime-unit.checks.py#L506) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1129` | `check_session_cli` | UT | [units/deploy-runtime-unit.checks.py:728](units/deploy-runtime-unit.checks.py#L728) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1421` | `check_parallel_and_restart` | UT | [units/deploy-runtime-unit.checks.py:995](units/deploy-runtime-unit.checks.py#L995) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1503` | `check_observed_collector` | IT | [integrations/cloudformation-deploy.checks.py:1260](integrations/cloudformation-deploy.checks.py#L1260) | pytest / 1 | 取得・保存、無関係な意味不備は継続／構文破損は停止、公開Task scopeを維持 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1640` | `check_shared_stack_mapping` | IT | [integrations/cloudformation-deploy.checks.py:1391](integrations/cloudformation-deploy.checks.py#L1391) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1803` | `check_import_implementation_mapping` | IT | [integrations/cloudformation-deploy.checks.py:1643](integrations/cloudformation-deploy.checks.py#L1643) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1859` | `check_integrated_child_mapping` | IT | [integrations/cloudformation-deploy.checks.py:1700](integrations/cloudformation-deploy.checks.py#L1700) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:1957` | `check_secretsmanager_arn_identifiers` | IT | [integrations/cloudformation-deploy.checks.py:1799](integrations/cloudformation-deploy.checks.py#L1799) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:2051` | `check_api_timing` | UT | [units/deploy-runtime-unit.checks.py:1077](units/deploy-runtime-unit.checks.py#L1077) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:2067` | `check_controlled_repair` | UT | [units/deploy-runtime-unit.checks.py:1094](units/deploy-runtime-unit.checks.py#L1094) | pytest / 1 | No source editing; original cleanup safety/provenance, retention and atomic reset | 配置/共有fixture分離 |
| `unknown/cloudformation-deploy.checks.py:2468` | `check_secret_runtime_bootstrap` | UT | [units/deploy-runtime-unit.checks.py:1487](units/deploy-runtime-unit.checks.py#L1487) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-destroy.checks.py:134` | `check_order_and_safety` | IT | [integrations/cloudformation-destroy.checks.py:136](integrations/cloudformation-destroy.checks.py#L136) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-destroy.checks.py:208` | `check_unused_export` | IT | [integrations/cloudformation-destroy.checks.py:210](integrations/cloudformation-destroy.checks.py#L210) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-destroy.checks.py:232` | `check_absence` | IT | [integrations/cloudformation-destroy.checks.py:234](integrations/cloudformation-destroy.checks.py#L234) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-destroy.checks.py:321` | `check_controller` | IT | [integrations/cloudformation-destroy.checks.py:323](integrations/cloudformation-destroy.checks.py#L323) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-destroy.checks.py:426` | `check_observed` | IT | [integrations/cloudformation-destroy.checks.py:441](integrations/cloudformation-destroy.checks.py#L441) | pytest / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-naming.checks.py:63` | `check_imports` | IT | [integrations/cloudformation-naming.checks.py:63](integrations/cloudformation-naming.checks.py#L63) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-naming.checks.py:102` | `check_names` | IT | [integrations/cloudformation-naming.checks.py:102](integrations/cloudformation-naming.checks.py#L102) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/cloudformation-naming.checks.py:126` | `check_flow_logs` | IT | [integrations/cloudformation-naming.checks.py:126](integrations/cloudformation-naming.checks.py#L126) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-naming.checks.py:172` | `check` | IT | [integrations/cloudformation-naming.checks.py:172](integrations/cloudformation-naming.checks.py#L172) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/cloudformation-naming.checks.py:180` | `check_fixtures` | IT | [integrations/cloudformation-naming.checks.py:180](integrations/cloudformation-naming.checks.py#L180) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `integrations/cloudtrail-input-reference.checks.py:20` | `check` | IT | [integrations/cloudtrail-input-reference.checks.py:20](integrations/cloudtrail-input-reference.checks.py#L20) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `unknown/deploy_preparation.checks.py:105` | `check_preparation` | IT | [integrations/deploy_preparation.checks.py:15](integrations/deploy_preparation.checks.py#L15) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:184` | `check_stale_and_conflicts` | IT | [integrations/deploy_preparation.checks.py:103](integrations/deploy_preparation.checks.py#L103) | direct / 1 | issue/runtime/契約候補/Model/生成Markdown・JSONの変更と削除を拒否（Framework入力条件を削除） | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:233` | `check_generated_boundaries` | IT | [integrations/deploy_preparation.checks.py:135](integrations/deploy_preparation.checks.py#L135) | direct / 1 | Adapter・取得・比較の連携 | 配置/共有fixture分離 |
| `unknown/deploy_preparation.checks.py:309` | `check_service_generated_equality` | IT | [integrations/deploy_preparation.checks.py:213](integrations/deploy_preparation.checks.py#L213) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_document.checks.py:96` | `check_snapshot` | IT | [integrations/design_document.checks.py:12](integrations/design_document.checks.py#L12) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_document.checks.py:145` | `check_links` | IT | [integrations/design_document.checks.py:61](integrations/design_document.checks.py#L61) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:149` | `check_secret_rotation_display` | IT | [integrations/design_layout.checks.py:14](integrations/design_layout.checks.py#L14) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:244` | `check_codebuild_variable_display` | IT | [integrations/design_layout.checks.py:143](integrations/design_layout.checks.py#L143) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:319` | `check_codebuild_vpc_display` | IT | [integrations/design_layout.checks.py:215](integrations/design_layout.checks.py#L215) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:406` | `check_subnet_list_links` | IT | [integrations/design_layout.checks.py:300](integrations/design_layout.checks.py#L300) | pytest / 16 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:458` | `check_guardduty_feature_display` | IT | [integrations/design_layout.checks.py:352](integrations/design_layout.checks.py#L352) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:487` | `check_cloudtrail_data_resources` | IT | [integrations/design_layout.checks.py:378](integrations/design_layout.checks.py#L378) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:592` | `check_codepipeline_display` | IT | [integrations/design_layout.checks.py:479](integrations/design_layout.checks.py#L479) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:704` | `check_config_firehose_references` | IT | [integrations/design_layout.checks.py:579](integrations/design_layout.checks.py#L579) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:838` | `check_resource_name_headings` | IT | [integrations/design_layout.checks.py:728](integrations/design_layout.checks.py#L728) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:934` | `check_quicksight_group_principal_reference` | IT | [integrations/design_layout.checks.py:815](integrations/design_layout.checks.py#L815) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/design_layout.checks.py:981` | `check_workflow` | IT | [integrations/design_layout.checks.py:862](integrations/design_layout.checks.py#L862) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/framework-input-isolation.checks.py:23` | `check` | IT | [integrations/framework-input-isolation.checks.py:14](integrations/framework-input-isolation.checks.py#L14) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/human-inputs-group-05.checks.py:253` | `check_declared_inputs` | IT | [integrations/human-inputs-group-05.checks.py:25](integrations/human-inputs-group-05.checks.py#L25) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `import-agent-sources::check_cli_preflight` | `check_cli_preflight` | IT | [integrations/import-cli.checks.py](integrations/import-cli.checks.py) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_logs_roundtrip` | `check_logs_roundtrip` | IT | [integrations/import-model.checks.py:70](integrations/import-model.checks.py#L70) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_config_sources` | `check_config_sources` | IT | [integrations/import-model.checks.py:92](integrations/import-model.checks.py#L92) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_vpc_eight_instances` | `check_vpc_eight_instances` | IT | [integrations/import-model.checks.py:108](integrations/import-model.checks.py#L108) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_quicksight_normalization` | `check_quicksight_normalization` | IT | [integrations/import-model.checks.py:122](integrations/import-model.checks.py#L122) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_registry_services` | `check_registry_services` | IT | [integrations/import-model.checks.py:132](integrations/import-model.checks.py#L132) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_managed_resource_addition` | `check_managed_resource_addition` | IT | [integrations/import-model.checks.py:146](integrations/import-model.checks.py#L146) | pytest / 3 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_existing_resource_selection_rejected` | `check_existing_resource_selection_rejected` | IT | [integrations/import-model.checks.py:196](integrations/import-model.checks.py#L196) | pytest / 2 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_optional_profile` | `check_optional_profile` | IT | [integrations/import-model.checks.py:207](integrations/import-model.checks.py#L207) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_explicit_no_profile` | `check_explicit_no_profile` | IT | [integrations/import-model.checks.py:218](integrations/import-model.checks.py#L218) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_single_acquisition` | `check_single_acquisition` | IT | [integrations/import-model.checks.py:229](integrations/import-model.checks.py#L229) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_source_race` | `check_source_race` | IT | [integrations/import-model.checks.py:237](integrations/import-model.checks.py#L237) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_create_definition_reuse` | `check_create_definition_reuse` | IT | [integrations/import-model.checks.py:249](integrations/import-model.checks.py#L249) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_cli_faults` | `check_cli_faults` | IT | [integrations/import-model.checks.py:261](integrations/import-model.checks.py#L261) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_inventory_parent_references` | `check_inventory_parent_references` | IT | [integrations/import-model.checks.py:280](integrations/import-model.checks.py#L280) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_exact_scope` | `check_exact_scope` | IT | [integrations/import-model.checks.py:289](integrations/import-model.checks.py#L289) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_external_reference_preservation` | `check_external_reference_preservation` | IT | [integrations/import-model.checks.py:300](integrations/import-model.checks.py#L300) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_mapping_preservation` | `check_mapping_preservation` | IT | [integrations/import-model.checks.py:320](integrations/import-model.checks.py#L320) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_shared_property_and_bindings` | `check_shared_property_and_bindings` | IT | [integrations/import-model.checks.py:329](integrations/import-model.checks.py#L329) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_foreign_source_writes_rejected` | `check_foreign_source_writes_rejected` | IT | [integrations/import-model.checks.py:348](integrations/import-model.checks.py#L348) | pytest / 5 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_add_identity_boundary` | `check_add_identity_boundary` | IT | [integrations/import-model.checks.py:365](integrations/import-model.checks.py#L365) | pytest / 4 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_unacquired_property_rejection` | `check_unacquired_property_rejection` | IT | [integrations/import-model.checks.py:406](integrations/import-model.checks.py#L406) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_repeat_without_reformat` | `check_repeat_without_reformat` | IT | [integrations/import-model.checks.py:416](integrations/import-model.checks.py#L416) | pytest / 1 | 同一Taskの再取得拒否、API未実行と保存済みModel不変 | Append-only Import |
| `import-agent-sources::check_fixed_identity_rejection` | `check_fixed_identity_rejection` | IT | [integrations/import-model.checks.py:442](integrations/import-model.checks.py#L442) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_empty_inventory_preserves_sources` | `check_empty_inventory_preserves_sources` | IT | [integrations/import-model.checks.py:456](integrations/import-model.checks.py#L456) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_partial_reflection` | `check_partial_reflection` | IT | [integrations/import-model.checks.py:469](integrations/import-model.checks.py#L469) | pytest / 1 | 未回答Resourceがある全サービスPublish拒否、部分保存なし | Append-only Import |
| `import-agent-sources::check_native_types_preserved` | `check_native_types_preserved` | IT | [integrations/import-model.checks.py:481](integrations/import-model.checks.py#L481) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_consumer_set_race` | `check_consumer_set_race` | IT | [integrations/import-model.checks.py:495](integrations/import-model.checks.py#L495) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_source_transaction_rollback` | `check_source_transaction_rollback` | IT | [integrations/import-model.checks.py:509](integrations/import-model.checks.py#L509) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_yaml_candidate_edit` | `check_yaml_candidate_edit` | IT | [integrations/import-model.checks.py:531](integrations/import-model.checks.py#L531) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_reflection_validation_boundary` | `check_reflection_validation_boundary` | IT | [integrations/import-model.checks.py:543](integrations/import-model.checks.py#L543) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_cross_process_evidence` | `check_cross_process_evidence` | IT | [integrations/import-cli.checks.py](integrations/import-cli.checks.py) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_dry_run_cleanup` | `check_dry_run_cleanup` | IT | [integrations/import-model.checks.py:553](integrations/import-model.checks.py#L553) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `import-agent-sources::check_evidence_and_display_recovery` | `check_evidence_and_display_recovery` | IT | [integrations/import-model.checks.py:572](integrations/import-model.checks.py#L572) | pytest / 1 | 取得・追加・保存・証跡・表示境界の連携 | Append-only Import |
| `integrations/issues_api_only.checks.py:27` | `main_checks` | IT | [integrations/issues_api_only.checks.py:11](integrations/issues_api_only.checks.py#L11) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/issues_failed_services.checks.py:21` | `main_checks` | IT | [integrations/issues_failed_services.checks.py:21](integrations/issues_failed_services.checks.py#L21) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/issues_policy_equivalence.checks.py:21` | `main_checks` | IT | [integrations/issues_policy_equivalence.checks.py:21](integrations/issues_policy_equivalence.checks.py#L21) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `integrations/issues_ref_returns.checks.py:18` | `main_checks` | IT | [integrations/issues_ref_returns.checks.py:18](integrations/issues_ref_returns.checks.py#L18) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 変更不要 |
| `unknown/issues_scan.checks.py:152` | `naming_target_scope_cases` | IT | [integrations/issues_scan.checks.py:14](integrations/issues_scan.checks.py#L14) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:226` | `checks` | IT | [integrations/issues_scan.checks.py:71](integrations/issues_scan.checks.py#L71) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:398` | `resource_cases` | IT | [integrations/issues_scan.checks.py:244](integrations/issues_scan.checks.py#L244) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:458` | `extended_cases` | IT | [integrations/issues_scan.checks.py:305](integrations/issues_scan.checks.py#L305) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:1917` | `check_nested_membership` | IT | [integrations/issues_scan.checks.py:1286](integrations/issues_scan.checks.py#L1286) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:1945` | `check_cloudtrail_membership` | IT | [integrations/issues_scan.checks.py:1314](integrations/issues_scan.checks.py#L1314) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:2034` | `check_condition_diagnostics` | IT | [integrations/issues_scan.checks.py:1403](integrations/issues_scan.checks.py#L1403) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:2147` | `check_scan_workflow` | IT | [integrations/issues_scan.checks.py:1516](integrations/issues_scan.checks.py#L1516) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:1289` | `check_summary_detail_cli` | IT | [integrations/issues_scan.checks.py:1534](integrations/issues_scan.checks.py#L1534) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 関数内抽出 |
| `unknown/issues_scan.checks.py:2274` | `check_arn_array_reference_forms` | IT | [integrations/issues_scan.checks.py:1657](integrations/issues_scan.checks.py#L1657) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:2337` | `check_eventbridge_reference_literals` | IT | [integrations/issues_scan.checks.py:1720](integrations/issues_scan.checks.py#L1720) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:2395` | `check_glue_connection_names` | IT | [integrations/issues_scan.checks.py:1778](integrations/issues_scan.checks.py#L1778) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:2460` | `check_added_reference_properties` | IT | [integrations/issues_scan.checks.py:1843](integrations/issues_scan.checks.py#L1843) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:2607` | `check_aws_standard_comparison` | IT | [integrations/issues_scan.checks.py:1990](integrations/issues_scan.checks.py#L1990) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/json-yaml-document-hash.checks.py:21` | `check` | IT | [integrations/json-yaml-document-hash.checks.py:14](integrations/json-yaml-document-hash.checks.py#L14) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `integrations/lambda-input-reference.checks.py:29` | `check` | IT | [integrations/lambda-input-reference.checks.py:29](integrations/lambda-input-reference.checks.py#L29) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `unknown/model-input-context-digest.checks.py:30` | `check` | IT | [integrations/model-input-context-digest.checks.py:30](integrations/model-input-context-digest.checks.py#L30) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model-test.checks.py:89` | `check` | IT | [integrations/model-test.checks.py:93](integrations/model-test.checks.py#L93) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:96` | `check_route53_endpoint_dns_roundtrip` | IT | [integrations/model_design.checks.py:11](integrations/model_design.checks.py#L13) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:144` | `check_firehose_import_pending_roundtrip` | IT | [integrations/model_design.checks.py:59](integrations/model_design.checks.py#L61) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:176` | `check_config_import_pending_roundtrip` | IT | [integrations/model_design.checks.py:91](integrations/model_design.checks.py#L96) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:222` | `check_desired_only_identifier_reference` | IT | [integrations/model_design.checks.py:124](integrations/model_design.checks.py#L132) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:260` | `check_catalog_display_order` | IT | [integrations/model_design.checks.py:162](integrations/model_design.checks.py#L175) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:331` | `check_kms_policy_execution_account` | IT | [integrations/model_design.checks.py:233](integrations/model_design.checks.py#L239) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:395` | `check_glue_argument_display` | IT | [integrations/model_design.checks.py:297](integrations/model_design.checks.py#L304) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:437` | `check_ec2_compact_display` | IT | [integrations/model_design.checks.py:339](integrations/model_design.checks.py#L346) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:491` | `check_vpc_endpoint_name_display` | IT | [integrations/model_design.checks.py:393](integrations/model_design.checks.py#L401) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:583` | `check_subnet_lambda_roundtrip` | IT | [integrations/model_design.checks.py:432](integrations/model_design.checks.py#L443) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:595` | `check_subnet_model_validation` | IT | [integrations/model_design.checks.py:444](integrations/model_design.checks.py#L455) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:632` | `check_athena_configuration_display` | IT | [integrations/model_design.checks.py:481](integrations/model_design.checks.py#L492) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:667` | `check_config_typed_anchors` | IT | [integrations/model_design.checks.py:516](integrations/model_design.checks.py#L527) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:762` | `check_kms_alias_display` | IT | [integrations/model_design.checks.py:611](integrations/model_design.checks.py#L620) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:817` | `check_nameless_type_display` | IT | [integrations/model_design.checks.py:666](integrations/model_design.checks.py#L676) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:907` | `check_nameless_logical_id_label` | IT | [integrations/model_design.checks.py:756](integrations/model_design.checks.py#L769) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:972` | `check_optional_naming_suffix` | IT | [integrations/model_design.checks.py:821](integrations/model_design.checks.py#L843) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1004` | `check_stack_policy` | IT | [integrations/model_design.checks.py:853](integrations/model_design.checks.py#L875) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1062` | `check_stack_mapping_roundtrip` | IT | [integrations/model_design.checks.py:910](integrations/model_design.checks.py#L931) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1254` | `check_secret_naming_values` | IT | [integrations/model_design.checks.py:1018](integrations/model_design.checks.py#L1039) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1353` | `check_naming_exclusions` | IT | [integrations/model_design.checks.py:1090](integrations/model_design.checks.py#L1059) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1412` | `check_codebuild_required_name` | IT | [integrations/model_design.checks.py:1149](integrations/model_design.checks.py#L1118) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1463` | `check_iam_role_name` | IT | [integrations/model_design.checks.py:1200](integrations/model_design.checks.py#L1169) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1523` | `check_required_name_tag` | IT | [integrations/model_design.checks.py:1260](integrations/model_design.checks.py#L1230) | pytest / 2 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:1656` | `check_service_failure_protection` | IT | [integrations/model_design.checks.py:1368](integrations/model_design.checks.py#L1340) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 入力変更検出前に既存Scope契約を作成。保存・rollback検証を保持 |
| `unknown/model_design.checks.py:1970` | `check_service_displays` | IT | [integrations/model_design.checks.py:1643](integrations/model_design.checks.py#L1628) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_design.checks.py:2092` | `check_observed_arn_authority` | IT | [integrations/model_design.checks.py:1735](integrations/model_design.checks.py#L1720) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `model_design.checks.py::check_dynamic_reference_candidates` | `check_dynamic_reference_candidates` | IT | [integrations/model_design.checks.py](integrations/model_design.checks.py#L1746) | pytest / 1 | 合成Snowflake Modelの正式candidate検証・生成・再読込、Username/Passwordの不正値拒否と入力・既存表示の保持 | 共通動的参照検証 |
| `unknown/model_files.checks.py:38` | `check_resource_reading` | IT | [integrations/model_files.checks.py:18](integrations/model_files.checks.py#L18) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:115` | `check_precision` | IT | [integrations/model_impact.checks.py:115](integrations/model_impact.checks.py#L115) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:161` | `check_identity_and_deletion` | IT | [integrations/model_impact.checks.py:161](integrations/model_impact.checks.py#L161) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:180` | `check_shared_environments` | IT | [integrations/model_impact.checks.py:180](integrations/model_impact.checks.py#L180) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:195` | `check_identifiers` | IT | [integrations/model_impact.checks.py:195](integrations/model_impact.checks.py#L195) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:223` | `check_type_and_unknown` | IT | [integrations/model_impact.checks.py:223](integrations/model_impact.checks.py#L223) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:239` | `check_import_scope` | IT | [integrations/model_impact.checks.py:239](integrations/model_impact.checks.py#L239) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:252` | `check_selection` | IT | [integrations/model_impact.checks.py:252](integrations/model_impact.checks.py#L252) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_impact.checks.py:268` | `check_cycles` | IT | [integrations/model_impact.checks.py:268](integrations/model_impact.checks.py#L268) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:105` | `check_human` | IT | [integrations/model_parameter_inputs.checks.py:11](integrations/model_parameter_inputs.checks.py#L11) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:294` | `check_declared_instance_inputs` | IT | [integrations/model_parameter_inputs.checks.py:196](integrations/model_parameter_inputs.checks.py#L196) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:353` | `check_kms_alias` | IT | [integrations/model_parameter_inputs.checks.py:255](integrations/model_parameter_inputs.checks.py#L255) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:413` | `check_external_instances` | IT | [integrations/model_parameter_inputs.checks.py:315](integrations/model_parameter_inputs.checks.py#L315) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_parameter_inputs.checks.py:494` | `check_service_contracts` | IT | [integrations/model_parameter_inputs.checks.py:386](integrations/model_parameter_inputs.checks.py#L386) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:72` | `check_transactions` | IT | [integrations/model_templates.checks.py:11](integrations/model_templates.checks.py#L11) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:156` | `check_expansion` | IT | [integrations/model_templates.checks.py:54](integrations/model_templates.checks.py#L54) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:187` | `check_layout` | IT | [integrations/model_templates.checks.py:85](integrations/model_templates.checks.py#L85) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:231` | `check_reference_impact` | IT | [integrations/model_templates.checks.py:129](integrations/model_templates.checks.py#L129) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:361` | `check_template_snapshot` | IT | [integrations/model_templates.checks.py:259](integrations/model_templates.checks.py#L259) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:392` | `check_creation` | IT | [integrations/model_templates.checks.py:290](integrations/model_templates.checks.py#L290) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:409` | `check_invalid` | IT | [integrations/model_templates.checks.py:306](integrations/model_templates.checks.py#L306) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:434` | `check_sync` | IT | [integrations/model_templates.checks.py:331](integrations/model_templates.checks.py#L331) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/model_templates.checks.py:462` | `check_common_shape` | IT | [integrations/model_templates.checks.py:359](integrations/model_templates.checks.py#L359) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/policy_tables.checks.py:47` | `check_iam` | IT | [integrations/policy_tables.checks.py:12](integrations/policy_tables.checks.py#L12) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/policy_tables.checks.py:254` | `check_service_policies` | IT | [integrations/policy_tables.checks.py:443](integrations/policy_tables.checks.py#L443) | pytest / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/policy_tables.checks.py:387` | `check_grouping_and_settings` | IT | [integrations/policy_tables.checks.py:446](integrations/policy_tables.checks.py#L446) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/producer-identifier-reference.checks.py:31` | `check` | IT | [integrations/producer-identifier-reference.checks.py:11](integrations/producer-identifier-reference.checks.py#L11) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `integrations/producer-name-reference.checks.py:29` | `check` | IT | [integrations/producer-name-reference.checks.py:29](integrations/producer-name-reference.checks.py#L29) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `unknown/raw-bucket-name-reference.checks.py:29` | `check` | IT | [integrations/raw-bucket-name-reference.checks.py:11](integrations/raw-bucket-name-reference.checks.py#L11) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `integrations/s3-bound-anchor.checks.py:37` | `check` | IT | [integrations/s3-bound-anchor.checks.py:21](integrations/s3-bound-anchor.checks.py#L21) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `integrations/security-group-input-reference.checks.py:29` | `check` | IT | [integrations/security-group-input-reference.checks.py:29](integrations/security-group-input-reference.checks.py#L29) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 変更不要 |
| `support/service_contracts.py:26` | `check_kms` | IT | [integrations/service_contracts.py:25](integrations/service_contracts.py#L25) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/service_contracts.py:53` | `check_security_group` | IT | [integrations/service_contracts.py:52](integrations/service_contracts.py#L52) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/service_contracts.py:78` | `check_route53` | IT | [integrations/service_contracts.py:77](integrations/service_contracts.py#L77) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/service_contracts.py:113` | `check_iam` | IT | [integrations/service_contracts.py:112](integrations/service_contracts.py#L112) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/service_contracts.py:145` | `check_s3` | IT | [integrations/service_contracts.py:144](integrations/service_contracts.py#L144) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `support/service_contracts.py:179` | `check_glue` | IT | [integrations/service_contracts.py:178](integrations/service_contracts.py#L178) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/service_contracts.py:202` | `check_cloudwatch_logs` | IT | [integrations/service_contracts.py:201](integrations/service_contracts.py#L201) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/service_contracts.py:219` | `check_lambda` | IT | [integrations/service_contracts.py:218](integrations/service_contracts.py#L218) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/service_contracts.py:245` | `check_eventbridge` | IT | [integrations/service_contracts.py:244](integrations/service_contracts.py#L244) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/service_contracts.py:277` | `check_codepipeline` | IT | [integrations/service_contracts.py:276](integrations/service_contracts.py#L276) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/service_contracts.py:313` | `check_responsibilities` | IT | [integrations/service_contracts.py:312](integrations/service_contracts.py#L312) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/service_contracts.py:401` | `check` | IT | [integrations/service_contracts.py:400](integrations/service_contracts.py#L400) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/service_contracts.py:410` | `check_fixtures` | IT | [integrations/service_contracts.py:409](integrations/service_contracts.py#L409) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `integrations/sync-existing-files.checks.py:30` | `check_failure_safety` | IT | [integrations/sync-existing-files.checks.py:30](integrations/sync-existing-files.checks.py#L30) | direct / 1 | CLI/subprocessまたはGitとの連携 | 変更不要 |
| `unknown/sync-model.checks.py:81` | `check_publication_boundary` | IT | [integrations/sync-model.checks.py:321](integrations/sync-model.checks.py#L321) | pytest / 6 | source/project/part/consumer/extra/contract変更を保存前拒否、保存ゼロと外部変更保持（mapping条件を削除） | 配置/共有fixture分離 |
| `unknown/sync-model.checks.py:129` | `check_unchanged_sidecar` | IT | [integrations/sync-model.checks.py:393](integrations/sync-model.checks.py#L393) | pytest / 2 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/sync-model.checks.py:157` | `check_changed_sidecar_publication` | IT | [integrations/sync-model.checks.py:414](integrations/sync-model.checks.py#L414) | pytest / 3 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/sync-model.checks.py:177` | `check_publication_rechecks_excluded_outputs` | IT | [integrations/sync-model.checks.py:434](integrations/sync-model.checks.py#L434) | pytest / 6 | 変更なしJSONも入力として保存前照合し、sidecar/source/契約の外部変更を保持して停止 | 配置/共有fixture分離 |
| `unknown/sync-model.checks.py:203` | `check_changed_sidecar_publication_rollback` | IT | [integrations/sync-model.checks.py:458](integrations/sync-model.checks.py#L458) | pytest / 2 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/sync-model.checks.py:238` | `check_unchanged_sidecar_path_safety` | IT | [integrations/sync-model.checks.py:493](integrations/sync-model.checks.py#L493) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/sync-model.checks.py:250` | `check_unchanged_sidecar_validation` | IT | [integrations/sync-model.checks.py:505](integrations/sync-model.checks.py#L505) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/sync-model.checks.py:330` | `check_failure_counts` | IT | [integrations/sync-model.checks.py:517](integrations/sync-model.checks.py#L517) | pytest / 1 | 候補不採用の部分成功・全体FAIL・保持設計リンクWARN分類を維持 | 配置/共有fixture分離 |
| `unknown/sync-model.checks.py:376` | `check_incoming_reference_models` | IT | [integrations/sync-model.checks.py:582](integrations/sync-model.checks.py#L582) | pytest / 2 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/sync-model.checks.py:402` | `check_required_preflight` | IT | [integrations/sync-model.checks.py:612](integrations/sync-model.checks.py#L612) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/sync-model.checks.py:485` | `check_required_property_parents` | IT | [integrations/sync-model.checks.py:692](integrations/sync-model.checks.py#L692) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/sync-model.checks.py:552` | `check_workflow` | IT | [integrations/sync-model.checks.py:751](integrations/sync-model.checks.py#L751) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/task_contract.checks.py:155` | `check_admission_selection` | IT | [integrations/task_contract.checks.py:169](integrations/task_contract.checks.py#L169) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/task_contract.checks.py:204` | `check_completed_legacy_and_paths` | IT | [integrations/task_contract.checks.py:46](integrations/task_contract.checks.py#L46) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/task_contract.checks.py:241` | `check_shared_issue_files` | IT | [integrations/task_contract.checks.py:190](integrations/task_contract.checks.py#L190) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/task_contract.checks.py:325` | `check_suspend_and_resume` | IT | [integrations/task_contract.checks.py:78](integrations/task_contract.checks.py#L78) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/task_contract.checks.py:521` | `check_atomic_contract_reads` | IT | [integrations/task_contract.checks.py:120](integrations/task_contract.checks.py#L120) | pytest / 4 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/used-definition-inputs.checks.py:29` | `check` | IT | [integrations/used-definition-inputs.checks.py:19](integrations/used-definition-inputs.checks.py#L19) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/cloudformation.py:304` | `check_cloudformation_stack_design` | IT | [integrations/validation_checks/cloudformation.py:17](integrations/validation_checks/cloudformation.py#L17) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/cloudformation.py:373` | `check_stack_mapping_targets` | IT | [integrations/validation_checks/cloudformation.py:87](integrations/validation_checks/cloudformation.py#L87) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `support/validation_checks/design.py:130` | `check_description_design_constraints` | IT | [integrations/validation_checks/design.py:16](integrations/validation_checks/design.py#L16) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:19` | `check_identifier_propagation` | IT | [integrations/validation_checks/references.py:13](integrations/validation_checks/references.py#L13) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:88` | `check_array_source_role_links` | IT | [integrations/validation_checks/references.py:82](integrations/validation_checks/references.py#L82) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:125` | `check_s3_bucket_policy_grouping` | IT | [integrations/validation_checks/references.py:119](integrations/validation_checks/references.py#L119) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:228` | `check_subnet_association_overview` | IT | [integrations/validation_checks/references.py:222](integrations/validation_checks/references.py#L222) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `support/validation_checks/references.py:330` | `check_resource_overview` | IT | [integrations/validation_checks/references.py:324](integrations/validation_checks/references.py#L324) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/runner.py:105` | `check_module_inputs` | IT | [integrations/validation_checks/runner.py:31](integrations/validation_checks/runner.py#L31) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `support/validation_checks/scenario.py:6` | `check_records` | IT | [integrations/validation_checks/scenario.py:10](integrations/validation_checks/scenario.py#L10) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/scope.py:13` | `check_deployment_iac_scope` | IT | [integrations/validation_checks/scope.py:32](integrations/validation_checks/scope.py#L32) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:12` | `check_task_contract` | IT | [integrations/validation_checks/task.py:25](integrations/validation_checks/task.py#L25) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:68` | `check_idle_without_active_task` | IT | [integrations/validation_checks/task.py:81](integrations/validation_checks/task.py#L81) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:97` | `check_destroy_phase` | IT | [integrations/validation_checks/task.py:110](integrations/validation_checks/task.py#L110) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:143` | `check_task_type_dispatch` | IT | [integrations/validation_checks/task.py:156](integrations/validation_checks/task.py#L156) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `support/validation_checks/task.py:157` | `check_task_type_cases` | IT | [integrations/validation_checks/task.py:170](integrations/validation_checks/task.py#L170) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/blueprint-loop.checks.py:191` | `check_cli` | IT | [integrations/validation_checks/terraform.py:28](integrations/validation_checks/terraform.py#L28) | direct / 1 | CLI/subprocessまたはGitとの連携 | 関数内抽出 |
| `unknown/validation_scope.checks.py:39` | `check_single_target_cache` | IT | [integrations/validation_scope.checks.py:15](integrations/validation_scope.checks.py#L15) | direct / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/validation_scope.checks.py:124` | `check_template_consumers` | IT | [integrations/validation_scope.checks.py:107](integrations/validation_scope.checks.py#L107) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_python.checks.py:33` | `check_output_decoding` | IT | [integrations/worktree_python.checks.py:14](integrations/worktree_python.checks.py#L14) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_python.checks.py:54` | `check_setup` | IT | [integrations/worktree_python.checks.py:54](integrations/worktree_python.checks.py#L54) | direct / 1 | CLI/subprocessまたはGitとの連携 | 共有環境の初回のみ構築、3 Task再利用、失敗復旧、登録整合性・権限拒否を確認 |
| `unknown/worktree_python.checks.py:141` | `check_real_global` | IT | [integrations/worktree_python.checks.py:131](integrations/worktree_python.checks.py#L131) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_python.checks.py:162` | `check_venv_fallback` | IT | [integrations/worktree_python.checks.py:147](integrations/worktree_python.checks.py#L147) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_python.checks.py:236` | `check_parallel_fallback` | IT | [integrations/worktree_python.checks.py:196](integrations/worktree_python.checks.py#L196) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_python.checks.py:307` | `check_symlink_safety` | IT | [integrations/worktree_python.checks.py:301](integrations/worktree_python.checks.py#L301) | direct / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:103` | `check_success_and_empty` | IT | [integrations/worktree_task.checks.py:16](integrations/worktree_task.checks.py#L16) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:132` | `check_finalize_line_endings` | IT | [integrations/worktree_task.checks.py:47](integrations/worktree_task.checks.py#L47) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:157` | `check_incomplete_and_git_safety` | IT | [integrations/worktree_task.checks.py:73](integrations/worktree_task.checks.py#L73) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:204` | `check_dirty_base_and_retry` | IT | [integrations/worktree_task.checks.py:110](integrations/worktree_task.checks.py#L110) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:225` | `check_ahead_and_rebase_conflict` | IT | [integrations/worktree_task.checks.py:133](integrations/worktree_task.checks.py#L133) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:252` | `check_collisions_and_base_selection` | IT | [integrations/worktree_task.checks.py:187](integrations/worktree_task.checks.py#L187) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:284` | `check_directory_layout` | IT | [integrations/worktree_task.checks.py:220](integrations/worktree_task.checks.py#L220) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:312` | `check_metadata_storage` | IT | [integrations/worktree_task.checks.py:249](integrations/worktree_task.checks.py#L249) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:365` | `check_cleanup_failure_and_retry` | IT | [integrations/worktree_task.checks.py:297](integrations/worktree_task.checks.py#L297) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:403` | `check_merge_retry_and_commit_failure` | IT | [integrations/worktree_task.checks.py:346](integrations/worktree_task.checks.py#L346) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:454` | `check_human_approved_validation_failure` | IT | [integrations/worktree_task.checks.py:398](integrations/worktree_task.checks.py#L398) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `unknown/worktree_task.checks.py:493` | `check_real_loop_integration` | IT | [integrations/worktree_task.checks.py:432](integrations/worktree_task.checks.py#L432) | direct / 1 | CLI/subprocessまたはGitとの連携 | 配置/共有fixture分離 |
| `integrations/sync-model.checks.py:638` | `check_publication_lock_wait` | IT | [integrations/sync-model.checks.py:963](integrations/sync-model.checks.py#L963) | pytest / 1 | sync-performance: real publication lock contention and reentrancy | 検証本体・assertを保持 |
| `integrations/sync-model.checks.py:667` | `check_generation_output_compatibility` | IT | [integrations/sync-model.checks.py:992](integrations/sync-model.checks.py#L992) | pytest / 1 | sync-performance: generated bytes and stdout compatibility | 検証本体・assertを保持 |
| `integrations/sync-model.checks.py:685` | `check_two_consumer_cli` | IT | [integrations/sync-model.checks.py:1010](integrations/sync-model.checks.py#L1010) | pytest / 1 | sync-performance: two-consumer CLI write/check and invalid scope | 検証本体・assertを保持 |
| `integrations/sync-model.checks.py:731` | `check_input_mutation` | IT | [integrations/sync-model.checks.py:1058](integrations/sync-model.checks.py#L1058) | pytest / 12 | sync-performance: four source kinds x change/delete/add, output preservation | 検証本体・assertを保持 |

| `integrations/check-model-aws.checks.py:644` | `check_domains` | IT | [integrations/check-model-aws.checks.py:668](integrations/check-model-aws.checks.py#L668) | pytest / 9 | 既存callbackを実行するパラメータ化入口。callbackと重複加算しない | 現在の入口 |

### IT 内部パターン

| ファイル / ケース | ループ地点・パターン数・入力 |
|---|---|
| `integrations/attribute-reference-resolution.checks.py::check_pair` | 1（内部パラメータ化なし） |
| `integrations/attribute-reference-resolution.checks.py::check_fixed_label` | L?: 動的 (root.rglob('*'))<br>L?: 動的 (root.rglob('*'))<br>L?: 動的 (content.splitlines()) |
| `integrations/attribute-reference-resolution.checks.py::check_stack` | 1（内部パラメータ化なし） |
| `integrations/attribute-reference-resolution.checks.py::check_preparation_cache` | L249: 2 ([('first', '001'), ('second', '002')])<br>L?: 動的 (root.rglob('*'))<br>L?: 動的 (root.rglob('*'))<br>L?: 動的 (values.items()) |
| `integrations/attribute-reference-resolution.checks.py::check` | L292: 2 ([('s3', 'cloudtrail'), ('lambda', 'eventbridge')]) |
| `integrations/auxiliary-model-dependencies.checks.py::check` | 1（内部パラメータ化なし） |
| `integrations/aws_mapping.checks.py::check_config` | L38: 動的 (['framework/mappings/aws/config.yaml', 'framework/mappings/aws/owners.json', schema + 'index.json', *[schema + index['AWS::' + kind.replace('.', '::')] for kind in (RECORDER, CHANNEL)], *['framework/materials/aws/' + kind.replace('.', '_') + '.properties' for kind in (RECORDER, CHANNEL)]])<br>L39: 動的 ((RECORDER, CHANNEL))<br>L40: 動的 ((RECORDER, CHANNEL))<br>L52: 動的 ([('001', RECORDER, recorder), ('002', CHANNEL, channel)])<br>L54: 動的 ({'resourceType': kind, 'resourceMode': 'IMPORT', 'logicalId': kind.replace('.', '_') + '_001'}.items())<br>L56: 動的 (enumerate(BASELINE[kind].items(), 1))<br>L67: 動的 ({'property': kind + '.' + prop, 'value': raw, 'comment': 'fixture'}.items())<br>L90: 動的 (m.compare_resource(ctx, resource))<br>L90: 動的 (model.resources)<br>L91: 動的 (model.resources)<br>L92: 動的 (range(2))<br>L94: 動的 (calls)<br>L98: 動的 (match)<br>L99: 動的 (match)<br>L100: 動的 (difference)<br>L103: 動的 ([(RECORDER, 'recorder', recorder), (CHANNEL, 'channel', channel)])<br>L107: 動的 (normalized)<br>L110: 動的 (normalized)<br>L110: 動的 (record['properties'].values())<br>L113: 動的 (model.resources)<br>L126: 動的 ((RECORDER, CHANNEL)) |
| `integrations/aws_mapping_compare.checks.py::mapping_checks` | L24: 動的 (cases)<br>L56: 2 (({'projects': [{}]}, {'projects': [{'webhook': None}]})) |
| `integrations/aws_mapping_display.checks.py::check` | 1（内部パラメータ化なし） |
| `integrations/blueprint-loop.checks.py::check_running_and_interruption` | L24: 動的 (history)<br>L25: 動的 (history)<br>L30: 動的 (history)<br>L46: 動的 (events(logs))<br>L47: 動的 (ended) |
| `integrations/blueprint-loop.checks.py::check_deploy_scope_isolation` | L59: 動的 ([*(scripts / 'tests').rglob('*.checks.py'), *(scripts / 'tests/units').rglob('test_*.py')])<br>L65: 2 (('dev', 'stg'))<br>L70: 2 (('dev', 'stg'))<br>L74: 動的 ((models[env], designs[env], parameters[env]))<br>L86: 2 ((('dev', 'deploy'), ('stg', 'update')))<br>L91: 動的 (files)<br>L132: 2 ((False, True)) |
| `integrations/blueprint-loop.checks.py::check_task_service_validation` | L237: 動的 (pstats.Stats(str(profile)).stats)<br>L279: 動的 (sorted(__import__('model.sources', fromlist=['source_inputs']).source_inputs(model))) |
| `integrations/blueprint-loop.checks.py::check_parallel_and_selection` | L298: 2 ((('a', 'b', 1), ('b', 'a', 0))) |
| `integrations/blueprint-loop.checks.py::check_staged_snapshot` | L415: 3 ((1, 2, 3)) |
| `integrations/blueprint-loop.checks.py::check_regression_authorization` | L438: 5 ((('full', set(), []), ('task', {'README.md'}, []), ('local', set(), ['--all']), ('task', {'framework/scripts/shared.py'}, ['--affected']), ('task', {'framework/scripts/tests/units/a.checks.py'}, ['--affected']))) |
| `integrations/blueprint-loop.checks.py::check_failure_suspension` | 1（内部パラメータ化なし） |
| `integrations/blueprint-loop.checks.py::check_startup_diagnostics` | L541: 動的 ((selected, other))<br>L630: 動的 ((directory / 'startup.jsonl').read_text(encoding='utf-8').splitlines()) |
| `integrations/blueprint-loop.checks.py::check_windows_exit_propagation` | L641: 4 ((0, 2, 7, 130)) |
| `integrations/blueprint-loop.checks.py::check_workflow` | L653: 2 (('units/blueprint-loop-unit.checks.py', 'integrations/service-parameter-inputs.checks.py'))<br>L687: 動的 ((failed_directory / 'startup.jsonl').read_text(encoding='utf-8').splitlines())<br>L691: 動的 (startup)<br>L694: 動的 (history)<br>L695: 動的 (ended)<br>L696: 動的 (ended)<br>L699: 動的 (history)<br>L726: 動的 (command)<br>L738: 9 (('framework/scripts/a.py', 'framework/rules/rule.md', 'framework/materials/input.json', 'framework/schema/schema.json', 'framework/catalog/catalog.json', 'framework/prompts/prompt.md', '.agents/skills/example/SKILL.md', 'AGENTS.md', 'README.md')) |
| `integrations/bound-anchor-name-change.checks.py::check` | L109: 3 ((root / 'model/preview/team/vpc.properties', build_path, kms_path))<br>L?: 2 (('model', 'docs/designs'))<br>L?: 動的 ((root / base).rglob('*'))<br>L?: 動的 (before)<br>L?: 3 (('model', 'model/parameters', 'docs/designs'))<br>L?: 動的 ((root / base).rglob('*'))<br>L?: 動的 (saved.items())<br>L?: 動的 (saved.items())<br>L?: 4 (('definition', 'resources', 'rows', 'labels'))<br>L?: 動的 (entries(after, 'desired.resource.')) |
| `integrations/bound-stack-name-change.checks.py::check` | L50: 2 ([('017', 'network', 'Network'), ('083', 'empty', 'Empty')])<br>L86: 3 (('-changed', '', '-second'))<br>L120: 4 ([('999', 'cfn-stack-app-preview-unknown', 'exactly'), ('017', 'bad_name', 'invalid fixed stack'), ('083', fixed, 'conflicting'), ('017', None, 'invalid fixed stack')])<br>L?: 動的 (vpc.items())<br>L?: 動的 (load_model(vpc_path).files)<br>L?: 4 ((directory / 'parameters.yaml', directory / 'bindings.json', root / 'docs/designs/preview/team/cloudformation-stacks.md', root / 'docs/designs/preview/team/vpc.md'))<br>L?: 動的 (bindings['instances'].items())<br>L?: 動的 (baseline.items())<br>L?: 動的 (vpc_bytes.items())<br>L?: 動的 (item.items())<br>L?: 2 ([('other', '210987654321'), ('team', '123456789012')]) |
| `integrations/check-model-aws.checks.py::service_checks` | L16: 動的 (m.SERVICES)<br>L22: 動的 (sorted(mapping.adapter_resource_types))<br>L63: 4 (('match', 'difference', 'missing', 'failed'))<br>L35: 動的 (relevant.items())<br>L42: 2 ((identity.id_path, identity.arn_path))<br>L46: 3 (('id', 'arn', 'name'))<br>L?: 動的 (definitions.items())<br>L?: 動的 (relevant.items())<br>L?: 動的 (results) |
| `integrations/check-model-aws.checks.py::cli_checks` | L119: 4 ([(FileNotFoundError('secret'), 'FileNotFoundError'), (SimpleNamespace(returncode=255, stdout='', stderr='secret credential failure'), 'AwsCliError'), (SimpleNamespace(returncode=0, stdout='invalid secret', stderr=''), 'JSONDecodeError'), (SimpleNamespace(returncode=0, stdout='[]', stderr=''), 'ValueError')])<br>L129: 2 ([('NoSuchBucket', 'resource_missing'), ('AccessDenied', 'acquisition_failed')])<br>L134: 2 (range(2)) |
| `integrations/check-model-aws.checks.py::check_cli_service_names` | 1（内部パラメータ化なし） |
| `integrations/check-model-aws.checks.py::batch_checks` | L306: 3 (((None, 1, 'identifier'), ('missing', 1, 'resource_missing'), ('failed', 2, 'acquisition_failed')))<br>L287: 2 (([], ['--coverage']))<br>L292: 8 (([], ['--all', '--service', 's3'], ['--all', '--environment', 'dev'], ['--all', '--target', ACCOUNT], ['--environment', 'dev', '--target', ACCOUNT], ['--service', 's3'], ['--environment', 'dev', '--service', 's3'], ['--target', ACCOUNT, '--service', 's3']))<br>L251: 動的 (stubbers)<br>L?: 動的 (report['results'])<br>L225: 動的 (requests[service])<br>L?: 2 ({'sts', *services})<br>L?: 動的 (api_calls)<br>L?: 動的 (batch['results'])<br>L230: 動的 (PATCHES.get((service, operation), {}).items())<br>L?: 動的 (batch_items)<br>L?: 動的 (items)<br>L?: 動的 (api_calls)<br>L?: 動的 (report['mappings'])<br>L?: 動的 (run.call_args.args[1])<br>L?: 動的 (api_calls)<br>L?: 動的 (services)<br>L?: 2 (('--service', service)) |
| `integrations/check-model-aws.checks.py::common_checks` | L393: 2 ((False, True))<br>L427: 3 ((None, 'missing', 'failed'))<br>L?: 動的 (m.compare_resource(ctx, model.resources[0]))<br>L?: 動的 (m.compare_resource(ctx, model.resources[0]))<br>L?: 動的 (m.compare_resource(ctx, resource))<br>L?: 動的 (results) |
| `integrations/check-model-aws.checks.py::association_checks` | L449: 2 ((False, True))<br>L474: 2 ((False, True))<br>L?: 動的 (values)<br>L?: 動的 (values)<br>L?: 動的 (values)<br>L?: 動的 (values)<br>L?: 動的 (stage_results)<br>L?: 動的 (values)<br>L?: 動的 (stage_results)<br>L?: 動的 (values) |
| `integrations/check-model-aws.checks.py::stack_checks` | L547: 動的 (cases)<br>L?: 4 ([('CREATE_COMPLETE', 'match'), ('UPDATE_COMPLETE', 'match'), ('IMPORT_COMPLETE', 'match'), ('ROLLBACK_COMPLETE', 'difference')])<br>L?: 3 (({'Stacks': []}, {'Stacks': [{'StackName': 'other', 'StackStatus': 'CREATE_COMPLETE'}]}, {'Stacks': [{'StackName': 'fixture'}, {'StackName': 'fixture'}]}))<br>L?: 2 ([('Stack with id fixture does not exist', 'resource_missing'), ('Invalid StackName', 'acquisition_failed')])<br>L?: 動的 (results) |
| `integrations/check-model-aws.checks.py::cfn_identity_checks` | L567: 動的 (enumerate(('ism', 'ced', 'sd'), 1))<br>L576: 動的 (enumerate(resources)) |
| `integrations/check-model-aws.checks.py::identity_registry_checks` | 1（内部パラメータ化なし） |
| `integrations/check-model-aws.checks.py::fixture_coverage` | L617: 動的 (m.SERVICES)<br>L625: 動的 (enumerate(sorted(mapping.adapter_resource_types), 1))<br>L?: 動的 (report['comparisonResourceTypes'].items())<br>L?: 動的 (sorted(definitions.items())) |
| `integrations/check-model-aws.checks.py::check_consumer_coverage` | 1（内部パラメータ化なし） |
| `units/deploy-runtime-unit.checks.py::check_sdk_execution` | L19: 動的 (scoped)<br>L24: 動的 (backend.calls)<br>L29: 動的 (backend.calls)<br>L46: 動的 (enumerate(backend.calls))<br>L47: 動的 (enumerate(backend.calls))<br>L48: 2 (((['NetworkVpcId'], 'COMPLETE'), ([], 'STOPPED')))<br>L55: 動的 (backend.calls)<br>L64: 動的 (backend.calls)<br>L70: 動的 (state.values())<br>L71: 動的 (backend.calls)<br>L83: 動的 (backend.calls)<br>L89: 動的 (backend.calls)<br>L95: 2 (('True', 'Conditional')) |
| `units/deploy-runtime-unit.checks.py::check_empty_rollback_recreation` | L127: 動的 (self.current)<br>L159: 2 (('A', 'B'))<br>L160: 動的 (enumerate(backend.calls))<br>L161: 動的 (enumerate(backend.calls))<br>L168: 2 (('A', 'B'))<br>L174: 動的 (items)<br>L179: 動的 (saved.values())<br>L185: 2 (([], [{'ResourceStatus': 'DELETE_COMPLETE'}]))<br>L190: 5 (('CREATE_COMPLETE', 'DELETE_SKIPPED', 'CREATE_FAILED', 'DELETE_FAILED', None))<br>L195: 3 (({'EnableTerminationProtection': True}, {'ParentId': 'parent'}, {'StackId': 'other'}))<br>L210: 3 (('DELETE_IN_PROGRESS', 'DELETE_COMPLETE', None)) |
| `units/deploy-runtime-unit.checks.py::check_template_validation` | 1（内部パラメータ化なし） |
| `integrations/cloudformation-deploy.checks.py::check_inputs` | L257: 動的 (enumerate(units(20, 10, 10), 1))<br>L258: 動的 (unit.items())<br>L260: 6 ((('desired.deployment.maxConcurrentStacks', '0'), ('desired.deployment.maxConcurrentStacks', '-1'), ('desired.deployment.maxConcurrentStacks', 'abc'), ('desired.stack.001.deployOrder', '0'), ('desired.stack.001.deployOrder', '-1'), ('desired.stack.001.deployOrder', 'abc')))<br>L270: 4 (('dependsOn', 'AfterStack', 'DependsOnStack', 'Dependencies'))<br>L280: 動的 (values.items())<br>L282: 動的 (scoped)<br>L327: 2 ((None, 'configured')) |
| `units/deploy-runtime-unit.checks.py::check_delivery` | L368: 動的 (((51200, '--template-body'), (51201, '--template-url'), (1024 * 1024, '--template-url')))<br>L373: 動的 (backend.calls)<br>L374: 動的 (backend.calls)<br>L379: 動的 (backend.calls)<br>L381: 動的 (backend.calls)<br>L389: 動的 (backend.calls)<br>L400: 3 ((('First', 'app-dev-assets'), ('Second', 'app-dev-assets'), ('Third', 'app-dev-other')))<br>L411: 3 (('First', 'Second', 'Third'))<br>L414: 動的 (backend.calls)<br>L415: 動的 (backend.calls)<br>L418: 動的 (enumerate(backend.calls))<br>L422: 動的 (resumed.calls)<br>L439: 2 (({'bucket': 'wrong-bucket'}, {'keyPrefix': 'wrong/'}))<br>L443: 動的 (resumed.calls)<br>L450: 動的 (fresh.calls)<br>L483: 動的 (unit.items())<br>L487: 動的 (artifact('First').items())<br>L501: 動的 (values.items())<br>L503: 動的 (deployment_settings(values)[1])<br>L503: 動的 (files)<br>L510: 動的 (values.items())<br>L518: 4 ((('source', '../secret'), ('keyPrefix', '../'), ('stack', 'unknown'), ('property', 'Other')))<br>L520: 動的 (values.items())<br>L529: 動的 (values.items())<br>L536: 動的 (stack_delivery(design).items())<br>L537: 動的 (values.items())<br>L542: 動的 (stack_delivery(design).items())<br>L547: 動的 (values.items())<br>L562: 動的 (entries(approved, 'desired.resource.'))<br>L566: 動的 (entries(approved, 'desired.row.'))<br>L584: 動的 (backend.calls)<br>L591: 動的 (zip(scoped, (20, 51201)))<br>L597: 動的 (scoped)<br>L613: 動的 (bootstrap.calls)<br>L615: 動的 (bootstrap.calls) |
| `units/deploy-runtime-unit.checks.py::check_delivery_encryption` | L641: 動的 (backend.calls)<br>L645: 動的 (backend.calls)<br>L646: 動的 (backend.session['placementPreflight'].values())<br>L655: 動的 (backend.calls)<br>L668: 2 (('[KMS_Key_001](kms.md#kms-app-dev-key)', '[KMS_Alias_001](kms.md#resource-KMS_Alias_001)'))<br>L688: 2 ((('AES256', None), ('aws:kms', 'test-key')))<br>L693: 動的 (backend.calls)<br>L701: 動的 (backend.calls)<br>L711: 動的 (({'Principal': {'AWS': TARGET['awsAccountId']}}, {'NotResource': '*'}))<br>L742: 動的 (((lambda b: setattr(b, 'default_algorithm', 'aws:kms'), 'MISMATCH'), (lambda b: setattr(b, 'region', 'us-east-1'), 'MISMATCH')))<br>L747: 動的 (backend.calls)<br>L748: 5 (('head-bucket', 'get-bucket-location', 'get-bucket-encryption', 'get-bucket-policy', 'describe-key'))<br>L759: 動的 (backend.calls)<br>L784: 動的 (resumed.calls)<br>L800: 動的 (scoped)<br>L812: 動的 (enumerate(backend.calls))<br>L814: 動的 (enumerate(backend.calls))<br>L830: 動的 (backend.calls)<br>L836: 動的 (backend.calls) |
| `units/deploy-runtime-unit.checks.py::check_session_cli` | L856: 動的 (enumerate(units(10, 20), 1))<br>L857: 動的 (unit.items())<br>L861: 動的 (values.items())<br>L870: 2 (('a', 'b'))<br>L931: 動的 (run.call_args_list)<br>L938: 動的 ((base / 'timing.jsonl').read_text().splitlines())<br>L939: 動的 (timing)<br>L948: 動的 (stopped['states'].values())<br>L949: 動的 (errors.items())<br>L957: 動的 (session['states'].values())<br>L963: 動的 (backends[-1].calls)<br>L978: 動的 (backends[-1].deployment_input_paths(units(10, 20)))<br>L989: 動的 (((params / 'a.json', '[{"ParameterKey":"Name","ParameterValue":"changed"}]'), (template, 'Resources: {}\\n# shared dev/stg template changed\\n'), (source, read_model(source) + 'display.deployment.comment=changed\\n'), (consumer, read_model(consumer) + 'desired.row.002.value=changed\\n'), (reference, 'desired.row.001.value=changed\\n'), (contract, contract.read_text() + '\\n# contract changed\\n'), (root / 'framework/scripts/check-deploy-context.py', '# controller dependency changed\\n')))<br>L1007: 4 ((('awsAccountId', '999999999999'), ('awsRegion', 'us-east-1'), ('awsProfile', 'other-profile'), ('iacEngine', 'terraform')))<br>L1026: 動的 (artifact.items())<br>L1027: 動的 (with_artifact.items())<br>L1037: 動的 (saved_source.items())<br>L1052: 動的 ((((10,), 1), ((10,) * 4, 4), ((10,) * 4 + (20,) * 4, 4)))<br>L1055: 動的 (enumerate(selected, 1))<br>L1056: 動的 (unit.items())<br>L1059: 動的 (values.items())<br>L1061: 動的 (contract.read_text().splitlines())<br>L1062: 動的 (selected)<br>L1065: 動的 (selected)<br>L1072: 動的 (session['states'].values())<br>L1073: 動的 (backends[-1].calls)<br>L1079: 5 (('version', 'validationStatus', 'validationDigest', 'validationTemplates', 'validationTemplatesDigest'))<br>L1121: 動的 (selected[:4]) |
| `units/deploy-runtime-unit.checks.py::check_parallel_and_restart` | L1139: 動的 (scoped[2:])<br>L1151: 動的 (selected)<br>L1152: 動的 (selected)<br>L1159: 動的 (scoped)<br>L1160: 動的 (enumerate(backend.events))<br>L1161: 動的 (backend.events[:first_poll])<br>L1166: 動的 (selected)<br>L1171: 動的 (backend.calls)<br>L1186: 動的 (backend.calls) |
| `integrations/cloudformation-deploy.checks.py::check_observed_collector` | L1298: 動的 (values.items())<br>L1345: 動的 (observed.items())<br>L1345: 動的 (values.items())<br>L1360: 動的 (range(1, 621))<br>L1367: 動的 ([template, *parts])<br>L1372: 動的 (before_parts.items())<br>L1377: 動的 (part_document.values.items())<br>L1379: 動的 (changes) |
| `integrations/cloudformation-deploy.checks.py::check_shared_stack_mapping` | L1410: 動的 (enumerate(('ism', 'ced', 'sd'), 1))<br>L1417: 動的 (unit.items())<br>L1423: 動的 (enumerate((('Name', '`' + name + '`'), ('VpcId', f"[{identity}](#{values[f'desired.resource.{identity}.anchor']})"), ('CidrBlock', f'`10.{index}.0.0/16`')), 1))<br>L1446: 動的 (scoped)<br>L1449: 動的 (enumerate(scoped, 1))<br>L1457: 動的 (scoped)<br>L1481: 動的 (scoped)<br>L1482: 動的 (((mappings, (root, 'dev', '123456789012', backend.templates, scoped), 6, 5), (preflight, (root, 'dev', '123456789012', [u['name'] for u in scoped]), 7, 5)))<br>L1484: 動的 (scoped)<br>L1531: 動的 ((scoped[0]['name'], 'missing'))<br>L1533: 動的 (((preflight.__wrapped__, mappings.__wrapped__), (preflight, mappings)))<br>L1557: 動的 (enumerate(scoped, 1))<br>L1559: 動的 (actual.items())<br>L1573: 動的 (scoped)<br>L1585: 3 (({'Ref': 'Unknown'}, {'Condition': 'Active'}, 'yes'))<br>L1588: 動的 (scoped)<br>L1598: 動的 (enumerate(('AllocationId', 'PublicIp'), 1)) |
| `integrations/cloudformation-deploy.checks.py::check_import_implementation_mapping` | L1656: 動的 (unit.items())<br>L1659: 2 ((('001', 'EC2.VPC'), ('002', 'EC2.Subnet')))<br>L1660: 動的 ((('resourceType', kind), ('resourceMode', 'IMPORT'), ('logicalId', kind.replace('.', '_') + '_001')))<br>L1689: 4 ((('Vpc', {'Type': 'AWS::EC2::VPC', 'Condition': 'Unknown'}, 'Condition'), ('Association', {'Type': 'AWS::EC2::SubnetRouteTableAssociation', 'Properties': {'SubnetId': {'Ref': 'Vpc'}}}, 'formal CFn type mismatch'), ('Unknown', {'Type': 'AWS::S3::Bucket'}, 'explicit mapping required'), ('Repository', {'Type': 'AWS::S3::Bucket'}, 'formal CFn type mismatch'))) |
| `integrations/cloudformation-deploy.checks.py::check_integrated_child_mapping` | L1720: 2 ((('S3.BucketPolicy', 'S3.Bucket', 'Bucket', 'PolicyDocument', 11), ('EC2.SubnetRouteTableAssociation', 'EC2.Subnet', 'SubnetId', 'RouteTableId', 5)))<br>L1725: 動的 (range(1, count + 1))<br>L1745: 動的 (values.items())<br>L1750: 動的 (unit.items())<br>L1757: 動的 (child_ids)<br>L1788: 動的 (model.rglob('*.properties'))<br>L1790: 動的 ([*child_ids, 'Repository'])<br>L1794: 動的 (children)<br>L1799: 動的 (children)<br>L1801: 動的 (before) |
| `integrations/cloudformation-deploy.checks.py::check_secretsmanager_arn_identifiers` | L1819: 2 ((('001', 'Secret1'), ('002', 'Secret1Rotation')))<br>L1821: 動的 ({'property': 'SecretsManager.Secret.KmsKeyId', 'value': '[KMS_Key_001](kms.md#kms-app-dev-key)', 'comment': 'secretの暗号化鍵'}.items())<br>L1829: 動的 (enumerate(selected, 1))<br>L1830: 動的 (unit.items())<br>L1831: 動的 (((model / 'secretsmanager.properties', secrets), (model / 'kms.properties', key), (model / 'cloudformation-stacks.properties', stacks)))<br>L1850: 動的 (document['Resources'].items())<br>L1857: 2 ((False, True))<br>L1861: 2 (('SecretArn', 'RotationArn'))<br>L1865: 動的 (saved.values())<br>L1869: 動的 (current.values())<br>L1872: 動的 ((model, root / 'docs/designs'))<br>L1872: 動的 (parent.rglob('*'))<br>L1874: 動的 (model.rglob('*.properties'))<br>L1885: 動的 (before)<br>L1891: 7 (('root', 'environment', 'directory', 'target', 'templates', 'mapping_plan', 'aws')) |
| `units/deploy-runtime-unit.checks.py::check_api_timing` | L1911: 動的 (path.read_text().splitlines())<br>L1912: 動的 (events)<br>L1913: 動的 (events) |
| `units/deploy-runtime-unit.checks.py::check_controlled_repair` | Original failure safety/provenance, retained/custom Resource and empty-shell rules; authoritative source bytes unchanged; legacy candidates never applied |
| `units/deploy-runtime-unit.checks.py::check_secret_runtime_bootstrap` | L2329: 4 ([('SecretOwner', 1), ('A', 2), ('B', 2), ('C', 3)])<br>L2338: 動的 (enumerate(selected, 1))<br>L2338: 動的 (unit.items())<br>L2339: 2 ([('secretsmanager', 'SecretsManager.Secret', 'SecretOwner', 'Secret'), ('quicksight', 'QuickSight.DataSource', 'B', 'Consumer')])<br>L2345: 動的 (selected)<br>L2363: 動的 (enumerate(active, 1))<br>L2363: 動的 (u.items())<br>L2371: 動的 (docs.items())<br>L2372: 動的 (active)<br>L2377: 動的 (active)<br>L2381: 動的 (active)<br>L2399: 動的 ((root / 'infra', modeldir))<br>L2399: 動的 (parent.rglob('*'))<br>L2401: 動的 (before.items())<br>L2410: 動的 (versions.items())<br>L2416: 動的 (versions.items())<br>L2421: 動的 (versions.items())<br>L2447: 動的 (versions.values())<br>L2499: 動的 (items)<br>L2518: 動的 (f.calls)<br>L2528: 動的 (f.before.items())<br>L2534: 動的 (f.calls)<br>L2536: 12 (('current', 'denied', 'kms', 'absent', 'import', 'crossAccount', 'crossRegion', 'unknownOwner', 'unknownVersions', 'invalidResponse', 'rotation', 'listDenied'))<br>L2552: 動的 (f.calls)<br>L2554: 7 (('opaque', 'mixed', 'pinned', 'multiple', 'unresolved', 'badExport', 'inactive'))<br>L2572: 2 ((True, False))<br>L2576: 2 ((('Username', 'username'), ('Password', 'password')))<br>L2590: 動的 (pair.values())<br>L2606: 6 (('BOOTSTRAP_INTENT', 'VALUE_CHECKED_MISSING', 'PUT_SUBMITTED', 'afterPut', 'BOOTSTRAP_CONFIRMED', 'RETRY_READY'))<br>L2639: 動的 (f.calls)<br>L2641: 動的 (f.calls)<br>L2644: 動的 (f.calls)<br>L2645: 2 (('race', 'promotionRace'))<br>L2653: 動的 (f.versions.values())<br>L2664: 4 (('denied', 'missing', 'timeout', 'invalid')) |
| `integrations/cloudformation-destroy.checks.py::check_order_and_safety` | L158: 2 (({'A': 20, 'B': 10}, {'A': 20, 'B': 20}))<br>L170: 2 (('list-exports', 'list-imports'))<br>L202: 動的 (({'StackId': stack_id('Other')}, {'StackName': 'Other'}, {'StackId': stack_id('A').replace('123456789012', '999999999999')}, {'StackId': stack_id('A').replace('ap-northeast-1', 'us-east-1')}))<br>L?: 2 (('C', 'D'))<br>L?: 動的 (fake.calls)<br>L?: 動的 (fake.calls) |
| `integrations/cloudformation-destroy.checks.py::check_unused_export` | L222: 動的 ((diagnostic.replace('ValidationError', 'AccessDenied'), diagnostic.replace('is not imported by any stack', 'does not exist'), 'An error occurred (ValidationError) when calling the ListImports operation: Invalid export name')) |
| `integrations/cloudformation-destroy.checks.py::check_absence` | L246: 動的 (({}, {'StackId': stack_id('A'), 'status': 'DELETE_INTENT'})) |
| `integrations/cloudformation-destroy.checks.py::check_controller` | L408: 2 (('task', 'issue'))<br>L?: 動的 (fake.calls)<br>L?: 動的 (fake.calls)<br>L?: 4 (('validate-template', 'create-change-set', 'execute-change-set', 'get-template'))<br>L?: 動的 (fake.calls) |
| `integrations/cloudformation-destroy.checks.py::check_observed` | L435: 動的 (list(values.items()))<br>L475: 2 (('A', 'B'))<br>L?: 動的 (plan['observed']['owners'].values())<br>L?: 動的 (owners)<br>L?: 動的 (plan['observed']['updates'].values())<br>L?: 動的 (changes.values())<br>L?: 動的 (updates)<br>L?: 動的 (before.items())<br>L?: 動的 (after.items())<br>L?: 動的 (pending['observed']['unmappedResources'])<br>L?: 2 (('A', 'B'))<br>L?: 動的 (values.items()) |
| `integrations/cloudformation-naming.checks.py::check_imports` | L81: 動的 (collection.items())<br>L69: 動的 (producer['Outputs'].items())<br>L82: 動的 (walk(consumer))<br>L?: 動的 (collection.items())<br>L?: 動的 (producer['Outputs'].items())<br>L90: 4 (('omitted', 'empty', 'configured', 'alternate'))<br>L?: 動的 (exports) |
| `integrations/cloudformation-naming.checks.py::check_names` | L107: 動的 (collection.items())<br>L108: 動的 (doc.get('Resources', {}).values())<br>L?: 動的 (entries(iam, 'desired.row.'))<br>L118: 3 (('omitted', 'empty', 'alternate'))<br>L110: 動的 (walk(resource)) |
| `integrations/cloudformation-naming.checks.py::check_flow_logs` | L129: 2 (('', '/example'))<br>L?: 動的 (collection.items()) |
| `integrations/cloudformation-naming.checks.py::check` | 1（内部パラメータ化なし） |
| `integrations/cloudformation-naming.checks.py::check_fixtures` | L185: 動的 (paths)<br>L?: 動的 (model_paths(ROOT)) |
| `integrations/cloudtrail-input-reference.checks.py::check` | L68: 2 ([original + '# annotation\n', original.replace('audit-preview', 'audit-next')])<br>L72: 5 ([(original.replace('resourceType=CloudTrail.Trail', 'resourceType=S3.Bucket'), 'type-mismatched'), (original.replace('017', '018'), 'type-mismatched'), (original.replace('CloudTrail.Trail.TrailName', 'CloudTrail.Trail.Description'), 'exactly one name'), (original.replace('`audit-preview`', '``'), 'exactly one name'), (original + 'desired.row.017-004.property=CloudTrail.Trail.TrailName\ndesired.row.017-004.value=`duplicate`\n', 'exactly one name')])<br>L?: 動的 (values.items()) |
| `integrations/deploy_preparation.checks.py::check_preparation` | L21: 動的 (root.rglob('*'))<br>L28: 動的 (root.rglob('*'))<br>L36: 動的 (model_parts(root / 'model/dev/123456789012/ec2.properties'))<br>L39: 動的 (declared)<br>L40: 動的 (declared)<br>L46: 動的 (plan['documents'])<br>L47: 動的 (document['chunks'])<br>L48: 動的 (plan['documents'])<br>L50: 4 (('ec2.md', 'iam.md', 'cloudformation-stacks.md', 'iam/worker-role-trust-policy.json'))<br>L54: 動的 (plan['inputs'].items())<br>L56: 動的 ((run / 'documents').iterdir())<br>L56: 動的 (d['chunks'])<br>L56: 動的 (plan['documents'])<br>L59: 動的 (source_inputs(entrance))<br>L61: 動的 (iam['chunks'])<br>L62: 2 ((1, 2))<br>L64: 動的 (STACKS)<br>L66: 動的 (model_rules['chunks'])<br>L83: 動的 ((run / 'timing.jsonl').read_text().splitlines())<br>L84: 動的 (events)<br>L85: 動的 (events)<br>L86: 動的 (events) |
| `integrations/deploy_preparation.checks.py::check_stale_and_conflicts` | L95: 8 (('issue', 'runtime', 'candidate', 'model', 'markdown-change', 'markdown-delete', 'json-change', 'json-delete')) |
| `integrations/deploy_preparation.checks.py::check_generated_boundaries` | L135: 動的 (original.splitlines())<br>L139: 4 (('authoritative JSON document missing', 'resource 001', 'row 001-002', 'iam/worker-role-trust-policy.json'))<br>L172: 動的 (plan['documents'])<br>L177: 動的 (plan['inputs'].items()) |
| `integrations/deploy_preparation.checks.py::check_service_generated_equality` | L223: 2 (('iam.md', 'iam/iam-role-001-trust-policy.json')) |
| `integrations/design_document.checks.py::check_snapshot` | L55: 2 (('CREATE', 'IMPORT'))<br>L?: 動的 (reads.call_args_list) |
| `integrations/design_document.checks.py::check_links` | L90: 動的 (cases)<br>L107: 3 ([(alias_text, []), (alias_text.replace(observed, 'different'), ['different']), (alias_text.replace(f'[{observed}](kms.md#kms-aliastwo)', f'[{observed}](kms.md#kms-aliasthree)'), [observed])])<br>L?: 80 (range(80))<br>L?: 動的 (zip(expected, validator.errors))<br>L?: 動的 (reads.call_args_list) |
| `integrations/design_layout.checks.py::check_secret_rotation_display` | L118: 動的 (values.items())<br>L132: 動的 (((text.replace('### SecretsManager.Secret: app-dev-key', '### SecretsManager.RotationSchedule: app-dev-key'), 'independent heading'), (text.replace('### SecretsManager.Secret: app-dev-key', '### S3.Bucket: app-dev-key'), 'wrong parent'), (text.replace('[app-dev-key](#secretsmanager-app-dev-key)', '[app-dev-token](#secretsmanager-app-dev-token)'), 'must reference enclosing'), (text.replace('RotationRules.AutomaticallyAfterDays', 'RotateImmediatelyOnUpdate'), 'duplicate property'), (text.replace('`30`', '`invalid`'), 'provider schema violation'), (text.replace('### SecretsManager.Secret\\n', '### SecretsManager.RotationSchedule\\n'), 'resource overview types')))<br>L141: 動的 (failures) |
| `integrations/design_layout.checks.py::check_codebuild_variable_display` | L181: 動的 (errors(short.replace('\| 2 \| Id \|', '\| 2 \| CodeBuild.Project.Id \|')))<br>L186: 動的 ((codebuild.replace('`hello:world`', '`PLAINTEXT:cde`'), codebuild.replace('<!-- codebuild-variable-type: SECRETS_MANAGER --> ', ''), codebuild.replace('SECRETS_MANAGER -->', 'UNKNOWN -->'), codebuild.replace('SECRETS_MANAGER -->', 'PARAMETER_STORE -->'), codebuild.replace(secret_link, '`venus-dev-snowflake-cicd-keypair-cde`'), codebuild.replace(secret_link, f'`{secret_link}`'), codebuild.replace(secret_link, '[secret](secretsmanager.md)'), codebuild.replace('#secretsmanager-snowflakekey', '#missing'), codebuild.replace('(secretsmanager.md#', '(missing.md#'), codebuild.replace('[venus-dev-snowflake-cicd-keypair-cde]', '[wrong-name]'))) |
| `integrations/design_layout.checks.py::check_codebuild_vpc_display` | L287: 動的 ((design_text.replace('Subnets[1]', 'Subnets[0]'), design_text.replace('Subnets[2]', 'Subnets[3]'), design_text.replace('Subnets[2]', 'Subnets[1]'), design_text.replace('SecurityGroupIds[1]', 'SecurityGroupIds[2]'), design_text.replace('VpcConfig.Subnets[1]', 'VpcConfig.Subnets'), design_text.replace('[subnet-00000000000000001](vpc.md#vpc-sbnt-one)', '`[subnet-00000000000000001](vpc.md#vpc-sbnt-one)`'), design_text.replace('[subnet-00000000000000001](vpc.md#vpc-sbnt-one)', '`["[subnet-00000000000000001](vpc.md#vpc-sbnt-one)"]`'), design_text.replace('[subnet-00000000000000001](vpc.md#vpc-sbnt-one)', '[PENDING_DEPLOY](security-group.md#security-group-codebuild-sg)'))) |
| `integrations/design_layout.checks.py::check_subnet_list_links` | 1（内部パラメータ化なし） |
| `integrations/design_layout.checks.py::check_guardduty_feature_display` | 1（内部パラメータ化なし） |
| `integrations/design_layout.checks.py::check_cloudtrail_data_resources` | L456: 5 (('All current and future S3 buckets', '`All current and future S3 bucket`', '`arn:aws:s3`', '`["arn:aws:s3"]`', '`[data-bucket](s3.md#s3-data-bucket)`'))<br>L468: 動的 ((trail.replace('DataResources[1]', 'DataResources[0]'), trail.replace('DataResources[2]', 'DataResources[3]'), trail.replace('DataResources[2]', 'DataResources[1]'), trail.replace('DataResources[1].S3', 'DataResources[1].Object'), trail.replace('[data-bucket](s3.md#s3-data-bucket) \| S3 object', '`data-bucket` \| S3 object'), trail.replace('DataResources[1].S3', 'EventSelectors[].DataResources[].Type'), trail.replace('[data-bucket](s3.md#s3-data-bucket) \| S3 object', '[function-one](lambda.md#lambda-function-one) \| S3 object'))) |
| `integrations/design_layout.checks.py::check_codepipeline_display` | L487: 動的 (enumerate(rows, 1))<br>L542: 動的 ((pipeline.replace('Stages[1]', 'Stages[]'), pipeline.replace('Stages[1]', 'Stages[0]'), pipeline.replace('Stages[2]', 'Stages[3]'), pipeline.replace('Stages[2]', 'Stages[1]'), pipeline.replace('Stages[1].Actions.', 'Stages[1].Actions[1].'), pipeline.replace('Stages[1].Actions.', 'Stages[1].Actions[].'), pipeline.replace('Actions[2]', 'Actions[3]'), pipeline.replace('Actions[2]', 'Actions[1]'), pipeline.replace('Actions[1]', 'Actions'), pipeline.replace('Configuration.BranchName', 'Configuration'), pipeline.replace('Configuration.PollForSourceChanges', 'Configuration.BranchName'), pipeline.replace('`dev`', '`{"Fn::ImportValue":"branch-export"}`'), pipeline.replace('`dev`', '`!ImportValue branch-export`'), pipeline.replace('[build](codebuild.md#codebuild-build)', '`{"Fn::ImportValue":"CdeDevApplicationBuildProjectName"}`'), pipeline.replace('[build](codebuild.md#codebuild-build)', '`build`'), pipeline.replace('[build](codebuild.md#codebuild-build)', '[repo](codecommit.md#codecommit-repo)'), pipeline.replace('[build](codebuild.md#codebuild-build)', '[wrong](codebuild.md#codebuild-build)'), pipeline.replace('[build](codebuild.md#codebuild-build)', '[build](codebuild.md#codebuild-missing)'), pipeline.replace('[build](codebuild.md#codebuild-build)', '`[build](codebuild.md#codebuild-build)`'), pipeline.replace('[repo](codecommit.md#codecommit-repo)', '[wrong](codecommit.md#codecommit-repo)')))<br>L565: 2 ((('Stages[1].Name', '`DuplicateStage`'), ('Stages[2].Actions[2].Name', '`DuplicateAction`'))) |
| `integrations/design_layout.checks.py::check_config_firehose_references` | L594: 動的 (enumerate(rows, 1))<br>L641: 動的 ((config.replace('RoleName \|', 'RoleARN \|'), config.replace(role_link, '`config-role`'), config.replace(role_link, '[wrong](iam.md#iam-resource)'), config.replace(role_link, '[alias/two](kms.md#resource-AliasTwo)'), config.replace(role_link, '[config-role](iam.md#iam-missing)')))<br>L649: 動的 (('[1234abcd-12ab-34cd-56ef-1234567890ab](kms.md#kms-keyone)', '[app-data](s3.md#s3-app-data)', role_link))<br>L653: 動的 (('`!ImportValue resource-export`', '`arn:aws:s3:::app-data`', '[wrong](s3.md#s3-app-data)', '[alias/two](kms.md#resource-AliasTwo)', '`' + link + '`'))<br>L664: 3 (('AWSServiceRoleForConfig', '`AWSServiceRoleForConfig`', '`AWSServiceCustom`'))<br>L671: 動的 (('`config-role`', '`AWSService`', '`AWSServiceRoleForConfig/path`', '`arn:aws:iam::123456789012:role/aws-service-role/config.amazonaws.com/AWSServiceRoleForConfig`', '`AWSServiceRoleForConfig', 'awsServiceRoleForConfig', 'AWSService' + 'x' * 55))<br>L679: 2 ((('KeyARN', '[1234abcd-12ab-34cd-56ef-1234567890ab](kms.md#kms-keyone)'), ('BucketARN', '[app-data](s3.md#s3-app-data)')))<br>L722: 動的 (values.items()) |
| `integrations/design_layout.checks.py::check_resource_name_headings` | L781: 動的 (((text.replace(f'### Scheduler.Schedule: {name}', f'### Scheduler.Schedule: {logical_id}'), 'heading must display resource name'), (text.replace(f'[{name}]', f'[{logical_id}]'), 'must not display internal logical ID'), (text.replace(f'\| `{name}` \|', '\| `PENDING_DEPLOY` \|'), 'display name must be confirmed'), (text.replace(anchor, 'scheduler-internal-id'), 'anchor must match saved Model anchor'), (text.replace(marker, '<!-- resource-logical-id: -->'), 'invalid resource identity'), (text + '\\n' + marker, 'invalid resource identity')))<br>L790: 動的 (failures)<br>L796: 3 (('one', 'two', 'three')) |
| `integrations/design_layout.checks.py::check_quicksight_group_principal_reference` | 1（内部パラメータ化なし） |
| `integrations/design_layout.checks.py::check_workflow` | L868: 動的 (LAYOUTS)<br>L933: 2 ((('BucketEncryption.BucketKeyEnabled', 'BucketEncryption.ServerSideEncryptionConfiguration[].BucketKeyEnabled'), ('LifecycleConfiguration.Rules[].NoncurrentVersionExpirationDays', 'LifecycleConfiguration.Rules[].NoncurrentVersionExpiration.NoncurrentDays')))<br>L937: 動的 (errors(KMS, s3_with_shortened_properties.replace(display, formal)))<br>L954: 動的 (bad_designs)<br>L956: 動的 (failures)<br>L957: 3 (('[alias/one](kms.md#resource-AliasTwo)', '[alias/two](kms.md#kms-keyone)', '[alias/two](kms.md#kms-missing)'))<br>L960: 動的 (errors(KMS, S3.replace('BucketEncryption[].KMSMasterKeyID', formal_kms)))<br>L963: 動的 (KMS.splitlines()) |
| `integrations/framework-input-isolation.checks.py::check` | L17: 5 (('stat', 'open', 'glob', 'rglob', 'iterdir')) |
| `integrations/human-inputs-group-05.checks.py::check_declared_inputs` | L?: 動的 (specs.items())<br>L?: 動的 (inputs.items())<br>L?: 動的 (text)<br>L?: 動的 (inputs) |
| `integrations/issues_api_only.checks.py::main_checks` | L21: 動的 (catalog.api_schemas)<br>L49: 3 (({'resourceType': 'Macie.Unknown'}, {}, {'resourceType': []}))<br>L37: 2 ((records, [api]))<br>L?: 動的 (baseline)<br>L?: 動的 (baseline)<br>L?: 動的 (baseline)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records) |
| `integrations/issues_failed_services.checks.py::main_checks` | L34: 動的 (enumerate(rows, 1))<br>L66: 動的 (models.items())<br>L78: 動的 (KMS_COMPARISON_FORMS.items())<br>L112: 3 ([('Log', 'arn:aws:logs:ap-northeast-1:123456789012:log-group:/fixture/log:*'), ('Build', 'arn:aws:codebuild:ap-northeast-1:123456789012:project/fixture-build'), ('Rule', 'arn:aws:events:ap-northeast-1:123456789012:rule/fixture-rule')])<br>L145: 2 ([('Missing', 'Arn'), ('Queue', 'MissingAttribute')])<br>L81: 4 ([('KeyId', key_id), ('KeyArn', key_arn), ('AliasName', 'alias/fixture'), ('AliasArn', alias_arn)])<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (selected)<br>L?: 動的 (records)<br>L?: 動的 (values.items()) |
| `integrations/issues_policy_equivalence.checks.py::main_checks` | L48: 動的 (actual['Statement'])<br>L68: 2 ((same, selected_same))<br>L79: 3 ([('IAM.Role', 'AssumeRolePolicyDocument.Statement[].Action'), ('IAM.ManagedPolicy', 'PolicyDocument.Statement[].Action'), ('IAM.User', action_path)])<br>L89: 2 (((reference, arn), (sub, arn + '/results/*')))<br>L99: 4 ((Expression('Sub', ['${Missing}', {}]), Expression('Sub', ['${Value}', {'Value': {'$resource': ['s3', '002'], '$attribute': 'Arn'}}]), Expression('Sub', ['${Value}', {'Value': Expression('Join', ['', [reference, '/*']])}]), Expression('Join', ['', [reference, '/*']])))<br>L109: 2 ([('Action', ['s3:PutObject']), ('Effect', 'Deny')])<br>L129: 4 ((None, 'invalid/path', 'wildcard-*', {'Ref': 'Bucket'}))<br>L71: 5 (([], ['s3:PutObject'], ['s3:GetObject', 's3:GetObject'], [True], [['s3:GetObject']]))<br>L74: 4 (('Tags[].Value', 'Policies[].Action', 'Policies[].PolicyDocument.Statement[].Condition.Action', 'Policies[].PolicyDocument.Statement[].Resource'))<br>L92: 3 ((text + '-other', text.replace('aws:', 'aws-cn:'), text.replace('data2', 'data1')))<br>L?: 動的 (records)<br>L?: 動的 (comparison.display_differences[identifier(result)])<br>L?: 動的 (values.items()) |
| `integrations/issues_ref_returns.checks.py::main_checks` | L29: 動的 (specs)<br>L31: 動的 (enumerate((consumer, producer), 1))<br>L46: 動的 (specs)<br>L?: 動的 (model.items()) |
| `integrations/issues_scan.checks.py::naming_target_scope_cases` | L32: 動的 (specifications.items())<br>L47: 3 (('CodeBuild.Project', 'CodePipeline.Pipeline', 'Glue.Job'))<br>L37: 動的 (enumerate(rows, 1))<br>L?: 動的 (material['names'])<br>L?: 動的 (selected)<br>L?: 動的 (specifications.values())<br>L?: 動的 (specifications.items())<br>L?: 動的 (rows)<br>L?: 動的 (specifications.values())<br>L?: 動的 (rows)<br>L?: 動的 (specifications.values())<br>L?: 動的 (rows)<br>L?: 動的 (specifications.values())<br>L?: 動的 (rows)<br>L?: 動的 (specifications.values())<br>L?: 動的 (rows)<br>L?: 動的 (material['names'])<br>L?: 動的 (values.items()) |
| `integrations/issues_scan.checks.py::checks` | L107: 動的 (loaded.locations.items())<br>L115: 動的 (indexed)<br>L162: 動的 (originals.items())<br>L?: 動的 (records)<br>L?: 動的 (comparison.run())<br>L?: 動的 (loaded.files)<br>L?: 動的 (transform)<br>L?: 動的 (unequal)<br>L?: 動的 (crlf.files.items())<br>L?: 動的 (names)<br>L?: 動的 (names)<br>L?: 動的 (artifact['judgments'])<br>L?: 動的 (missing)<br>L?: 動的 (oldrows)<br>L?: 動的 (records)<br>L?: 動的 (differences)<br>L?: 動的 (differences)<br>L?: 動的 (partial)<br>L?: 動的 (partial)<br>L?: 動的 (unequal)<br>L?: 動的 (names)<br>L?: 動的 (paths)<br>L?: 動的 (errors)<br>L?: 動的 (missing)<br>L?: 動的 (artifact['judgments'])<br>L?: 動的 (issue_errors(root, {('dev', '123456789012', 's3')}))<br>L?: 動的 (records)<br>L?: 2 (('completed', 'suspend')); Issues既存出力と未作成IaC出力の不変、契約なし拒否 |
| `integrations/issues_scan.checks.py::resource_cases` | L292: 動的 (source.with_suffix('').glob('*.properties'))<br>L294: 動的 (original_files.items())<br>L250: 動的 (source.with_suffix('').glob('*.properties'))<br>L252: 動的 (model_file_contents(source, '\n'.join((f'{key}={value}' for key, value in model.items())) + '\n').items())<br>L?: 動的 (load_model(source).files.items())<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (comparison.rows['s3']['001'])<br>L?: 動的 (records)<br>L?: 動的 (model.items()) |
| `integrations/issues_scan.checks.py::extended_cases` | L340: 動的 (source.with_suffix('').glob('*.properties'))<br>L342: 動的 (originals.items())<br>L310: 動的 (source.with_suffix('').glob('*.properties'))<br>L312: 動的 (model_file_contents(source, '\n'.join((f'{key}={value}' for key, value in values.items())) + '\n').items())<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (material['names'])<br>L?: 動的 (records)<br>L?: 動的 (material['names'])<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (material['names'])<br>L?: 動的 (rows.items())<br>L?: 動的 (vpc.items())<br>L?: 動的 (material['names'])<br>L?: 動的 (kms.items())<br>L?: 動的 (values.items()) |
| `integrations/issues_scan.checks.py::check_nested_membership` | L?: 動的 (comparison.results)<br>L?: 動的 (enumerate(rows, 1))<br>L?: 動的 (comparison.results) |
| `integrations/issues_scan.checks.py::check_cloudtrail_membership` | L1321: 2 ([('001', 'Function'), ('002', 'Other')])<br>L1347: 動的 (enumerate(fields, 1))<br>L1382: 動的 ((lambda rows: rows, lambda rows: rows[::-1], lambda rows: rows[::2] + rows[1::2]))<br>L?: 動的 (result)<br>L?: 動的 (result)<br>L?: 動的 (rows)<br>L?: 動的 (result) |
| `integrations/issues_scan.checks.py::check_condition_diagnostics` | L1461: 4 ([({'Condition': 'Missing'}, 'unresolved'), ({'Condition': 'Broken'}, 'cyclic'), ('false', 'non-boolean'), ({'Fn::Equals': [{'Ref': 'Unknown'}, 'x']}, 'unsupported')])<br>L1470: 2 ((False, True))<br>L1497: 4 ((True, 'false', None, 0))<br>L?: 動的 (cause['inputs'])<br>L?: 動的 (candidate([{'ParameterKey': 'Enable', 'ParameterValue': 'true'}], 'Combined'))<br>L?: 動的 (records)<br>L?: 動的 (active)<br>L?: 動的 (active) |
| `integrations/issues_scan.checks.py::check_scan_workflow` | 1（内部パラメータ化なし） |
| `integrations/issues_scan.checks.py::check_summary_detail_cli` | L?: 動的 (actions)<br>L?: 動的 (group['members']) |
| `integrations/issues_scan.checks.py::check_arn_array_reference_forms` | L1663: 3 ([('001', 'IAM.Role', 'Role'), ('002', 'IAM.ManagedPolicy', 'Policy'), ('003', 'IAM.ManagedPolicy', 'OtherPolicy')])<br>L1671: 2 (('Policy', 'OtherPolicy'))<br>L1714: 2 ((('[same-name](#missing-policy)', 'reference mapping matches=0'), ('`PENDING_DEPLOY`', 'desired value is unresolved')))<br>L?: 動的 (results)<br>L?: 動的 (values.items()) |
| `integrations/issues_scan.checks.py::check_eventbridge_reference_literals` | L1727: 2 ([('001', 'Function'), ('002', 'OtherFunction')])<br>L1746: 動的 ([arn.replace('arn:aws:', 'arn:aws-cn:'), arn.replace('ap-northeast-1', 'us-east-1'), arn.replace('123456789012', '999999999999'), arn + ':1', arn + ':alias', arn.replace(':function:', ':layer:'), arn + '-other'])<br>L?: 動的 (functions.items()) |
| `integrations/issues_scan.checks.py::check_glue_connection_names` | L1785: 4 ([('001', 'Connection', 'Glue.Connection'), ('002', 'OtherConnection', 'Glue.Connection'), ('003', 'Job', 'Glue.Job'), ('004', 'Project', 'CodeBuild.Project')])<br>L1799: 7 (['app-dev-data1', {'Ref': 'Name'}, {'Fn::Sub': '${Name}'}, {'Fn::Join': ['-', ['app', 'dev', 'data1']]}, {'Fn::If': ['Active', {'Ref': 'Name'}, 'inactive']}, {'Fn::FindInMap': ['Names', 'dev', 'Connection']}, {'Fn::Select': [0, {'Fn::Split': [',', 'app-dev-data1,other']}]}])<br>L1811: 6 ([('different', 'difference'), ({'Ref': 'Missing'}, 'uncompared'), ({'Ref': 'Connection'}, 'uncompared'), ({'Fn::Sub': '${Connection}'}, 'uncompared'), ({'Ref': 'OtherConnection'}, 'uncompared'), ('UNSET', 'uncompared')])<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 動的 (values.items()) |
| `integrations/issues_scan.checks.py::check_added_reference_properties` | L1862: 動的 (specs)<br>L1872: 動的 (models.items())<br>L1903: 動的 (cases.items())<br>L1925: 2 ([('Role', 'Glue.Job', 'Role'), ('Function', 'Lambda.Permission', 'FunctionName')])<br>L1931: 2 (('Alias', 'Key'))<br>L1947: 6 ([None, {'Ref': 'AWS::NoValue'}, {'Fn::If': ['Active', {'Ref': 'AWS::NoValue'}, {'Ref': 'Vpc'}]}, {'Ref': 'Role'}, {'Ref': 'Group'}, 'UNSET'])<br>L1975: 3 (({}, {'ResourceType': 'Subnet'}, {'ResourceType': 'UNSET'}))<br>L1983: 3 ([('EC2.FlowLog', 'ResourceId'), ('CodeBuild.Project', 'Environment.EnvironmentVariables[].Value'), ('Route53.RecordSet', 'ResourceRecords[]')])<br>L1864: 2 (('', 'Other'))<br>L1904: 動的 (properties)<br>L1932: 動的 (cases['Alias'])<br>L?: 動的 (model.items()) |
| `integrations/issues_scan.checks.py::check_aws_standard_comparison` | L2013: 動的 (specs.items())<br>L2064: 3 (({}, {'Type': 'PARAMETER_STORE'}, {'Type': 'PLAINTEXT'}))<br>L2079: 4 (('${Unknown}', '${Role}', '${Role.Arn}', '${aws:username}'))<br>L2015: 動的 (resources)<br>L2019: 動的 (enumerate(rows, 1))<br>L?: 動的 (records)<br>L?: 動的 (selected)<br>L?: 動的 (values.items()) |
| `integrations/json-yaml-document-hash.checks.py::check` | L38: 2 ([('preview', human), ('release', human)])<br>L46: 動的 (paths.items())<br>L?: 動的 (first.items())<br>L?: 動的 (paths.items()) |
| `integrations/lambda-input-reference.checks.py::check` | L83: 5 ([(original.replace('resourceType=Lambda.Function', 'resourceType=S3.Bucket'), 'type-mismatched'), (original.replace('052', '053'), 'type-mismatched'), (original.replace('Lambda.Function.FunctionName', 'Lambda.Function.Description'), 'exactly one name'), (original.replace('`app-preview-one`', '``'), 'exactly one name'), (original + 'desired.row.052-004.property=Lambda.Function.FunctionName\ndesired.row.052-004.value=`duplicate`\n', 'exactly one name')])<br>L?: 2 ([('default-label', '021', {}), ('existing-label', '083', {'Function': 'PENDING_DEPLOY'})])<br>L?: 動的 (values.items()) |
| `integrations/model-input-context-digest.checks.py::check` | L75: 4 (([], [target, target], [{**target, 'awsExecutionAccountId': 123}], [{**target, 'awsExecutionAccountId': 'bad'}]))<br>L?: 動的 (values.items()) |
| `integrations/model-test.checks.py::check` | L143: 動的 (ordinary)<br>L200: 2 (('Action', 'Condition'))<br>L218: 3 ([({'Fn::GetAtt': ['role', 'Arn']}, 'match'), ({'Fn::GetAtt': ['role', 'RoleId']}, 'design_unresolved'), ({'Fn::Sub': '${role.RoleId}'}, 'design_unresolved')])<br>L231: 3 ([('property', 'IAM.Role.MaxSessionDuration'), ('value', '`3600`'), ('comment', 'fixture')])<br>L112: 2 ([('vpc', vpc), ('iam', iam)])<br>L115: 動的 (sources.items())<br>L?: 動的 (sources.items())<br>L?: 動的 (records)<br>L?: 動的 (records)<br>L?: 2 (('vpc', 'iam'))<br>L?: 動的 (failed)<br>L?: 動的 (rt['audit'](configured, 'wrong', cli)[2])<br>L?: 動的 (rt['audit'](vpc, '', cli)[2])<br>L?: 動的 (rt['audit'](vpc, None, cli)[2])<br>L?: 動的 (cli.calls)<br>L?: 動的 (result)<br>L?: 動的 (resolved)<br>L?: 動的 (result)<br>L?: 動的 (result)<br>L?: 動的 (result)<br>L?: 動的 (changed)<br>L?: 動的 (logs[0].parent.glob('vpc-*.log'))<br>L?: 動的 (findings.errors)<br>L?: 2 ([('cde', '123456789012'), ('other', '210987654321')])<br>L?: 2 (('completed', 'suspend')); 既存/未作成出力の不変、running保存、契約変更/契約なし拒否 |
| `integrations/model_design.checks.py::check_route53_endpoint_dns_roundtrip` | L23: 3 ([('property', 'EC2.VPCEndpoint.Id'), ('value', 'vpce-014d2843ef114f19d'), ('comment', '一意に識別するID')])<br>L32: 動的 ([('property', 'Route53.RecordSet.ResourceRecords'), ('value', dns), ('comment', 'CNAMEの接続先DNS')])<br>L44: 動的 ((valid.replace(dns, dns.replace('014d2843ef114f19d', '014d2843ef114f190')), valid.replace('vpce-svc-04feb508c997b211e', 'vpce-svc-04feb508c997b2110'), valid.replace('ap-northeast-1.vpce.amazonaws.com', 'us-east-1.vpce.amazonaws.com'), valid.replace('vpc-endpoint.md#vpc-endpoint-vpce-app-dev-snowflake', 'route53.md#route53-snow.example.com')))<br>L52: 動的 ((dns, 'Interface', 'com.amazonaws.vpce.ap-northeast-1.vpce-svc-04feb508c997b211e')) |
| `integrations/model_design.checks.py::check_firehose_import_pending_roundtrip` | L88: 動的 (errors(valid)) |
| `integrations/model_design.checks.py::check_config_import_pending_roundtrip` | L104: 3 ([('property', 'Config.ConfigurationRecorder.Id'), ('value', '`PENDING_DEPLOY`'), ('comment', '一意に識別するID')])<br>L124: 動的 (errors(valid)) |
| `integrations/model_design.checks.py::check_desired_only_identifier_reference` | L162: 動的 (source) |
| `integrations/model_design.checks.py::check_catalog_display_order` | L196: 動的 (shown)<br>L199: 4 ((('10.0.0.0/16', '10.1.0.0/16'), ('アドレス範囲', '変更された説明'), ('vpc-123', 'vpc-456'), ('"first"', '"changed"')))<br>L207: 動的 (('\\n'.join((line for line in output.splitlines() if ' \| CidrBlock \| ' not in line)), output.replace(' \| CidrBlock \| ', ' \| UnknownField \| ')))<br>L207: 動的 (output.splitlines())<br>L225: 3 ((('QuickSight.DataSource', ['Type', 'Name', 'DataSourceParameters.AthenaParameters.WorkGroup', 'AwsAccountId', 'DataSourceId']), ('S3.Bucket', ['Tags[].Key', 'Tags[].Value', 'Region', 'BucketName']), ('CodeBuild.Project', ['VpcConfig.VpcId', 'VpcConfig.SecurityGroupIds', 'VpcConfig.Subnets', 'Name'])))<br>L228: 動的 (enumerate(fields))<br>L231: 動的 (rows)<br>L231: 動的 (shown)<br>L233: 動的 (shown[:2]) |
| `integrations/model_design.checks.py::check_kms_policy_execution_account` | L259: 動的 (policy['Statement'])<br>L261: 2 ((0, 1))<br>L264: 2 ((False, True))<br>L270: 動的 (('キーの利用権限', f'cross-account:{root_arn}', f'cross-account:{arn}extra'))<br>L276: 動的 (target.items())<br>L295: 2 ((False, True)) |
| `integrations/model_design.checks.py::check_glue_argument_display` | L316: 動的 (json.loads(arguments).items())<br>L329: 動的 (output.splitlines())<br>L332: 動的 (invalid)<br>L336: 2 (('`{}`', '`{"--one":"one"}`'))<br>L339: 3 (('`[]`', '`{"--one":true}`', '`{"--one":"first","--one":"second"}`')) |
| `integrations/model_design.checks.py::check_ec2_compact_display` | L349: 2 ((1, 5))<br>L351: 動的 (range(1, count + 1))<br>L370: 動的 (range(1, count + 1))<br>L388: 動的 (invalid) |
| `integrations/model_design.checks.py::check_vpc_endpoint_name_display` | L414: 2 (('CREATE', 'IMPORT'))<br>L424: 動的 ((output.replace('ec2-name-tag:', 'missing-name-tag:'), output.replace('["\\\\"Name\\\\""', '["\\\\"name\\\\""'), output.replace('\| Name \|', '\| ServiceName \|'))) |
| `integrations/model_design.checks.py::check_subnet_lambda_roundtrip` | 1（内部パラメータ化なし） |
| `integrations/model_design.checks.py::check_subnet_model_validation` | 1（内部パラメータ化なし） |
| `integrations/model_design.checks.py::check_athena_configuration_display` | L496: 動的 ((ROOT / 'framework/materials/aws/Athena_WorkGroup.properties').read_text(encoding='utf-8').splitlines())<br>L497: 動的 (enumerate(fields, 1))<br>L504: 動的 (zip(rows, displayed)) |
| `integrations/model_design.checks.py::check_config_typed_anchors` | L538: 2 (('cde', 'non-cde'))<br>L565: 動的 (((recorder, recorder_anchor, 'Config_ConfigurationRecorder_001'), (channel, channel_anchor, 'Config_DeliveryChannel_001')))<br>L582: 動的 ((('001', 'config-default'), ('001', channel_anchor), ('002', 'config-default'), ('002', recorder_anchor)))<br>L588: 動的 (values.items())<br>L590: 動的 (list(values.items())) |
| `integrations/model_design.checks.py::check_kms_alias_display` | L657: 動的 (diagnostics(validator))<br>L660: 2 ((None, 'CDE用ログキー（log）'))<br>L671: 2 (('alias/', 'venus-dev-log-cde')) |
| `integrations/model_design.checks.py::check_nameless_type_display` | L706: 動的 (((output.replace(f'<!-- resource-logical-id: {logical_id} -->', ''), 'hidden logical ID'), (output.replace(anchor, 'guardduty-wrong'), 'anchor'), (output.replace(f'参照: [{kind}]', '参照: [wrong]'), 'nameless resource link'), (output.replace(f'参照: [{kind}]', f'参照: [{logical_id}]'), 'must not display internal logical ID')))<br>L713: 動的 (errors)<br>L744: 動的 (second.items())<br>L752: 動的 (failures(mixed))<br>L764: 動的 (diagnostics(validator)) |
| `integrations/model_design.checks.py::check_nameless_logical_id_label` | L777: 動的 (enumerate(('BuildProtectionPlan', 'QuarantineProtectionPlan'), 1))<br>L789: 動的 (item.items())<br>L803: 2 ((('001', 'BuildProtectionPlan'), ('002', 'QuarantineProtectionPlan')))<br>L809: 動的 (values.items())<br>L810: 4 (('', 'UNSET', 'PENDING_DEPLOY', 'wrong-label'))<br>L811: 動的 (invalid)<br>L813: 動的 (errors)<br>L814: 2 ((('resourceType', 'GuardDuty.Detector'), ('logicalId', 'OtherPlan')))<br>L820: 動的 (failures(values, output.replace(f'<!-- resource-logical-id: GuardDuty_MalwareProtectionPlan_{identity} -->', '')))<br>L821: 動的 (failures(values, output.replace(values['desired.resource.001.anchor'], 'guardduty-wrong')))<br>L823: 動的 (values.items())<br>L826: 動的 (values.items())<br>L828: 動的 (failures(named, output.replace(kind, 'SNS.Topic').replace('GuardDuty_MalwareProtectionPlan_', 'SNS_Topic_')))<br>L833: 動的 (diagnostics(validator)) |
| `integrations/model_design.checks.py::check_optional_naming_suffix` | L857: 動的 (patterns)<br>L858: 動的 (naming_rule_files(ROOT, kind.partition('.')[0]))<br>L863: 2 (('', '-aaaaaa')) |
| `integrations/model_design.checks.py::check_stack_policy` | L876: 動的 (naming_rule_files(ROOT))<br>L879: 動的 (enumerate((('app-b', '20'), ('network', '10'), ('app-a', '20')), 1))<br>L899: 動的 (stacks)<br>L900: 動的 (stacks)<br>L901: 動的 (stacks)<br>L902: 動的 (stacks)<br>L905: 動的 (entry.items())<br>L905: 動的 (stack_model(values)[1])<br>L905: 動的 (stacks)<br>L914: 6 ((('desired.stack.001.deployOrder', '0'), ('desired.stack.001.deployOrder', '-1'), ('desired.stack.001.deployOrder', 'abc'), ('desired.deployment.maxConcurrentStacks', '0'), ('desired.deployment.maxConcurrentStacks', '-1'), ('desired.deployment.maxConcurrentStacks', '1.5'))) |
| `integrations/model_design.checks.py::check_stack_mapping_roundtrip` | L957: 動的 (enumerate(('ism', 'key'), 1))<br>L958: 動的 ({'name': 'cfn-stack-app-dev-' + purpose, 'template': 'shared.yaml', 'parameters': purpose + '.json', 'deployOrder': '10'}.items())<br>L960: 2 ((1, 2))<br>L962: 動的 (values.items())<br>L971: 7 (('', 'invalid', 'stack-resource', 'stack-Bad_Id', 'stack-Resource-With-Hyphens', ' stack-Resource', 'stack-Resource '))<br>L980: 動的 ((rendered.replace('id="' + values['desired.resource.001.anchor'] + '"', 'id="ec2-missing"'), rendered.replace('`10.0.0.0/16`', '`10.1.0.0/16`')))<br>L989: 動的 ((source, stack_source))<br>L989: 動的 (load_model(model).files)<br>L993: 動的 (before)<br>L995: 2 ((('invalid', 'invalid cfn-logicalId'), ('absent-DepartmentVpc', 'undeclared stack')))<br>L1004: 動的 (kms.items())<br>L1024: 動的 (authority)<br>L1029: 動的 (before) |
| `integrations/model_design.checks.py::check_secret_naming_values` | L1042: 動的 (secret_rules)<br>L1046: 2 (('Name', 'SecretsManager.Secret.Name'))<br>L1051: 3 (('', 'UNSET', 'PENDING_DEPLOY')) |
| `integrations/model_design.checks.py::check_naming_exclusions` | L1061: 11 ((('IAM.ManagedPolicy', 'ManagedPolicyName'), ('IAM.User', 'UserName'), ('IAM.InstanceProfile', 'InstanceProfileName'), ('Config.ConfigurationRecorder', 'Name'), ('Config.DeliveryChannel', 'Name'), ('Glue.Connection', 'ConnectionInput.Name'), ('GuardDuty.Detector', 'Name'), ('Glue.Database', 'DatabaseInput.Name'), ('Glue.Table', 'TableInput.Name'), ('Route53.HostedZone', 'Name'), ('Route53.RecordSet', 'Name')))<br>L1068: 動的 ((field, kind + '.' + field))<br>L1096: 3 (('', 'UNSET', 'PENDING_DEPLOY'))<br>L1100: 動的 (diagnostics(validator))<br>L1111: 3 ((('SecretsManager.Secret', 'Name'), ('Glue.Database', 'DatabaseInput.Name'), ('Glue.Table', 'TableInput.Name'))) |
| `integrations/model_design.checks.py::check_codebuild_required_name` | L1132: 動的 (('', '``', '`   `', '`UNSET`', '` UNSET `', '`PENDING_DEPLOY`', '`Pending`', '`TBD`', '`none`', '`未確定`', '`{{application}}`', f'[{name}](#codebuild-{name})'))<br>L1146: 動的 (invalid)<br>L1148: 動的 (enumerate(bad_rows, 1))<br>L1150: 動的 (formal_rows)<br>L1155: 動的 (enumerate(bad_rows, 1))<br>L1159: 動的 (diagnostics(validator)) |
| `integrations/model_design.checks.py::check_iam_role_name` | L1177: 動的 (('', '``', '`   `', '`UNSET`', '` UNSET `', '`PENDING_DEPLOY`', '`Pending`', '`TBD`', '`none`', '`未確定`', '`{{application}}`', f'[{name}](#resource-{logical_id})'))<br>L1208: 動的 ((name, logical_id, 'wrong-name', '/service-role/' + name))<br>L1215: 動的 (invalid)<br>L1217: 動的 (enumerate(bad_rows, 1))<br>L1219: 動的 (formal_rows)<br>L1224: 動的 (enumerate(bad_rows, 1))<br>L1225: 動的 (failures(rendered)) |
| `integrations/model_design.checks.py::check_required_name_tag` | L1251: 動的 (('', '``', '`   `', '`UNSET`', '` UNSET `', '`PENDING_DEPLOY`', '`Pending`', '`TBD`', '`none`', '`not-used`', '`{{application}}`', f'[{name}](#{anchor})'))<br>L1280: 動的 (('wrong-label', current_id, logical_id))<br>L1284: 動的 (diagnostics(validator))<br>L1305: 動的 (diagnostics(validator))<br>L1307: 動的 (invalid_tags)<br>L1310: 動的 (enumerate(bad_rows, 1))<br>L1314: 動的 ((lambda: resource_display_name(kind, formal_rows), lambda: markdown_for(path, bad, root)))<br>L1323: 動的 (enumerate(bad_rows, 1)) |
| `integrations/model_design.checks.py::check_service_failure_protection` | L1351: 動的 (sources.items())<br>L1354: 動的 (load_model(model).files)<br>L1354: 動的 (sources)<br>L1359: 動的 (load_model(model).files)<br>L1359: 動的 (sources)<br>L1362: 動的 (docs.rglob('*'))<br>L1377: 動的 (docs.rglob('*'))<br>L1381: 動的 (docs.rglob('*'))<br>L1389: 2 ((('desired.row.001-001.value', '``', 'confirmed resource display label is missing'), ('desired.row.001-002.value', '`31`', 'schema')))<br>L1395: 動的 (docs.rglob('*'))<br>L1397: 動的 (docs.rglob('*'))<br>L1405: 動的 (diagnostics(validator))<br>L1412: 動的 (iam.items())<br>L1422: 動的 (docs.rglob('*'))<br>L1424: 動的 (docs.rglob('*'))<br>L1435: 動的 (docs.rglob('*'))<br>L1456: 動的 (docs.rglob('*'))<br>L1460: 動的 (load_model(model).files)<br>L1460: 動的 (sources)<br>L1469: 動的 (load_model(model).files)<br>L1469: 動的 (sources)<br>L1470: 動的 (docs.rglob('*'))<br>L1475: 動的 (readonly.findings.warnings)<br>L1476: 動的 (docs.rglob('*'))<br>L1477: 動的 (load_model(model).files)<br>L1477: 動的 (sources)<br>L1482: 動的 (load_model(model).files)<br>L1482: 動的 (sources)<br>L1485: 動的 (docs.rglob('*'))<br>L1497: 動的 (docs.rglob('*'))<br>L1498: 動的 (load_model(model).files)<br>L1498: 動的 (sources)<br>L1500: 動的 (docs.rglob('*'))<br>L1505: 動的 (load_model(model).files)<br>L1505: 動的 (sources)<br>L1520: 動的 (docs.rglob('*'))<br>L1528: 動的 (snapshot.items())<br>L1535: 動的 (docs.rglob('*'))<br>L1543: 動的 (load_model(model).files)<br>L1543: 動的 (sources)<br>L1556: 動的 (load_model(model).files)<br>L1556: 動的 (sources)<br>L1558: 動的 (docs.rglob('*'))<br>L1580: 動的 ((base, docs))<br>L1580: 動的 (directory.rglob('*'))<br>L1581: 動的 (files)<br>L1614: 動的 (docs.rglob('*'))<br>L1625: 動的 (docs.rglob('*')) |
| `integrations/model_design.checks.py::check_service_displays` | L1697: 動的 (enumerate((('Id', '[EC2_SecurityGroupIngress_001](security-group.md#resource-EC2_SecurityGroupIngress_001)'), ('IpProtocol', '`tcp`'), ('FromPort', '`22`'), ('ToPort', '`22`'), ('SourceSecurityGroupId', '[PENDING_DEPLOY](#security-group-dev-app-data-01-sg)')), 1))<br>L1708: 2 (('Ingress', 'Egress'))<br>L1711: 動的 (variant.items())<br>L1714: 4 (('PENDING_DEPLOY', '`PENDING_DEPLOY`', 'sgr-00000001', '`sgr-00000001`')) |
| `integrations/model_design.checks.py::check_observed_arn_authority` | L1730: 2 (('IMPORT', 'CREATE'))<br>L1737: 動的 (findings.errors)<br>L1741: 動的 (findings.errors) |
| `integrations/model_files.checks.py::check_resource_reading` | L19: 60 (range(1, 61))<br>L60: 2 ((text, '# padding\n' * 540 + text))<br>L99: 3 ((text.replace('desired.resource.002.logicalId=Resource2', 'desired.resource.002.logicalId=Resource1'), text.replace('[Resource1](#kms-resource-001)', '[Missing](#missing)'), text.replace('[Resource1](#kms-resource-001)', '[Other](other.md#kms-resource-001)')))<br>L65: 5 (('001', 'Resource1', 'kms-resource-001', 'Resource2', '003'))<br>L93: 4 (('', 'Resource', '999', 'Resource61'))<br>L57: 動的 (sorted(values.items()))<br>L70: 動的 (result.stdout.splitlines())<br>L45: 動的 (values.items())<br>L63: 動的 (loaded.values.items())<br>L64: 動的 (loaded.files)<br>L52: 3 (('001', '002', '003'))<br>L52: 4 ((f'desired.resource.{identity}.', f'display.resource.{identity}.', f'desired.row.{identity}-', f'observed.row.{identity}-'))<br>L97: 動的 (snapshot.items())<br>L87: 動的 (loaded.locations.values()) |
| `integrations/model_impact.checks.py::check_precision` | L138: 動的 (data['instances'].values())<br>L?: 3 (('uses-first', 'fixed-export', 'continues'))<br>L?: 動的 (validator.errors)<br>L?: 動的 (template.read_text().replace('{"setting":"<<Setting>>"}', '{"fixed":true}').splitlines())<br>L?: 6 (('uses-first', 'uses-second', 'fixed-export', 'continues', 'stops-here', 'disabled')) |
| `integrations/model_impact.checks.py::check_identity_and_deletion` | 1（内部パラメータ化なし） |
| `integrations/model_impact.checks.py::check_shared_environments` | L183: 2 (('dev', 'stg')) |
| `integrations/model_impact.checks.py::check_identifiers` | L203: 2 ((1, 2)) |
| `integrations/model_impact.checks.py::check_type_and_unknown` | 1（内部パラメータ化なし） |
| `integrations/model_impact.checks.py::check_import_scope` | 1（内部パラメータ化なし） |
| `integrations/model_impact.checks.py::check_selection` | 1（内部パラメータ化なし） |
| `integrations/model_impact.checks.py::check_cycles` | 1（内部パラメータ化なし） |
| `integrations/model_parameter_inputs.checks.py::check_human` | L26: 動的 (records.items())<br>L64: 2 (('main-vpc', 'service'))<br>L113: 動的 (environments)<br>L120: 動的 (selected['instances'].items())<br>L123: 2 (('missing', 'private-c'))<br>L140: 動的 (extbindings['instances'].values())<br>L146: 動的 (selected['instances'].items())<br>L157: 10 ([(lambda p: p['instances']['main-vpc']['parameters'].update(Name='obsolete'), 'unknown parameter'), (lambda p: p['instances']['main-vpc']['parameters'].update(EnableDnsSupport=True), 'unknown parameter'), (lambda p: p['instances']['main-vpc']['parameters'].pop('CidrBlock'), 'missing required'), (lambda p: p['instances']['main-vpc']['parameters'].update(CidrBlock=10), 'type mismatch'), (lambda p: p['instances']['main-vpc']['parameters'].update(CidrBlock='10.10.0.1/23'), 'constraint cidr'), (lambda p: p['parameters'].update(Suffix=True), 'type mismatch'), (lambda p: p['parameters'].update(Environment='invented'), 'unknown parameter'), (lambda p: p['parameters'].pop('Suffix'), 'missing required'), (lambda p: p['instances']['private-a']['parameters'].update(Suffix='override'), 'ambiguous parameter source'), (lambda p: p['instances']['private-a']['parameters'].update(NameSuffix='bad'), 'constraint enum')])<br>L14: 動的 (environments)<br>L28: 動的 (human['instances'].items())<br>L34: 動的 (environments)<br>L38: 動的 (environments)<br>L67: 2 (('unknown', 17))<br>L?: 動的 (environments)<br>L?: 動的 ((root / 'docs/designs').rglob('*'))<br>L?: 4 (('model', 'model/parameters', 'model/templates', 'docs/designs'))<br>L?: 動的 ((root / base).rglob('*'))<br>L?: 動的 (baseline.items())<br>L?: 動的 (all_bytes.items())<br>L?: 動的 (params['instances'].values())<br>L?: 動的 (bindings['instances'].values())<br>L?: 動的 (before['preview'])<br>L?: 動的 (before['preview'])<br>L?: 3 (('017', '042', '083'))<br>L?: 動的 (environments)<br>L?: 動的 (kinds)<br>L?: 動的 (kinds.items()) |
| `integrations/model_parameter_inputs.checks.py::check_declared_instance_inputs` | L207: 2 (('service', 'Legal_42-name'))<br>L227: 7 ([(lambda h: h['instances'].update(unregistered={'parameters': {}}), 'binding mismatch'), (lambda h: h['instances'][identity]['parameters'].update(ValueUnknown=1), 'unknown parameter'), (lambda h: h['instances']['required']['parameters'].pop('Enabled'), 'missing required parameter'), (lambda h: h['instances'][identity]['parameters'].update(Value1=True), 'parameter type mismatch'), (lambda h: h['instances']['required']['parameters'].update(Hidden='override'), 'internal information'), (lambda h: h['instances'].update({'bindings-only': {'parameters': {}}}), 'input-free instances belong in bindings'), (lambda h: h['instances'].pop(identity), 'input-bearing instances require YAML')])<br>L244: 2 (('dev', 'stg'))<br>L?: 動的 (instances['instances']) |
| `integrations/model_parameter_inputs.checks.py::check_kms_alias` | L303: 3 ([(original.replace('KMS.Alias', 'KMS.Key'), 'type-mismatched'), (original.replace('KMS.Alias.AliasName', 'KMS.Alias.TargetKeyId'), 'exactly one name'), (original + 'desired.row.012-003.property=KMS.Alias.AliasName\ndesired.row.012-003.value=`alias/duplicate`\n', 'exactly one name')])<br>L?: 動的 (values.items()) |
| `integrations/model_parameter_inputs.checks.py::check_external_instances` | L347: 2 ([('dev', '017'), ('stg', '083')])<br>L334: 動的 ([identity, '099'] if duplicate else [identity]) |
| `integrations/model_parameter_inputs.checks.py::check_service_contracts` | 1（内部パラメータ化なし） |
| `integrations/model_templates.checks.py::check_transactions` | 1（内部パラメータ化なし） |
| `integrations/model_templates.checks.py::check_expansion` | L59: 動的 (models.items())<br>L62: 動的 (models.items())<br>L79: 動的 (models)<br>L62: 動的 (load_model(root / 'model' / env / 'team/iam.properties').values.values()) |
| `integrations/model_templates.checks.py::check_layout` | L90: 5 (('model/templates/team/iam.properties', 'model/parameters/team/iam.properties', 'model/parameters/dev/team/iam/parameters.yaml', 'model/dev/team/iam.json', 'model/dev/team/iam.properties/part-001.properties'))<br>L104: 2 (('dev', 'stg'))<br>L109: 4 (('model/templates/team/unrelated.properties.tpl', 'model/templates/team/iam.json', 'model/parameters/dev/team/iam.json', 'docs/unrelated.md'))<br>L114: 2 (('dev', 'stg'))<br>L118: 4 ((({part.relative_to(root).as_posix()}, True), ({'model/parameters/dev/team/iam/parameters.yaml'}, False), ({'model/parameters/stg/team/iam/parameters.yaml'}, True), ({'model/dev/team/iam.properties'}, False)))<br>L106: 3 (('parameters.yaml', 'bindings.json', 'observed.json'))<br>L87: 2 (('dev', 'stg')) |
| `integrations/model_templates.checks.py::check_reference_impact` | L156: 2 ([('codepipeline', 'codebuild', 'CodeBuild.Project', 'CodePipeline.Pipeline'), ('lambda', 'codepipeline', 'CodePipeline.Pipeline', 'Lambda.Function')])<br>L176: 2 (('codepipeline', 'lambda'))<br>L223: 動的 (impact.dependencies(root).values())<br>L246: 動的 (original.splitlines(keepends=True)) |
| `integrations/model_templates.checks.py::check_template_snapshot` | L279: 動的 (files) |
| `integrations/model_templates.checks.py::check_creation` | L295: 2 (range(2))<br>L301: 動的 (root.rglob('*'))<br>L303: 動的 (root.rglob('*')) |
| `integrations/model_templates.checks.py::check_invalid` | L311: 4 ((lambda p: p.update(unknown=1), lambda p: p['instances']['role_011']['parameters'].pop('Name'), lambda p: p['instances']['role_011']['parameters'].update(Name=True), lambda p: p['instances']['role_011'].update(definition='Role')))<br>L313: 3 ((lambda b: b['instances']['role_011'].update(definition='missing'), lambda b: b['instances']['role_018']['resources'].update(role='011'), lambda b: b['instances']['role_011']['rows'].update(name='099-004')))<br>L316: 9 (('<<Missing>>', '<<#Name>>x<</Name>>', '<<^Name>>x<</Name>>', '<<>partial>>', '<<&Name>>', '<<{Name}>>', '<<= x y =>>', '{{#Name}}', '{{>partial}}'))<br>L319: 4 (('a"b\\日本語=終', '', '<<not-reparsed>>', '${AWS::Region} {{resolve:ssm:literal}}'))<br>L325: 2 (('parameters.yaml', 'bindings.json')) |
| `integrations/model_templates.checks.py::check_sync` | L347: 1 ((('\r\n', False),))<br>L335: 動的 (root.rglob('*'))<br>L339: 動的 (before.items()) |
| `integrations/model_templates.checks.py::check_common_shape` | L368: 動的 (minimal) |
| `integrations/policy_tables.checks.py::check_iam` | L51: 2 (('RoleA', 'RoleB'))<br>L110: 4 (('Property：', 'JSON：', 'Version：', 'Id：'))<br>L124: 動的 (reversed(resources_in(indexed_lines)))<br>L178: 3 ((('S' * 16, True), ('S' * 17, False), (17, False)))<br>L53: 3 ((('trust-policy', trust), ('logging', inline), ('extra', inline)))<br>L?: 動的 (rendered.splitlines())<br>L?: 動的 (indexed_lines[start:resource.table_end])<br>L?: 動的 (shown)<br>L?: 動的 (errors(rendered))<br>L?: 動的 (line.strip('\|').split('\|'))<br>L?: 動的 (minimal.splitlines())<br>L?: 2 (('\| RoleName \|', '\| Policies[]')) |
| `integrations/policy_tables.checks.py::check_service_policies` | L226: 動的 ((repository / 'framework/materials/aws').glob('*.properties'))<br>L239: 動的 (POLICY_FORMATS.items())<br>L346: 5 (('ApiGateway.RestApi.SecurityPolicy', 'ElasticLoadBalancingV2.Listener.SslPolicy', 'NetworkFirewall.FirewallPolicy.FirewallPolicy.StatefulEngineOptions.StreamExceptionPolicy', 'S3.Bucket.PublicAccessBlockConfiguration.BlockPublicPolicy', 'SSO.PermissionSet.ManagedPolicies'))<br>L228: 動的 (catalog.read_text(encoding='utf-8').splitlines())<br>L268: 2 (('sample-a', 'sample-b'))<br>L288: 4 (('Property：', 'JSON：', 'Version：', 'Id：'))<br>L325: 4 ((f'Property：`{prop}`', f'JSON：[Access]({service}/access.json)', 'Version：`2012-10-17`', 'Id：`access-policy`'))<br>L276: 動的 (enumerate(rows, 1))<br>L?: 動的 (catalog.read_text(encoding='utf-8').splitlines())<br>L?: 動的 (types)<br>L?: 動的 (original.splitlines()) |
| `integrations/policy_tables.checks.py::check_grouping_and_settings` | L429: 4 (({'LifecyclePolicyText': {}}, {'LifecyclePolicyText': 'not-json'}, {'LifecyclePolicyText': '[]'}, {'LifecyclePolicyText': '{"rules":[],"rules":[]}'})) |
| `integrations/producer-identifier-reference.checks.py::check` | L60: 2 (['`vpc-fixture-two`', '`PENDING_DEPLOY`'])<br>L66: 2 (((producer_text.replace('row.id.property=EC2.VPC.VpcId', 'row.id.property=EC2.Subnet.SubnetId'), observed['values']), (producer_text.replace('row.name.property=EC2.VPC.Name', 'row.name.property=EC2.VPC.VpcId'), {**observed['values'], 'observed.row.001-001.value': '`duplicate`'})))<br>L75: 6 ([({}, 'matching observed identifier'), ({'observed.row.001-002.property': 'EC2.Subnet.SubnetId', 'observed.row.001-002.value': '`subnet-one`'}, 'invalid observed key/value'), ({**observed['values'], 'observed.row.001-001.property': 'EC2.VPC.VpcId', 'observed.row.001-001.value': '`duplicate`'}, 'invalid observed key/value'), ({**observed['values'], 'observed.row.001-002.value': False}, 'invalid observed key/value'), ({**observed['values'], 'observed.row.001-002.value': '``'}, 'nonempty non-ARN string'), ({**observed['values'], 'observed.row.001-002.value': 'arn:aws:fixture'}, 'nonempty non-ARN string')])<br>L85: 3 ([({'resource': '002'}, 'type-mismatched'), ({'resourceType': 'EC2.Subnet', 'property': 'EC2.Subnet.SubnetId'}, 'type-mismatched'), ({'property': 'EC2.VPC.Name'}, 'not a catalog identifier')])<br>L?: 動的 (observed['values'].items())<br>L?: 動的 ({**desired, **observed['values']}.items())<br>L?: 動的 (values.items())<br>L?: 動的 (desired.items()) |
| `integrations/producer-name-reference.checks.py::check` | L71: 2 ([('preview', '-Case_01'), ('later', '')])<br>L132: 6 ([(original.replace('resourceType=IAM.Role', 'resourceType=IAM.Policy'), 'type-mismatched'), (original.replace('054', '055'), 'type-mismatched'), (original.replace('IAM.Role.RoleName', 'IAM.Role.Path'), 'exactly one name'), (original.replace('IAM.Role.RoleName', 'Glue.SecurityConfiguration.Name'), 'exactly one name'), (original.replace('`venusinf-preview-IfInbound1802Role-Case_01`', '``'), 'exactly one name'), (original + 'desired.row.054-002.property=IAM.Role.RoleName\ndesired.row.054-002.value=`duplicate`\n', 'exactly one name')])<br>L73: 動的 (refs.items())<br>L?: 動的 (producer_texts)<br>L?: 動的 (load_model(producer).files)<br>L?: 動的 (refs.items())<br>L?: 動的 (values.items()) |
| `integrations/raw-bucket-name-reference.checks.py::check` | L63: 5 ([(original.replace('resourceType=S3.Bucket', 'resourceType=IAM.Role'), 'type-mismatched'), (original.replace('017', '018'), 'type-mismatched'), (original.replace('S3.Bucket.BucketName', 'S3.Bucket.Description'), 'exactly one name'), (original.replace('`app-preview-RAW-one`', '``'), 'exactly one name'), (original + 'desired.row.017-002.property=S3.Bucket.BucketName\ndesired.row.017-002.value=`duplicate`\n', 'exactly one name')])<br>L?: 2 ([('first', '003'), ('second', '088')])<br>L?: 動的 (values.items()) |
| `integrations/s3-bound-anchor.checks.py::check` | L?: 動的 (updated)<br>L?: 動的 (values)<br>L?: 動的 (values.items()) |
| `integrations/security-group-input-reference.checks.py::check` | L90: 5 ([(original.replace('resourceType=EC2.SecurityGroup', 'resourceType=EC2.Subnet'), 'type-mismatched'), (original.replace('052', '053'), 'type-mismatched'), (original.replace('EC2.SecurityGroup.GroupName', 'EC2.SecurityGroup.GroupDescription'), 'exactly one name'), (original.replace('`app-preview-one`', '``'), 'exactly one name'), (original + 'desired.row.052-004.property=EC2.SecurityGroup.GroupName\ndesired.row.052-004.value=`duplicate`\n', 'exactly one name')])<br>L?: 2 ([('default-label', '021', {}), ('existing-label', '083', {'SecurityGroup': 'PENDING_DEPLOY'})])<br>L?: 動的 (values.items()) |
| `integrations/service_contracts.py::check_kms` | L26: 動的 (cases('kms'))<br>L41: 3 ([('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')])<br>L30: 動的 (before.keys() | after.keys())<br>L36: 動的 (before.items())<br>L31: 動的 (before.items())<br>L37: 動的 (before)<br>L39: 動的 (alias_rows) |
| `integrations/service_contracts.py::check_security_group` | L53: 動的 (cases('security-group'))<br>L66: 3 ([('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')])<br>L60: 動的 (before.keys() | after.keys())<br>L54: 動的 (original['instances'].items())<br>L54: 動的 (item['parameters']) |
| `integrations/service_contracts.py::check_route53` | L78: 動的 (cases('route53'))<br>L101: 3 ([('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')])<br>L87: 動的 (before.keys() | after.keys())<br>L81: 動的 (original['instances'].items())<br>L81: 動的 (item['parameters'])<br>L97: 動的 (before.keys() | changed_name.keys())<br>L99: 動的 (differences)<br>L100: 動的 (changed_name)<br>L100: 動的 (before) |
| `integrations/service_contracts.py::check_iam` | L114: 動的 (cases('iam'))<br>L115: 動的 (before.items())<br>L132: 3 ([('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')])<br>L128: 動的 (before.keys() | after.keys())<br>L130: 動的 (differences)<br>L129: 動的 (differences) |
| `integrations/service_contracts.py::check_s3` | L146: 動的 (cases('s3'))<br>L157: 3 ([('unknown', 'unknown parameter'), ('missing', 'missing required parameter'), ('type', 'parameter type mismatch')])<br>L171: 動的 (before.items())<br>L153: 動的 (before.keys() | changed.keys())<br>L147: 動的 (human['instances'].items())<br>L175: 動的 (t.model_paths(ROOT)) |
| `integrations/service_contracts.py::check_glue` | L180: 動的 (cases('glue'))<br>L189: 動的 (resource_row_index(renamed).values())<br>L190: 動的 (rows)<br>L184: 動的 (resource_row_index(before).values())<br>L184: 動的 (rows)<br>L183: 動的 (defs.values())<br>L185: 動的 (timeouts)<br>L195: 動的 (arguments.values()) |
| `integrations/service_contracts.py::check_cloudwatch_logs` | L204: 動的 (cases('cloudwatch-logs'))<br>L206: 動的 (defs.values())<br>L210: 動的 (resource_row_index(before).values())<br>L212: 動的 (rows)<br>L207: 動的 (d.parameters.values())<br>L209: 動的 (defs.values())<br>L211: 動的 (rows) |
| `integrations/service_contracts.py::check_lambda` | L220: 動的 (cases('lambda'))<br>L221: 動的 (resource_row_index(before).items())<br>L225: 動的 (rows)<br>L236: 動的 (before.keys() | after.keys())<br>L231: 動的 (human['instances'].items()) |
| `integrations/service_contracts.py::check_eventbridge` | L246: 動的 (cases('eventbridge'))<br>L247: 動的 (resource_row_index(before).items())<br>L264: 動的 (fixed_retry.items())<br>L251: 動的 (rows)<br>L266: 動的 (resource_row_index(before).values())<br>L266: 動的 (rows)<br>L265: 動的 (human['instances'].values())<br>L268: 動的 (retry_rows) |
| `integrations/service_contracts.py::check_codepipeline` | L279: 動的 (cases('codepipeline'))<br>L280: 動的 (resource_row_index(before).items())<br>L285: 動的 (rows)<br>L294: 動的 (before.keys() | after.keys())<br>L282: 動的 (rows)<br>L291: 動的 (human['instances'].items())<br>L284: 動的 (restored)<br>L284: 動的 (formal)<br>L288: 動的 (doc.values()) |
| `integrations/service_contracts.py::check_responsibilities` | L317: 動的 (sorted(services))<br>L319: 動的 (cases(service))<br>L327: 動的 (before.items())<br>L343: 動的 (trace.values())<br>L350: 動的 (slots)<br>L344: 動的 (source.get('inputs', {}).values())<br>L351: 動的 (params.items())<br>L349: 動的 (human['instances'].items())<br>L323: 動的 (entries(before, 'desired.stack.'))<br>L326: 動的 (bindings['instances'].values())<br>L342: 動的 (trace.values())<br>L382: 動的 (before)<br>L357: 動的 (spec.items())<br>L390: 動的 (before.items())<br>L385: 動的 (before.items())<br>L389: 動的 (difference) |
| `integrations/service_contracts.py::check` | 1（内部パラメータ化なし） |
| `integrations/service_contracts.py::check_fixtures` | 1（内部パラメータ化なし） |
| `integrations/sync-existing-files.checks.py::check_failure_safety` | L40: 4 (('framework/a.txt', 'framework/b.txt', 'AGENTS.md', 'README.md'))<br>L53: 動的 (target.rglob('*'))<br>L70: 動的 (target.rglob('*')) |
| `integrations/sync-model.checks.py::check_publication_boundary` | L325: 動的 ((design, artifact))<br>L345: 動的 (originals) |
| `integrations/sync-model.checks.py::check_unchanged_sidecar` | 1（内部パラメータ化なし） |
| `integrations/sync-model.checks.py::check_changed_sidecar_publication` | 1（内部パラメータ化なし） |
| `integrations/sync-model.checks.py::check_publication_rechecks_excluded_outputs` | 1（内部パラメータ化なし） |
| `integrations/sync-model.checks.py::check_changed_sidecar_publication_rollback` | L459: 動的 ((design, artifact)) |
| `integrations/sync-model.checks.py::check_unchanged_sidecar_path_safety` | 1（内部パラメータ化なし） |
| `integrations/sync-model.checks.py::check_unchanged_sidecar_validation` | L507: 動的 ((design, artifact))<br>L513: 動的 (before) |
| `integrations/sync-model.checks.py::check_failure_counts` | L526: 動的 (range(17))<br>L537: 動的 (range(5))<br>L540: 動的 (generated)<br>L541: 4 (('design.collections', 'design.ownership', 'design.stacks', 'framework.policy-tables'))<br>L547: 動的 (paths)<br>L548: 6 (('design.names', 'design.tables', 'design.overviews', 'design.links', 'design.artifacts', 'design.observed'))<br>L551: 2 ((False, True))<br>L555: 2 ((False, True)) |
| `integrations/sync-model.checks.py::check_incoming_reference_models` | L588: 2 (('s3', 'kms')) |
| `integrations/sync-model.checks.py::check_required_preflight` | L630: 動的 (values.items())<br>L635: 2 ((False, True))<br>L640: 2 ((False, True))<br>L661: 4 (('', '``', '`""`', '`UNSET`'))<br>L665: 動的 (complete.items()) |
| `integrations/sync-model.checks.py::check_required_property_parents` | L705: 動的 (enumerate((('ConnectionInput.Name', '`sample`'), ('Name', '[Connection](#glue-sample)'), ('CatalogId', '`123456789012`'), ('ConnectionInput.ConnectionType', '`JDBC`'), ('ConnectionInput.PhysicalConnectionRequirements.AvailabilityZone', '`ap-northeast-1a`'), ('ConnectionInput.ValidateCredentials', '`true`')), 1))<br>L719: 動的 (values.items())<br>L737: 2 (('ConnectionInput', 'CatalogId'))<br>L738: 動的 (values.items())<br>L740: 動的 (values.items())<br>L744: 動的 (original.splitlines())<br>L746: 動的 (design_errors(content))<br>L747: 動的 (design_errors(original.replace('`true`', '`not-a-boolean`'))) |
| `integrations/sync-model.checks.py::check_workflow` | L874: 動的 (lines)<br>L943: 動的 (stack_rows)<br>L945: 動的 (stack_rows)<br>L948: 動的 (stack_rows) |
| `integrations/task_contract.checks.py::check_admission_selection` | 1（内部パラメータ化なし） |
| `integrations/task_contract.checks.py::check_completed_legacy_and_paths` | L56: 動的 ((old, new))<br>L69: 9 (('../escape', '/tmp/escape', './file', 'a//file', 'a/../file', '*.md', 'a/**', '.git/config', '.')) |
| `integrations/task_contract.checks.py::check_shared_issue_files` | L?: 2 (('retained issue', 'second issue')) |
| `integrations/task_contract.checks.py::check_suspend_and_resume` | 1（内部パラメータ化なし） |
| `integrations/task_contract.checks.py::check_atomic_contract_reads` | L161: 動的 (during.values()) |
| `integrations/used-definition-inputs.checks.py::check` | L37: 2 ([('Plain', '`fixed`'), ('Endpoint', '`<<EndpointIngressCidr>>`')])<br>L63: 4 ([({}, 'missing required parameter'), ({'Value1': 'old'}, 'unknown parameter'), ({'EndpointIngressCidr': 3}, 'type mismatch'), ({'EndpointIngressCidr': '10.0.0.1/24'}, 'constraint cidr')])<br>L?: 2 ((1, 2))<br>L?: 動的 (range(1, count + 1))<br>L?: 動的 (before.items()) |
| `integrations/validation_checks/cloudformation.py::check_cloudformation_stack_design` | L40: 2 (('job-01', 'job-02'))<br>L56: 5 ((('<!-- max-concurrent-stacks: 2 -->', '<!-- max-concurrent-stacks: 0 -->'), ('<!-- max-concurrent-stacks: 2 -->', '<!-- max-concurrent-stacks: -1 -->'), ('\| 1 \| 10 \|', '\| 1 \| 0 \|'), ('\| 1 \| 10 \|', '\| 1 \| -1 \|'), ('\| 1 \| 10 \|', '\| 1 \| abc \|')))<br>L63: 7 ((('\| 2 \| 10 \| stack-job-02 \| job.yaml', '\| 2 \| 10 \| stack-job-01 \| job.yaml', 'duplicate stack name'), ('job-02.json', 'job-01.json', 'parameter file belongs to multiple stacks'), ('\| job.yaml \|', '\| ../job.yaml \|', 'invalid stack template filename'), ('\| No. \| Deploy<br>Order \| StackName \| Template \| Parameters \| Comment \|', '\| StackName \| Template \| Parameters \|', 'invalid CloudFormation stack design header'), ('\| 2 \| 10 \| stack-job-02', '\| 3 \| 10 \| stack-job-02', 'No. must be sequential'), ('\| 月次jobを配置するstack \|', '\| \|', 'invalid CloudFormation stack design row'), ('月次jobを配置するstack', 'monthly job', 'stack Comment must describe its purpose in Japanese')))<br>L?: 動的 (errors())<br>L?: 動的 (errors())<br>L?: 動的 (errors()) |
| `integrations/validation_checks/cloudformation.py::check_stack_mapping_targets` | L?: 動的 (errors())<br>L?: 動的 (errors())<br>L?: 動的 (values.items()) |
| `integrations/validation_checks/design.py::check_description_design_constraints` | L87: 3 ((('RoleOne', 'IAM.Role.Description', 'iam.md', iam_text.replace('Application role', '日本語の説明'), sg_text), ('GroupOne', 'EC2.SecurityGroup.GroupDescription', 'security-group.md', iam_text, sg_text.replace('Application access', '日本語の説明')), ('GroupOne', 'EC2.SecurityGroup.GroupDescription', 'security-group.md', iam_text, sg_text.replace('Application access', 'Why?'))))<br>L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors)<br>L?: 4 ((filename, resource, prop, 'must match')) |
| `integrations/validation_checks/references.py::check_identifier_propagation` | L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors) |
| `integrations/validation_checks/references.py::check_array_source_role_links` | L?: 動的 (errors('wrong-role'))<br>L?: 動的 (rows) |
| `integrations/validation_checks/references.py::check_s3_bucket_policy_grouping` | L?: 動的 (errors(wrong_order))<br>L?: 動的 (errors(unset_region))<br>L?: 動的 (errors(literal_alias))<br>L?: 動的 (errors(wrong_alias))<br>L?: 動的 (errors(wrong_heading))<br>L?: 動的 (errors(explicit_bucket))<br>L?: 動的 (errors(separate_heading)) |
| `integrations/validation_checks/references.py::check_subnet_association_overview` | L238: 3 (range(1, 4))<br>L266: 動的 (subnet_rows)<br>L310: 2 (('rtb-00000001', *(f'subnet-{number:08d}' for number in range(1, 4))))<br>L319: 動的 (bad_designs)<br>L?: 3 (range(1, 4))<br>L?: 動的 (validator.errors)<br>L?: 3 (range(1, 4))<br>L?: 動的 (failures) |
| `integrations/validation_checks/references.py::check_resource_overview` | L380: 動的 (invalid_sections)<br>L?: 動的 (errors(valid.replace('\| 1 \| [app-dev-data', '\| 2 \| [app-dev-data', 1)))<br>L?: 動的 (errors(valid.replace('アプリケーションのデータを保管するbucket \|', 'resource \|', 1)))<br>L?: 動的 (errors(valid.replace('アプリケーションのデータを保管するbucket \|', 'バケット（app-dev-data-123456789012）の設定 \|', 1)))<br>L?: 動的 (errors(sg))<br>L?: 動的 (errors(valid.replace('\| No. \| ResourceName \|', '\| ResourceName \|', 1)))<br>L?: 動的 (errors(extra))<br>L?: 動的 (errors(valid.replace('\| ResourceName \|', '\| BucketName \|', 1)))<br>L?: 動的 (errors(missing_row))<br>L?: 動的 (failures) |
| `integrations/validation_checks/runner.py::check_module_inputs` | 1（内部パラメータ化なし） |
| `integrations/validation_checks/scenario.py::check_records` | L30: 動的 (cases) |
| `integrations/validation_checks/scope.py::check_deployment_iac_scope` | L41: 2 (('dev', 'stg'))<br>L46: 2 ((('dev', 'deploy'), ('stg', 'update')))<br>L54: 動的 (values.items())<br>L86: 2 (('dev', 'stg'))<br>L97: 動的 (validator.errors)<br>L100: 動的 (validator.errors)<br>L107: 動的 (validator.errors)<br>L111: 動的 (validator.errors)<br>L114: 動的 (validator.errors) |
| `integrations/validation_checks/task.py::check_task_contract` | L?: 動的 (validator.errors) |
| `integrations/validation_checks/task.py::check_idle_without_active_task` | L?: 動的 (validator.errors) |
| `integrations/validation_checks/task.py::check_destroy_phase` | L143: 16 (('check_structure', 'check_task_scope', 'check_tasks', 'check_project_topology', 'check_validation_scope', 'check_model_files', 'check_issue_gate', 'check_task_type_requirements', 'check_initialized_paths', 'check_catalog', 'check_resource_layout', 'check_scoped_designs', 'check_designs', 'check_observed_values', 'check_acceptance_checks', *banned))<br>L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors)<br>L?: 動的 (validator.errors) |
| `integrations/validation_checks/task.py::check_task_type_dispatch` | L160: 2 ((('vpc', 'EC2.VPC', 'Name'), ('cloudwatch-logs', 'Logs.LogGroup', 'LogGroupName'))) |
| `integrations/validation_checks/task.py::check_task_type_cases` | L180: 動的 (valid.items())<br>L223: 6 (({'model/parameters/dev/cde/cloudwatch-logs/parameters.yaml'}, {'model/templates/cde/cloudwatch-logs.properties.tpl'}, {'model/parameters/dev/cde/cloudwatch-logs/parameters.yaml', 'model/parameters/dev/cde/vpc/parameters.yaml', 'docs/designs/dev/cde/vpc.md'}, {'docs/designs/dev/cde/vpc.md'}, {'docs/designs/dev/cde/iam/role01-policy.json'}, set()))<br>L?: 動的 (validator.errors)<br>L?: 動的 (changed) |
| `integrations/validation_checks/terraform.py::check_cli` | L37: 2 (('dev', 'stg'))<br>L42: 4 ((['fmt'], ['fmt', '-check'], ['init', '-backend=false', '-input=false'], ['validate'])) |
| `integrations/validation_scope.checks.py::check_single_target_cache` | L16: 動的 (services.items())<br>L24: 動的 (enumerate(sorted(model_projection.identifier_outputs(root).get(kind, set())), 2))<br>L32: 2 (['ec2', *services])<br>L90: 動的 (invalid.errors)<br>L31: 動的 (values.items())<br>L35: 動的 (sorted(scope))<br>L37: 動的 (sorted(scope)) |
| `integrations/validation_scope.checks.py::check_template_consumers` | L99: 2 (('dev', 'stg'))<br>L108: 5 (((['--scope', 'dev/team/config', '--scope', 'stg/team/config'], 0), (['--scope', 'dev/team/config'], 1), (['--scope', 'dev/other/config'], 1), (['--scope', '../team/config'], 1), (['--scope', 'dev/team/config', '--all'], 2)))<br>L101: 2 (('dev', 'stg'))<br>L142: 動的 (args)<br>L104: 動的 (sorted(scope)) |
| `integrations/worktree_python.checks.py::check_output_decoding` | L15: 2 (('cp932', 'utf-8'))<br>L17: 動的 ((b'', 'エラー詳細\n'.encode(encoding)))<br>L18: 2 ((0, 7)) |
| `integrations/worktree_python.checks.py::check_setup` | L49: 動的 ((first, second))<br>L87: 動的 ((AttributeError('unexpected setup error'), KeyboardInterrupt()))<br>L100: 4 ((None, 'global', 'venv', 'unknown'))<br>L?: 2 ((OSError('creation failed'), AssertionError('creation failed'))) |
| `integrations/worktree_python.checks.py::check_real_global` | L?: 動的 (commands.call_args_list) |
| `integrations/worktree_python.checks.py::check_venv_fallback` | L173: 2 (('interpreter', 'bin'))<br>L?: 動的 (commands.call_args_list) |
| `integrations/worktree_python.checks.py::check_parallel_fallback` | L?: 動的 (states)<br>L?: 動的 (commands.call_args_list) |
| `integrations/worktree_python.checks.py::check_symlink_safety` | 1（内部パラメータ化なし） |
| `integrations/worktree_task.checks.py::check_success_and_empty` | L15: 2 ((False, True)) |
| `integrations/worktree_task.checks.py::check_finalize_line_endings` | L46: 2 ((b'\n', b'\r\n'))<br>L47: 2 ((False, True))<br>L48: 3 ((b'', b'  ', b'\t')) |
| `integrations/worktree_task.checks.py::check_incomplete_and_git_safety` | L72: 6 (('running', 'suspend', 'unexpected-commit', 'git-conflict', 'missing-python-setup', 'missing-python-status')) |
| `integrations/worktree_task.checks.py::check_dirty_base_and_retry` | 1（内部パラメータ化なし） |
| `integrations/worktree_task.checks.py::check_ahead_and_rebase_conflict` | L131: 2 ((False, True)) |
| `integrations/worktree_task.checks.py::check_collisions_and_base_selection` | L?: 動的 (wt.worktrees(root)) |
| `integrations/worktree_task.checks.py::check_directory_layout` | L202: 動的 ((root / '.other/example', root / '.worktrees/other', root / '.worktrees/example/extra', root / '.git/worktrees/example'))<br>L212: 3 (('setup', 'finalize', 'cleanup')) |
| `integrations/worktree_task.checks.py::check_metadata_storage` | L255: 3 (('.worktrees', '.worktrees/.blueprint', '.worktrees/.blueprint/tasks')) |
| `integrations/worktree_task.checks.py::check_cleanup_failure_and_retry` | 1（内部パラメータ化なし） |
| `integrations/worktree_task.checks.py::check_merge_retry_and_commit_failure` | L308: 2 ((False, True)) |
| `integrations/worktree_task.checks.py::check_human_approved_validation_failure` | L361: 4 (('accepted', 'running', 'git-conflict', 'blank')) |
| `integrations/worktree_task.checks.py::check_real_loop_integration` | L398: 6 (('docs/designs', 'model/parameters', 'model/templates', 'infra', 'tests/scenarios', 'tests/results'))<br>L402: 動的 ((root / 'framework/scripts/tests').rglob('*.checks.py')) |

| `integrations/check-model-aws.checks.py::check_domains` | callback/subdirectory: 9組（services、common、associations、identity-registry、batch、cli、stacks、cfn-identity、coverage） |

## main / module 直接実行シナリオ明細

以下は関数ケース表と別の検証地点台帳。ひとつのシナリオに複数地点があるため、各行を独立テスト件数としては合算しない。元の各地点を同一ASTで対応付ける。コメントに依存せずassert、明示的失敗、Mock/unittest検証を網羅する。

| 元ファイル : 行 / シナリオ | 分類 | 現在の配置 / シナリオ | 検証条件 |
|---|---|---|---|
| `integrations/compact-model-sources.checks.py:36` / `module` | IT | `integrations/compact-model-sources.checks.py:36` | `assert load_model(path).values == desired` |
| `integrations/compact-model-sources.checks.py:38` / `module` | IT | `integrations/compact-model-sources.checks.py:38` | `assert observed in t.input_snapshot(path)` |
| `integrations/compact-model-sources.checks.py:40` / `module` | IT | `integrations/compact-model-sources.checks.py:40` | `assert not any((k.startswith('observed.') for k in t.reference_values(path, '017', 'S3.Bucket', 'identifier').values))` |
| `integrations/compact-model-sources.checks.py:70` / `module` | IT | `integrations/compact-model-sources.checks.py:70` | `assert observed.read_bytes() == original and marker.read_text() == 'before'` |
| `integrations/compact-model-sources.checks.py:73` / `module` | IT | `integrations/compact-model-sources.checks.py:73` | `assert load_model(path).values == desired` |
| `integrations/compact-model-sources.checks.py:76` / `module` | IT | `integrations/compact-model-sources.checks.py:76` | `assert 'labels' not in binding['instances']['fixture']` |
| `integrations/compact-model-sources.checks.py:78` / `module` | IT | `integrations/compact-model-sources.checks.py:78` | `assert load_model(path).values == desired` |
| `integrations/compact-model-sources.checks.py:84` / `module` | IT | `integrations/compact-model-sources.checks.py:84` | `assert load_model(path).values == desired` |
| `integrations/compact-model-sources.checks.py:44` / `module` | IT | `integrations/compact-model-sources.checks.py:44` | `assert values[key] == value and values[key.removesuffix('value') + 'property'] == desired['desired.row.017-023.property']` |
| `integrations/compact-model-sources.checks.py:45` / `module` | IT | `integrations/compact-model-sources.checks.py:45` | `assert values[key.removesuffix('value') + 'comment'] == desired['desired.row.017-023.comment']` |
| `integrations/compact-model-sources.checks.py:51` / `module` | IT | `integrations/compact-model-sources.checks.py:51` | `assert load_model(path).locations[key][0] == observed` |
| `integrations/compact-model-sources.checks.py:53` / `module` | IT | `integrations/compact-model-sources.checks.py:53` | `assert t.json_read(output[observed]) == {'version': 1, 'values': {key: value}}` |
| `integrations/compact-model-sources.checks.py:55` / `module` | IT | `integrations/compact-model-sources.checks.py:55` | `assert t.json_read(observed.read_text())['values'] == {key: value}` |
| `integrations/compact-model-sources.checks.py:49` / `module` | IT | `integrations/compact-model-sources.checks.py:49` | `assert expansion.provenance[metadata]['derivedFrom'] == 'desired.' + metadata.removeprefix('observed.')` |
| `integrations/compact-model-sources.checks.py:50` / `module` | IT | `integrations/compact-model-sources.checks.py:50` | `assert load_model(path).locations[metadata][0].is_relative_to(root / 'model/templates')` |
| `integrations/compact-model-sources.checks.py:104` / `module` | IT | `integrations/compact-model-sources.checks.py:104` | `assert after['desired.resource.017.anchor'] == before[path]['desired.resource.017.anchor']` |
| `integrations/compact-model-sources.checks.py:105` / `module` | IT | `integrations/compact-model-sources.checks.py:105` | `assert set(after) == set(before[path])` |
| `integrations/compact-model-sources.checks.py:106` / `module` | IT | `integrations/compact-model-sources.checks.py:106` | `assert (after != before[path]) == (path.parent.parent.name != 'independent')` |
| `integrations/runtime-model.checks.py:38` / `module` | IT | `integrations/runtime-model.checks.py:38` | `assert model_paths(root) == [path] and model_paths(root, 'prod') == []` |
| `integrations/runtime-model.checks.py:60` / `module` | IT | `integrations/runtime-model.checks.py:58` | `assert design_source_digest(path) != old and affected(root, [yaml.relative_to(root)]) == {('preview', 'team', 'example')}` |
| `integrations/runtime-model.checks.py:63` / `module` | IT | `integrations/runtime-model.checks.py:61` | `assert set(model_paths(root)) == {path, other}` |
| `integrations/runtime-model.checks.py:64` / `module` | IT | `integrations/runtime-model.checks.py:62` | `assert affected(root, [template.relative_to(root)]) == {('preview', 'team', 'example'), ('release', 'team', 'example')}` |
| `integrations/runtime-model.checks.py:65` / `module` | IT | `integrations/runtime-model.checks.py:63` | `assert load_model(other).values == values and design_source_digest(path) != old` |
| `integrations/runtime-model.checks.py:68` / `module` | IT | `integrations/runtime-model.checks.py:66` | `print('Runtime Models: PASS (source discovery; binding-only resources; fixed identities; creation/rerun; missing/corrupt/unknown rejection; input invalidation)')` |
| `integrations/runtime-model.checks.py:43` / `module` | IT | `integrations/runtime-model.checks.py:42` | `assert snapshot_model(path) == before and load_model(path).values == values` |
| `integrations/runtime-model.checks.py:47` / `module` | IT | `integrations/runtime-model.checks.py:45` | `assert model_paths(root) == [path]` |
| `integrations/sync-existing-files.checks.py:25` / `module` | IT | `integrations/sync-existing-files.checks.py:25` | `assert SPEC and SPEC.loader` |
| `integrations/sync-existing-files.checks.py:94` / `main` | IT | `integrations/sync-existing-files.checks.py:93` | `assert result.returncode == 0, result.stderr` |
| `integrations/sync-existing-files.checks.py:95` / `main` | IT | `integrations/sync-existing-files.checks.py:94` | `assert (target / 'framework' / 'scripts' / SCRIPT.name).is_file()` |
| `integrations/sync-existing-files.checks.py:97` / `main` | IT | `integrations/sync-existing-files.checks.py:96` | `assert (target / '.agents/skills/initialize/SKILL.md').read_bytes() == skill.read_bytes()` |
| `integrations/sync-existing-files.checks.py:104` / `main` | IT | `integrations/sync-existing-files.checks.py:103` | `assert preview.returncode == 0, preview.stderr` |
| `integrations/sync-existing-files.checks.py:105` / `main` | IT | `integrations/sync-existing-files.checks.py:104` | `assert 'pending=2' in preview.stdout, preview.stdout` |
| `integrations/sync-existing-files.checks.py:110` / `main` | IT | `integrations/sync-existing-files.checks.py:109` | `assert updated.returncode == 0, updated.stderr` |
| `integrations/sync-existing-files.checks.py:111` / `main` | IT | `integrations/sync-existing-files.checks.py:110` | `assert 'copied=2 added=0 pending=0' in updated.stdout, updated.stdout` |
| `integrations/sync-existing-files.checks.py:115` / `main` | IT | `integrations/sync-existing-files.checks.py:114` | `assert repeated.returncode == 0, repeated.stderr` |
| `integrations/sync-existing-files.checks.py:116` / `main` | IT | `integrations/sync-existing-files.checks.py:115` | `assert 'pending=0' in repeated.stdout, repeated.stdout` |
| `integrations/sync-existing-files.checks.py:117` / `main` | IT | `integrations/sync-existing-files.checks.py:116` | `assert 'scope=framework,.agents,AGENTS.md,README.md' in repeated.stdout` |
| `integrations/sync-existing-files.checks.py:118` / `main` | IT | `integrations/sync-existing-files.checks.py:117` | `assert 'excluded=project.json,docs,infra,model,tasks,tests' in repeated.stdout` |
| `integrations/sync-existing-files.checks.py:100` / `main` | IT | `integrations/sync-existing-files.checks.py:99` | `assert (target / name).read_bytes() == (root / name).read_bytes()` |
| `integrations/sync-existing-files.checks.py:107` / `main` | IT | `integrations/sync-existing-files.checks.py:106` | `assert f'WOULD COPY: {name}' in preview.stdout` |
| `integrations/sync-existing-files.checks.py:108` / `main` | IT | `integrations/sync-existing-files.checks.py:107` | `assert (target / name).read_text(encoding='utf-8') == 'outdated'` |
| `integrations/sync-existing-files.checks.py:113` / `main` | IT | `integrations/sync-existing-files.checks.py:112` | `assert (target / name).read_bytes() == (root / name).read_bytes()` |
| `integrations/sync-existing-files.checks.py:120` / `main` | IT | `integrations/sync-existing-files.checks.py:119` | `assert (target / relative).read_text(encoding='utf-8') == 'target-specific'` |
| `integrations/sync-existing-files.checks.py:122` / `main` | IT | `integrations/sync-existing-files.checks.py:121` | `assert {path.relative_to(target).as_posix() for path in (target / relative.split('/')[0]).rglob('*') if path.is_file()} == {relative}` |
| `units/script_loader.checks.py:38` / `main` | UT | `units/script_loader.checks.py:38` | `assert result.ready` |
| `units/script_loader.checks.py:29` / `main` | UT | `units/script_loader.checks.py:29` | `assert release.wait(5)` |
| `units/script_loader.checks.py:44` / `main` | UT | `units/script_loader.checks.py:44` | `assert started.wait(5)` |
| `units/script_loader.checks.py:51` / `main` | UT | `units/script_loader.checks.py:51` | `assert first.result(timeout=5) is waiting.result(timeout=5)` |
| `units/script_loader.checks.py:52` / `main` | UT | `units/script_loader.checks.py:52` | `assert locate.call_count == 1` |
| `units/script_loader.checks.py:47` / `main` | UT | `units/script_loader.checks.py:47` | `assert entered.wait(5)` |
| `units/script_loader.checks.py:48` / `main` | UT | `units/script_loader.checks.py:48` | `assert not returned.wait(0.1), 'partially initialized module escaped'` |
| `unknown/array_display.checks.py:50` / `main` | UT | `units/array_display.checks.py:50` | `assert restored_rows(shown, 'S3.Bucket') == source` |
| `unknown/array_display.checks.py:52` / `main` | UT | `units/array_display.checks.py:52` | `assert fields[1:5] == ['LifecycleConfiguration.Rules[1].Transitions[1].StorageClass', 'LifecycleConfiguration.Rules[1].Transitions[1].TransitionInDays', 'LifecycleConfiguration.Rules[1].Transitions[2].StorageClass', 'LifecycleConfiguration.Rules[1].Transitions[2].TransitionInDays']` |
| `unknown/array_display.checks.py:53` / `main` | UT | `units/array_display.checks.py:53` | `assert fields[7] == 'LifecycleConfiguration.Rules[2].Transitions[1].StorageClass'` |
| `unknown/array_display.checks.py:54` / `main` | UT | `units/array_display.checks.py:54` | `assert fields[-4:] == ['Tags[1].Key', 'Tags[1].Value', 'Tags[2].Key', 'Tags[2].Value']` |
| `unknown/array_display.checks.py:71` / `main` | UT | `units/array_display.checks.py:71` | `assert [row[1] for row in output] == ['Stages[1].Actions[1].InputArtifacts[1].Name', 'Stages[1].Actions[1].InputArtifacts[2].Name', 'Stages[2].Actions[1].Name']` |
| `unknown/array_display.checks.py:72` / `main` | UT | `units/array_display.checks.py:72` | `assert restored_rows(output, 'CodePipeline.Pipeline') == original` |
| `unknown/array_display.checks.py:75` / `main` | UT | `units/array_display.checks.py:75` | `assert [row[1] for row in output] == ['Tasks[1].Name', 'Tasks[1].Subnets[1]', 'Tasks[1].Subnets[2]', 'Tasks[2].Name', 'Tasks[2].Subnets[1]']` |
| `unknown/array_display.checks.py:76` / `main` | UT | `units/array_display.checks.py:76` | `assert restored_rows(output, 'Example.Resource') == original` |
| `unknown/array_display.checks.py:65` / `main` | UT | `units/array_display.checks.py:65` | `assert len(output) == count and restored_rows(output, 'EC2.Instance') == original` |
| `unknown/array_display.checks.py:83` / `main` | UT | `units/array_display.checks.py:83` | `assert [row[1] for row in output] == expected` |
| `unknown/array_display.checks.py:84` / `main` | UT | `units/array_display.checks.py:84` | `assert restored_rows(output, kind) == original` |
| `unknown/array_display.checks.py:89` / `main` | UT | `units/array_display.checks.py:89` | `assert output[0][1] == expected` |
| `unknown/array_display.checks.py:90` / `main` | UT | `units/array_display.checks.py:84` | `assert restored_rows(output, kind) == original` |
| `unknown/array_display.checks.py:67` / `main` | UT | `units/array_display.checks.py:67` | `assert output[0][1] == 'SecurityGroupIds[1]'` |
| `unknown/array_display.checks.py:107` / `main` | UT | `units/array_display.checks.py:107` | `assert '[]' not in output[0][1] and '[1]' in output[0][1], (kind, prop)` |
| `unknown/array_display.checks.py:108` / `main` | UT | `units/array_display.checks.py:108` | `assert restored_rows(output, kind) == original, (kind, prop)` |
| `unknown/array_display.checks.py:101` / `main` | UT | `units/array_display.checks.py:101` | `assert len(output) == 2 and output[0][1].endswith('[1]') and output[1][1].endswith('[2]'), (kind, prop)` |
| `unknown/array_display.checks.py:102` / `main` | UT | `units/array_display.checks.py:84` | `assert restored_rows(output, kind) == original` |
| `aws-context::main:70` / `main` | UT | `units/check-deploy-context.checks.py:70` | `assert target == {'alias': 'cde', 'awsAccountId': '123456789012', 'awsRegion': 'ap-northeast-1', 'iacEngine': 'terraform'}` |
| `aws-context::main:76` / `main` | UT | `units/check-deploy-context.checks.py:76` | `assert run.call_args.args[0][:3] == ['/mock/aws', '--profile', 'deploy']` |
| `aws-context::main:77` / `main` | UT | `units/check-deploy-context.checks.py:77` | `assert run.call_args.args[0][3:5] == ['--region', 'ap-northeast-1']` |
| `aws-context::main:90` / `main` | UT | `units/check-deploy-context.checks.py:90` | `assert commands == ['aws']` |
| `aws-context::main:91` / `main` | UT | `units/check-deploy-context.checks.py:91` | `assert '--profile' not in run.call_args.args[0]` |
| `aws-context::main:106` / `main` | UT | `units/check-deploy-context.checks.py:106` | `assert commands == ['aws']` |
| `aws-context::main:111` / `main` | UT | `units/check-deploy-context.checks.py:111` | `assert 'topology target must exist exactly once' in str(error)` |
| `aws-context::main:113` / `main` | UT | `units/check-deploy-context.checks.py:113` | `raise AssertionError('aliased target was selected without its alias')` |
| `aws-context::main:126` / `main` | UT | `units/check-deploy-context.checks.py:126` | `assert target['awsProfile'] == 'stg-cde'` |
| `aws-context::main:127` / `main` | UT | `units/check-deploy-context.checks.py:127` | `assert run.call_args.args[0][:3] == ['/mock/aws', '--profile', 'stg-cde']` |
| `aws-context::main:134` / `main` | UT | `units/check-deploy-context.checks.py:134` | `assert error is failure` |
| `aws-context::main:136` / `main` | UT | `units/check-deploy-context.checks.py:136` | `raise AssertionError('identity rejection ignored')` |
| `aws-context::main:143` / `main` | UT | `units/check-deploy-context.checks.py:143` | `assert 'profile not found' in str(error)` |
| `aws-context::main:145` / `main` | UT | `units/check-deploy-context.checks.py:145` | `raise AssertionError('failed configured profile was accepted')` |
| `aws-context::main:146` / `main` | UT | `units/check-deploy-context.checks.py:146` | `assert run.call_count == 1` |
| `aws-context::main:147` / `main` | UT | `units/check-deploy-context.checks.py:147` | `assert run.call_args.args[0][2] == 'stg-cde'` |
| `aws-context::main:158` / `main` | UT | `units/check-deploy-context.checks.py:158` | `assert target['awsAccountId'] == '123456789012'` |
| `aws-context::main:159` / `main` | UT | `units/check-deploy-context.checks.py:159` | `assert target['awsExecutionAccountId'] == '999999999999'` |
| `aws-context::main:164` / `main` | UT | `units/check-deploy-context.checks.py:164` | `assert error is failure` |
| `aws-context::main:166` / `main` | UT | `units/check-deploy-context.checks.py:166` | `raise AssertionError('STS identity rejection ignored')` |
| `aws-context::main:169` / `main` | UT | `units/check-deploy-context.checks.py:169` | `assert MODULE.load_target(root, 'production', account_id='210987654321')['awsAccountId'] == '210987654321'` |
| `aws-context::main:175` / `main` | UT | `units/check-deploy-context.checks.py:175` | `assert 'AWS region ID is invalid' in str(error)` |
| `aws-context::main:177` / `main` | UT | `units/check-deploy-context.checks.py:177` | `raise AssertionError('invalid AWS region ID was accepted')` |
| `aws-context::main:182` / `main` | UT | `units/check-deploy-context.checks.py:182` | `assert MODULE.main() == 1` |
| `aws-context::main:183` / `main` | UT | `units/check-deploy-context.checks.py:183` | `assert 'Deploy context: FAIL: identity rejected' in errors.getvalue()` |
| `unknown/cloudformation_schema.checks.py:21` / `main` | UT | `units/cloudformation_schema.checks.py:21` | `assert snapshot_errors(root) == []` |
| `unknown/cloudformation_schema.checks.py:40` / `main` | UT | `units/cloudformation_schema.checks.py:40` | `assert catalog.literal_errors('EC2.SecurityGroup', 'Tags[].Value', '日本語') == []` |
| `unknown/cloudformation_schema.checks.py:41` / `main` | UT | `units/cloudformation_schema.checks.py:41` | `assert catalog.literal_errors('EC2.SecurityGroupIngress', 'Description', '日本語') == []` |
| `unknown/cloudformation_schema.checks.py:43` / `main` | UT | `units/cloudformation_schema.checks.py:43` | `assert catalog.property_schema('Events.Rule', 'EventPattern')['type'] == ['string', 'object']` |
| `unknown/cloudformation_schema.checks.py:69` / `main` | UT | `units/cloudformation_schema.checks.py:69` | `assert 'BearerTokenAuthenticationEnabled' in logs['properties']` |
| `unknown/cloudformation_schema.checks.py:70` / `main` | UT | `units/cloudformation_schema.checks.py:70` | `assert catalog.literal_errors('Logs.LogGroup', 'KmsKeyId', 'arn:aws:kms:ap-northeast-1:123456789012:key/11111111-2222-3333-4444-555555555555') == []` |
| `unknown/cloudformation_schema.checks.py:75` / `main` | UT | `units/cloudformation_schema.checks.py:75` | `assert catalog.literal_errors('Logs.LogGroup', 'KmsKeyId', 'not-used')` |
| `unknown/cloudformation_schema.checks.py:76` / `main` | UT | `units/cloudformation_schema.checks.py:76` | `assert catalog.literal_errors('Logs.LogGroup', 'RetentionInDays', '30') == []` |
| `unknown/cloudformation_schema.checks.py:77` / `main` | UT | `units/cloudformation_schema.checks.py:77` | `assert catalog.literal_errors('Logs.LogGroup', 'RetentionInDays', '31')` |
| `unknown/cloudformation_schema.checks.py:85` / `main` | UT | `units/cloudformation_schema.checks.py:85` | `assert catalog.required_properties('Athena.WorkGroup') == {'Name'}` |
| `unknown/cloudformation_schema.checks.py:86` / `main` | UT | `units/cloudformation_schema.checks.py:86` | `assert catalog.literal_errors('Athena.WorkGroup', 'State', 'ENABLED') == []` |
| `unknown/cloudformation_schema.checks.py:87` / `main` | UT | `units/cloudformation_schema.checks.py:87` | `assert catalog.literal_errors('Athena.WorkGroup', 'State', 'unexpected')` |
| `unknown/cloudformation_schema.checks.py:88` / `main` | UT | `units/cloudformation_schema.checks.py:88` | `assert catalog.property_schema('DynamoDB.Table', 'KeySchema[].AttributeName')['type'] == 'string'` |
| `unknown/cloudformation_schema.checks.py:127` / `main` | UT | `units/cloudformation_schema.checks.py:127` | `assert catalog.property_schema('IAM.User', 'UserName')['type'] == 'string'` |
| `unknown/cloudformation_schema.checks.py:128` / `main` | UT | `units/cloudformation_schema.checks.py:128` | `assert catalog.property_schema('IAM.User', 'LoginProfile.PasswordResetRequired')['type'] == 'boolean'` |
| `unknown/cloudformation_schema.checks.py:129` / `main` | UT | `units/cloudformation_schema.checks.py:129` | `assert 'object' in catalog.property_schema('IAM.User', 'Policies[].PolicyDocument')['type']` |
| `unknown/cloudformation_schema.checks.py:130` / `main` | UT | `units/cloudformation_schema.checks.py:130` | `assert catalog.required_properties('GuardDuty.MalwareProtectionPlan') == {'ProtectedResource', 'Role'}` |
| `unknown/cloudformation_schema.checks.py:131` / `main` | UT | `units/cloudformation_schema.checks.py:131` | `assert 'GuardDuty.MalwareProtectionPlan.MalwareProtectionPlanId=IDENTIFIER_OUTPUT' in (materials / 'GuardDuty_MalwareProtectionPlan.properties').read_text(encoding='utf-8').splitlines()` |
| `unknown/cloudformation_schema.checks.py:134` / `main` | UT | `units/cloudformation_schema.checks.py:134` | `assert catalog.property_schema('GuardDuty.MalwareProtectionPlan', 'MalwareProtectionPlanId')['type'] == 'string'` |
| `unknown/cloudformation_schema.checks.py:135` / `main` | UT | `units/cloudformation_schema.checks.py:135` | `assert catalog.schema('GuardDuty.MalwareProtectionPlan')['primaryIdentifier'] == ['/properties/MalwareProtectionPlanId']` |
| `unknown/cloudformation_schema.checks.py:138` / `main` | UT | `units/cloudformation_schema.checks.py:138` | `assert catalog.literal_errors('GuardDuty.MalwareProtectionPlan', 'Actions.Tagging.Status', 'ENABLED') == []` |
| `unknown/cloudformation_schema.checks.py:140` / `main` | UT | `units/cloudformation_schema.checks.py:140` | `assert 'EC2.EIP.AllocationId=IDENTIFIER_OUTPUT' in eip` |
| `unknown/cloudformation_schema.checks.py:141` / `main` | UT | `units/cloudformation_schema.checks.py:141` | `assert 'EC2.EIP.PublicIp=IDENTIFIER_OUTPUT' in eip` |
| `unknown/cloudformation_schema.checks.py:142` / `main` | UT | `units/cloudformation_schema.checks.py:142` | `assert 'Glue.Database.DatabaseName=' in (materials / 'Glue_Database.properties').read_text(encoding='utf-8')` |
| `unknown/cloudformation_schema.checks.py:145` / `main` | UT | `units/cloudformation_schema.checks.py:145` | `assert 'SNS.Topic.TopicArn' not in (materials / 'SNS_Topic.properties').read_text(encoding='utf-8')` |
| `unknown/cloudformation_schema.checks.py:160` / `main` | UT | `units/cloudformation_schema.checks.py:160` | `assert 'LakeFormation.PrincipalPermissions.PrincipalIdentifier=IDENTIFIER_OUTPUT' in lake` |
| `unknown/cloudformation_schema.checks.py:161` / `main` | UT | `units/cloudformation_schema.checks.py:161` | `assert 'LakeFormation.PrincipalPermissions.ResourceIdentifier=IDENTIFIER_OUTPUT' in lake` |
| `unknown/cloudformation_schema.checks.py:170` / `main` | UT | `units/cloudformation_schema.checks.py:170` | `assert len(scheduler) == 43` |
| `unknown/cloudformation_schema.checks.py:171` / `main` | UT | `units/cloudformation_schema.checks.py:171` | `assert 'Scheduler.Schedule.Arn=' not in scheduler` |
| `unknown/cloudformation_schema.checks.py:172` / `main` | UT | `units/cloudformation_schema.checks.py:172` | `assert DesignSchemaCatalog(root).cloudformation_type('Scheduler.Schedule') == 'AWS::Scheduler::Schedule'` |
| `unknown/cloudformation_schema.checks.py:173` / `main` | UT | `units/cloudformation_schema.checks.py:173` | `assert catalog.required_properties('Scheduler.Schedule') == {'FlexibleTimeWindow', 'ScheduleExpression', 'Target'}` |
| `unknown/cloudformation_schema.checks.py:182` / `main` | UT | `units/cloudformation_schema.checks.py:182` | `assert catalog.literal_errors('Scheduler.Schedule', 'FlexibleTimeWindow.Mode', 'OFF') == []` |
| `unknown/cloudformation_schema.checks.py:183` / `main` | UT | `units/cloudformation_schema.checks.py:183` | `assert catalog.literal_errors('Scheduler.Schedule', 'FlexibleTimeWindow.Mode', 'WRONG')` |
| `unknown/cloudformation_schema.checks.py:214` / `main` | UT | `units/cloudformation_schema.checks.py:214` | `assert catalog.literal_errors('SSM.MaintenanceWindowTask', 'TaskType', 'RUN_COMMAND') == []` |
| `unknown/cloudformation_schema.checks.py:215` / `main` | UT | `units/cloudformation_schema.checks.py:215` | `assert catalog.literal_errors('Config.ConfigRule', 'Source.Owner', 'AWS') == []` |
| `unknown/cloudformation_schema.checks.py:216` / `main` | UT | `units/cloudformation_schema.checks.py:216` | `assert resource_name_fields('SSM.Association') == ['AssociationName']` |
| `unknown/cloudformation_schema.checks.py:219` / `main` | UT | `units/cloudformation_schema.checks.py:219` | `assert resource_display_name('SSM.Association', rows) == 'patch-scan'` |
| `unknown/cloudformation_schema.checks.py:220` / `main` | UT | `units/cloudformation_schema.checks.py:220` | `assert resource_display_name('SSM.Association', rows[:1]) is None` |
| `unknown/cloudformation_schema.checks.py:32` / `main` | UT | `units/cloudformation_schema.checks.py:32` | `assert catalog.property_schema(resource_type, property_path)['type'] == 'string'` |
| `unknown/cloudformation_schema.checks.py:50` / `main` | UT | `units/cloudformation_schema.checks.py:50` | `assert catalog.literal_errors(resource_type, property_path, 'not-used')` |
| `unknown/cloudformation_schema.checks.py:83` / `main` | UT | `units/cloudformation_schema.checks.py:83` | `raise AssertionError('non-schema Logs.LogGroup.Encryption was accepted')` |
| `unknown/cloudformation_schema.checks.py:180` / `main` | UT | `units/cloudformation_schema.checks.py:180` | `assert f'Scheduler.Schedule.{path}=' in scheduler` |
| `unknown/cloudformation_schema.checks.py:181` / `main` | UT | `units/cloudformation_schema.checks.py:181` | `assert catalog.property_schema('Scheduler.Schedule', path)` |
| `unknown/cloudformation_schema.checks.py:197` / `main` | UT | `units/cloudformation_schema.checks.py:197` | `assert DesignSchemaCatalog(root).cloudformation_type(kind) == 'AWS::' + kind.replace('.', '::', 1)` |
| `unknown/cloudformation_schema.checks.py:198` / `main` | UT | `units/cloudformation_schema.checks.py:198` | `assert LAYOUTS[kind] == 'independent'` |
| `unknown/cloudformation_schema.checks.py:204` / `main` | UT | `units/cloudformation_schema.checks.py:204` | `assert all((not line.partition('=')[0].split('.')[-1].lower().endswith('arn') for line in lines if line.endswith('=IDENTIFIER_OUTPUT')))` |
| `unknown/cloudformation_schema.checks.py:212` / `main` | UT | `units/cloudformation_schema.checks.py:212` | `assert catalog.literal_errors(kind, prop, value) == [], (kind, prop)` |
| `unknown/cloudformation_schema.checks.py:213` / `main` | UT | `units/cloudformation_schema.checks.py:213` | `assert catalog.literal_errors(kind, prop, 'INVALID_ENUM'), (kind, prop)` |
| `unknown/cloudformation_schema.checks.py:49` / `main` | UT | `units/cloudformation_schema.checks.py:49` | `assert catalog.literal_errors(resource_type, property_path, raw_value) == []` |
| `unknown/cloudformation_schema.checks.py:64` / `main` | UT | `units/cloudformation_schema.checks.py:64` | `assert catalog.literal_errors('Test.Union', 'Value', raw_value) == [], (node, raw_value)` |
| `unknown/cloudformation_schema.checks.py:66` / `main` | UT | `units/cloudformation_schema.checks.py:66` | `assert catalog.literal_errors('Test.Union', 'Value', raw_value), (node, raw_value)` |
| `unknown/cloudformation_schema.checks.py:122` / `main` | UT | `units/cloudformation_schema.checks.py:122` | `assert f'{resource_type}.{property_path}=' in lines, property_path` |
| `unknown/cloudformation_schema.checks.py:124` / `main` | UT | `units/cloudformation_schema.checks.py:124` | `assert 'type' in node` |
| `unknown/cloudformation_schema.checks.py:157` / `main` | UT | `units/cloudformation_schema.checks.py:157` | `assert f'{resource_type}.{path}=' in lines, path` |
| `unknown/cloudformation_schema.checks.py:158` / `main` | UT | `units/cloudformation_schema.checks.py:158` | `assert catalog.property_schema(resource_type, path)` |
| `unknown/cloudformation_schema.checks.py:168` / `main` | UT | `units/cloudformation_schema.checks.py:168` | `raise AssertionError(f'unsupported Athena.WorkGroup path: {path}')` |
| `unknown/cloudformation_schema.checks.py:202` / `main` | UT | `units/cloudformation_schema.checks.py:202` | `assert f'{kind}.{path}' in selected, (kind, path)` |
| `unknown/cloudformation_schema.checks.py:203` / `main` | UT | `units/cloudformation_schema.checks.py:203` | `assert catalog.property_schema(kind, path)` |
| `unknown/cloudformation_schema.checks.py:35` / `main` | UT | `units/cloudformation_schema.checks.py:35` | `assert catalog.literal_errors(spelling, property_path, value) == [], (spelling, value)` |
| `unknown/cloudformation_schema.checks.py:38` / `main` | UT | `units/cloudformation_schema.checks.py:38` | `assert any(('must match' in error for error in errors)), (spelling, value, errors)` |
| `unknown/cloudformation_schema.checks.py:126` / `main` | UT | `units/cloudformation_schema.checks.py:126` | `assert node['type'] == 'string'` |
| `unknown/comparison_core.checks.py:39` / `module` | UT | `units/comparison_core-unit.checks.py:39` | `assert projected == trail_expected, projected` |
| `unknown/comparison_core.checks.py:40` / `module` | UT | `units/comparison_core-unit.checks.py:40` | `assert all((row['property'] == trail_kind + prop for (_, row), (prop, _) in zip(trail_rows, trail_fields)))` |
| `unknown/comparison_core.checks.py:49` / `module` | UT | `units/comparison_core-unit.checks.py:49` | `raise AssertionError('unproven CloudTrail membership accepted')` |
| `unknown/comparison_core.checks.py:47` / `module` | UT | `units/comparison_core-unit.checks.py:47` | `assert 'array membership unresolved' in str(error)` |
| `unknown/comparison_core.checks.py:62` / `module` | UT | `units/comparison_core-unit.checks.py:62` | `assert tree == expected, (rows, tree)` |
| `unknown/comparison_core.checks.py:85` / `module` | UT | `units/comparison_core-unit.checks.py:85` | `assert tree == {'Stages': stages}, tree` |
| `unknown/comparison_core.checks.py:94` / `module` | UT | `units/comparison_core-unit.checks.py:94` | `raise AssertionError('ambiguous membership accepted: ' + path)` |
| `unknown/comparison_core.checks.py:91` / `module` | UT | `units/comparison_core-unit.checks.py:91` | `assert path in str(error)` |
| `unknown/comparison_core.checks.py:92` / `module` | UT | `units/comparison_core-unit.checks.py:92` | `assert tree == {'Existing': 1}, 'unresolved rows must not partially mutate the tree'` |
| `unknown/comparison_core.checks.py:99` / `module` | UT | `units/comparison_core-unit.checks.py:99` | `assert same(left, right) is False` |
| `unknown/comparison_core.checks.py:100` / `module` | UT | `units/comparison_core-unit.checks.py:100` | `assert same(None, None) is True and same({}, {}) is True and (same([], []) is True)` |
| `unknown/comparison_core.checks.py:101` / `module` | UT | `units/comparison_core-unit.checks.py:101` | `assert comparison_result([None, False]) is False and comparison_result([None, True]) is None` |
| `unknown/comparison_core.checks.py:102` / `module` | UT | `units/comparison_core-unit.checks.py:102` | `assert comparison_result([None, True], any_match=True) is True` |
| `unknown/comparison_core.checks.py:103` / `module` | UT | `units/comparison_core-unit.checks.py:103` | `assert selected_same({'a': 1}, {'a': 1, 'b': 2}) is True` |
| `unknown/comparison_core.checks.py:105` / `module` | UT | `units/comparison_core-unit.checks.py:105` | `assert same(ref, dict(ref)) is False and same(ref, ResourceReference(ref)) is True` |
| `unknown/comparison_core.checks.py:107` / `module` | UT | `units/comparison_core-unit.checks.py:107` | `assert same(expression, safe_value(expression)) is False` |
| `unknown/comparison_core.checks.py:108` / `module` | UT | `units/comparison_core-unit.checks.py:108` | `assert safe_value({'Password': 'one', 'Arn': 'arn:aws:s3:::private'}) == {'Password': '<masked>', 'Arn': '<masked ARN/secret>'}` |
| `unknown/comparison_core.checks.py:150` / `module` | UT | `units/comparison_core-unit.checks.py:150` | `assert same(evaluate(chain), expected)` |
| `unknown/comparison_core.checks.py:151` / `module` | UT | `units/comparison_core-unit.checks.py:151` | `assert same(evaluate(chain), evaluate(select('0', split)))` |
| `unknown/comparison_core.checks.py:152` / `module` | UT | `units/comparison_core-unit.checks.py:152` | `assert evaluator.string_operand(evaluate(first))` |
| `unknown/comparison_core.checks.py:153` / `module` | UT | `units/comparison_core-unit.checks.py:153` | `assert not same(evaluate(chain), safe_value(expected))` |
| `unknown/comparison_core.checks.py:154` / `module` | UT | `units/comparison_core-unit.checks.py:154` | `assert not same(evaluate(chain), evaluate(select(0, {'Fn::Split': [',', first]})))` |
| `unknown/comparison_core.checks.py:155` / `module` | UT | `units/comparison_core-unit.checks.py:155` | `assert evaluator.string_operand(evaluate(select(0, getatt('Numbers')))) is False` |
| `unknown/comparison_core.checks.py:156` / `module` | UT | `units/comparison_core-unit.checks.py:156` | `assert evaluate(select(1, ['a', 'b'])) == 'b'` |
| `unknown/comparison_core.checks.py:157` / `module` | UT | `units/comparison_core-unit.checks.py:157` | `assert evaluate(select(1, {'Fn::Split': [':', 'zone:dns']})) == 'dns'` |
| `unknown/comparison_core.checks.py:158` / `module` | UT | `units/comparison_core-unit.checks.py:158` | `assert evaluate({'Fn::Split': [':', '']}) == ['']` |
| `unknown/comparison_core.checks.py:180` / `module` | UT | `units/comparison_core-unit.checks.py:157` | `assert evaluate(select(1, {'Fn::Split': [':', 'zone:dns']})) == 'dns'` |
| `unknown/design_catalog.checks.py:138` / `main` | UT | `units/design_catalog-unit.checks.py:12` | `assert not api_snapshot_errors(ROOT)` |
| `unknown/design_catalog.checks.py:140` / `main` | UT | `units/design_catalog-unit.checks.py:14` | `assert catalog.cloudformation_type('Macie.Session') == 'AWS::Macie::Session'` |
| `unknown/design_catalog.checks.py:142` / `main` | UT | `units/design_catalog-unit.checks.py:16` | `assert group['identityProperties'] == ['AwsAccountId', 'Namespace', 'GroupName']` |
| `unknown/design_catalog.checks.py:143` / `main` | UT | `units/design_catalog-unit.checks.py:17` | `assert group['identifierOutputs'] == ['Arn', 'PrincipalId']` |
| `unknown/design_catalog.checks.py:144` / `main` | UT | `units/design_catalog-unit.checks.py:18` | `assert group['source']['readOperations'] == ['ListGroups', 'DescribeGroup']` |
| `unknown/design_catalog.checks.py:145` / `main` | UT | `units/design_catalog-unit.checks.py:19` | `assert group['source']['updateOperation'] == 'UpdateGroup'` |
| `unknown/design_catalog.checks.py:146` / `main` | UT | `units/design_catalog-unit.checks.py:20` | `assert group['source']['deleteOperation'] == 'DeleteGroup'` |
| `unknown/design_catalog.checks.py:147` / `main` | UT | `units/design_catalog-unit.checks.py:21` | `assert catalog.required_design_properties(QUICKSIGHT_GROUP) == {'AwsAccountId', 'Namespace', 'GroupName'}` |
| `unknown/design_catalog.checks.py:160` / `main` | UT | `units/design_catalog-unit.checks.py:34` | `raise AssertionError('API design leaked into the CFn catalog')` |
| `unknown/design_catalog.checks.py:164` / `main` | IT | `integrations/issues_api_only.checks.py:46` | `assert result.returncode == 1 and 'CloudFormation unsupported' in result.stdout` |
| `unknown/design_catalog.checks.py:154` / `main` | UT | `units/design_catalog-unit.checks.py:28` | `raise AssertionError(f'unsupported CFn type accepted: {resource_type}')` |
| `unknown/export-design-pdf.checks.py:22` / `module` | IT | `integrations/export-design-pdf.checks.py:22` | `assert SPEC and SPEC.loader` |
| `unknown/export-design-pdf.checks.py:77` / `main` | IT | `integrations/export-design-pdf.checks.py:77` | `assert expected == {'dev-cde-vpc-a': 2, 'dev-cde-iam-role': 2, 'dev-cde-iam-role-two': 1, 'dev-cde-iam-policy': 1, 'appendix-dev-cde-vpc-policy': 2, 'stg-non-cde-vpc-a': 2}, expected` |
| `unknown/export-design-pdf.checks.py:85` / `main` | IT | `integrations/export-design-pdf.checks.py:85` | `assert '[Role](#dev-cde-iam-role)' in merged` |
| `unknown/export-design-pdf.checks.py:86` / `main` | IT | `integrations/export-design-pdf.checks.py:86` | `assert '[A](#dev-cde-vpc-a)' in merged` |
| `unknown/export-design-pdf.checks.py:87` / `main` | IT | `integrations/export-design-pdf.checks.py:87` | `assert '[A](#stg-non-cde-vpc-a)' in merged` |
| `unknown/export-design-pdf.checks.py:88` / `main` | IT | `integrations/export-design-pdf.checks.py:88` | `assert merged.count('{#appendix-dev-cde-vpc-policy}') == 1` |
| `unknown/export-design-pdf.checks.py:89` / `main` | IT | `integrations/export-design-pdf.checks.py:89` | `assert merged.count('](#appendix-dev-cde-vpc-policy)') == 2` |
| `unknown/export-design-pdf.checks.py:90` / `main` | IT | `integrations/export-design-pdf.checks.py:90` | `assert '[example](missing.md#example)' in merged` |
| `unknown/export-design-pdf.checks.py:91` / `main` | IT | `integrations/export-design-pdf.checks.py:91` | `assert '# 詳細設計書' not in merged` |
| `unknown/export-design-pdf.checks.py:92` / `main` | IT | `integrations/export-design-pdf.checks.py:92` | `assert '# dev / cde {#target-dev-cde .target-title .first-target}' in merged` |
| `unknown/export-design-pdf.checks.py:93` / `main` | IT | `integrations/export-design-pdf.checks.py:93` | `assert '# stg / non-cde {#target-stg-non-cde .target-title}' in merged` |
| `unknown/export-design-pdf.checks.py:94` / `main` | IT | `integrations/export-design-pdf.checks.py:94` | `assert '## IAM 詳細設計 {#service-dev-cde-iam .service-title .first-service}' in merged` |
| `unknown/export-design-pdf.checks.py:95` / `main` | IT | `integrations/export-design-pdf.checks.py:95` | `assert '## VPC 詳細設計 {#service-dev-cde-vpc .service-title}' in merged` |
| `unknown/export-design-pdf.checks.py:96` / `main` | IT | `integrations/export-design-pdf.checks.py:96` | `assert '## VPC 詳細設計 {#service-stg-non-cde-vpc .service-title .first-service}' in merged` |
| `unknown/export-design-pdf.checks.py:97` / `main` | IT | `integrations/export-design-pdf.checks.py:97` | `assert '\| No. \| Role \|\n\| ---: \| --- \|\n\| 1 \| [Role](#dev-cde-iam-role) \|\n\| 2 \| [RoleTwo](#dev-cde-iam-role-two) \|' in merged` |
| `unknown/export-design-pdf.checks.py:98` / `main` | IT | `integrations/export-design-pdf.checks.py:98` | `assert '\| No. \| Policy \|\n\| ---: \| --- \|\n\| 1 \| [Policy](#dev-cde-iam-policy) \|' in merged` |
| `unknown/export-design-pdf.checks.py:99` / `main` | IT | `integrations/export-design-pdf.checks.py:99` | `assert '\| No. \| Property \|\n\| ---: \| --- \|\n\| 1 \| RoleName \|' in merged` |
| `unknown/export-design-pdf.checks.py:100` / `main` | IT | `integrations/export-design-pdf.checks.py:100` | `assert '<a id="dev-cde-vpc-a"></a>\n\n#### EC2.VPC: A' in merged` |
| `unknown/export-design-pdf.checks.py:114` / `main` | IT | `integrations/export-design-pdf.checks.py:114` | `assert run.call_count == 1 and run.call_args.args[0] == ['weasyprint', '--info']` |
| `unknown/export-design-pdf.checks.py:115` / `main` | IT | `integrations/export-design-pdf.checks.py:115` | `assert output.read_bytes() == b'existing PDF'` |
| `unknown/export-design-pdf.checks.py:113` / `main` | IT | `integrations/export-design-pdf.checks.py:113` | `raise AssertionError('missing native libraries must stop PDF export')` |
| `unknown/export-design-pdf.checks.py:111` / `main` | IT | `integrations/export-design-pdf.checks.py:111` | `assert 'README.md#pdf-dependencies' in str(error) and missing_native in str(error)` |
| `unknown/glue_datazone_catalog.checks.py:102` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:12` | `assert snapshot_errors(ROOT) == []` |
| `unknown/glue_datazone_catalog.checks.py:111` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:21` | `assert catalog.required_properties('Glue.Catalog') == {'Name'}` |
| `unknown/glue_datazone_catalog.checks.py:112` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:22` | `assert catalog.required_properties('DataZone.Domain') == {'Name'}` |
| `unknown/glue_datazone_catalog.checks.py:113` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:23` | `assert catalog.required_properties('DataZone.Project') == {'DomainIdentifier', 'Name'}` |
| `unknown/glue_datazone_catalog.checks.py:114` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:24` | `assert catalog.required_properties('DataZone.DataSource') == {'DomainIdentifier', 'Name', 'ProjectIdentifier', 'Type'}` |
| `unknown/glue_datazone_catalog.checks.py:120` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:30` | `assert catalog.literal_errors('DataZone.Domain', 'DomainVersion', 'V2') == []` |
| `unknown/glue_datazone_catalog.checks.py:121` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:31` | `assert catalog.literal_errors('DataZone.DataSource', 'Type', 'GLUE') == []` |
| `unknown/glue_datazone_catalog.checks.py:110` / `main` | UT | `units/glue_datazone_catalog-unit.checks.py:20` | `assert catalog.schema(resource_type)['typeName'] == 'AWS::' + resource_type.replace('.', '::', 1)` |
| `unknown/glue_datazone_catalog.checks.py:130` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:19` | `assert CatalogId current value in Glue view` |
| `unknown/glue_datazone_catalog.checks.py:131` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:20` | `assert acquired Glue Catalog link in DataZone view` |
| `unknown/glue_datazone_catalog.checks.py:132` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:21` | `assert 'desired.resource.001.resourceType=Glue.Catalog' in glue_model` |
| `unknown/glue_datazone_catalog.checks.py:133` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:22` | `assert 'desired.row.001-001.value=[FederatedCatalog](#glue-federatedcatalog)' in glue_model` |
| `unknown/glue_datazone_catalog.checks.py:134` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:23` | `assert 'observed.row.001-001.value=PENDING_DEPLOY' in glue_model` |
| `unknown/glue_datazone_catalog.checks.py:135` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:24` | `assert 'desired.service.datazone.ownedCatalogResourceTypes=DataZone.Domain,DataZone.Project,DataZone.DataSource' in datazone_model` |
| `unknown/glue_datazone_catalog.checks.py:136` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:25` | `assert 'desired.resource.003.resourceType=DataZone.DataSource' in datazone_model` |
| `unknown/glue_datazone_catalog.checks.py:137` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:26` | `assert 'desired.row.003-003.value=[FederatedCatalog](glue.md#glue-federatedcatalog)' in datazone_model` |
| `unknown/glue_datazone_catalog.checks.py:138` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:27` | `assert 'observed.row.003-003.value=federated-catalog' in datazone_model` |
| `unknown/glue_datazone_catalog.checks.py:139` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:28` | `assert 'desired.row.003-007.value=GLUE' in datazone_model` |
| `unknown/glue_datazone_catalog.checks.py:152` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:41` | `assert original == {path: path.read_bytes() for path in (glue, datazone)}` |
| `unknown/glue_datazone_catalog.checks.py:151` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:40` | `raise AssertionError('legacy model with internal-ID headings was silently adopted')` |
| `unknown/glue_datazone_catalog.checks.py:149` / `main` | IT | `integrations/glue_datazone_catalog.checks.py:38` | `assert 'anchor must be unique and match its name' in str(error)` |
| `unknown/issue_gate.checks.py:27` / `main` | UT | `units/issue_gate-unit.checks.py:15` | `assert not issue_errors(root, scope)` |
| `unknown/issue_gate.checks.py:32` / `main` | UT | `units/issue_gate-unit.checks.py:20` | `assert len(issue_errors(root, scope)) == 1` |
| `unknown/issue_gate.checks.py:33` / `main` | UT | `units/issue_gate-unit.checks.py:21` | `assert not issue_errors(root, {('prod', 'cde', 'ec2')})` |
| `unknown/issue_gate.checks.py:34` / `main` | UT | `units/issue_gate-unit.checks.py:22` | `assert not issue_errors(root, {('dev', 'non-cde', 'ec2')})` |
| `unknown/issue_gate.checks.py:35` / `main` | UT | `units/issue_gate-unit.checks.py:23` | `assert not issue_errors(root, {('dev', 'cde', 's3')})` |
| `unknown/issue_gate.checks.py:36` / `main` | UT | `units/issue_gate-unit.checks.py:24` | `assert not issue_errors(root, set())` |
| `unknown/issue_gate.checks.py:37` / `main` | UT | `units/issue_gate-unit.checks.py:25` | `assert issue_errors(root, None)` |
| `unknown/issue_gate.checks.py:39` / `main` | UT | `units/issue_gate-unit.checks.py:27` | `assert len(issue_errors(root, scope)) == 2` |
| `unknown/issue_gate.checks.py:41` / `main` | UT | `units/issue_gate-unit.checks.py:29` | `assert issue_errors(root, scope)` |
| `unknown/issue_gate.checks.py:42` / `main` | UT | `units/issue_gate-unit.checks.py:23` | `assert not issue_errors(root, {('dev', 'cde', 's3')})` |
| `unknown/issue_gate.checks.py:44` / `main` | UT | `units/issue_gate-unit.checks.py:32` | `assert 'ambiguous' in issue_errors(root, {('dev', 'cde', 's3')})[0]` |
| `unknown/issue_gate.checks.py:45` / `main` | UT | `units/issue_gate-unit.checks.py:33` | `assert issue_errors(root, scope, remediation=scope)` |
| `unknown/issue_gate.checks.py:47` / `main` | UT | `units/issue_gate-unit.checks.py:29` | `assert issue_errors(root, scope)` |
| `unknown/issue_gate.checks.py:49` / `main` | UT | `units/issue_gate-unit.checks.py:15` | `assert not issue_errors(root, scope)` |
| `unknown/issue_gate.checks.py:51` / `main` | UT | `units/issue_gate-unit.checks.py:15` | `assert not issue_errors(root, scope)` |
| `unknown/issue_gate.checks.py:53` / `main` | UT | `units/issue_gate-unit.checks.py:15` | `assert not issue_errors(root, scope)` |
| `unknown/issue_gate.checks.py:58` / `main` | UT | `units/issue_gate-unit.checks.py:29` | `assert issue_errors(root, scope)` |
| `unknown/issue_gate.checks.py:59` / `main` | UT | `units/issue_gate-unit.checks.py:23` | `assert not issue_errors(root, {('dev', 'cde', 's3')})` |
| `unknown/issue_gate.checks.py:72` / `main` | IT | `integrations/issue_gate.checks.py:32` | `assert instance.errors` |
| `unknown/issue_gate.checks.py:77` / `main` | IT | `integrations/issue_gate.checks.py:37` | `assert not instance.errors` |
| `unknown/issue_gate.checks.py:117` / `main` | IT | `integrations/issue_gate.checks.py:32` | `assert instance.errors` |
| `unknown/issue_gate.checks.py:122` / `main` | IT | `integrations/issue_gate.checks.py:32` | `assert instance.errors` |
| `unknown/issue_gate.checks.py:126` / `main` | IT | `integrations/issue_gate.checks.py:32` | `assert instance.errors` |
| `unknown/issue_gate.checks.py:167` / `main` | IT | `integrations/issue_gate.checks.py:126` | `assert subprocess.run(command, capture_output=True).returncode == 1` |
| `unknown/issue_gate.checks.py:168` / `main` | IT | `integrations/issue_gate.checks.py:127` | `assert subprocess.run([*command, '--task'], capture_output=True).returncode == 0` |
| `unknown/issue_gate.checks.py:56` / `main` | UT | `units/issue_gate-unit.checks.py:15` | `assert not issue_errors(root, scope)` |
| `unknown/issue_gate.checks.py:88` / `main` | IT | `integrations/issue_gate.checks.py:37` | `assert not instance.errors` |
| `unknown/issue_gate.checks.py:91` / `main` | IT | `integrations/issue_gate.checks.py:37` | `assert not instance.errors` |
| `unknown/issue_gate.checks.py:133` / `main` | IT | `integrations/issue_gate.checks.py:93` | `raise AssertionError('model save bypassed issues')` |
| `unknown/issue_gate.checks.py:183` / `main` | IT | `integrations/issue_gate.checks.py:142` | `raise AssertionError('all-scope remediation accepted')` |
| `unknown/issue_gate.checks.py:108` / `main` | IT | `integrations/issue_gate.checks.py:68` | `assert instance.errors, (task_type, allowed, changed)` |
| `unknown/issue_gate.checks.py:131` / `main` | IT | `integrations/issue_gate.checks.py:91` | `assert 'unresolved issue blocks task' in str(error)` |
| `unknown/issue_gate.checks.py:148` / `main` | IT | `integrations/issue_gate.checks.py:107` | `raise AssertionError('deploy preflight bypassed issues')` |
| `unknown/issue_gate.checks.py:149` / `main` | IT | `integrations/issue_gate.checks.py:108` | `run.assert_not_called()` |
| `unknown/issue_gate.checks.py:176` / `main` | IT | `integrations/issue_gate.checks.py:135` | `raise AssertionError('invalid remediation scope accepted')` |
| `unknown/issue_gate.checks.py:146` / `main` | IT | `integrations/issue_gate.checks.py:105` | `assert 'unresolved issue' in str(error)` |
| `unknown/issue_gate.checks.py:158` / `main` | IT | `integrations/issue_gate.checks.py:117` | `raise AssertionError('AWS mutation bypassed issues')` |
| `unknown/issue_gate.checks.py:159` / `main` | IT | `integrations/issue_gate.checks.py:108` | `run.assert_not_called()` |
| `unknown/issue_gate.checks.py:156` / `main` | IT | `integrations/issue_gate.checks.py:105` | `assert 'unresolved issue' in str(error)` |
| `unknown/lambda_permission.checks.py:93` / `main` | UT | `units/lambda_permission-unit.checks.py:12` | `assert not layout_errors(ROOT)` |
| `unknown/lambda_permission.checks.py:94` / `main` | UT | `units/lambda_permission-unit.checks.py:13` | `assert formal_property('Permission.Action', FUNCTION) == PERMISSION + '.Action'` |
| `unknown/lambda_permission.checks.py:149` / `main` | IT | `integrations/lambda_permission.checks.py:66` | `assert properties(read_model(source)) == properties(HELPERS.text(values))` |
| `unknown/lambda_permission.checks.py:155` / `main` | IT | `integrations/lambda_permission.checks.py:72` | `assert path.read_bytes() == saved` |
| `unknown/lambda_permission.checks.py:109` / `main` | IT | `integrations/lambda_permission.checks.py:26` | `assert len(grouped) == parents * children` |
| `unknown/lambda_permission.checks.py:110` / `main` | IT | `integrations/lambda_permission.checks.py:27` | `assert '### Lambda.Permission' not in output` |
| `unknown/lambda_permission.checks.py:112` / `main` | IT | `integrations/lambda_permission.checks.py:29` | `assert 'Permission.Id' not in visible and 'Permission.FunctionName' not in visible` |
| `unknown/lambda_permission.checks.py:113` / `main` | IT | `integrations/lambda_permission.checks.py:30` | `assert visible.count('Permission.Action') == parents * children` |
| `unknown/lambda_permission.checks.py:114` / `main` | IT | `integrations/lambda_permission.checks.py:31` | `assert 'Permission.Principal' in visible or children == 0` |
| `unknown/lambda_permission.checks.py:115` / `main` | IT | `integrations/lambda_permission.checks.py:32` | `assert output.count('\| No. \| Property \| Value \| Source / Comment \|') == parents` |
| `unknown/lambda_permission.checks.py:117` / `main` | IT | `integrations/lambda_permission.checks.py:34` | `assert model_projection.linked_resource(path, '[permission-1-1](#lambda-app-dev-invoke-1-1)') == (PERMISSION, 'Invoke1_1')` |
| `unknown/model_files.checks.py:182` / `main` | IT | `integrations/model_files.checks.py:154` | `assert limit == 2 and len(units) == 1` |
| `unknown/model_files.checks.py:193` / `main` | IT | `integrations/model_files.checks.py:165` | `assert load_model(stack).values == values` |
| `unknown/model_files.checks.py:160` / `main` | IT | `integrations/model_files.checks.py:132` | `assert combined == text` |
| `unknown/model_files.checks.py:161` / `main` | IT | `integrations/model_files.checks.py:133` | `assert list(properties(combined).items()) == list(properties(text).items())` |
| `unknown/model_files.checks.py:162` / `main` | IT | `integrations/model_files.checks.py:134` | `assert all((len(content.splitlines()) <= 600 for content in output.values()))` |
| `unknown/model_files.checks.py:163` / `main` | IT | `integrations/model_files.checks.py:135` | `assert len(output) == (1 if count <= 600 else 1 + (count + 549) // 550)` |
| `unknown/model_files.checks.py:191` / `main` | IT | `integrations/model_files.checks.py:163` | `raise AssertionError('missing projection part accepted')` |
| `unknown/quicksight-display.checks.py:25` / `main` | UT | `units/quicksight-display-unit.checks.py:16` | `assert len(fields) == 15` |
| `unknown/quicksight-display.checks.py:30` / `main` | UT | `units/quicksight-display-unit.checks.py:29` | `assert shown == [[identity, prop.removeprefix(KIND + '.').removeprefix('DataSourceParameters.'), value, comment] for identity, prop, value, comment in source]` |
| `unknown/quicksight-display.checks.py:35` / `main` | IT | `integrations/quicksight-display.checks.py:22` | `assert not children` |
| `unknown/quicksight-display.checks.py:36` / `main` | IT | `integrations/quicksight-display.checks.py:23` | `assert restored[3:] == ['\| ' + ' \| '.join(row) + ' \|' for row in source]` |
| `unknown/regression_guard.checks.py:50` / `main` | IT | `integrations/regression_guard.checks.py:30` | `assert record['version'] == 1 and len(bytes.fromhex(record['salt'])) == 16` |
| `unknown/regression_guard.checks.py:51` / `main` | IT | `integrations/regression_guard.checks.py:31` | `assert bytes.fromhex(record['hash']) == guard.password_hash(password, bytes.fromhex(record['salt']))` |
| `unknown/regression_guard.checks.py:42` / `main` | IT | `integrations/regression_guard.checks.py:22` | `assert [path.name for path in root.iterdir()] == ['.lock'], 'service_source created extra files/directories'` |
| `unknown/regression_guard.checks.py:44` / `main` | IT | `integrations/regression_guard.checks.py:24` | `assert password not in saved` |
| `unknown/regression_guard.checks.py:48` / `main` | IT | `integrations/regression_guard.checks.py:28` | `assert lock.read_text(encoding='utf-8') == saved, 'service_source overwrote existing .lock'` |
| `unknown/regression_guard.checks.py:77` / `main` | IT | `integrations/regression_guard.checks.py:57` | `assert entry.call_count == 2` |
| `unknown/regression_guard.checks.py:91` / `main` | UT | `units/regression_guard-unit.checks.py:25` | `assert visible in output.getvalue() and 'fixture-private-password-and-hash' not in output.getvalue()` |
| `unknown/regression_guard.checks.py:47` / `main` | UT | `units/regression_guard-unit.checks.py:15` | `entry.assert_not_called()` |
| `unknown/regression_guard.checks.py:69` / `main` | UT | `units/regression_guard-unit.checks.py:15` | `entry.assert_not_called()` |
| `unknown/regression_guard.checks.py:81` / `main` | UT | `units/regression_guard-unit.checks.py:15` | `entry.assert_not_called()` |
| `unknown/regression_guard.checks.py:90` / `main` | UT | `units/regression_guard-unit.checks.py:24` | `assert guard.main() == 2` |
| `unknown/regression_guard.checks.py:66` / `main` | UT | `units/regression_guard-unit.checks.py:15` | `entry.assert_not_called()` |
| `unknown/resource_mode.checks.py:100` / `main` | IT | `integrations/resource_mode.checks.py:40` | `assert not (error := check(model())), error` |
| `unknown/resource_mode.checks.py:101` / `main` | IT | `integrations/resource_mode.checks.py:41` | `assert 'lower-kebab-case' in check(model(name='PRIVATE_SUBNET_01'))` |
| `unknown/resource_mode.checks.py:103` / `main` | IT | `integrations/resource_mode.checks.py:43` | `assert not (error := check(imported)), error` |
| `unknown/resource_mode.checks.py:104` / `main` | IT | `integrations/resource_mode.checks.py:44` | `assert 'PRIVATE_SUBNET_01' in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:105` / `main` | IT | `integrations/resource_mode.checks.py:45` | `assert not (error := check(model(name=None, mode='IMPORT'))), error` |
| `unknown/resource_mode.checks.py:107` / `main` | IT | `integrations/resource_mode.checks.py:47` | `assert '\| Name \|' not in output and 'Tags[]' not in output` |
| `unknown/resource_mode.checks.py:108` / `main` | IT | `integrations/resource_mode.checks.py:48` | `assert '### EC2.VPC\n' in output and '\| resourceMode \|' not in output` |
| `unknown/resource_mode.checks.py:109` / `main` | IT | `integrations/resource_mode.checks.py:49` | `assert 'lower-kebab-case' in check(model(name='PRIVATE_SUBNET_01', mode=None))` |
| `unknown/resource_mode.checks.py:110` / `main` | IT | `integrations/resource_mode.checks.py:50` | `assert not (error := check(model(mode=None))), error` |
| `unknown/resource_mode.checks.py:111` / `main` | IT | `integrations/resource_mode.checks.py:51` | `assert 'resource-mode:' not in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:132` / `main` | IT | `integrations/resource_mode.checks.py:65` | `assert not (error := check(tagged)), error` |
| `unknown/resource_mode.checks.py:133` / `main` | IT | `integrations/resource_mode.checks.py:66` | `assert '\| Tags[1].Key \| name \|' in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:140` / `main` | IT | `integrations/resource_mode.checks.py:73` | `assert 'lower-kebab-case' in check(mixed)` |
| `unknown/resource_mode.checks.py:144` / `main` | IT | `integrations/resource_mode.checks.py:77` | `assert 'provider schema violation' in check(bad)` |
| `unknown/resource_mode.checks.py:145` / `main` | IT | `integrations/resource_mode.checks.py:78` | `assert 'display Mapping property missing: EC2.VPC.Unknown' in check({**bad, 'desired.row.001-004.property': 'EC2.VPC.Unknown'})` |
| `unknown/resource_mode.checks.py:146` / `main` | IT | `integrations/resource_mode.checks.py:79` | `assert 'invalid resource row' in check({key: value for key, value in imported.items() if key != 'desired.row.001-001.comment'})` |
| `unknown/resource_mode.checks.py:148` / `main` | IT | `integrations/resource_mode.checks.py:81` | `assert 'requires the corresponding Tags[].Value' in check({key: value for key, value in model('EC2.Instance', 'LEGACY', 'IMPORT').items() if not key.startswith('desired.row.001-005.')})` |
| `unknown/resource_mode.checks.py:152` / `main` | IT | `integrations/resource_mode.checks.py:85` | `assert 'requires the corresponding Tags[].Key' in check({key: value for key, value in model('EC2.Instance', 'LEGACY', 'IMPORT').items() if not key.startswith('desired.row.001-004.')})` |
| `unknown/resource_mode.checks.py:158` / `main` | UT | `units/resource_mode-unit.checks.py:12` | `assert resource_mode({}) == 'CREATE'` |
| `unknown/resource_mode.checks.py:159` / `main` | IT | `integrations/resource_mode.checks.py:43` | `assert not (error := check(imported)), error` |
| `unknown/resource_mode.checks.py:171` / `main` | IT | `integrations/resource_mode.checks.py:103` | `assert resource_modes(stale.splitlines(), imported)['ec2-private_subnet_01'] == 'IMPORT'` |
| `unknown/resource_mode.checks.py:182` / `main` | UT | `units/resource_mode-unit.checks.py:19` | `assert naming_errors(root, 'CloudFront.CachePolicy', rows)` |
| `unknown/resource_mode.checks.py:183` / `main` | UT | `units/resource_mode-unit.checks.py:20` | `assert not naming_errors(root, 'CloudFront.CachePolicy', rows, 'IMPORT')` |
| `unknown/resource_mode.checks.py:184` / `main` | UT | `units/resource_mode-unit.checks.py:21` | `assert naming_errors(root, 'IAM.Role', [], 'IMPORT')` |
| `unknown/resource_mode.checks.py:185` / `main` | UT | `units/resource_mode-unit.checks.py:22` | `assert naming_errors(root, 'CodeBuild.Project', [], 'IMPORT')` |
| `unknown/resource_mode.checks.py:186` / `main` | IT | `integrations/resource_mode.checks.py:43` | `assert not (error := check(imported)), error` |
| `unknown/resource_mode.checks.py:188` / `main` | IT | `integrations/resource_mode.checks.py:115` | `assert SYNC.sync(root, True, 'dev', '123456789012', services=['ec2']) == 0` |
| `unknown/resource_mode.checks.py:189` / `main` | IT | `integrations/resource_mode.checks.py:116` | `assert SYNC.sync(root, False, 'dev', '123456789012', services=['ec2']) == 0` |
| `unknown/resource_mode.checks.py:190` / `main` | IT | `integrations/resource_mode.checks.py:117` | `assert snapshot_model(source) == before` |
| `unknown/resource_mode.checks.py:191` / `main` | IT | `integrations/resource_mode.checks.py:44` | `assert 'PRIVATE_SUBNET_01' in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:220` / `main` | IT | `integrations/resource_mode.checks.py:147` | `assert saved KMS view equals generated Markdown` |
| `unknown/resource_mode.checks.py:223` / `main` | IT | `integrations/resource_mode.checks.py:150` | `assert '### KMS.Alias' not in kms_path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:92` / `main` | IT | `integrations/resource_mode.checks.py:32` | `assert read_model(source) == original` |
| `unknown/resource_mode.checks.py:94` / `main` | IT | `integrations/resource_mode.checks.py:34` | `assert projected == {key: value for key, value in values.items() if not key.startswith('display.')}` |
| `unknown/resource_mode.checks.py:95` / `main` | IT | `integrations/resource_mode.checks.py:51` | `assert 'resource-mode:' not in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:96` / `main` | IT | `integrations/resource_mode.checks.py:36` | `assert 'resource-entry:' not in path.read_text(encoding='utf-8')` |
| `unknown/resource_mode.checks.py:125` / `main` | IT | `integrations/resource_mode.checks.py:58` | `assert check(model(kind, None, 'CREATE', '表示名'))` |
| `unknown/resource_mode.checks.py:126` / `main` | IT | `integrations/resource_mode.checks.py:59` | `assert not (error := check(model(kind, 'LEGACY_NAME_01', 'IMPORT'))), error` |
| `unknown/resource_mode.checks.py:157` / `main` | IT | `integrations/resource_mode.checks.py:90` | `assert 'resourceMode must be CREATE or IMPORT' in check({**imported, 'desired.resource.001.resourceMode': invalid})` |
| `unknown/resource_mode.checks.py:179` / `main` | IT | `integrations/resource_mode.checks.py:111` | `raise AssertionError('stale generated view accepted')` |
| `unknown/resource_mode.checks.py:124` / `main` | IT | `integrations/resource_mode.checks.py:57` | `assert not (error := check(model(kind, None, 'IMPORT', label))), error` |
| `unknown/resource_mode.checks.py:168` / `main` | IT | `integrations/resource_mode.checks.py:100` | `raise AssertionError('invalid resourceMode metadata accepted')` |
| `unknown/resource_mode.checks.py:177` / `main` | IT | `integrations/resource_mode.checks.py:109` | `assert 'stale or missing' in str(error), error` |
| `unknown/resource_mode.checks.py:121` / `main` | UT | `units/resource_mode-unit.checks.py:35` | `assert bool(validator.errors) == (mode == 'CREATE'), (kind, mode, validator.errors)` |
| `unknown/rotation_schedule.checks.py:112` / `main` | IT | `integrations/rotation_schedule.checks.py:112` | `assert '\| SecretsManager.RotationSchedule.ExternalSecretRotationMetadata' not in metadata_output` |
| `unknown/rotation_schedule.checks.py:197` / `main` | IT | `integrations/rotation_schedule.checks.py:197` | `assert path.read_text().count('[key-current](kms.md#kms-app-dev-key)') == 2` |
| `unknown/rotation_schedule.checks.py:205` / `main` | IT | `integrations/rotation_schedule.checks.py:205` | `assert path.read_bytes() == saved[path]` |
| `unknown/rotation_schedule.checks.py:206` / `main` | IT | `integrations/rotation_schedule.checks.py:206` | `assert (path.parent / 'kms.md').read_bytes() != saved[path.parent / 'kms.md']` |
| `unknown/rotation_schedule.checks.py:207` / `main` | IT | `integrations/rotation_schedule.checks.py:207` | `assert 'kms-app-dev-renamed' in (path.parent / 'kms.md').read_text()` |
| `unknown/rotation_schedule.checks.py:208` / `main` | IT | `integrations/rotation_schedule.checks.py:208` | `assert properties(read_model(models / 'secretsmanager.properties')) == properties(HELPERS.text(values))` |
| `unknown/rotation_schedule.checks.py:215` / `main` | IT | `integrations/rotation_schedule.checks.py:215` | `assert 'kms-app-dev-key' not in path.read_text()` |
| `unknown/rotation_schedule.checks.py:216` / `main` | IT | `integrations/rotation_schedule.checks.py:216` | `assert path.read_text().count('[key-current](kms.md#kms-app-dev-renamed)') == 2` |
| `unknown/rotation_schedule.checks.py:88` / `main` | IT | `integrations/rotation_schedule.checks.py:88` | `assert len(children) == count` |
| `unknown/rotation_schedule.checks.py:90` / `main` | IT | `integrations/rotation_schedule.checks.py:90` | `assert '### SecretsManager.RotationSchedule' not in output` |
| `unknown/rotation_schedule.checks.py:91` / `main` | IT | `integrations/rotation_schedule.checks.py:91` | `assert 'app-dev-secret-1_rotate：属性の設定値' in output` |
| `unknown/rotation_schedule.checks.py:93` / `main` | IT | `integrations/rotation_schedule.checks.py:93` | `assert model_projection.linked_resource(path, '[PENDING_DEPLOY](#secretsmanager-app-dev-secret-1_rotate)') == (ROTATION, 'Secret1Rotation')` |
| `unknown/rotation_schedule.checks.py:111` / `main` | IT | `integrations/rotation_schedule.checks.py:111` | `assert f'\| RotationSchedule.ExternalSecretRotationMetadata[{index // 2 + 1}].{field} \| `{value}` \|' in metadata_output` |
| `unknown/rotation_schedule.checks.py:166` / `main` | IT | `integrations/rotation_schedule.checks.py:166` | `assert '\| Id \|' not in rendered` |
| `unknown/rotation_schedule.checks.py:167` / `main` | IT | `integrations/rotation_schedule.checks.py:167` | `assert legacy[f'desired.row.{identity}-099.value'] == '`PENDING_DEPLOY`'` |
| `unknown/security_group_tables.checks.py:104` / `main` | UT | `units/security_group_tables-unit.checks.py:12` | `assert not layout_errors(REPOSITORY)` |
| `unknown/security_group_tables.checks.py:109` / `main` | UT | `units/security_group_tables-unit.checks.py:17` | `assert LAYOUTS[resource_type]['display'] == 'rule-table'` |
| `unknown/security_group_tables.checks.py:111` / `main` | UT | `units/security_group_tables-unit.checks.py:19` | `assert selected - {'GroupId'} <= COMMENTS.keys()` |
| `unknown/security_group_tables.checks.py:133` / `main` | IT | `integrations/security_group_tables.checks.py:32` | `assert not errors(DESIGN), errors(DESIGN)` |
| `unknown/security_group_tables.checks.py:136` / `main` | IT | `integrations/security_group_tables.checks.py:35` | `assert path.read_bytes() == original` |
| `unknown/security_group_tables.checks.py:141` / `main` | IT | `integrations/security_group_tables.checks.py:40` | `assert validator.model_service_metadata(model_path, catalog[0]) == metadata[path]` |
| `unknown/security_group_tables.checks.py:142` / `main` | IT | `integrations/security_group_tables.checks.py:41` | `assert not validator.errors, validator.errors` |
| `unknown/security_group_tables.checks.py:156` / `main` | IT | `integrations/security_group_tables.checks.py:43` | `assert not errors(short_design), errors(short_design)` |
| `unknown/security_group_tables.checks.py:157` / `main` | IT | `integrations/security_group_tables.checks.py:44` | `assert expanded_design(short_design) == expanded_design(DESIGN)` |
| `unknown/security_group_tables.checks.py:158` / `main` | IT | `integrations/security_group_tables.checks.py:45` | `assert not errors(DESIGN)` |
| `unknown/security_group_tables.checks.py:159` / `main` | IT | `integrations/security_group_tables.checks.py:46` | `assert 'observed.row.002-001.comment=一意に識別するID\n' in generated` |
| `unknown/security_group_tables.checks.py:160` / `main` | IT | `integrations/security_group_tables.checks.py:47` | `assert 'desired.row.001-004.comment=所属するVPCのID\n' in generated` |
| `unknown/security_group_tables.checks.py:161` / `main` | IT | `integrations/security_group_tables.checks.py:48` | `assert 'desired.row.002-005.comment=通信元として許可するSecurity GroupのID\n' in generated` |
| `unknown/security_group_tables.checks.py:162` / `main` | IT | `integrations/security_group_tables.checks.py:49` | `assert 'comment=通信先として許可するSecurity GroupのID\n' in generated` |
| `unknown/security_group_tables.checks.py:163` / `main` | IT | `integrations/security_group_tables.checks.py:50` | `assert 'comment=Security Group' not in generated` |
| `unknown/security_group_tables.checks.py:164` / `main` | IT | `integrations/security_group_tables.checks.py:51` | `assert 'desired.row.001-002.property=EC2.SecurityGroup.GroupDescription\n' in generated` |
| `unknown/security_group_tables.checks.py:165` / `main` | IT | `integrations/security_group_tables.checks.py:52` | `assert 'desired.row.001-002.value=`Application access`\n' in generated` |
| `unknown/security_group_tables.checks.py:166` / `main` | IT | `integrations/security_group_tables.checks.py:53` | `assert 'desired.row.001-004.property=EC2.SecurityGroup.VpcId\n' in generated` |
| `unknown/security_group_tables.checks.py:167` / `main` | IT | `integrations/security_group_tables.checks.py:54` | `assert 'desired.row.001-004.value=[vpc-app-dev](vpc.md#vpc-vpc-app-dev)\n' in generated` |
| `unknown/security_group_tables.checks.py:168` / `main` | IT | `integrations/security_group_tables.checks.py:55` | `assert 'observed.row.001-004.value=vpc-00000001\n' in generated` |
| `unknown/security_group_tables.checks.py:169` / `main` | IT | `integrations/security_group_tables.checks.py:56` | `assert generated.count('.property=EC2.SecurityGroup.GroupDescription\n') == 2` |
| `unknown/security_group_tables.checks.py:170` / `main` | IT | `integrations/security_group_tables.checks.py:57` | `assert 'desired.row.006-004.value=Project\n' in generated` |
| `unknown/security_group_tables.checks.py:171` / `main` | IT | `integrations/security_group_tables.checks.py:58` | `assert 'desired.row.006-007.value=dev\n' in generated` |
| `unknown/security_group_tables.checks.py:172` / `main` | IT | `integrations/security_group_tables.checks.py:59` | `assert 'desired.resource.002.resourceType=EC2.SecurityGroupIngress' in generated` |
| `unknown/security_group_tables.checks.py:173` / `main` | IT | `integrations/security_group_tables.checks.py:60` | `assert 'desired.resource.002.logicalId=IngressOne' in generated` |
| `unknown/security_group_tables.checks.py:174` / `main` | IT | `integrations/security_group_tables.checks.py:61` | `assert 'desired.resource.002.parentProperty=EC2.SecurityGroupIngress.GroupId' in generated` |
| `unknown/security_group_tables.checks.py:175` / `main` | IT | `integrations/security_group_tables.checks.py:62` | `assert 'desired.resource.002.parentReference=[GroupOne](#security-group-groupone)' in generated` |
| `unknown/security_group_tables.checks.py:176` / `main` | IT | `integrations/security_group_tables.checks.py:63` | `assert 'desired.resource.005.parentProperty=EC2.SecurityGroupEgress.GroupId' in generated` |
| `unknown/security_group_tables.checks.py:177` / `main` | IT | `integrations/security_group_tables.checks.py:64` | `assert 'desired.resource.006.logicalId=GroupTwo' in generated` |
| `unknown/security_group_tables.checks.py:178` / `main` | IT | `integrations/security_group_tables.checks.py:65` | `assert 'desired.row.002-001.value=[IngressOne](#security-group-ingressone)' in generated` |
| `unknown/security_group_tables.checks.py:179` / `main` | IT | `integrations/security_group_tables.checks.py:66` | `assert 'observed.row.002-001.value=`sgr-00000001`' in generated` |
| `unknown/security_group_tables.checks.py:180` / `main` | IT | `integrations/security_group_tables.checks.py:67` | `assert 'desired.row.002-005.value=[GroupTwo](#security-group-grouptwo)' in generated` |
| `unknown/security_group_tables.checks.py:181` / `main` | IT | `integrations/security_group_tables.checks.py:68` | `assert 'observed.row.002-005.value=PENDING_DEPLOY' in generated` |
| `unknown/security_group_tables.checks.py:182` / `main` | IT | `integrations/security_group_tables.checks.py:69` | `assert 'SecurityGroupRuleId' not in generated and '<!--' not in generated` |
| `unknown/security_group_tables.checks.py:183` / `main` | IT | `integrations/security_group_tables.checks.py:70` | `assert 'desired.note.' not in generated and '=—' not in generated` |
| `unknown/security_group_tables.checks.py:184` / `main` | IT | `integrations/security_group_tables.checks.py:71` | `assert model_projection.linked_resource(path, '[sgr-00000001](#security-group-ingressone)') == ('EC2.SecurityGroupIngress', 'IngressOne')` |
| `unknown/security_group_tables.checks.py:185` / `main` | IT | `integrations/security_group_tables.checks.py:72` | `assert VALIDATOR.rendered_policy_design(path) == DESIGN` |
| `unknown/security_group_tables.checks.py:188` / `main` | IT | `integrations/security_group_tables.checks.py:75` | `assert len(children) == 4` |
| `unknown/security_group_tables.checks.py:189` / `main` | IT | `integrations/security_group_tables.checks.py:76` | `assert children['security-group-ingressthree']['logicalId'] == 'IngressThree'` |
| `unknown/security_group_tables.checks.py:190` / `main` | IT | `integrations/security_group_tables.checks.py:77` | `assert [row[2] for row in children['security-group-ingresstwo']['rows']] == ['`PENDING_DEPLOY`', '`icmpv6`', '`128`', '`0`', '`2001:db8::/64`']` |
| `unknown/security_group_tables.checks.py:192` / `main` | IT | `integrations/security_group_tables.checks.py:79` | `assert inline == [['EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol', '`-1`'], ['EC2.SecurityGroup.SecurityGroupEgress[].CidrIp', '`0.0.0.0/0`'], ['EC2.SecurityGroup.SecurityGroupEgress[].Description', '`IPv4 outbound`'], ['EC2.SecurityGroup.SecurityGroupEgress[].IpProtocol', '`-1`'], ['EC2.SecurityGroup.SecurityGroupEgress[].CidrIp', '`10.1.0.0/16`']]` |
| `unknown/security_group_tables.checks.py:201` / `main` | IT | `integrations/security_group_tables.checks.py:88` | `assert not errors(inbound_only), errors(inbound_only)` |
| `unknown/security_group_tables.checks.py:202` / `main` | IT | `integrations/security_group_tables.checks.py:89` | `assert '### EC2.SecurityGroup: GroupTwo' in DESIGN` |
| `unknown/security_group_tables.checks.py:205` / `main` | IT | `integrations/security_group_tables.checks.py:92` | `assert not errors(no_tags), errors(no_tags)` |
| `unknown/security_group_tables.checks.py:206` / `main` | IT | `integrations/security_group_tables.checks.py:93` | `assert 'EC2.SecurityGroup.Tags[]' not in '\n'.join(security_group_table_lines(no_tags.splitlines()))` |
| `unknown/security_group_tables.checks.py:211` / `main` | IT | `integrations/security_group_tables.checks.py:98` | `assert not errors(inline_peer), errors(inline_peer)` |
| `unknown/security_group_tables.checks.py:212` / `main` | IT | `integrations/security_group_tables.checks.py:99` | `assert any(('EC2.SecurityGroup.SecurityGroupIngress[].SourceSecurityGroupId \| [PENDING_DEPLOY](#security-group-grouptwo)' in line for line in security_group_table_lines(inline_peer.splitlines())))` |
| `unknown/security_group_tables.checks.py:235` / `main` | IT | `integrations/security_group_tables.checks.py:122` | `assert not errors(moved), errors(moved)` |
| `unknown/security_group_tables.checks.py:237` / `main` | IT | `integrations/security_group_tables.checks.py:124` | `assert moved_children['security-group-egressone']['parentLogicalId'] == 'GroupTwo'` |
| `unknown/security_group_tables.checks.py:238` / `main` | IT | `integrations/security_group_tables.checks.py:125` | `assert moved_children['security-group-egressone']['logicalId'] == 'EgressOne'` |
| `unknown/security_group_tables.checks.py:240` / `main` | IT | `integrations/security_group_tables.checks.py:127` | `assert '\| FromPort \|' not in DESIGN and '\| ToPort \|' not in DESIGN` |
| `unknown/security_group_tables.checks.py:241` / `main` | IT | `integrations/security_group_tables.checks.py:128` | `assert '.property=Port\n' not in generated` |
| `unknown/security_group_tables.checks.py:249` / `main` | IT | `integrations/security_group_tables.checks.py:136` | `assert port_properties('—', '-1') == {}` |
| `unknown/security_group_tables.checks.py:250` / `main` | IT | `integrations/security_group_tables.checks.py:137` | `assert port_properties('—', 'icmpv6') == {}` |
| `unknown/security_group_tables.checks.py:251` / `main` | IT | `integrations/security_group_tables.checks.py:138` | `assert 'SecurityGroupRuleId' not in DESIGN` |
| `unknown/security_group_tables.checks.py:252` / `main` | IT | `integrations/security_group_tables.checks.py:139` | `assert '\| SourceSecurityGroupId \|' not in DESIGN` |
| `unknown/security_group_tables.checks.py:253` / `main` | IT | `integrations/security_group_tables.checks.py:140` | `assert '\| DestinationSecurityGroupId \|' not in DESIGN` |
| `unknown/security_group_tables.checks.py:254` / `main` | IT | `integrations/security_group_tables.checks.py:141` | `assert '.property=EC2.SecurityGroupIngress.SourceSecurityGroupId\n' in generated` |
| `unknown/security_group_tables.checks.py:255` / `main` | IT | `integrations/security_group_tables.checks.py:142` | `assert '.property=EC2.SecurityGroupEgress.DestinationSecurityGroupId\n' in generated` |
| `unknown/security_group_tables.checks.py:256` / `main` | IT | `integrations/security_group_tables.checks.py:143` | `assert 'rule-id:' not in generated` |
| `unknown/security_group_tables.checks.py:257` / `main` | IT | `integrations/security_group_tables.checks.py:144` | `assert 'アプリケーションの通信を制御するSG' not in generated` |
| `unknown/security_group_tables.checks.py:258` / `main` | IT | `integrations/security_group_tables.checks.py:145` | `assert '\| Tags \|' not in DESIGN` |
| `unknown/security_group_tables.checks.py:259` / `main` | IT | `integrations/security_group_tables.checks.py:146` | `assert 'security-group-tags' not in generated` |
| `unknown/security_group_tables.checks.py:113` / `main` | UT | `units/security_group_tables-unit.checks.py:21` | `assert 'EC2.SecurityGroup' in catalog[1][f'EC2.SecurityGroup.SecurityGroup{direction}[].{prop}']` |
| `unknown/security_group_tables.checks.py:154` / `main` | UT | `units/security_group_tables-unit.checks.py:42` | `assert invalid.errors, (filename, service, kinds)` |
| `unknown/security_group_tables.checks.py:220` / `main` | IT | `integrations/security_group_tables.checks.py:107` | `assert not errors(text), errors(text)` |
| `unknown/security_group_tables.checks.py:223` / `main` | IT | `integrations/security_group_tables.checks.py:110` | `assert path.read_bytes() == source` |
| `unknown/security_group_tables.checks.py:224` / `main` | IT | `integrations/security_group_tables.checks.py:111` | `assert model.count('.resourceType=EC2.SecurityGroup\n') == 2` |
| `unknown/security_group_tables.checks.py:225` / `main` | IT | `integrations/security_group_tables.checks.py:112` | `assert 'desired.resource.002.anchor=security-group-grouptwo\n' in model` |
| `unknown/security_group_tables.checks.py:226` / `main` | IT | `integrations/security_group_tables.checks.py:113` | `assert '.resourceType=EC2.SecurityGroupIngress' not in model` |
| `unknown/security_group_tables.checks.py:227` / `main` | IT | `integrations/security_group_tables.checks.py:114` | `assert '.resourceType=EC2.SecurityGroupEgress' not in model` |
| `unknown/security_group_tables.checks.py:228` / `main` | IT | `integrations/security_group_tables.checks.py:115` | `assert 'desired.note.' not in model` |
| `unknown/security_group_tables.checks.py:229` / `main` | IT | `integrations/security_group_tables.checks.py:116` | `assert ('.property=EC2.SecurityGroup.Tags[].Key' in model) == (tag_line in text)` |
| `unknown/security_group_tables.checks.py:248` / `main` | IT | `integrations/security_group_tables.checks.py:135` | `assert port_properties(display, protocol) == {'FromPort': f'`{first}`', 'ToPort': f'`{last}`'}` |
| `unknown/security_group_tables.checks.py:309` / `main` | IT | `integrations/security_group_tables.checks.py:196` | `assert any((message in error for error in failures)), (message, failures)` |
| `unknown/security_group_tables.checks.py:317` / `main` | IT | `integrations/security_group_tables.checks.py:204` | `raise AssertionError('invalid horizontal rule must not generate a model')` |
| `unknown/validation_cache.checks.py:88` / `main` | IT | `integrations/validation_cache.checks.py:25` | `assert PassCache(root, directory=directory).service_key(entry) != before` |
| `unknown/validation_cache.checks.py:98` / `main` | IT | `integrations/validation_cache.checks.py:25` | `assert PassCache(root, directory=directory).service_key(entry) != before` |
| `unknown/validation_scope.checks.py:197` / `main` | UT | `units/validation_scope-unit.checks.py:23` | `assert active_scope(root, True) is None` |
| `unknown/validation_scope.checks.py:199` / `main` | UT | `units/validation_scope-unit.checks.py:25` | `assert active_scope(root) is None` |
| `unknown/validation_scope.checks.py:203` / `main` | UT | `units/validation_scope-unit.checks.py:29` | `assert active_scope(root) == scope` |
| `unknown/validation_scope.checks.py:260` / `main` | IT | `integrations/validation_scope.checks.py:219` | `assert len(scoped_files(root, 'model', '.properties', scope)) == 4` |
| `unknown/validation_scope.checks.py:264` / `main` | IT | `integrations/validation_scope.checks.py:223` | `assert not validator.errors, validator.errors` |
| `unknown/validation_scope.checks.py:275` / `main` | IT | `integrations/validation_scope.checks.py:234` | `assert len(workers) == 4 and (not validator.errors), validator.errors` |
| `unknown/validation_scope.checks.py:276` / `main` | IT | `integrations/validation_scope.checks.py:235` | `assert validator.generated_models_checked` |
| `unknown/validation_scope.checks.py:286` / `main` | IT | `integrations/validation_scope.checks.py:247` | `assert any(('outside validation scope' in error for error in validator.errors))` |
| `unknown/validation_scope.checks.py:294` / `main` | IT | `integrations/validation_scope.checks.py:262` | `assert any(('missing design anchor' in error for error in rejected.errors)), rejected.errors` |
| `unknown/validation_scope.checks.py:316` / `main` | IT | `integrations/validation_scope.checks.py:284` | `assert any(('invalid design JSON' in error for error in rejected.errors))` |
| `unknown/validation_scope.checks.py:321` / `main` | IT | `integrations/validation_scope.checks.py:289` | `assert full.errors and 'logs' in '\n'.join(full.errors)` |
| `unknown/validation_scope.checks.py:325` / `main` | IT | `integrations/validation_scope.checks.py:293` | `assert result.returncode and 'validation scope missing' in result.stderr` |
| `unknown/validation_scope.checks.py:329` / `main` | IT | `integrations/validation_scope.checks.py:297` | `assert result.returncode and 'outside active task validation scope' in result.stderr` |
| `unknown/validation_scope.checks.py:283` / `main` | IT | `integrations/validation_scope.checks.py:242` | `assert rejected.errors` |
| `unknown/validation_scope.checks.py:196` / `main` | UT | `units/validation_scope-unit.checks.py:22` | `raise AssertionError('missing/incomplete scope accepted')` |
| `unknown/validation_scope.checks.py:308` / `main` | IT | `integrations/validation_scope.checks.py:276` | `raise AssertionError('selected invalid design accepted')` |
| `unknown/validation_scope.checks.py:306` / `main` | IT | `integrations/validation_scope.checks.py:274` | `assert token in str(error), error` |

main/module検証地点の現在配置: integrations=305, units=232。

| `units/update-catalog-lock.checks.py:21` / `module` | UT | `units/update-catalog-lock.checks.py:21` | `assert SPEC and SPEC.loader` |
| `units/update-catalog-lock.checks.py:12` / `module` | UT | `units/update-catalog-lock.checks.py:12` | `raise SystemExit('Focused checks require assertions; run without -O')` |
| `units/update-catalog-lock.checks.py:32` / `main` | UT | `units/update-catalog-lock.checks.py:32` | `assert [path.name for path in MODULE.catalog_files()] == sorted(names)` |
| `units/validation-units.checks.py:7` / `module` | UT | `units/validation-units.checks.py:7` | `raise SystemExit('Focused checks require assertions; run without -O')` |
| `units/validation-units.checks.py:34` / `main` | UT | `units/validation-units.checks.py:34` | `assert MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch('01_initialize.md')` |
| `units/validation-units.checks.py:35` / `main` | UT | `units/validation-units.checks.py:35` | `assert not MODULE.CODEX_PROMPT_FILENAME_PATTERN.fullmatch('initialize.md')` |
| `units/validation_cache-unit.checks.py:7` / `module` | UT | `units/validation_cache-unit.checks.py:7` | `raise SystemExit('Focused checks require assertions; run without -O')` |
| `units/validation_cache-unit.checks.py:163` / `module` | UT | `units/validation_cache-unit.checks.py:163` | `raise SystemExit(run(__file__))` |
| `units/validation_cache-unit.checks.py:16` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:16` | `assert cache.load(key) is None` |
| `units/validation_cache-unit.checks.py:18` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:18` | `assert cache.load(key) == 17` |
| `units/validation_cache-unit.checks.py:19` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:19` | `assert PassCache(root, fresh=True, directory=directory).load(key) is None` |
| `units/validation_cache-unit.checks.py:26` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:26` | `assert PassCache(root, directory=directory).key('catalog') == key` |
| `units/validation_cache-unit.checks.py:28` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:28` | `assert PassCache(root, directory=directory).key('catalog') == key` |
| `units/validation_cache-unit.checks.py:30` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:30` | `assert cache.load(key) is None` |
| `units/validation_cache-unit.checks.py:49` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:49` | `assert read_inputs(values)[0][1]['value'] == 'first'` |
| `units/validation_cache-unit.checks.py:51` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:51` | `assert read_inputs(values)[0][1]['value'] == 'second', 'later invocations must see edits'` |
| `units/validation_cache-unit.checks.py:62` / `check_cache_location` | UT | `units/validation_cache-unit.checks.py:62` | `raise AssertionError('cache directory inside repository accepted')` |
| `units/validation_cache-unit.checks.py:158` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:158` | `assert tasks.contracts(project)['tasks/first.md'] == original` |
| `units/validation_cache-unit.checks.py:23` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:23` | `assert cache.load(key) is None` |
| `units/validation_cache-unit.checks.py:37` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:37` | `assert added != before` |
| `units/validation_cache-unit.checks.py:39` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:39` | `assert PassCache(root, directory=directory).key('catalog') != added` |
| `units/validation_cache-unit.checks.py:41` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:41` | `assert PassCache(root, directory=directory).key('catalog') == before` |
| `units/validation_cache-unit.checks.py:44` / `check_cache_inputs` | UT | `units/validation_cache-unit.checks.py:44` | `assert design_material_files(root) is design_material_files(root)` |
| `units/validation_cache-unit.checks.py:130` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:130` | `assert scans.call_count == 2` |
| `units/validation_cache-unit.checks.py:156` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:156` | `assert import_scope.selected(project) == ('dev', 'cde', 'iam')` |
| `units/validation_cache-unit.checks.py:104` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:104` | `assert scans.call_count == 1` |
| `units/validation_cache-unit.checks.py:105` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:105` | `assert selections.call_count == 1` |
| `units/validation_cache-unit.checks.py:108` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:108` | `assert import_scope.selected(project) == ('dev', 'cde', 'sqs')` |
| `units/validation_cache-unit.checks.py:129` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:129` | `assert read(path) is cached` |
| `units/validation_cache-unit.checks.py:149` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:149` | `raise AssertionError(f'contract {change} was not detected')` |
| `units/validation_cache-unit.checks.py:103` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:103` | `assert import_scope.selected(project) == ('dev', 'cde', 'sqs')` |
| `units/validation_cache-unit.checks.py:107` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:107` | `assert import_scope.selected(project) == ('dev', 'cde', 's3')` |
| `units/validation_cache-unit.checks.py:116` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:116` | `assert import_scope.read_context(project) == before` |
| `units/validation_cache-unit.checks.py:117` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:117` | `assert read(path) is cached` |
| `units/validation_cache-unit.checks.py:119` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:119` | `assert read(path) is not cached` |
| `units/validation_cache-unit.checks.py:134` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:134` | `assert import_scope.selected(project) == ('dev', 'cde', 'sqs')` |
| `units/validation_cache-unit.checks.py:147` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:147` | `assert 'changed during validation' in str(error)` |
| `units/validation_cache-unit.checks.py:114` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:114` | `assert import_scope.read_context(project)[2] == path.absolute()` |
| `units/validation_cache-unit.checks.py:115` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:115` | `assert read(path) is not cached` |
| `units/validation_cache-unit.checks.py:126` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:126` | `raise AssertionError('cached result bypassed Task read permission')` |
| `units/validation_cache-unit.checks.py:128` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:128` | `assert read(path) is not cached` |
| `units/validation_cache-unit.checks.py:124` / `check_retained_common_key` | UT | `units/validation_cache-unit.checks.py:124` | `assert 'outside selected' in str(error)` |

| `integrations/design_catalog.checks.py:77` / `main` | IT | `integrations/design_catalog.checks.py:77` | `assert len(bad_values) == len(expected_errors) == 23` |
| `integrations/design_catalog.checks.py:80` / `main` | IT | `integrations/design_catalog.checks.py:80` | `assert not schema.api_value_errors(MACIE_JOB, job_schema, VALUES, '')` |
| `integrations/design_catalog.checks.py:81` / `main` | IT | `integrations/design_catalog.checks.py:81` | `assert not schema.job_errors(VALUES)` |
| `integrations/design_catalog.checks.py:22` / `main` | IT | `integrations/design_catalog.checks.py:22` | `assert '### QuickSight.Group: reader-group' in group_model` |
| `integrations/design_catalog.checks.py:23` / `main` | IT | `integrations/design_catalog.checks.py:23` | `assert '\| QuickSight.Group.PrincipalId \| `PENDING_DEPLOY` \|' in group_model` |
| `integrations/design_catalog.checks.py:24` / `main` | IT | `integrations/design_catalog.checks.py:24` | `assert 'QuickSight.Group.Arn' not in group_model and 'arn:' not in group_model` |
| `integrations/design_catalog.checks.py:88` / `main` | IT | `integrations/design_catalog.checks.py:88` | `assert all((any((message in error for error in errors)) for message in expected)), (values, expected, errors)` |
| `integrations/design_catalog.checks.py:104` / `main` | IT | `integrations/design_catalog.checks.py:104` | `raise AssertionError('wrong S3 link label accepted')` |
| `integrations/design_catalog.checks.py:113` / `main` | IT | `integrations/design_catalog.checks.py:113` | `raise AssertionError('bucketCriteria accepted with a fixed bucket table')` |
| `integrations/design_catalog.checks.py:102` / `main` | IT | `integrations/design_catalog.checks.py:102` | `assert 'label must match its S3 Bucket' in str(error)` |
| `integrations/design_catalog.checks.py:111` / `main` | IT | `integrations/design_catalog.checks.py:111` | `assert 'conflicts with bucketCriteria' in str(error)` |

## 共通fixture・検証補助

| 現在のファイル | 内容 |
|---|---|
| `support/aws_mapping_compare_fixtures.py` | outcome |
| `support/aws_mapping_display_fixtures.py` | fixture |
| `support/aws_mapping_fixtures.py` | import/定数/共通fixture |
| `support/blueprint_loop_fixtures.py` | events, make_project_fixture, make_loop_fixture |
| `support/check_model_aws_fixtures.py` | check, expect, shape_value, remove_tokens, set_path, Offline, FakeResource, acquired, model_text, offline_network |
| `support/cloudformation_deploy_fixtures.py` | units, states, rejects, Fake, starts, finish, StubAws, DeliveryAws |
| `support/compare_environments_fixtures.py` | path, copy_inputs, cli |
| `support/deploy_preparation_fixtures.py` | fixture, arguments, invoke |
| `support/design_catalog_fixtures.py` | markdown, quicksight_group_markdown |
| `support/design_document_fixtures.py` | reference_fixture |
| `support/design_layout_fixtures.py` | catalog |
| `support/framework_input_isolation_fixtures.py` | import/定数/共通fixture |
| `support/glue_datazone_catalog_fixtures.py` | write_designs |
| `support/import_model_fixtures.py` | check, AwsCli, project_fixture, spec, metadata, binding, declaration, save_service, build_seed, fixture, aws, stage, correspondence, exclusions, logs_edit, publish_fixture, snapshot |
| `support/issue_gate_fixtures.py` | import/定数/共通fixture |
| `support/issues_api_only_fixtures.py` | cli_exit |
| `support/issues_scan_fixtures.py` | write, write_report, render_iac, fixture, task, compare, mutate_template, expect_error, concurrency, legacy_mechanical, required_context, baseline_input, worker, benchmark, summary_fixture, protected_sources, scan_project |
| `support/json_yaml_document_hash_fixtures.py` | import/定数/共通fixture |
| `support/lambda_permission_fixtures.py` | fixture, rejects |
| `support/it_fixture_bundle.py` | fingerprint, protect, build, bundle, source |
| `support/it_workspace.py` | _copy_tree, populate（可変Project seedのみ） |
| `support/rotation_schedule_fixtures.py` | fixture |
| `support/model_design_fixtures.py` | model, text, roundtrip, root, project, main |
| `support/model_files_fixtures.py` | import/定数/共通fixture |
| `support/model_parameter_inputs_fixtures.py` | rejected, declaration, fixture, root |
| `support/model_sources.py` | write_model, write_fixture_files, snapshot_model, catalog_display |
| `support/model_templates_fixtures.py` | rejected, fixture, role_model, config_model, write_fixture, install_candidate, root, common_shape_template |
| `support/policy_tables_fixtures.py` | import/定数/共通fixture |
| `support/producer_identifier_reference_fixtures.py` | rejected |
| `support/pytest_cli.py` | Diagnostics, run |
| `support/quicksight_display_fixtures.py` | import/定数/共通fixture |
| `support/raw_bucket_name_reference_fixtures.py` | rejected |
| `support/regression_guard_fixtures.py` | rejected |
| `support/resource_mode_fixtures.py` | model |
| `support/security_group_tables_fixtures.py` | import/定数/共通fixture |
| `support/service_fixtures.py` | input_spec, service, build_typed_services, build_input_templates, typed_services, input_templates |
| `support/sync_model_fixtures.py` | build_generated_policy, generated_policy |
| `support/validation_cache_fixtures.py` | import/定数/共通fixture |
| `support/validation_scope_fixtures.py` | import/定数/共通fixture |
| `support/validator.py` | load, project, git_project, commit, write, schema_validator |
| `support/worktree_python_fixtures.py` | blocked |
| `support/worktree_task_fixtures.py` | git, contract, fixture, cli, start, finish_contract, retained |



## main/moduleの内部パターン

| ファイル / 入口 | ループ入力（パターン数） |
|---|---|
| `integrations/compact-model-sources.checks.py:41` | 5: `('false', '0', '', 'null', '`PENDING_DEPLOY`')` |
| `integrations/compact-model-sources.checks.py:57` | 3: `(False, 0, None)` |
| `integrations/compact-model-sources.checks.py:59` | 3: `({key: 'x', 'observed.row.017-023.property': 'wrong'}, {'observed.row.999-001.value': 'x'}, {'observed.row.017-023.state': 'unknown'})` |
| `integrations/compact-model-sources.checks.py:72` | 動的: `range(2)` |
| `integrations/compact-model-sources.checks.py:79` | 4: `('definition', 'resources', 'rows', 'parameters')` |
| `integrations/compact-model-sources.checks.py:81` | 3: `(None, [], {'Unknown': 'x'})` |
| `integrations/compact-model-sources.checks.py:47` | 2: `('property', 'comment')` |
| `integrations/compact-model-sources.checks.py:54` | 動的: `range(2)` |
| `integrations/compact-model-sources.checks.py:95` | 3: `(('preview', 'Common'), ('release', 'Common'), ('independent', 'Independent'))` |
| `integrations/compact-model-sources.checks.py:102` | 動的: `paths` |
| `integrations/comparison_core.checks.py:68` | 2: `[('comparison_rows', 'iac_values', 'iac_evaluation'), ('iac_evaluation', 'iac_values', 'comparison_rows')]` |
| `integrations/eventbridge-producer-name-reference.checks.py:105` | 3: `[('lambda', 'Lambda.Function', 'FunctionName'), ('sqs', 'SQS.Queue', 'QueueName'), ('iam', 'IAM.User', 'UserName')]` |
| `integrations/glue_datazone_catalog.checks.py:29` | 2: `((glue, glue_model), (datazone, datazone_model))` |
| `integrations/group-03-input-references.checks.py:128` | 2: `[('iam', 'IAM.InstanceProfile', 'IAM.InstanceProfile.InstanceProfileName'), ('kms', 'KMS.Key', None)]` |
| `integrations/human-inputs-group-05.checks.py:289` | 動的: `sorted(SERVICES)` |
| `integrations/issue_gate.checks.py:39` | 3: `('issues.md', 'iac-issues.md', 'diff.md')` |
| `integrations/issue_gate.checks.py:128` | 3: `('- `dev/cde/s3`', '- `all`', '- `dev/cde/ec2`\n- `dev/cde/ec2`')` |
| `integrations/issue_gate.checks.py:53` | 9: `(('design', investigation, report), ('infrastructure', investigation, report), ('migration', investigation, 'model/dev/cde/ec2.properties'), ('migration', investigation + '- `infra/**`\n', report), ('migration', investigation, 'infra/dev/cde/ec2.yaml'), ('migration', investigation, f'issues/prod/cde/{name}'), ('migration', investigation.replace('## Validation scope', '## Missing scope'), report), ('migration', investigation.replace('dev/cde/ec2', 'all'), report), ('migration', investigation.replace(report, f'issues/prod/cde/{name}'), report))` |
| `integrations/issue_gate.checks.py:111` | 2: `('create-change-set', 'execute-change-set')` |
| `integrations/lambda_permission.checks.py:20` | 4: `((1, 0, False), (1, 1, False), (2, 2, False), (2, 2, True))` |
| `integrations/lambda_permission.checks.py:38` | 2: `('parentProperty', 'parentReference')` |
| `integrations/lambda_permission.checks.py:48` | 10: `((output.replace('Permission.Action', 'Permission.Id', 1), 'must not be displayed'), (output.replace('Permission.Action', 'Permission.FunctionName', 1), 'must not be displayed'), (output.replace('<!-- lambda-permission: [', '<!-- lambda-permission: broken[', 1), 'invalid Lambda Permission metadata'), (output.replace('Permission.Action', 'Lambda.Permission.Action', 1), 'Permission.*'), (output.replace('<!-- lambda-permission:', '<!-- invalid-permission:', 1), 'complete identity'), (output.replace('<!-- logical-id: Invoke1_1 -->', '', 1), 'complete identity'), (output.replace('<!-- logical-id: Invoke1_2 -->', '<!-- logical-id: Invoke1_1 -->', 1), 'duplicate grouped'), (output.replace('Permission.Principal', 'Permission.Action', 1), 'duplicate Lambda Permission'), (output.replace('[Worker1]\\u0028#lambda-app-dev-worker-1\\u0029', '[Wrong]\\u0028#lambda-wrong\\u0029', 1), 'must reference enclosing'), (output.replace('"Lambda.Permission.Id"', '"Wrong.Id"', 1), 'invalid Lambda Permission metadata'))` |
| `integrations/model_files.checks.py:124` | 4: `(0, 600, 601, 1700)` |
| `integrations/model_files.checks.py:136` | 動的: `model_parts(source)` |
| `integrations/model_files.checks.py:142` | 動的: `range(1, 111)` |
| `integrations/model_files.checks.py:155` | 動的: `__import__('model_templates').source_inputs(stack) - {root / 'project.json'}` |
| `integrations/model_files.checks.py:129` | 動的: `old - output.keys() - {source}` |
| `integrations/model_impact.checks.py:279` | 3: `[('iam', 'IAM.Role', 'RoleName'), ('s3', 'S3.Bucket', 'BucketName'), ('lambda', 'Lambda.Function', 'FunctionName')]` |
| `integrations/model_impact.checks.py:283` | 5: `[('identifiers', check_identifiers), ('type', check_type_and_unknown), ('import', check_import_scope), ('selection', check_selection), ('cycles', check_cycles)]` |
| `integrations/regression_guard.checks.py:42` | 4: `('{}', 'not JSON', '{"version":1,"salt":"00","hash":"00"}', '{"version":1,"salt":null,"hash":"00"}')` |
| `integrations/resource_mode.checks.py:55` | 3: `('EC2.VPC', 'EC2.VPCEndpoint', 'EC2.Instance')` |
| `integrations/resource_mode.checks.py:89` | 4: `('', 'REFERENCE', 'create', 'IMPORT ')` |
| `integrations/resource_mode.checks.py:94` | 3: `(marker + '\n' + marker, marker.replace('IMPORT', 'REFERENCE'), marker.replace('private_subnet_01', 'missing'))` |
| `integrations/resource_mode.checks.py:56` | 3: `(None, '取得済みresource', 'InternalId')` |
| `integrations/rotation_schedule.checks.py:84` | 2: `(1, 2)` |
| `integrations/rotation_schedule.checks.py:101` | 動的: `list(metadata)` |
| `integrations/rotation_schedule.checks.py:105` | 動的: `enumerate((('Key', 'first'), ('Value', 'one'), ('Key', 'second'), ('Value', 'two')), 1)` |
| `integrations/rotation_schedule.checks.py:110` | 動的: `enumerate((('Key', 'first'), ('Value', 'one'), ('Key', 'second'), ('Value', 'two')))` |
| `integrations/rotation_schedule.checks.py:118` | 2: `('parentReference', 'parentProperty')` |
| `integrations/rotation_schedule.checks.py:122` | 4: `('[Missing](#missing)', '[Secret1](elsewhere.md#secretsmanager-app-dev-secret-1)', '[WrongLogicalId](#secretsmanager-app-dev-secret-1)', '[Secret1Rotation](#secretsmanager-app-dev-secret-1_rotate)')` |
| `integrations/rotation_schedule.checks.py:127` | 3: `(('desired.resource.002.parentProperty', ROTATION + '.Id'), ('desired.row.002-003.value', '[Secret2](#secretsmanager-app-dev-secret-2)'), ('desired.row.002-003.value', '[Wrong](#secretsmanager-app-dev-secret-1)'))` |
| `integrations/rotation_schedule.checks.py:132` | 1: `('002-003',)` |
| `integrations/rotation_schedule.checks.py:136` | 動的: `list(values.items())` |
| `integrations/rotation_schedule.checks.py:154` | 動的: `invalid_views` |
| `integrations/rotation_schedule.checks.py:161` | 2: `((SECRET, '001'), (ROTATION, '002'))` |
| `integrations/rotation_schedule.checks.py:179` | 2: `('001', '003')` |
| `integrations/rotation_schedule.checks.py:193` | 2: `('001', '003')` |
| `integrations/rotation_schedule.checks.py:180` | 2: `(('desired', '[Key](kms.md#kms-app-dev-key)'), ('observed', 'PENDING_DEPLOY'))` |
| `integrations/runtime-model.checks.py:39` | 動的: `range(2)` |
| `integrations/runtime-model.checks.py:43` | 3: `(template, source / 'parameters.yaml', source / 'bindings.json')` |
| `integrations/runtime-model.checks.py:52` | 3: `('instances: [', 'instances: {}\nunknown: true\n', 'instances: null\n')` |
| `integrations/security_group_tables.checks.py:106` | 2: `(no_rules, no_rules.replace(tag_line + '\n', ''))` |
| `integrations/security_group_tables.checks.py:129` | 8: `(('tcp', '443', 443, 443), ('udp', '1000-2000', 1000, 2000), ('6', '0-65535', 0, 65535), ('17', '53', 53, 53), ('icmp', 'Type=8, Code=0', 8, 0), ('58', 'Type=128, Code=0', 128, 0), ('1', 'Type=-1, Code=-1', -1, -1), ('icmpv6', 'Type=128, Code=-1', 128, -1))` |
| `integrations/security_group_tables.checks.py:194` | 動的: `bad` |
| `integrations/security_group_tables.checks.py:197` | 3: `(DESIGN.replace('\| Inbound \|', '\| invalid \|', 1), DESIGN.replace(' \| `tcp` \|', ' \| — \|', 1), DESIGN + '\n\| Direction \| IpProtocol \| Port \|\n\| --- \| --- \| --- \|\n')` |
| `integrations/service-parameter-inputs.checks.py:9` | 5: `('athena', 'codecommit', 'datazone', 'security-hub', 'sqs')` |
| `integrations/sync-existing-files.checks.py:83` | 動的: `protected` |
| `integrations/sync-existing-files.checks.py:98` | 2: `('AGENTS.md', 'README.md')` |
| `integrations/sync-existing-files.checks.py:105` | 2: `('AGENTS.md', 'README.md')` |
| `integrations/sync-existing-files.checks.py:111` | 2: `('AGENTS.md', 'README.md')` |
| `integrations/sync-existing-files.checks.py:118` | 動的: `protected` |
| `integrations/validation_scope.checks.py:164` | 3: `('dev', 'prod', 'stg')` |
| `integrations/validation_scope.checks.py:238` | 2: `({('unknown', 'cde', 'ec2')}, {('dev', 'cde', 'missing')})` |
| `integrations/validation_scope.checks.py:267` | 2: `((source.replace('EC2.Instance.InstanceType', 'EC2.Instance.EbsOptimized'), 'EbsOptimized'), (source.replace('`dev-app-cde-01`', '`UNSET`'), 'Name'))` |
| `integrations/validation_scope.checks.py:165` | 2: `('cde', 'non-cde')` |
| `integrations/validation_scope.checks.py:217` | 動的: `sorted(scope)` |
| `integrations/validation_scope.checks.py:198` | 動的: `enumerate((('InstanceId', f'[AppInstance](#ec2-{name})'), ('ImageId', '`ami-0123456789abcdef0`'), ('InstanceType', '`t3.micro`'), ('SubnetId', f'[subnet-app-{env}-{target}](vpc.md#{anchor})'), ('Tags[].Key', '`Name`'), ('Tags[].Value', f'`{name}`')), 1)` |
| `integrations/worktree_task.checks.py:440` | 12: `(check_success_and_empty, check_finalize_line_endings, check_incomplete_and_git_safety, check_dirty_base_and_retry, check_ahead_and_rebase_conflict, check_collisions_and_base_selection, check_directory_layout, check_metadata_storage, check_cleanup_failure_and_retry, check_merge_retry_and_commit_failure, check_human_approved_validation_failure, check_real_loop_integration)` |
| `units/array_display.checks.py:55` | 5: `('[0]', '[2]', '[01]', '[]', '[x]')` |
| `units/array_display.checks.py:62` | 3: `(('`[ "sg-one", "sg-two" ]`', 2), ('`["sg-one"]`', 1), ('`[]`', 1))` |
| `units/array_display.checks.py:77` | 2: `(('GuardDuty.Detector', [('Features.ONE', '`ENABLED`'), ('Features[].AdditionalConfiguration[].Name', '`nested`'), ('Features[].AdditionalConfiguration[].Status', '`ENABLED`'), ('Features.TWO', '`DISABLED`')], ['Features[1].ONE', 'Features[1].AdditionalConfiguration[1].Name', 'Features[1].AdditionalConfiguration[1].Status', 'Features[2].TWO']), ('CloudTrail.Trail', [('EventSelectors.DataResources[1].S3', '[one](#one)'), ('EventSelectors.DataResources[2].Lambda', '[two](#two)'), ('EventSelectors.IncludeManagementEvents', '`true`'), ('EventSelectors.IncludeManagementEvents', '`false`'), ('EventSelectors.DataResources[3].S3', '[three](#three)')], ['EventSelectors[1].DataResources[1].S3', 'EventSelectors[1].DataResources[2].Lambda', 'EventSelectors[1].IncludeManagementEvents', 'EventSelectors[2].IncludeManagementEvents', 'EventSelectors[2].DataResources[1].S3']))` |
| `units/array_display.checks.py:86` | 2: `(('CloudTrail.Trail', 'EventSelectors.IncludeManagementEvents', 'EventSelectors[1].IncludeManagementEvents'), ('S3.Bucket', 'BucketEncryption.BucketKeyEnabled', 'BucketEncryption[1].BucketKeyEnabled'))` |
| `units/array_display.checks.py:93` | 動的: `design_material_files(ROOT)` |
| `units/array_display.checks.py:95` | 動的: `path.read_text().splitlines()` |
| `units/check-deploy-context.checks.py:184` | 9: `(None, 123456789012, '', 'UNSET', '123', '1234567890123', ' 123456789012', '123456789012\n', '１２３４５６７８９０１２')` |
| `units/check-deploy-context.checks.py:196` | 8: `(None, 123, '', ' ', ' padded ', 'UNSET', 'bad\nprofile', 'bad\x00profile')` |
| `units/check-deploy-context.checks.py:139` | 2: `('cde', 'non-cde')` |
| `units/check-deploy-context.checks.py:169` | 2: `(False, True)` |
| `units/check-deploy-context.checks.py:140` | 2: `(False, True)` |
| `units/cloudformation_schema.checks.py:24` | 2: `(('IAM.Role', 'Description', ('Role for application logs', 'Cafe café ¡ÿ', 'tab\tline\nreturn\r', 'quotes \'" and ?%\\'), ('日本語の説明', 'emoji 😀', 'bad\x00', 'bad\x1f', 'bad\x7f', 'bad\x80', 'bad\xa0', 'badĀ', 'text\n日本語')), ('EC2.SecurityGroup', 'GroupDescription', ('Application access', 'aZ09 ._-:/()#,@[]+=&;{}!$*'), ('日本語の説明', 'café', 'tab\t', 'line\n', 'return\r', "quote'", 'quote"', 'question?', 'percent%', 'backslash\\', 'pipe\|', 'text\n日本語')))` |
| `units/cloudformation_schema.checks.py:44` | 2: `(('Events.Rule', 'EventPattern'), ('IAM.User', 'Policies[].PolicyDocument'))` |
| `units/cloudformation_schema.checks.py:53` | 7: `(({'type': ['object', 'array']}, ('{}', '[]'), ('42', 'true', '"text"', '{invalid')), ({'type': ['boolean', 'null']}, ('false', 'true', 'null'), ('0', '"null"', '{}')), ({'type': ['string', 'integer'], 'minimum': 2, 'minLength': 3}, ('2', 'abc'), ('1', 'ab')), ({'type': ['string', 'boolean'], 'enum': [False]}, ('false',), ('true', 'text')), ({'type': ['integer', 'number'], 'maximum': 3}, ('2', '2.5'), ('4', 'true')), ({'type': ['object', 'string'], 'const': {'enabled': True}}, ('{"enabled":true}',), ('{}', 'text')), ({'type': ['object', 'string'], 'pattern': '^allowed$'}, ('{}', 'allowed'), ('other',)))` |
| `units/cloudformation_schema.checks.py:91` | 動的: `{'IAM.User': ('UserName', 'Groups', 'LoginProfile.Password', 'LoginProfile.PasswordResetRequired', 'ManagedPolicyArns', 'Path', 'PermissionsBoundary', 'Policies[].PolicyName', 'Policies[].PolicyDocument', 'Tags[].Key', 'Tags[].Value'), 'SecretsManager.Secret': ('Type',), 'SecretsManager.RotationSchedule': ('ExternalSecretRotationMetadata[].Key', 'ExternalSecretRotationMetadata[].Value', 'ExternalSecretRotationRoleArn'), 'GuardDuty.MalwareProtectionPlan': ('Actions.Tagging.Status', 'ProtectedResource.S3Bucket.BucketName', 'ProtectedResource.S3Bucket.ObjectPrefixes[]', 'Role', 'Tags[].Key', 'Tags[].Value')}.items()` |
| `units/cloudformation_schema.checks.py:148` | 動的: `{'Glue.Connection': 'ConnectionInput ConnectionInput.AuthenticationConfiguration ConnectionInput.PhysicalConnectionRequirements ConnectionInput.AthenaProperties', 'Glue.Catalog': 'FederatedCatalog', 'Athena.WorkGroup': 'WorkGroupConfiguration WorkGroupConfiguration.EngineVersion WorkGroupConfiguration.ResultConfiguration WorkGroupConfiguration.ResultConfiguration.EncryptionConfiguration', 'LakeFormation.PrincipalPermissions': 'Catalog Permissions PermissionsWithGrantOption Principal Resource Principal.DataLakePrincipalIdentifier Resource.Catalog Resource.Database Resource.Table Resource.TableWithColumns Resource.Database.CatalogId Resource.Database.Name Resource.Table.CatalogId Resource.Table.DatabaseName Resource.Table.Name Resource.Table.TableWildcard Resource.TableWithColumns.CatalogId Resource.TableWithColumns.DatabaseName Resource.TableWithColumns.Name Resource.TableWithColumns.ColumnNames Resource.TableWithColumns.ColumnWildcard Resource.TableWithColumns.ColumnWildcard.ExcludedColumnNames', 'QuickSight.DataSource': 'Credentials.KeyPairCredentials Credentials.KeyPairCredentials.KeyPairUsername Credentials.KeyPairCredentials.PrivateKey Credentials.KeyPairCredentials.PrivateKeyPassphrase'}.items()` |
| `units/cloudformation_schema.checks.py:162` | 2: `('DataCatalog.DatabaseName', 'DataCatalog.TableName')` |
| `units/cloudformation_schema.checks.py:176` | 8: `('Name', 'FlexibleTimeWindow.Mode', 'ScheduleExpression', 'ScheduleExpressionTimezone', 'Target.Arn', 'Target.RoleArn', 'Target.Input', 'Target.RetryPolicy.MaximumRetryAttempts')` |
| `units/cloudformation_schema.checks.py:185` | 動的: `{'EC2.VPCBlockPublicAccessOptions': 'AccountId InternetGatewayBlockMode', 'EC2.VPCBlockPublicAccessExclusion': 'ExclusionId InternetGatewayExclusionMode VpcId SubnetId Tags[].Key Tags[].Value', 'Organizations.Policy': 'Id Name Type Content TargetIds', 'FMS.Policy': 'Id PolicyName IncludeMap.ACCOUNT IncludeMap.ORGUNIT ExcludeMap.ACCOUNT ExcludeResourceTags RemediationEnabled SecurityServicePolicyData.Type SecurityServicePolicyData.ManagedServiceData', 'SSM.PatchBaseline': 'Id Name OperatingSystem DefaultBaseline PatchGroups ApprovalRules.PatchRules[].ApproveAfterDays ApprovalRules.PatchRules[].PatchFilterGroup.PatchFilters[].Key', 'SSM.Association': 'AssociationId AssociationName Name Parameters Targets[].Key ScheduleExpression', 'SSM.MaintenanceWindow': 'WindowId Name Schedule ScheduleTimezone Duration Cutoff AllowUnassociatedTargets', 'SSM.MaintenanceWindowTarget': 'WindowTargetId WindowId Name ResourceType Targets[].Key', 'SSM.MaintenanceWindowTask': 'WindowTaskId WindowId Name TaskArn TaskType Targets[].Key TaskInvocationParameters.MaintenanceWindowRunCommandParameters.Parameters', 'Config.ConfigRule': 'ConfigRuleId ConfigRuleName Source.Owner Source.SourceIdentifier Source.CustomPolicyDetails.PolicyText Scope.ComplianceResourceTypes InputParameters EvaluationModes[].Mode'}.items()` |
| `units/cloudformation_schema.checks.py:206` | 4: `(('EC2.VPCBlockPublicAccessOptions', 'InternetGatewayBlockMode', 'block-bidirectional'), ('EC2.VPCBlockPublicAccessExclusion', 'InternetGatewayExclusionMode', 'allow-egress'), ('Organizations.Policy', 'Type', 'SERVICE_CONTROL_POLICY'), ('SSM.PatchBaseline', 'OperatingSystem', 'AMAZON_LINUX_2023'))` |
| `units/cloudformation_schema.checks.py:33` | 2: `(resource_type, catalog.canonical_type(resource_type))` |
| `units/cloudformation_schema.checks.py:48` | 3: `('{"source":["aws.ec2"]}', 'plain string', '{invalid json')` |
| `units/cloudformation_schema.checks.py:63` | 動的: `accepted` |
| `units/cloudformation_schema.checks.py:65` | 動的: `rejected` |
| `units/cloudformation_schema.checks.py:121` | 動的: `properties` |
| `units/cloudformation_schema.checks.py:156` | 動的: `paths.split()` |
| `units/cloudformation_schema.checks.py:201` | 動的: `paths.split()` |
| `units/cloudformation_schema.checks.py:34` | 動的: `accepted` |
| `units/cloudformation_schema.checks.py:36` | 動的: `rejected` |
| `units/comparison_core-unit.checks.py:37` | 3: `(trail_rows, trail_rows[::-1], trail_rows[::2] + trail_rows[1::2])` |
| `units/comparison_core-unit.checks.py:41` | 4: `(trail_rows[:3], trail_rows + [(trail_rows[0][0], dict(trail_rows[0][1], value='`false`'))], [('unknown', trail_rows[0][1]), *trail_rows[1:]], [(trail_rows[0][0], dict(trail_rows[0][1], property=trail_kind + 'EventSelectors[1].IncludeManagementEvents')), *trail_rows[1:]])` |
| `units/comparison_core-unit.checks.py:51` | 6: `[([('A', 1), ('B.C', None)], {'A': 1, 'B': {'C': None}}), ([('A[].K', 'a'), ('A[].V', 1), ('A[].K', 'a'), ('A[].V', 2)], {'A': [{'K': 'a', 'V': 1}, {'K': 'a', 'V': 2}]}), ([('A[2].K', 'b'), ('A[1].K', 'a')], {'A': [{'K': 'a'}, {'K': 'b'}]}), ([('A[]', [1, 1]), ('A[]', 2), ('B', 1), ('B', [2, 2])], {'A': [1, 1, 2], 'B': [1, 2, 2]}), ([('A[1].B[]', [1, 1]), ('A[2].B[]', [])], {'A': [{'B': [1, 1]}, {'B': []}]}), ([('A[2]', 'same'), ('A[1]', 'same')], {'A': ['same', 'same']})]` |
| `units/comparison_core-unit.checks.py:60` | 動的: `rows` |
| `units/comparison_core-unit.checks.py:81` | 3: `(rows, list(reversed(rows)), sorted(rows))` |
| `units/comparison_core-unit.checks.py:83` | 動的: `ordered` |
| `units/comparison_core-unit.checks.py:86` | 5: `('A[].B[].K', 'A[].B[1].K', 'A[1].B[].K', 'A[].B[]', 'A[0].K')` |
| `units/comparison_core-unit.checks.py:98` | 7: `[(True, 1), (1, 1.0), ('1', 1), (None, ''), ({}, []), ([1, 2], [2, 1]), ([1, 1], [1])]` |
| `units/comparison_core-unit.checks.py:159` | 6: `[(select(0, getatt('UnknownLength')), 'index 0, symbolic array minItems=0'), (select(1, getatt('DnsEntries')), 'index 1, symbolic array minItems=1'), (select(0, getatt('UnknownType')), 'array type is unproven'), (select(1, split), 'index 1, symbolic array minItems=1'), (select(getatt('Name'), ['a']), 'index is unproven'), ({'Fn::Split': [':', select(0, getatt('UnknownElement'))]}, 'string type is unproven')]` |
| `units/comparison_core-unit.checks.py:168` | 18: `[select(2, getatt('DnsEntries')), select(0, getatt('Name')), select(True, ['a']), select(-1, ['a']), select(1.0, ['a']), select('x', ['a']), select(1, ['a']), select(0, []), select(0, [None]), select(0, {}), {'Fn::Select': [0]}, {'Fn::Split': [':', getatt('DnsEntries')]}, {'Fn::Split': [':', select(0, getatt('Numbers'))]}, {'Fn::Split': ['', 'text']}, {'Fn::Split': [1, 'text']}, {'Fn::Split': [':', None]}, {'Fn::Split': [':']}, {'Fn::Join': ['', [select(0, getatt('Numbers'))]]}]` |

| `units/update-catalog-lock.checks.py:28` | 動的: `(PurePosixPath, PureWindowsPath)` |
| `units/update-catalog-lock.checks.py:29` | 動的: `names` |
| `units/update-catalog-lock.checks.py:32` | 動的: `MODULE.catalog_files()` |

| `integrations/design_catalog.checks.py:82` | 動的: `zip(bad_values, expected_errors, strict=True)` |
| `integrations/design_catalog.checks.py:84` | 動的: `values.items()` |
| `integrations/design_catalog.checks.py:28` | 動的: `VALUES.items()` |
| `integrations/design_catalog.checks.py:29` | 動的: `VALUES.items()` |
| `integrations/design_catalog.checks.py:88` | 動的: `expected` |
| `integrations/design_catalog.checks.py:88` | 動的: `errors` |

## IT 実行グループの完了記録

279関数・357パターンとは別の19実行グループ。direct_groupは既存main入口、moduleは既存トップレベルの最終到達地点を記録する。独立検証関数数には加算しない。

| 元パス | 入口 | 分類 | 現在の配置 | 実行方式 / グループ数 |
| --- | --- | --- | --- | --- |
| `compact-model-sources.checks.py` | `__module__` | IT | [group](integrations/compact-model-sources.checks.py) | module / 1 |
| `comparison_core.checks.py` | `__module__` | IT | [group](integrations/comparison_core.checks.py) | module / 1 |
| `design_catalog.checks.py` | `main` | IT | [group](integrations/design_catalog.checks.py#L15) | direct_group / 1 |
| `eventbridge-producer-name-reference.checks.py` | `__module__` | IT | [group](integrations/eventbridge-producer-name-reference.checks.py) | module / 1 |
| `export-design-pdf.checks.py` | `main` | IT | [group](integrations/export-design-pdf.checks.py) | direct_group / 1 |
| `glue_datazone_catalog.checks.py` | `main` | IT | [group](integrations/glue_datazone_catalog.checks.py#L15) | direct_group / 1 |
| `group-03-input-references.checks.py` | `__module__` | IT | [group](integrations/group-03-input-references.checks.py) | module / 1 |
| `issue_gate.checks.py` | `main` | IT | [group](integrations/issue_gate.checks.py) | direct_group / 1 |
| `lambda_permission.checks.py` | `main` | IT | [group](integrations/lambda_permission.checks.py#L15) | direct_group / 1 |
| `quicksight-display.checks.py` | `main` | IT | [group](integrations/quicksight-display.checks.py) | direct_group / 1 |
| `regression_guard.checks.py` | `main` | IT | [group](integrations/regression_guard.checks.py) | direct_group / 1 |
| `resource_mode.checks.py` | `main` | IT | [group](integrations/resource_mode.checks.py#L15) | direct_group / 1 |
| `rotation_schedule.checks.py` | `main` | IT | [group](integrations/rotation_schedule.checks.py#L46) | direct_group / 1 |
| `runtime-model.checks.py` | `__module__` | IT | [group](integrations/runtime-model.checks.py) | module / 1 |
| `security_group_tables.checks.py` | `main` | IT | [group](integrations/security_group_tables.checks.py) | direct_group / 1 |
| `service-parameter-inputs.checks.py` | `__module__` | IT | [group](integrations/service-parameter-inputs.checks.py) | module / 1 |
| `validate-blueprint.checks.py` | `main` | IT | [integrations/validate-blueprint.checks.py:15](integrations/validate-blueprint.checks.py#L15) | direct_group / 1 |
| `validation_cache.checks.py` | `check_producer_inputs` | IT | [producer inputs](integrations/validation_cache.checks.py#L46) | direct_group / 1 |
| `validation_cache.checks.py` | `main` | IT | [group](integrations/validation_cache.checks.py) | direct_group / 1 |
`model_templates.checks.py::check_expansion` also checks a substantive shared trust-policy change in both consumer outputs and unchanged regeneration bytes/exit status.

## 契約・公開処理の通常責務

| 元パス | ケース | 分類 | 現在の配置 | 実行方式 / 展開数 | 検証責務 | 変更 |
|---|---|---|---|---|---|---|
| `integrations/task_contract.checks.py:204` | `check_atomic_output_rollback` | IT | [integrations/task_contract.checks.py:204](integrations/task_contract.checks.py#L204) | pytest / 1 | 通常の契約・保存・変更検出を維持 | 予約専用検証を除去し既存assertを整理 |
| `units/task-contract-unit.checks.py:96` | `check_task_change_rolls_back_publication` | UT | [units/task-contract-unit.checks.py:97](units/task-contract-unit.checks.py#L97) | pytest / 3 | scope/completed/suspendへの処理中変更とrollbackを確認 | 予約専用検証を除去し既存assertを整理 |
| `units/task-contract-unit.checks.py:114` | `check_publication_preserves_contract` | UT | [units/task-contract-unit.checks.py:118](units/task-contract-unit.checks.py#L118) | pytest / 3 | running/completed/suspendの3条件で拒否時の既存・新規・削除対象不変を確認 | 予約専用検証を除去し既存assertを整理 |
| `units/task-contract-unit.checks.py:131` | `check_source_guard_keeps_plan_consistency` | UT | [units/task-contract-unit.checks.py:158](units/task-contract-unit.checks.py#L158) | pytest / 1 | 通常の契約・保存・変更検出を維持 | 予約専用検証を除去し既存assertを整理 |
| `units/task-contract-unit.checks.py:148` | `check_scope_change_during_planning` | UT | [units/task-contract-unit.checks.py:175](units/task-contract-unit.checks.py#L175) | pytest / 1 | 通常の契約・保存・変更検出を維持 | 予約専用検証を除去し既存assertを整理 |

| `unknown/issues_scan.checks.py:602` | `check_comparison_repair` | IT | [integrations/issues_scan.checks.py:1551](integrations/issues_scan.checks.py#L1551) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:717` | `check_local_reference` | IT | [integrations/issues_scan.checks.py:1554](integrations/issues_scan.checks.py#L1554) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:803` | `check_symbolic_string` | IT | [integrations/issues_scan.checks.py:1563](integrations/issues_scan.checks.py#L1563) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:903` | `check_reference_property_contract` | IT | [integrations/issues_scan.checks.py:1560](integrations/issues_scan.checks.py#L1560) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:1003` | `check_reference_diagnostics` | IT | [integrations/issues_scan.checks.py:976](integrations/issues_scan.checks.py#L976) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:1133` | `check_reference_identity_report` | IT | [integrations/issues_scan.checks.py:1557](integrations/issues_scan.checks.py#L1557) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:1514` | `check_action_report` | IT | [integrations/issues_scan.checks.py:1525](integrations/issues_scan.checks.py#L1525) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:1613` | `check_mismatch_display` | IT | [integrations/issues_scan.checks.py:1528](integrations/issues_scan.checks.py#L1528) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:1724` | `check_state_report` | IT | [integrations/issues_scan.checks.py:1531](integrations/issues_scan.checks.py#L1531) | pytest / 1 | Model/文書の生成・保存・再読込または同期 | 配置/共有fixture分離 |
| `unknown/issues_scan.checks.py:2184` | `check_glue_secret_reference` | IT | [integrations/issues_scan.checks.py:1654](integrations/issues_scan.checks.py#L1654) | pytest / 1 | 複数コンポーネント、参照または永続化の連携 | 配置/共有fixture分離 |

| `model-validation-reuse` | `check_common_conditions_preserved` | IT | [integrations/model-validation-reuse.checks.py:94](integrations/model-validation-reuse.checks.py#L94) | pytest / 7 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |
| `model-validation-reuse` | `check_read_scope_lifetime` | IT | [integrations/model-validation-reuse.checks.py:135](integrations/model-validation-reuse.checks.py#L135) | pytest / 1 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |
| `model-validation-reuse` | `check_deferred_guard_and_cleanup` | IT | [integrations/model-validation-reuse.checks.py:164](integrations/model-validation-reuse.checks.py#L164) | pytest / 1 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |
| `model-validation-reuse` | `check_generation_failures_never_pass` | IT | [integrations/model-validation-reuse.checks.py:194](integrations/model-validation-reuse.checks.py#L194) | pytest / 4 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |
| `model-validation-reuse` | `check_single_and_parallel_threads` | IT | [integrations/model-validation-reuse.checks.py:223](integrations/model-validation-reuse.checks.py#L223) | pytest / 1 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |
| `model-validation-reuse` | `check_authorization_before_memo_and_publication` | IT | [integrations/model-validation-reuse.checks.py:255](integrations/model-validation-reuse.checks.py#L255) | pytest / 1 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |
| `model-validation-reuse` | `check_scoped_validation_threads_and_failures` | IT | [integrations/model-validation-reuse.checks.py:281](integrations/model-validation-reuse.checks.py#L281) | pytest / 1 | Model入力・生成候補・保存済み設計の連携 | 新規合成回帰 |

## Static Mapping sharing acceptance

| Source | Case | Layer | Implementation | Execution / count | Responsibility | Change |
| --- | --- | --- | --- | --- | --- | --- |
| `static-aws-mappings` | `check_import_and_owners_are_lazy` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L172) | pytest / 1 | 静的索引・遅延共有・失敗保持・default互換を独立fixtureで検証 | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_runtime_cache` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L211) | pytest / 1 | 現行Mappingの遅延読取・provider/root/scope分離・再利用（ファイル破損条件を削除） | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_parallel_services` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L242) | pytest / 1 | 静的索引・遅延共有・失敗保持・default互換を独立fixtureで検証 | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_runtime_full_reuse` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L262) | pytest / 1 | 静的索引・遅延共有・失敗保持・default互換を独立fixtureで検証 | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_runtime_failures` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L290) | pytest / 1 | 独立したread/runtime/control例外のsingle-flight・保持・再利用（parse破損条件を削除） | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_full_failure_isolation` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L336) | pytest / 1 | 静的索引・遅延共有・失敗保持・default互換を独立fixtureで検証 | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_stage_alias` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L363) | pytest / 1 | 静的索引・遅延共有・失敗保持・default互換を独立fixtureで検証 | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_readonly_defaults` | UT | [units/aws_mapping-unit.checks.py](units/aws_mapping-unit.checks.py#L388) | pytest / 1 | standalone監査へ埋込むField.copy_defaultの独立性（Mapping default差し替えを削除） | 旧LRU/可変clone契約を置換 |
| `static-aws-mappings` | `check_sync_mapping_lifetime` | IT | [integrations/model-validation-reuse.checks.py](integrations/model-validation-reuse.checks.py#L313) | pytest / 4 | 実syncのstage作成前登録・正常/例外解除・source共有 | 新規合成回帰 |

## Integrated generation and validation cases

| Origin | Case | Class | Location | Entry / count | Responsibility | Change |
| --- | --- | --- | --- | --- | --- | --- |
| `units/sync-model-unit.checks.py` | `check_snapshot_conflict` | UT | [units/sync-model-unit.checks.py:183](units/sync-model-unit.checks.py#L183) | pytest / 1 | raw bytes矛盾・不存在・seal・列挙のguard | 新仕様の回帰 |
| `integrations/sync-model.checks.py` | `check_integrated_validator` | IT | [integrations/sync-model.checks.py:1192](integrations/sync-model.checks.py#L1192) | pytest / 2 | 同一候補の検証回数・一括入力境界・互換性・rollbackを独立fixtureで確認 | 新仕様の回帰 |
| `integrations/sync-model.checks.py` | `check_multiple_targets_barrier` | IT | [integrations/sync-model.checks.py:1373](integrations/sync-model.checks.py#L1373) | pytest / 5 | 同一候補の検証回数・一括入力境界・互換性・rollbackを独立fixtureで確認 | 新仕様の回帰 |
| `units/sync-model-unit.checks.py` | `check_framework_write_does_not_discover` | UT | [units/sync-model-unit.checks.py:383](units/sync-model-unit.checks.py#L383) | pytest / 2 | framework writeをModel探索前に拒否 | 新仕様の回帰 |
| `units/sync-model-unit.checks.py` | `check_result_reuse_is_scoped` | UT | [units/sync-model-unit.checks.py:392](units/sync-model-unit.checks.py#L392) | pytest / 1 | CheckResultの状態・キー・候補scope再利用境界 | 新仕様の回帰 |
| `units/blueprint-loop-unit.checks.py` | `check_write_validator_stops_followups` | UT | [units/blueprint-loop-unit.checks.py:474](units/blueprint-loop-unit.checks.py#L474) | pytest / 2 | 同一候補の検証回数・一括入力境界・互換性・rollbackを独立fixtureで確認 | 新仕様の回帰 |
| `units/blueprint-loop-unit.checks.py` | `check_staged_write_rejected` | UT | [units/blueprint-loop-unit.checks.py:489](units/blueprint-loop-unit.checks.py#L489) | pytest / 1 | 同一候補の検証回数・一括入力境界・互換性・rollbackを独立fixtureで確認 | 新仕様の回帰 |
| `integrations/sync-model.checks.py` | `check_normal_writer_contents` | IT | [integrations/sync-model.checks.py:350](integrations/sync-model.checks.py#L350) | pytest / 1 | 同一候補の検証回数・一括入力境界・互換性・rollbackを独立fixtureで確認 | 新仕様の回帰 |
| `units/validation_cache-unit.checks.py` | `check_retained_common_key` | UT | [units/validation_cache-unit.checks.py:66](units/validation_cache-unit.checks.py#L66) | pytest / 1 | Task読取cacheの選択・権限分離、契約内容/改行/追加/削除/selectorの最終比較 | 新仕様の回帰 |

## Framework definitions outside sync candidates

| Original | Case | Layer | Current | Execution | Responsibility | Preservation |
| --- | --- | --- | --- | --- | --- | --- |
| `integrations/sync-model.checks.py` | `check_stage_definition_sources` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L38) | pytest / 1 | 元FrameworkのSchema/Mapping/Layout/Policyとstage候補で生成・検証・投影がバイト一致し定義を不変に保つ | 新規 |
| `integrations/sync-model.checks.py` | `check_stage_candidate_isolation` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L183) | pytest / 6 | 元の正常文書を使わずstage Model/names/schema/overview/policy/linkの破損を検出する | 新規 |
| `integrations/sync-model.checks.py` | `check_stage_definition_errors` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L222) | pytest / 4 | 元FrameworkのSchema/Mapping/Naming/Layout参照エラーを握りつぶさない | 新規 |
| `integrations/sync-model.checks.py` | `check_stage_cloudformation_definitions` | IT | [integrations/sync-model.checks.py](integrations/sync-model.checks.py#L258) | pytest / 1 | CFn生成バイト一致とstage stack authorityの変更を検出し元保存値に戻らない | 新規 |

## Generation publication boundary assertion mapping

- `check_generation_counts` の回数・内容assertionはIT `check_normal_writer_contents` に統合。通常生成を別ケースで繰り返さない。
- `check_batch_input_change` はIT `check_input_mutation` と `check_publication_boundary`（契約変更を追加）へ統合。
- `check_stage_inputs_without_framework` の通常write保証はIT `check_stage_definition_sources` に統合。
- UT `check_file_rollback`、`check_publish_callback_rollback`、`check_generation_transaction_recovery` はIT `model_templates.check_transactions` の固有assertionへ統合。
- internal syncの実Git・生成・再読込はITへ移動。Fake runnerのContext/output・停止と軽量reader/Git差分判定はUTに残す。
- generated_policy seedは共有definitions_rootから1回生成。通常ケースはproject/Model/出力/契約だけをコピーし、定義変更ケースだけ専用rootを用意する。

| 元パス | 関数 | 分類 | 現在の配置 | 実行 / 条件数 | 検証責務 | 対応 |
|---|---|---|---|---|---|---|
| `units/sync-model-unit.checks.py` | `check_planned_outputs_and_boundary` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#check_planned_outputs_and_boundary) | pytest / 1 | 保存bytesのno-op選別と明示パスTask境界 | 軽量判定 |
| `units/sync-model-unit.checks.py` | `check_final_git_paths` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#check_final_git_paths) | pytest / 4 | Fake Gitの固定基準・正味差分とindex許可集合 | 軽量判定 |

| `units/sync-model-unit.checks.py` | `check_stage_dependency_selection` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#check_stage_dependency_selection) | pytest / 1 | Fake Model file listで入出向き依存と最小stageを選別 | 軽量依存選択 |

| `units/sync-model-unit.checks.py` | `check_git_baseline_fail_closed` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#check_git_baseline_fail_closed) | pytest / 1 | Fake Gitのmanaged/unborn/故障・NULパス | 軽量差分判定 |

## IMPORT Model-only統合・削除と外部証跡

新規UT 8関数/35パターン、IT 3関数/9入口パターン。Worktree直接関数は内部で統合成功・単独削除成功・完了後改変拒否の3条件を検証。既存有効ケースの削除・skipなし。旧証跡パスfixtureを外部署名receiptへ変更し、旧パスは移行テストだけに保持する。

| 元ケース | 現在の関数 | 種別 | 配置 | 入口 / 件数 | 検証責務 | 変更理由 |
|---|---|---|---|---|---|---|
| `import-resource-consolidation::check_model_operation_preserves_consumers` | `check_model_operation_preserves_consumers` | UT | [units/import-model-unit.checks.py:501](units/import-model-unit.checks.py#L501) | pytest / 2 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_model_operation_rejects_unproved_changes` | `check_model_operation_rejects_unproved_changes` | UT | [units/import-model-unit.checks.py:519](units/import-model-unit.checks.py#L519) | pytest / 9 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_model_operation_contract_scope` | `check_model_operation_contract_scope` | UT | [units/import-model-unit.checks.py:553](units/import-model-unit.checks.py#L553) | pytest / 8 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_model_operation_row_correspondence` | `check_model_operation_row_correspondence` | UT | [units/import-model-unit.checks.py:582](units/import-model-unit.checks.py#L582) | pytest / 1 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_model_operation_shape_preservation` | `check_model_operation_shape_preservation` | UT | [units/import-model-unit.checks.py:600](units/import-model-unit.checks.py#L600) | pytest / 5 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_external_completion_proof` | `check_external_completion_proof` | UT | [units/import-model-unit.checks.py:682](units/import-model-unit.checks.py#L682) | pytest / 7 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_snapshot_proof_resigning_and_cleanup` | `check_snapshot_proof_resigning_and_cleanup` | UT | [units/import-model-unit.checks.py:746](units/import-model-unit.checks.py#L746) | pytest / 1 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_model_only_publication` | `check_model_only_publication` | IT | [integrations/model-operation-publication.checks.py:36](integrations/model-operation-publication.checks.py#L36) | pytest / 6 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_import_snapshot_evidence` | `check_import_snapshot_evidence` | IT | [integrations/blueprint-loop.checks.py:785](integrations/blueprint-loop.checks.py#L785) | pytest / 2 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |
| `import-resource-consolidation::check_model_operation_integration` | `check_model_operation_integration` | IT | [integrations/worktree_task.checks.py:680](integrations/worktree_task.checks.py#L680) | direct / 1 | GitなしのModel-only統合・削除・通常編集、共有Consumer不変性、実保存とrollback | IMPORT統合・削除 |

| `sync attachment staging` | `check_linked_attachments` | UT | [units/sync-model-unit.checks.py](units/sync-model-unit.checks.py#check_linked_attachments) | pytest / 2 | ローカル添付のバイト保持、欠落リンク失敗、復元と入力変更検出 | 新規 |

## Import Inventory 汎用取得

| `import-inventory::check_partial_acquisition_cannot_complete` | `check_partial_acquisition_cannot_complete` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L604) | pytest / 1 | 部分取得失敗をPublish完了と誤認せず既存ModelとAWS非実行を維持 | Import Inventory |
| `import-inventory::check_generic_acquisition_roundtrip` | `check_generic_acquisition_roundtrip` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L627) | pytest / 1 | Adapter未登録DataZoneの取得証跡とAWS非実行Publishを連携 | Import Inventory |
| `import-inventory::check_inventory_singleflight_and_isolation` | `check_inventory_singleflight_and_isolation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_context_api_singleflight_and_failures` | `check_context_api_singleflight_and_failures` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_cloudtrail_all_model_properties` | `check_cloudtrail_all_model_properties` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_tgw_provider_and_composite_identity` | `check_tgw_provider_and_composite_identity` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_inventory_status_and_partial_retention` | `check_inventory_status_and_partial_retention` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_cloudcontrol_json_and_readonly_boundary` | `check_cloudcontrol_json_and_readonly_boundary` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_composite_identity_same_resource_only` | `check_composite_identity_same_resource_only` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_inventory_capability_outcomes` | `check_inventory_capability_outcomes` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 4 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_fetch_singleflight_and_trace` | `check_fetch_singleflight_and_trace` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_tgw_compare_provider_evaluation` | `check_tgw_compare_provider_evaluation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_legacy_adapter_api_counts` | `check_legacy_adapter_api_counts` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | 取得能力・Singleton・Identity・API回数の合成検証 | Import Inventory |
| `import-inventory::check_acquisition_account_region_isolation` | `check_acquisition_account_region_isolation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 2 | Context隔離・CLI選択・Identity不明の拒否 | Import Inventory |
| `import-inventory::check_resource_type_cli_selection` | `check_resource_type_cli_selection` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | Context隔離・CLI選択・Identity不明の拒否 | Import Inventory |
| `import-inventory::check_unknown_acquired_identity_rejected` | `check_unknown_acquired_identity_rejected` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | Context隔離・CLI選択・Identity不明の拒否 | Import Inventory |

Athena ResultConfiguration EncryptionConfiguration.KmsKey regression in `integrations/issues_failed_services.checks.py::main_checks` uses synthetic Model loading, Key Arn selection, GetAtt/ImportValue, same/different keys, rejected KeyId/AliasName/AliasArn on either/both sides, and unresolved form/identity cases. Other KMS contracts retain their existing expectations.

## Atomic Model operation contracts and API boundaries

- `units/task-contract-unit.checks.py::check_batch_operation_contract`: five pairs,
  immutable normalized contract, duplicate/mixed/
  missing/malformed declarations and JSON/pointer/scope rejection.
- `units/import-model-unit.checks.py::check_batch_model_operation`: simultaneous five-pair
  semantic comparison and failure for a single missing observed transfer.
- `units/import-model-unit.checks.py::check_intermediate_source_context`: explicit parent
  despite a different environment selector, raw read/save without expansion or staging,
  one-use/no-op/fresh context behavior, concurrent input change and path/syntax rejection.
- Existing operation preservation/rejection cases retain their assertions; verification
  now lives in `model.operations`. Existing loop scheduler tests
  import validation.loop and exercise the compatibility CLI separately. Validator shared
  fixture imports validation.runner; no test cases were deleted for module movement.
- Production source helpers now live at `framework/scripts/model/sources.py`; the existing
  fixture stays `framework/scripts/tests/support/model_sources.py`. Shared dependency
  changes conservatively select all UTs through the existing mapping fallback.

| Original case | Case | Class | Current location | Execution / count | Responsibility | Change |
| --- | --- | --- | --- | --- | --- | --- |
| `atomic/worktree_task` | `check_final_candidate_staleness` | IT | [worktree candidate](integrations/worktree_task.checks.py#L472) | direct / 1 | Real Git latest-base commit/rebase and stale base/HEAD/Task/dirty rejection; isolated loop callback | Added |
| `atomic/import-model` | `check_intermediate_model_sources` | IT | [source writes](integrations/model-operation-publication.checks.py#L93) | pytest / 1 | Git-free Model raw writes, prior-leaf retention on I/O error and real journal recovery before snapshot; managed authorization is checked separately | Added |

`units/import-model-unit.checks.py::check_explicit_reference_operation` (6 parameter cases)
covers typed local value/JSON/parentReference, external name/identifier and explicit D→D
reevaluation; undeclared changes and reference literalization fail. Existing test bodies
are retained. New IT cases use the existing Framework IT discovery/receipt runner;
no new runner or live AWS/consumer inputs are introduced.

| `atomic/batch-saves` | `check_batch_leaf_saves` | IT | [five pair saves](integrations/model-operation-publication.checks.py#L135) | pytest / 1 | transfer saves retain all five sources, empty-reference retarget is no-op, delete removes all and final semantic check passes; base unchanged | Added |

| `import/references` | `check_reference_publication` | IT | [physical reference publication](integrations/import-model.checks.py#L653) | pytest / 7 | acquired Trail scalar links and JSON Pointer references to a unique local CREATE bucket; JSON retains acquired AWS literals with external name metadata; one producer read per expansion/physical-verification permission context and unchanged API count; a producer race rolls back sources and retains the external edit | Added |

## Generic Model dependency detach

| Original case | Case | Class | Current location | Execution / count | Responsibility | Change |
| --- | --- | --- | --- | --- | --- | --- |
| `dependency/contract` | `check_dependency_detach_contract` | UT | [strict opt-in contract](units/task-contract-unit.checks.py) | pytest / 1 | exact JSON/keys/IDs/scope, malformed/duplicate/conflicting declarations; ordinary design unchanged | Added |
| `dependency/stack-usage` | `check_stack_reference_usage` | UT | [fixed-ID Stack usage](units/import-model-unit.checks.py) | pytest / 7 | synthetic Stack and Resource references, pointers/provenance, unrelated deletion meaning check, collision/missing/type/format/name/shape rejection | Added |
| `dependency/usage` | `check_generic_reference_usage` | UT | [fixed-ID usage](units/import-model-unit.checks.py) | pytest / 1 | service-a/service-b cycle, identical names with distinct IDs, source line and value, read-only state | Added |
| `dependency/shape` | `check_reference_active_shapes_and_documents` | UT | [active shapes](units/import-model-unit.checks.py) | pytest / 2 | active choice, inactive optional JSON/unused Definition, escaped JSON pointer, separate display links | Added |
| `dependency/unresolved` | `check_reference_fail_closed` | UT | [unresolved references](units/import-model-unit.checks.py) | pytest / 4 | unknown fixed ID, cyclic name expansion, broken internal link and missing input fail closed | Added |
| `dependency/delete` | `check_value_preserving_detach_and_single_deletions` | UT | [separate single deletions](units/import-model-unit.checks.py) | pytest / 1 | independent value-preserving detach followed by two unchanged single-delete checks; other environment preserved | Added |
| `dependency/preservation` | `check_refactor_rejects_changes` | UT | [preservation rejection](units/import-model-unit.checks.py) | pytest / 10 | changed value/mode/anchor/observed/foreign consumer, identical-name retarget, scope, retained/undeclared reference and CREATE reject | Added |
| `dependency/integration` | `check_model_refactor_integration` | IT | [ordinary publish and final candidate](integrations/worktree_task.checks.py#L751) | direct / 1 | ordinary design atomic publication, operation-writer rejection, one final verification, actual base producer change/rebase blocks merge and preserves worktree | Added |
| `dependency/bounded-read` | `check_reference_readonly_and_bounded_expansion` | UT | [bounded read-only API](units/import-model-unit.checks.py) | pytest / 1 | one selected-service expansion for outgoing, selected target only for incoming, pending journal refusal without Model writes | Added |
| `dependency/structure` | `check_reference_structural_and_remaining_delete` | UT | [structural and surviving references](units/import-model-unit.checks.py) | pytest / 1 | parentReference identity/role, structural detach and deletion with remaining name reference rejected | Added |
| `dependency/json-types` | `check_dependency_json_types_and_exact_detach` | UT | [exact JSON detach](units/import-model-unit.checks.py) | pytest / 1 | declared JSON leaf detach, retained sibling reference, undeclared change, boolean/number type changes, escaped marker impersonation rejection | Added |
| `dependency/link-label` | `check_reference_embedded_link_label` | UT | [embedded label reference](units/import-model-unit.checks.py) | pytest / 1 | typed name in Markdown label and link target remain distinct fixed-ID usages | Added |

The existing IT cases retain their assertions and registrations after the runtime extraction:
blueprint-loop orchestration uses the CLI and validator API boundaries; deployment fixtures
copy the complete runtime; publication races are injected at GenerationInputs.verify;
Model-only imports avoid the presentation dependency; cache comparisons unwrap both CLI
and read API scopes; saved-validation tracing excludes candidate validators; publication
failure checks allow candidate validation; shared-input saves register a synthetic Task;
partial-cache validation spies on compare_generation with the full consumer scope.

## Approved suspend integration

| 元パス | ケース | 区分 | 現在の入口 | 実行 / 件数 | 責務 | 保持内容 |
| --- | --- | --- | --- | --- | --- | --- |
| `worktree_task.checks.py` | `check_approved_model_reads` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L528) | direct / 1 | 承認済みsuspendのModel比較・証跡・Git統合 | 合成Modelで値不変/IMPORT変更拒否/有効・欠落・改竄・期限・identity・scope・未完了証跡と通常実行拒否、status保持、cleanupを検証 |

既存 `check_suspend_and_resume` に状態非依存の契約参照、通常実行拒否、selector・構造・symlink拒否を追加。

既存 `check_model_operation_integration` の3シナリオに、承認済みsuspendのmerge/delete成功と不正な値変更拒否の3シナリオを追加。
## User-selected IMPORT add / refresh / replace

| Origin | Case | Class | Location | Entry / conditions | Responsibility | Scope |
|---|---|---|---|---|---|---|
| `import-selected::check_selected_overwrite` | `check_selected_overwrite` | UT | [units/import-model-unit.checks.py:1547](units/import-model-unit.checks.py#L1547) | pytest / 2 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_overwrite_identity_and_mode_boundary` | `check_overwrite_identity_and_mode_boundary` | UT | [units/import-model-unit.checks.py:1568](units/import-model-unit.checks.py#L1568) | pytest / 4 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_overwrite_does_not_grant_unrelated_edits` | `check_overwrite_does_not_grant_unrelated_edits` | UT | [units/import-model-unit.checks.py:1578](units/import-model-unit.checks.py#L1578) | pytest / 8 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_refresh_new_rows_and_missing_properties` | `check_refresh_new_rows_and_missing_properties` | UT | [units/import-model-unit.checks.py:1601](units/import-model-unit.checks.py#L1601) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_overwrite_duplicate_selection_and_destination_identity` | `check_overwrite_duplicate_selection_and_destination_identity` | UT | [units/import-model-unit.checks.py:1616](units/import-model-unit.checks.py#L1616) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_selected_binding_switch_preserves_fixed_maps` | `check_selected_binding_switch_preserves_fixed_maps` | UT | [units/import-model-unit.checks.py:1630](units/import-model-unit.checks.py#L1630) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_overwrite_reference_permission_is_property_scoped` | `check_overwrite_reference_permission_is_property_scoped` | UT | [units/import-model-unit.checks.py:1642](units/import-model-unit.checks.py#L1642) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_import_llm_choice_contract` | `check_import_llm_choice_contract` | UT | [units/import-model-unit.checks.py:1660](units/import-model-unit.checks.py#L1660) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_user_selected_overwrite_publication` | `check_user_selected_overwrite_publication` | IT | [integrations/import-model.checks.py:782](integrations/import-model.checks.py#L782) | pytest / 6 | refresh/replace/bindの通常保存・dry-run、非選択・他環境保護 | User-selected Import |
| `import-selected::check_mixed_add_refresh_single_publication` | `check_mixed_add_refresh_single_publication` | IT | [integrations/import-model.checks.py:822](integrations/import-model.checks.py#L822) | pytest / 2 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_replace_rejects_incoming_references` | `check_replace_warns_incoming_references` | IT | [integrations/import-model.checks.py:858](integrations/import-model.checks.py#L858) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_first_resource_uses_existing_source_format` | `check_first_resource_uses_existing_source_format` | IT | [integrations/import-model.checks.py:881](integrations/import-model.checks.py#L881) | pytest / 4 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |
| `import-selected::check_refresh_switches_definition_without_foreign_changes` | `check_refresh_switches_definition_without_foreign_changes` | IT | [integrations/import-model.checks.py:915](integrations/import-model.checks.py#L915) | pytest / 1 | 選択済み更新・取得証跡・非選択保護・原子的保存 | User-selected Import |

## Resource Delete parent transaction units

`units/resource-delete-unit.checks.py` retains source deletion, identity/raw-value preservation,
reference detach/retarget, warnings, Issue Gate and failed-leaf rollback assertions.
Its authored Model helpers are shared by `support/resource_delete_fixtures.py`.
The pre-commit incomplete-leaf assertion is in Worktree guard UT; actual failed-candidate
repair, one final check, one ff-only merge and cleanup are in Worktree operation IT.
Business tests use ordinary Git or file snapshots and never create lifecycle records.


## 保存・通常統合ガード

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `guard-cache/equivalence` | `check_guard_cache_equivalence` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 12 | 最終候補のキャッシュcontext有無による結果一致、旧Model不変性を要求しない検証 | Added |
| `guard-runtime/process` | `check_registered_guard_process` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L21) | pytest / 8 | 明示Task・通常/承認contract_file、warning・非ゼロstdout/stderr、起動/runtime失敗 | Added |
| `guard-runtime/preconditions` | `check_prepare_rejects_before_git_write` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L80) | pytest / 11 | 安価な前提違反、ガード拒否、ガード中のTask/HEAD/変更をGit書込み前に拒否 | Added |
| `guard-runtime/json` | `check_cli_failure_diagnostics` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L116) | pytest / 1 | CLI JSONと子診断の分離 | Added |
| `guard-runtime/integration` | `check_registered_normal_model_guard` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py#L605) | direct / 1 | Model依存なし親・登録済みvenv子・通常ガードから実commit/merge/cleanup、pipなし | Added |

既存の承認付きsuspendのガード・証跡テストは子プロセスで実行し、拒否理由と状態保持を継続する。
dirty baseは高コスト解析・commit前に拒否するため、既存テストは未コミット内容の保持を確認する。

## Model properties v2

観測保存の単体ケースは既存 capability 型の模擬 context を使用し、Task/worktree からの権限付与を実証しない。現行 IT は合成 properties と実管理 Task による保存・Import・Deploy の経路を検査する。Import の会話品質の実証とは区別する。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `model-v2::check_scalar_spelling_and_patch` | `check_scalar_spelling_and_patch` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L17) | pytest / 1 | scalar の原文と部分更新 | Model v2 |
| `model-v2::check_json_continuation_and_types` | `check_json_continuation_and_types` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L29) | pytest / 1 | 明示 JSON 継続・native type・配列順序 | Model v2 |
| `model-v2::check_invalid_properties` | `check_invalid_properties` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L41) | pytest / 12 | 重複キー・不正定数・不正継続・暗黙継続の拒否 | Model v2 |
| `model-v2::check_unsupported_version` | `check_unsupported_version` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L47) | pytest / 4 | 未知形式と旧形式の通常読取拒否 | Model v2 |
| `model-v2::check_discovery_alias_and_account` | `check_discovery_alias_and_account` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L19) | pytest / 1 | 任意環境・複数 Alias・account・未作成 Model | Model v2 |
| `model-v2::check_runtime_metadata_is_not_authority` | `check_runtime_metadata_is_not_authority` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L53) | pytest / 1 | 観測 metadata の導出・空・不存在・PENDING_DEPLOY | Model v2 |
| `model-v2::check_parts_and_large_resource` | `check_parts_and_large_resource` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L68) | pytest / 1 | 所有 block・巨大 Resource・parts 欠番 | Model v2 |
| `model-v2::check_unsafe_parts` | `check_unsafe_parts` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L93) | pytest / 7 | 欠落・重複・未登録・逸脱・symlink・block 分割 | Model v2 |
| `model-v2::check_reference_schema_and_pointer` | `check_reference_schema_and_pointer` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L122) | pytest / 1 | 参照 schema・既存 JSON string leaf・WARNING | Model v2 |
| `model-v2::check_cli_subprocess_and_canonical_imports` | `check_cli_subprocess_and_canonical_imports` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L147) | pytest / 1 | 新 CLI の別プロセス起動・恒久 PYTHONPATH 不要・型 identity | Model v2 |
| `model-v2::check_stack_metadata_is_not_runtime_input` | `check_stack_metadata_is_not_runtime_input` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L168) | pytest / 1 | 固定 placementName と変更可能 name・不変 snapshot | Model v2 |
| `model-v2::check_observed_byte_preservation_and_one_use` | `check_observed_byte_preservation_and_one_use` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L196) | pytest / 1 | 観測のみの原文差替え・一回使い切り保存 context | Model v2 |
| `model-v2::check_source_save_conflict_and_rollback` | `check_source_save_conflict_and_rollback` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L214) | pytest / 3 | source/Task 競合の保持・I/O 失敗 rollback | Model v2 |
| `model-v2::check_observed_cannot_bypass_import_or_change_authority` | `check_observed_cannot_bypass_import_or_change_authority` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L241) | pytest / 1 | IMPORT 物理 ID 保護・非観測と未登録書込・承認 flag 拒否 | Model v2 |
| `model-v2::check_declared_and_direct_links_coalesce_or_retain_conflicts` | `check_declared_and_direct_links_coalesce_or_retain_conflicts` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L259) | pytest / 1 | 直接リンク統合・意味競合の保持・incoming・読取非破壊 | Model v2 |
| `model-v2::check_reference_occurrence_identifies_overlapping_text` | `check_reference_occurrence_identifies_overlapping_text` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L288) | pytest / 1 | 重なりを含む参照断片の厳密な出現位置 | Model v2 |
| `model-v2::check_deploy_rejects_legacy_session_format` | `check_deploy_rejects_legacy_session_format` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L53) | pytest / 6 | 旧 Deploy session の形式・snapshot・意味版の拒否 | Model v2 |
| `model-v2::check_observed_insertion_is_local_without_reflow` | `check_observed_insertion_is_local_without_reflow` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L61) | pytest / 1 | 観測キー追加削除と CRLF・無関係な原文の不変 | Model v2 |
| `model-v2::check_import_observation_foreign_reference_and_identity_spoof` | `check_import_observation_foreign_reference_and_identity_spoof` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L78) | pytest / 1 | IMPORT の外部参照観測更新・自身 ID 保護・偽装リンク拒否 | Model v2 |
| `model-v2::check_properties_import_review_operations` | `check_properties_import_review_operations` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L306) | pytest / 4 | add/refresh/bind/replace の全件 Review と固定 identity | Model v2 |
| `model-v2::check_properties_reference_review_after_map_and_ownership` | `check_properties_reference_review_after_map_and_ownership` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L335) | pytest / 4 | 完全 after map・空削除・旧新 owner・非選択保護 | Model v2 |
| `model-v2::check_properties_import_rejects_legacy_evidence` | `check_properties_import_rejects_legacy_evidence` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L373) | pytest / 4 | 旧 acquisition/Review/checkpoint/receipt の版拒否 | Model v2 |
| `model-v2::check_runtime_projection_validation_and_metadata_separation` | `check_runtime_projection_validation_and_metadata_separation` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L380) | pytest / 1 | 正本全体と派生投影・Stack metadata の分離 | Model v2 |
| `model-v2::check_stack_render_cli_uses_only_canonical_modules` | `check_stack_render_cli_uses_only_canonical_modules` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L394) | pytest / 1 | Stack render 別プロセス・model.* の型一貫性 | Model v2 |
| `model-v2::check_incoming_missing_producer_does_not_match_unrelated_metadata` | `check_incoming_missing_producer_does_not_match_unrelated_metadata` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L430) | pytest / 1 | 不在 producer の incoming が無関係な宣言を含めない | Model v2 |
| `model-v2::check_properties_normal_generation_uses_new_authority` | `check_properties_normal_generation_uses_new_authority` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L447) | pytest / 1 | 新正本からの通常生成・原文保持・stage 入力完全性 | Model v2 |
| `model-v2::check_managed_properties_save` | `check_managed_properties_save` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L488) | pytest / 13 | 実 Task・HEAD・原文・集合競合・一回保存・rollback・中断 journal | Model v2 |
| `model-v2::check_properties_context_requires_managed_running_task` | `check_properties_context_requires_managed_running_task` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L605) | pytest / 1 | 管理 worktree と running Task の保存権限 | Model v2 |
| `model-v2::check_deploy_digest_covers_all_nonobserved_authority` | `check_deploy_digest_covers_all_nonobserved_authority` | IT | [integrations/cloudformation-deploy.checks.py](integrations/cloudformation-deploy.checks.py#L2677) | pytest / 3 | display/reference/placement を含む非観測設計 digest | Model v2 |
| `model-v2::check_deploy_observed_baseline_advances_only_proven_outputs` | `check_deploy_observed_baseline_advances_only_proven_outputs` | IT | [integrations/cloudformation-deploy.checks.py](integrations/cloudformation-deploy.checks.py#L2702) | pytest / 5 | 観測差分だけの baseline 更新と同時設計変更拒否 | Model v2 |
| `model-v2::check_deploy_preparation_separates_producer_reads_from_writes` | `check_deploy_preparation_separates_producer_reads_from_writes` | IT | [integrations/cloudformation-deploy.checks.py](integrations/cloudformation-deploy.checks.py#L2731) | pytest / 1 | producer 読取依存と許可書込先の分離 | Model v2 |
| `model-v2::check_properties_import_acquire_review_publish` | `check_properties_import_acquire_review_publish` | IT | [integrations/import-model.checks.py](integrations/import-model.checks.py#L967) | pytest / 11 | 一回取得・Review・別プロセス保存・source/receipt/view rollback・強制終了回復 | Model v2 |
| `model-v2::check_properties_standalone_audit_has_no_framework_runtime` | `check_properties_standalone_audit_has_no_framework_runtime` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L615) | pytest / 1 | 独立 audit の生成・Framework import 不要・未取得 ERROR | Model v2 |
| `model-v2::check_properties_model_operation_preservation` | `check_properties_model_operation_preservation` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L644) | pytest / 6 | merge/delete の固定 identity・観測・native type・非選択保持 | Model v2 |
| `model-v2::check_properties_retarget_keeps_other_fragments_and_reference_ids` | `check_properties_retarget_keeps_other_fragments_and_reference_ids` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L684) | pytest / 6 | retarget の literal 断片・context・format・固定 refid 保持 | Model v2 |
| `model-v2::check_managed_observation_preserves_exact_authority` | `check_managed_observation_preserves_exact_authority` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L722) | pytest / 8 | 実 Task の Row whitelist・非観測不変・IMPORT 物理 ID 保護 | Model v2 |
| `model-v2::check_ordinary_properties_edit_uses_real_task_guard` | `check_ordinary_properties_edit_uses_real_task_guard` | IT | [integrations/model-properties-v2.checks.py](integrations/model-properties-v2.checks.py#L810) | pytest / 6 | 通常 design 編集と作成・固定 ID・IMPORT 構成・Task 保護 | Model v2 |

Model v2 の移行では、旧 `parameter_value` の literal 自動 backtick 化だけを廃止し、
`check_one_way_model_contract` は参照／型／IMPORT 表示の検査を保持したまま、通常 scalar の
数値風文字列・引用符・backtick を変更しない roundtrip 検査へ置き換えた。
新 Import 回帰の Review 通過は機械的整合性の証明であり、LLM の全件提示・明示保存同意・
変更時再提示・取消時未保存を対話で実証したことを意味しない。

旧 check_other_definition_input_dependencies（8 variants）は Model の Definition／optional／choice／default／template owner が廃止されたため終了した。非選択 Resource／環境の値・identity・reference の保持は check_overwrite_does_not_grant_unrelated_edits と新 canonical snapshot/Task/Review 回帰に引き継ぐ。旧 YAML 部分編集ケースは properties の原文保持・native 値・no-op へ移管し、ケースと parameter matrix を保持する。

旧 Import approval の保存 transaction 15 ケースは同じケース ID・parameter 数を維持して import-model IT へ移管した。削除済み publish_selected の Mock ではなく、実管理 worktree・取得 evidence・全件 Review・共通 publisher/receipt の競合・rollback と表示専用回復を検査する。AWS transport だけを合成に固定する。

| `model-v2::review-complete-canonical-changes` | `check_review_reports_every_canonical_change` | UT | [units/import-approval-unit.checks.py](units/import-approval-unit.checks.py) | pytest / 1 | 全正本キー・Row comment・display・service の Before/After と存在性を全件 Review に表示 | Model v2 |

Properties v2 の検査移管（検査目的と parameter matrix を維持）:

- model_files の検索・Resource group・trace・scope・Task 選択・原文不変・競合・publication cache 無効化を新 CLI／reader で検査する。旧 template parser 呼出し回数は廃止し、同一 snapshot の canonical reader 再利用と権限再確認を検査する。600 行は header を含む初回の目安になり、Resource block の途中分割をしない。
- Import の value／approval／reference の単体ケースは model.* と明示 properties fixture へ移管する。参照の selector／template provenance は固定 producer identity／consumerKey／pointer／format／property／labelPolicy に置き換える。別環境への暗黙展開や未使用 Definition の生成は存在しない。
- Model merge の optional／choice／optional-json は、対応する明示 Row／document の完全転送と他環境不変を検査する。Stack の Resource 混在は Stack schema の構造不正、形式不正は失敗、producer 不在・名前不一致は WARNING として区別する。
- 保存値を再展開しないため参照の循環自体は失敗ではない。有限の読取りと値の不変を検査する。内部 marker は文字列ではないため、JSON の NUL 文字列が marker を偽装できないことと、native 値の変更禁止を検査する。
- retarget／delete の固定 identity、同値の表示でも異なる producer、JSON sibling・型・配列順序、複数 leaf、one-use、第五保存 rollback、親 Task の未完・最新 base・修復後一回統合のケースを新共通保存 API に移管する。旧 bindings は固定 metadata、unused input は未申告の正本情報へ置換する。

サービス fixture は共有入力や tpl を生成せず、環境ごとに全値を明記した properties を作る。サービス別の型・Policy・配列・投影・変更箇所の検査は継続し、廃止された入力 grammar の負例は正本キー／必須 Row／strict JSON／正式 schema の検査へ移管する。文字列の正式 Property（例: Route53 TTL）は数値風の表記から型推測しない。producer／context の変更は参照 WARNING と保存値不変を検査し、必要な値・metadata の変更を明示した候補で照合する。


## Properties v2 reference and Import assertion mapping

既存の関数名・入口数と固定 Resource/Row ID を維持する。旧展開文法だけの検査は
普通の properties と `desired.reference` の構造・所有者・使用位置の検査へ置き換える。
無効な構文・未知形式・範囲違反・I/O を参照 WARNING に読み替えない。

| 既存ケース | 現在の検査対象・保持する assertion |
| --- | --- |
| `import-model` の全108 pytest instances | canonical 候補の add／refresh／bind／replace／混在、全件 Review、非選択/CREATE/固定 identity/別環境の保持、実保存1回、外部変更拒否、source と receipt の rollback、表示のみ復旧、別プロセスの単一 CLI |
| `check_model_only_publication` / `check_intermediate_model_sources` / `check_batch_leaf_saves` | Gitなしの状態Providerと一回使い切り context / prepare/publish API、限定操作・通常編集の境界、一次保存と最終検証の分離、5組の転送→未削除状態→削除完了、base 不変、journal 復旧。親の完了は final-candidate の別ケースで検査 |
| `check_reference_publication` | scalar保存リンクとJSON物理値＋外部name参照のJSON Pointer、宣言/直接リンクの重複排除、read_context ごとの producer 読取再利用、読取依存の競合で source/receipt 復元、producer 外部変更の保持、再取得なしの表示復旧 |
| raw-bucket / producer-identifier と各 schema UT | 正式 Property、固定 ID、backtick・JSON native type/順序、raw name と observed identifier、空/不存在/PENDING の区別、labelPolicy と必要/禁止フィールド。型・名前・識別子の不一致や producer 不在は値を保持して WARNING |
| CloudTrail / Lambda / Security Group / Group 03 / EventBridge / producer-name | 旧サービス/Resource/Row と case・suffix・固定ラベル・親子/逆リンクを保持。producer の変更による consumer 値の自動展開を廃止し、保存値不変・WARNING・producer 原文依存 hash の変化を検査 |
| attribute `check_pair` / `check_fixed_label` / `check_stack` | 相互保存リンク・固定ラベル・厳密 JSON・Stack name と placementName の区別、参照 trace、未知形式/重複キーの読取時エラーと書込ゼロ、欠落 producer の WARNING、固定 snapshot の再利用と fresh 照合 |
| attribute `check_preparation_cache` | 同一 snapshot の2 Resource読取で物理 parser 1回、途中外部変更で旧 snapshot 不変、次の snapshot で変更可視、欠落入口の I/O エラーと原文復元 |
| 旧属性展開 cycle の拒否 | 展開 engine を廃止したため evaluator cycle は存在しない。相互に保存された Resource/Stack/name 参照が再帰せず、値・原文を自動変更しないことへ移行 |
| 旧 producer 変更による design digest 変化 | 設計 digest は対象 Model の observed を除く全正本。producer/comment/observed の変更は完全な読取依存 snapshot の hash/照合で検知し、consumer の設計 digest と保存値は不変 |
| producer-name の CodeBuild→Logs 直接リンク | 直接 Markdown リンクも依存として追跡するため、IAM→Logs→CodeBuild の affected 集合を検査する |

旧 template selector/input schema の廃止と実保存保護の削除を混同しない。
ここでの Review と対話規約検査は合成 fixture／文書契約の検査であり、実際の LLM と
Human の対話品質・全件提示・最終保存同意を実証したという意味ではない。


旧 `units/model_templates-unit.checks.py::check_template_syntax` は template DSL 専用のため廃止した。
7入力のうち旧 optional/choice/boolean 宣言文法3件は削除済み engine と共に廃止し、
JSON Pointer の負数・先頭0・不正escape・非文字列は model-format v2 と reference schema
UT/IT で引き続き拒否する。transaction、競合、固定 identity、親子、保存権限のケースは
この廃止対象に含めない。

`json-yaml-document-hash` は parameters 保存を廃止し、同じ2環境・Resource/Rowと
JSON型/配列順序を実管理 worktree の prepare/publish、no-op bytes、派生hash traceで確認する。
`used-definition-inputs` は暗黙の共有入力の廃止を、同値の Resource を別々に編集する保存検査へ移行した。
`compact-model-sources` の rollback は共有 journal transaction の機械的検査であり、
公開保存権限は別の実管理 context ITで検査する。`runtime-model` は実在入口だけの discovery と
登録targetからの自動生成不存在、原文snapshot、環境独立性、旧形式拒否を検査する。


Properties v2 の scope/discovery は登録環境名 `templates` / `parameters` も通常の環境名として扱い、現行propertiesのパス・形式・part集合を検証する。

`model_templates` IT の9入口は properties v2 へ移行した。実 journal の部分書込・callback・
process-death・復元失敗・CRLF/no-op、固定 Role 数2/5・Row ID・JSONポリシー生成、parts/scope、
参照 chain と旧 graph、immutable snapshot、明示作成、scalar原文、sync/newline/driftを保持する。
旧 optional/choice engine の振舞いは、明示的な最小/完全 authority の JSON型・配列順・
派生hashと構造異常へ置き換える。共通 transaction の fixture は公開保存権限を発行しない。


Properties v2 の追加移行対応（model-properties-v2）:
- `model_impact` の8入口は保存済み参照の保守的な推移閉包を検査する。旧展開 engine の
  attribute 単位の最小 scope 最適化は廃止し、実際の宣言／直接リンクだけを追う。
  固定 producer の不在、削除前 graph、環境独立、循環、IMPORT の Resource 単位の差分検査は維持する。
- `model-validation-reuse` は原文変更・権限取消・各 validator・thread isolation・例外後の cleanup を維持する。
  view だけの保存後は同じ正本 snapshot を再利用し、同一 permission/input context 内の再解析を抑止する。
- `validation_cache` は新 index/parts の原文と依存 Model・project の bytes を検査する。
  コメントや observed の変更は完全 snapshot を変え、設計 digest は canonical な非 observed 値だけを使う。
- `human-inputs-group-05` は3サービスの明示 properties、native JSON、固定 ID、環境独立、
  派生 hash と実管理 Task の保存／no-op／拒否を検査する。廃止した template 入力 enum/default/choice
  の旧検査を新 properties の型推測・暗黙値展開として残さない。
- `model_design` の既存表示・命名・サービス単位の失敗保持／rollback と `issues_scan` の
  gate／全件比較／保存失敗／マスク／参照・配列の意味の検査は canonical fixture へ移行する。
- `sync-model` は saved reference の意味・stage の producer 観測値・cold worker・原文不変と
  source/Task/file-set 競合・複数対象の保存 barrier を維持する。
- `check_shared_snapshot_parses_each_producer_once_and_rechecks_permission` は相互参照を持つ合成 Model を
  同じ入力 snapshot で一回ずつ解析し、権限 context 変更時は分離、取消後は cached read も拒否する。

これらは開発中の focused/offline 検査であり、最終 Full／全体 IT／local integration の代用ではない。

Model v2 の原文取得 cache は Model ごとの raw snapshot と参照診断済み投影を分離し、
同じ入力・permission context 内の producer を再解析しない。incoming は全登録 Model の
正本構造を検査し、要求 producer に関係する使用箇所だけを解決する。関係のない参照の
producer を読まず、構文・I/O・scope の不正を WARNING へ握り潰さない。相対 Markdown の
環境／target／dotted service は固定 scope として保持し、root 外への逸脱を拒否する。
旧平置き Model/Import の20 module/CLI を廃止した。旧 reader は移行 export の隔離子プロセスだけで使う。

| Case ID | Function | Level | Source | Mode / Count | Responsibility | Group |
| --- | --- | --- | --- | --- | --- | --- |
| `model-v2::macie-authority` | `check_macie_renders_current_document_without_artifact_reads` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L111) | pytest / 6 | Inline bucketCriteria and missing/stale/broken JSON never overrides the current document or changes properties bytes | Model v2 |
| `model-v2::display-diagnostics` | `check_shared_display_selection_and_diagnostics` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L158) | pytest / 5 | Nameless IMPORT type, root name, explicit fallback label, rule-table and grouped KMS alias share final display selection | Model v2 |

## Shared JSON compatibility

| Case ID | Entry | Class | File | Execution | Responsibility | Origin |
| --- | --- | --- | --- | --- | --- | --- |
| json-format/parse | check_parse | UT | [JSON](units/json-format.checks.py) | pytest / 4 | Model/Policy native values and Unicode | Added |
| json-format/errors | check_errors | UT | [JSON](units/json-format.checks.py) | pytest / 12 | Exact duplicate/constant/syntax messages | Added |
| json-format/overflow | check_model_overflow_only | UT | [JSON](units/json-format.checks.py) | pytest / 3 | Model rejects overflow; Policy retains infinity | Added |
| json-format/bytes | check_output_bytes_and_hashes | UT | [JSON](units/json-format.checks.py) | pytest / 1 | Fixed pre-refactor UTF-8 bytes and distinct hashes | Added |
| json-format/exports | check_compatibility_exports | UT | [JSON](units/json-format.checks.py) | pytest / 1 | Existing public exports remain identical | Added |
| json-format/isolation | check_isolated_imports_and_standalone_audit | UT | [JSON](units/json-format.checks.py) | pytest / 4 | Fresh isolated imports and standalone audit parser | Added |

| `model-v2::type-display-constraints` | `check_type_display_constraints` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L195) | pytest / 4 | Multiple resources, required names and grouped resources retain type-display restrictions | Model v2 |
| `model-v2::resource-acquisition-scope` | `check_resource_acquisition_scope` | UT | [units/model-format-v2.checks.py](units/model-format-v2.checks.py#L211) | pytest / 12 | Adapter, SDK and Cloud Control guard direct and cached access across environment and Alias | Model v2 |

## Invocation-local reference diagnostic parsing

| 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 |
|---|---|---|---|---|
| `existing-ut-inventory` | `check_diagnose_lazy_parsing_and_exact_results` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py) | pytest / 2 | name/identifier の解析回数、警告順序・内容・依存全体、戻り値の変更分離 |
| `existing-ut-inventory` | `check_diagnose_producers_are_separate` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py) | pytest / 1 | 実 producer 解決で snapshot/prefix 分離 |
| `existing-ut-inventory` | `check_diagnose_does_not_parse_unused_rows` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py) | pytest / 6 | 空入力・不存在・早期分岐で不正 row を先行解析しない |
| `existing-ut-inventory` | `check_diagnose_errors_propagate` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py) | pytest / 1 | 不正宣言・使用 row・解析例外の伝播 |
| `existing-ut-inventory` | `check_diagnose_fresh_inputs_in_outer_context` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py) | pytest / 1 | outer input_context 内の診断間変更・削除・追加と snapshot 保持 |
| `existing-ut-inventory` | `check_diagnose_display_name_uses_real_projection` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py) | pytest / 1 | 実 display-name 投影の警告と依存全体 |


## Environment context retirement

| ケース | 層 | ファイル | 実行 | 検証目的 |
| --- | --- | --- | --- | --- |
| `existing-ut-inventory` | `check_environment_literals_and_account_context` | UT | [units/model-environment-reference-unit.checks.py](units/model-environment-reference-unit.checks.py) | pytest / 1 | 環境名を含むscalar/JSONの保存値と選択scope、account参照・traceの保持 |
| `existing-ut-inventory` | `check_retired_declarations_rejected` | UT | [units/model-environment-reference-unit.checks.py](units/model-environment-reference-unit.checks.py) | pytest / 4 | refid非依存でscalar/JSONの旧環境宣言をreader・Review・trace・export比較で拒否、bytes不変 |

移行exportの環境変数は実値のみ。名前・タグ・JSONの環境名を保持し、account・Resource・Stackの参照意味と比較を継続する。retarget fixtureは通常の環境名prefixに加え同一leafのexecutionAccountId参照を持ち、literal断片と他の現役参照の保護を検証する。

Model v2 移行完了に伴い、固定旧 Framework の export/convert/compare と限定移行契約の10関数・23条件を廃止した。現行保存・Import・Deploy・参照更新・rollback の15関数・82条件は、ケースIDとparameter matrixを保ち model-properties-v2（42条件）、cloudformation-deploy（9条件）、import-model（31条件）へ統合する。

## Required reference input with pending observation

| ケース | 層 | ファイル | 実行 | 検証目的 |
| --- | --- | --- | --- | --- |
| `existing-ut-inventory` | `check_pending_reference_is_required_input` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py) | pytest / 1 | 保存済みResource URIは観測値が未配備でも必須入力として保持し、空値・未確定literalは拒否、入力不変 |

| `candidate-model/repair` | `check_repair_invalid_model` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 40 | 不正な旧参照・形式・identity・重複の修正保存、IMPORT固定値変更、候補検証・権限・scope・競合・rollback、旧Model Git展開なし | Added |

## 残存UTの登録整合

既存の未登録UTを実collectionと直接実行入口から補完する。テスト本体・実行入口は追加せず、pytestの展開数は収集結果、直接実行は既存呼出しを確認した1入口で登録する。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `existing-ut-inventory` | `check_sdk_lifetime` | UT | [units/aws_definitions.checks.py](units/aws_definitions.checks.py#L38) | direct / 1 | sdk lifetime | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_failure_waiters` | UT | [units/aws_definitions.checks.py](units/aws_definitions.checks.py#L61) | direct / 1 | failure waiters | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_full_validation_dependencies` | UT | [units/aws_definitions.checks.py](units/aws_definitions.checks.py#L97) | direct / 1 | full validation dependencies | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_stage_survival_and_definition_sources` | UT | [units/aws_definitions.checks.py](units/aws_definitions.checks.py#L138) | direct / 1 | stage survival and definition sources | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_validation_projection_scope` | UT | [units/aws_mapping_display-unit.checks.py](units/aws_mapping_display-unit.checks.py#L17) | pytest / 1 | validation projection scope | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unit_dispatch` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L171) | pytest / 1 | unit dispatch | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_ci_workflow` | UT | [units/blueprint-loop-unit.checks.py](units/blueprint-loop-unit.checks.py#L214) | pytest / 1 | ci workflow | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_fixed_identity_anchors` | UT | [units/design_layout-unit.checks.py](units/design_layout-unit.checks.py#L74) | pytest / 1 | fixed identity anchors | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_atomic_bytes` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L15) | pytest / 1 | atomic bytes | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_atomic_failure` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L27) | pytest / 2 | atomic failure | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_save_rollback_patch` | UT | [units/file_operations-unit.checks.py](units/file_operations-unit.checks.py#L45) | pytest / 1 | save rollback patch | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_model_operation_catalog_arrays` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L604) | pytest / 6 | model operation catalog arrays | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_batch_model_operation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1050) | pytest / 1 | batch model operation | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_intermediate_source_context` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1069) | pytest / 2 | intermediate source context | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_explicit_reference_operation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1118) | pytest / 6 | explicit reference operation | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_effective_reference_identity` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1191) | pytest / 2 | effective reference identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_local_reference_effective_identity` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1221) | pytest / 1 | local reference effective identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_stack_reference_usage_identity` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1237) | pytest / 1 | stack reference usage identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_reference_target_diagnostics` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1262) | pytest / 2 | reference target diagnostics | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_issues_never_waive_delete_reference_safety` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1547) | pytest / 2 | issues never waive delete reference safety | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_publication_verifies_only_acquisition_selected_additions` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1663) | pytest / 1 | publication verifies only acquisition selected additions | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_existing_hyphenated_fixed_id_cannot_receive_rows` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1674) | pytest / 1 | existing hyphenated fixed id cannot receive rows | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_refactor_json_value_structure` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py#L1825) | pytest / 22 | refactor json value structure | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_exact_reference` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L92) | pytest / 44 | exact reference | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_guardduty_bucket_reference_contract` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L110) | pytest / 1 | guardduty bucket reference contract | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_no_guessed_or_foreign_identity` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L138) | pytest / 1 | no guessed or foreign identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_ambiguous_and_wrong_explicit_link` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L149) | pytest / 1 | ambiguous and wrong explicit link | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_publication_mixed_array_and_physical_value` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L163) | pytest / 1 | publication mixed array and physical value | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_observed_and_reused_index` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L180) | pytest / 1 | observed and reused index | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_pending_explicit_reference_after_destroy` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L197) | pytest / 9 | pending explicit reference after destroy | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_append_only_and_later_import` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L222) | pytest / 1 | append only and later import | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_selected_new_import_can_resolve_only_its_declared_producer` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L237) | pytest / 1 | selected new import can resolve only its declared producer | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_declared_identifier_forms` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L279) | pytest / 4 | declared identifier forms | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_import_compact_display_and_create_guards` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L287) | pytest / 1 | import compact display and create guards | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_markdown_roundtrip_keeps_physical_values` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L317) | pytest / 3 | markdown roundtrip keeps physical values | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_mixed_literals_cannot_hide_behind_observations` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L343) | pytest / 1 | mixed literals cannot hide behind observations | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_role_arn_requires_account_and_explicit_path` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L354) | pytest / 2 | role arn requires account and explicit path | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_guardduty_role_acquired_value_consistency` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L364) | pytest / 1 | guardduty role acquired value consistency | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_import_reference_observation_sync_remains_guarded` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L393) | pytest / 1 | import reference observation sync remains guarded | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_design_link_validation_uses_physical_identity` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L422) | pytest / 4 | design link validation uses physical identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unknown_link_like_aws_data_is_not_inferred` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L454) | pytest / 1 | unknown link like aws data is not inferred | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_packed_variable_roundtrip_and_tamper` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L463) | pytest / 1 | packed variable roundtrip and tamper | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_packed_pipeline_configuration_roundtrip` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L483) | pytest / 1 | packed pipeline configuration roundtrip | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_native_cloudtrail_all_bucket_display` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L517) | pytest / 1 | native cloudtrail all bucket display | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_native_array_literals_cannot_evade_matching_model` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L532) | pytest / 1 | native array literals cannot evade matching model | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unobserved_link_requires_typed_target` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L551) | pytest / 5 | unobserved link requires typed target | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unobserved_structured_links_and_strict_import` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L570) | pytest / 4 | unobserved structured links and strict import | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_observed_comparison_in_design_and_import` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L613) | pytest / 2 | observed comparison in design and import | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unobserved_local_and_identity_self_links` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L627) | pytest / 1 | unobserved local and identity self links | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_design_pending_observation_retains_target_guard` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L642) | pytest / 3 | design pending observation retains target guard | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_saved_import_impact_analysis` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L679) | pytest / 2 | saved import impact analysis | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_preserved_analysis_cache_boundary` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L698) | pytest / 2 | preserved analysis cache boundary | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_impact_keeps_invalid_reference_diagnostics` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L718) | pytest / 4 | impact keeps invalid reference diagnostics | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_analysis_permission_restores_after_exception_and_foreign_scope` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L739) | pytest / 1 | analysis permission restores after exception and foreign scope | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_review_runs_saved_reference_impact` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L757) | pytest / 2 | review runs saved reference impact | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_preserved_read_does_not_authorize_writes` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L776) | pytest / 1 | preserved read does not authorize writes | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_configuration_index_reuses_scans_and_keeps_raw_fields` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L787) | pytest / 1 | configuration index reuses scans and keeps raw fields | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_configuration_index_preserves_exception_priority` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L821) | pytest / 1 | configuration index preserves exception priority | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_observation_index_keeps_every_legacy_prefix` | UT | [units/import-references-unit.checks.py](units/import-references-unit.checks.py#L837) | pytest / 1 | observation index keeps every legacy prefix | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_deletion_gate_and_task_validation` | UT | [units/issue_gate-unit.checks.py](units/issue_gate-unit.checks.py#L29) | pytest / 1 | deletion gate and task validation | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_ordinary_issue_gate_restored` | UT | [units/issue_gate-unit.checks.py](units/issue_gate-unit.checks.py#L49) | pytest / 5 | ordinary issue gate restored | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_deletion_contract_fail_closed` | UT | [units/issue_gate-unit.checks.py](units/issue_gate-unit.checks.py#L77) | pytest / 9 | deletion contract fail closed | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_deletion_scope_fail_closed` | UT | [units/issue_gate-unit.checks.py](units/issue_gate-unit.checks.py#L87) | pytest / 4 | deletion scope fail closed | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_deletion_task_selection` | UT | [units/issue_gate-unit.checks.py](units/issue_gate-unit.checks.py#L93) | pytest / 1 | deletion task selection | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_remediation_still_requires_explicit_scope` | UT | [units/issue_gate-unit.checks.py](units/issue_gate-unit.checks.py#L108) | pytest / 1 | remediation still requires explicit scope | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_deletion_cli_requires_task_opt_in` | UT | [units/issue_gate-unit.checks.py](units/issue_gate-unit.checks.py#L121) | pytest / 2 | deletion cli requires task opt in | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_resume_issue_gate` | UT | [units/issue_gate-unit.checks.py](units/issue_gate-unit.checks.py#L131) | pytest / 2 | resume issue gate | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_generation_uses_deletion_gate` | UT | [units/issue_gate-unit.checks.py](units/issue_gate-unit.checks.py#L150) | pytest / 2 | generation uses deletion gate | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_operation_pass_cache` | UT | [units/issues_scan-unit.checks.py](units/issues_scan-unit.checks.py#L205) | pytest / 1 | operation pass cache | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_parse` | UT | [units/json-format.checks.py](units/json-format.checks.py#L22) | pytest / 4 | parse | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_errors` | UT | [units/json-format.checks.py](units/json-format.checks.py#L35) | pytest / 12 | errors | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_model_overflow_only` | UT | [units/json-format.checks.py](units/json-format.checks.py#L42) | pytest / 3 | model overflow only | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_output_bytes_and_hashes` | UT | [units/json-format.checks.py](units/json-format.checks.py#L50) | pytest / 1 | output bytes and hashes | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_compatibility_exports` | UT | [units/json-format.checks.py](units/json-format.checks.py#L66) | pytest / 1 | compatibility exports | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_isolated_imports_and_standalone_audit` | UT | [units/json-format.checks.py](units/json-format.checks.py#L82) | pytest / 4 | isolated imports and standalone audit | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_success_invalidation_and_scope` | UT | [units/kms-validation-reuse-unit.checks.py](units/kms-validation-reuse-unit.checks.py#L26) | pytest / 1 | success invalidation and scope | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_strict_documents_repeat_failure` | UT | [units/kms-validation-reuse-unit.checks.py](units/kms-validation-reuse-unit.checks.py#L57) | pytest / 6 | strict documents repeat failure | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_no_kms_still_parses_malformed_rows` | UT | [units/kms-validation-reuse-unit.checks.py](units/kms-validation-reuse-unit.checks.py#L69) | pytest / 1 | no kms still parses malformed rows | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_service_reuse_and_direct_call_diagnostics` | UT | [units/kms-validation-reuse-unit.checks.py](units/kms-validation-reuse-unit.checks.py#L78) | pytest / 1 | service reuse and direct call diagnostics | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_snapshots` | UT | [units/model-identity.checks.py](units/model-identity.checks.py#L44) | direct / 1 | snapshots | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_cfn_and_outputs` | UT | [units/model-identity.checks.py](units/model-identity.checks.py#L97) | direct / 1 | cfn and outputs | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_selection_order_findings_and_fresh_calls` | UT | [units/model-input-selection-unit.checks.py](units/model-input-selection-unit.checks.py#L53) | pytest / 1 | selection order findings and fresh calls | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_catalog_failure_precedes_owner` | UT | [units/model-input-selection-unit.checks.py](units/model-input-selection-unit.checks.py#L83) | pytest / 1 | catalog failure precedes owner | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_first_owner_exception_precedes_resource_checks` | UT | [units/model-input-selection-unit.checks.py](units/model-input-selection-unit.checks.py#L93) | pytest / 1 | first owner exception precedes resource checks | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_zero_resources_never_classified` | UT | [units/model-input-selection-unit.checks.py](units/model-input-selection-unit.checks.py#L108) | pytest / 1 | zero resources never classified | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_selected_mutation_is_isolated` | UT | [units/model-input-selection-unit.checks.py](units/model-input-selection-unit.checks.py#L115) | pytest / 1 | selected mutation is isolated | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_reference_leaf_preservation` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L26) | pytest / 1 | reference leaf preservation | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_typed_findings` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L37) | pytest / 1 | typed findings | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_incomplete_references_keep_known_records` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L48) | pytest / 1 | incomplete references keep known records | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_reference_analysis_keeps_invalid_source_error` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L63) | pytest / 1 | reference analysis keeps invalid source error | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_deleted_target_retains_before_value` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L72) | pytest / 1 | deleted target retains before value | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_replace_keeps_snapshot_and_reports_impact` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L88) | pytest / 1 | replace keeps snapshot and reports impact | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_reference_view_retained_but_io_still_fails` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L102) | pytest / 1 | reference view retained but io still fails | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_completion_only_waives_reference_not_run` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L133) | pytest / 1 | completion only waives reference not run | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_legacy_issues_keep_number_and_mixed_error` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L149) | pytest / 1 | legacy issues keep number and mixed error | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_json_leaf_warning_keeps_sibling_error` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L165) | pytest / 1 | json leaf warning keeps sibling error | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_json_cli_warning_success` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L176) | pytest / 1 | json cli warning success | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_generation_metadata_reaches_findings` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L188) | pytest / 1 | generation metadata reaches findings | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_legacy_diagnostic_forms` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L215) | pytest / 8 | legacy diagnostic forms | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_bucket_missing_source_and_real_errors` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L236) | pytest / 1 | bucket missing source and real errors | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_link_display_and_readback_classification` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L258) | pytest / 1 | link display and readback classification | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_independent_model_validation` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L304) | pytest / 4 | independent model validation | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_generation_warning_keeps_independent_error` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L313) | pytest / 1 | generation warning keeps independent error | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_unavailable_service_keeps_source_errors_and_no_cache` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L337) | pytest / 2 | unavailable service keeps source errors and no cache | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_model_warning_only_completion_and_literal_error` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L366) | pytest / 2 | model warning only completion and literal error | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_model_document_uses_authoritative_json` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L385) | pytest / 1 | model document uses authoritative json | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_analysis_generation_keeps_independent_checks` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L409) | pytest / 2 | analysis generation keeps independent checks | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_shared_snapshot_parses_each_producer_once_and_rechecks_permission` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L438) | pytest / 1 | shared snapshot parses each producer once and rechecks permission | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_cross_environment_direct_link_preserves_scope_and_dependency` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L467) | pytest / 1 | cross environment direct link preserves scope and dependency | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_usage_index_preserves_order_and_all_candidates` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L527) | pytest / 1 | usage index preserves order and all candidates | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_usage_index_skips_accumulated_direct_links` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L564) | pytest / 1 | usage index skips accumulated direct links | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_usage_index_retains_conflicting_direct_links` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L580) | pytest / 6 | usage index retains conflicting direct links | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_usage_index_keeps_producer_order_and_io_errors` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L613) | pytest / 1 | usage index keeps producer order and io errors | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_usage_index_is_invocation_local` | UT | [units/model-reference-warnings-unit.checks.py](units/model-reference-warnings-unit.checks.py#L644) | pytest / 1 | usage index is invocation local | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_standalone_contract` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L53) | pytest / 1 | standalone contract | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_preserves_producers_and_equal_renderings` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L67) | pytest / 2 | preserves producers and equal renderings | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_rejects_unsafe_candidates` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L78) | pytest / 18 | rejects unsafe candidates | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_json_positions` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L134) | pytest / 2 | json positions | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_route_table_pair_example` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L150) | pytest / 1 | route table pair example | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_guarded_save` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L189) | pytest / 11 | guarded save | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_final_candidate_uses_latest_base` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L263) | pytest / 1 | final candidate uses latest base | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_additional_boundaries` | UT | [units/model-retarget-unit.checks.py](units/model-retarget-unit.checks.py#L298) | pytest / 5 | additional boundaries | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_one_way_model_contract` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L221) | pytest / 1 | one way model contract | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_selected_model_row_consumption` | UT | [units/model_design-unit.checks.py](units/model_design-unit.checks.py#L288) | pytest / 1 | selected model row consumption | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_reference_target_candidates` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L35) | pytest / 8 | reference target candidates | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_stack_target_identity` | UT | [units/model_parameter_inputs-unit.checks.py](units/model_parameter_inputs-unit.checks.py#L69) | pytest / 3 | stack target identity | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_fixed_ownership_and_invocation_isolation` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L47) | pytest / 1 | fixed ownership and invocation isolation | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_lazy_whole_model_parse_and_error_order` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L64) | pytest / 1 | lazy whole model parse and error order | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_explicit_mapping_uniqueness_and_no_name_inference` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L87) | pytest / 1 | explicit mapping uniqueness and no name inference | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_ten_deletions` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L83) | pytest / 2 | ten deletions | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_contract_rejects_unscoped_deletion` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L101) | pytest / 6 | contract rejects unscoped deletion | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_deletion_and_detach_normalization` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L121) | pytest / 1 | deletion and detach normalization | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_final_rejects_unrequested_changes` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L132) | pytest / 6 | final rejects unrequested changes | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_related_detach_and_two_consumers` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L152) | pytest / 1 | related detach and two consumers | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_remaining_reference_is_warning` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L176) | pytest / 1 | remaining reference is warning | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_fifth_save_failure_retains_first_four` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L186) | pytest / 2 | fifth save failure retains first four | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_finalize_rejects_incomplete_leaves` | UT | [units/worktree-model-guard-unit.checks.py](units/worktree-model-guard-unit.checks.py) | pytest / 1 | finalize rejects incomplete leaves | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_related_retarget` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L239) | pytest / 1 | related retarget | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_delete_issue_exception_is_service_scoped` | UT | [units/resource-delete-unit.checks.py](units/resource-delete-unit.checks.py#L256) | pytest / 1 | delete issue exception is service scoped | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_one_parent_merge_and_failed_candidate_repair` | IT | [integrations/worktree-model-operation.checks.py](integrations/worktree-model-operation.checks.py) | pytest / 2 | one parent merge and failed candidate repair | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_batch_operation_contract` | UT | [units/task-contract-unit.checks.py](units/task-contract-unit.checks.py#L214) | pytest / 1 | batch operation contract | 既存テストの登録漏れ補完・本体変更なし |
| `existing-ut-inventory` | `check_idle_git_paths_and_state` | UT | [units/worktree-guard-unit.checks.py](units/worktree-guard-unit.checks.py#L129) | pytest / 6 | idle git paths and state | 既存テストの登録漏れ補完・本体変更なし |

## Shared Framework references

Framework seedと全体・部分コピー専用helperを撤去。実リポジトリのFrameworkを `definition_root` / `mapping_alias` / `mappings_for` と既存 `definitions_root` 引数で読み取り、Model・Task・IaC入力・Outputだけを独立workspaceへ配置する。pytestは `shared_framework` と `project_workspace` / `managed_project_workspace` を使用する。残る4 seedは可変Projectデータ専用で、runnerのInventory・完了Receipt・到達性検証を維持する。

Humanが明示許可した例外として `integrations/sync-existing-files.checks.py` の配布機能ITのみ実Frameworkをコピーする。テストfixtureのFrameworkコピーやsymlink/hardlinkは使用しない。Mapping/Schema読取例外は実ソースへの読取境界で検証し、定義ファイルを書き換えない。

## JSON settings without Resource markup

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `json-settings::values` | `check_json_settings` | UT | [units/producer-identifier-reference-unit.checks.py](units/producer-identifier-reference-unit.checks.py) | pytest / 1 | document/inline JSONのResourceリンク拒否、escaped Pointer、URLとJSON外部リンク保持、identifierメタデータ再利用、物理値非解決 | Model |
| `json-settings::boundaries` | `check_json_boundaries` | UT | [units/producer-identifier-reference-unit.checks.py](units/producer-identifier-reference-unit.checks.py) | pytest / 1 | 共通候補検証、独立Model検証、生成前拒否と正本不変 | Model |

既存 model-identity / json-resource-arn / s3-kms-reference の生成ケースは、JSON内selectorの生成拒否と正本不変を確認する。legacy operandの読取・影響分析・ARN解決・IaC比較は従来assertionを保持。純粋JSONの独立fixtureでArtifact生成を確認し、通常のJSON外部KMS Aliasリンクは引き続き生成・検証する。

import-references のSubnet配列とCodePipeline Configuration生成fixtureは確認済みliteralを使用する。ConfigurationのProjectNameは既存外部name参照とJSON Pointerで追跡し、IMPORTがリンク要求warningを出さず取得値の相違は拒否することを確認。入口/展開数は維持。

## Static Parameter Export scaffold mapping

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `static-export-handle::check_static_exports_share_mapping_and_skip_observed` | `check_static_exports_share_mapping_and_skip_observed` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L114) | pytest / 1 | 論理ID非依存、通常/implementation一致、直接・cached observed同期の除外 | Model |
| `static-export-handle::check_static_export_decoded_fixture` | `check_static_export_decoded_fixture` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L141) | pytest / 1 | 独立YAMLのParameter直接Export再現、共有decoderと両モード一致 | Model |
| `static-export-handle::check_static_export_rejects_resource_configuration` | `check_static_export_rejects_resource_configuration` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L169) | pytest / 1 | Properties・Condition・DependsOn・Metadata・Policy属性の拒否 | Model |
| `static-export-handle::check_static_export_requires_direct_parameter_exports` | `check_static_export_requires_direct_parameter_exports` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L182) | pytest / 1 | 空Outputs・未宣言Parameter・式Value・Export不備の拒否 | Model |
| `static-export-handle::check_static_export_rejects_dependencies_and_unknown_expressions` | `check_static_export_rejects_dependencies_and_unknown_expressions` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L211) | pytest / 1 | Ref/GetAtt/Sub・未使用分岐/変数・依存・未知式・Transformの拒否 | Model |
| `static-export-handle::check_static_export_requires_sole_resource` | `check_static_export_requires_sole_resource` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L240) | pytest / 1 | WaitCondition参照・他Resource混在・通常未対応Resourceの拒否 | Model |
| `static-export-handle::check_static_export_preserves_explicit_mapping_checks` | `check_static_export_preserves_explicit_mapping_checks` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L258) | pytest / 1 | 明示管理維持、重複・formal Type・CREATE制約と両モード一致 | Model |
| `static-export-handle::check_static_export_preserves_removal_guards` | `check_static_export_preserves_removal_guards` | UT | [units/observed-mapping.checks.py](units/observed-mapping.checks.py#L280) | pytest / 1 | 削除対象の対応付けとcached同期の削除保護を維持 | Model |


## Deploy SDK boundaries and common decoder

| Case ID | Check | Class | File | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `deploy-sdk::boundary-sharing` | `check_boundary_sharing` | UT | [units/deploy-sdk.checks.py](units/deploy-sdk.checks.py) | pytest / 5 | inline/large/artifact/shared bucket: independent delivery/Create/Execute boundaries | Offline fake SDK |
| `deploy-sdk::object-outcomes` | `check_conditional_put_outcomes` | UT | [units/deploy-sdk.checks.py](units/deploy-sdk.checks.py) | pytest / 4 | conditional PUT, fresh HEAD, 412/409/timeout/403 | Offline fake SDK |
| `deploy-sdk::deletion-evidence` | `check_deletion_evidence` | UT | [units/deploy-sdk.checks.py](units/deploy-sdk.checks.py) | pytest / 5 | Delete/Snapshot/Retain/skipped/unknown preserve identifiers correctly | Execution evidence |
| `deploy-sdk::initialization` | `check_client_concurrency` | UT | [units/aws-client.checks.py](units/aws-client.checks.py) | pytest / 1 | context isolation and serialized Session/client initialization | Fake Session |
| `deploy-sdk::pagination` | `check_complete_pages` | UT | [units/aws-client.checks.py](units/aws-client.checks.py) | pytest / 5 | complete inventories and invalid-token rejection | SDK pages |
| `deploy-sdk::decoder` | `check_scalars_and_intrinsics` | UT | [units/cloudformation-format.checks.py](units/cloudformation-format.checks.py) | pytest / 1 | isolated CFn loader, JSON/YAML, intrinsics and existing scalar semantics | Source text/bytes |


## Deploy controller correctness and durable resume (1023v2)

従来の SDK/request・scheduler・session差替え・repair/bootstrap判定の10関数は、assertionを保持して `units/deploy-runtime-unit.checks.py` へ移動した。上の旧ケースIDから移動先を追跡できる。新ITは実controller入口、target/Task/CFN読込、guard、SDK wrapper、scheduler、session再読込、observed公開を通す。AWS置換はSDK client取得境界だけとし、observed失敗は対象ファイルI/Oにだけ注入する。子プロセス間の共有はsession/intentとcontroller外のfake AWS JSONに限る。

| Case ID | Check | Class | File | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `deploy-v2::selected-parent` | `check_selected_parent` | UT | [units/deploy-observed-unit.checks.py](units/deploy-observed-unit.checks.py) | pytest / 14 | direct/true/false/nested/nonselected/inactive/missing parent, both integrated kinds | synthetic Models |
| `deploy-v2::scope-discovery` | `check_discovery_defers_semantics` | UT | [units/deploy-observed-unit.checks.py](units/deploy-observed-unit.checks.py) | pytest / 1 | raw discovery, related validation and corrupt input rejection | synthetic Models |
| `deploy-v2::cleanup-boundary` | `check_cleanup_refreshes_create_boundary` | UT | [units/deploy-sdk.checks.py](units/deploy-sdk.checks.py) | pytest / 14 | rollback/delete-intent, current object, encryption/policy/KMS/Export value/producer change and unchanged continuation | delivery state |
| `deploy-v2::profile` | `check_effective_default_profile` | UT | [units/aws-client.checks.py](units/aws-client.checks.py) | pytest / 1 | real SDK provider chain, private config and synthetic credentials | offline SDK |
| `deploy-v2::orders` | `check_orders_and_observed` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 1 | real observed publication in an ordinary Git repository before next DeployOrder, old measurement metadata compatibility | YAML Project |
| `deploy-v2::approval` | `check_approval_resume` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 1 | same ChangeSet/digest approval retained across resume | SDK boundary |
| `deploy-v2::observed-io` | `check_observed_io_resume` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 1 | AWS SUCCESS retained through persistent publication failure in one invocation, explicit resume retries without Execute | target I/O failure |
| `deploy-v2::group-delivery` | `check_group_delivery` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 2 | complete delivery before Create, no starts on failure | real S3 wrappers |
| `deploy-v2::guard-drain` | `check_input_guard_drains_peer` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 1 | input change stops new mutation and drains accepted peer | real guard |
| `deploy-v2::execution-process` | `check_subprocess_execution_resume` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 2 | response loss and process exit without finally, stable ID/token and no duplicate Execute | separate processes |
| `deploy-v2::cleanup-repair-process` | `check_cleanup_and_repair_process_resume` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 1 | unchanged-input cleanup and external-child cleanup intent recovery, original evidence and fresh AWS state | separate processes |
| `deploy-v2::bootstrap-process` | `check_bootstrap_process_resume` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 2 | original token, private version reuse, external AWSCURRENT rejection | separate processes |

| `deploy-v2::sdk-shapes` | `check_sdk_arguments_and_pages` | UT | [units/aws-client.checks.py](units/aws-client.checks.py) | pytest / 1 | real SDK request/response schema and pagination | botocore Stubber |

| `deploy-v2::durable-delivery-reset` | `check_cleanup_delivery_evidence_is_durable` | UT | [units/deploy-sdk.checks.py](units/deploy-sdk.checks.py) | pytest / 1 | cleanup reset saves existing evidence atomically, repaired input replans | saved state |


## Deploy observed publication plans and controller Remove resume

Task fixtureは独立した通常Gitとtask_contract.startで開始・選択し、可変Projectを通常repositoryへ置く。Framework定義は共有参照する。UTは計画照合の純粋判定、ITは実保存・journal/rollback・生成・session再読込・別プロセス再開を検証する。pytest receiptは既存run_it.pyが収集する。

| Case ID | Check | Class | File | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `observed-resume::classification` | `check_classification` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 8 | exact before/after, no-op, journal-only mixed state, third bytes and file set rejection | manifests |
| `observed-resume::execution` | `check_execution_identity` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 5 | successful original Stack/ChangeSet/digest/token binding | execution evidence |
| `observed-resume::journal` | `check_journal_ownership` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 7 | own originals, complete restoration, unrelated receipt and third bytes rejection | journal records |
| `observed-resume::plan` | `check_plan_validation` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 14 | Legacy managedTask exclusion only; Task/evidence/manifest/candidate/desired/unrelated bytes/file set/Allowed paths/stage/original-set/manifest-set checks | isolated bytes |
| `observed-resume::intent-io` | `check_intent_save_failure` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 1 | failed intent persistence leaves Model untouched | session I/O |
| `observed-resume::peer-barrier` | `check_pending_plan_drained_peer_barrier` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 1 | saved plan finishes before drained peers synchronize | scheduler state |
| `observed-resume::first-error` | `check_original_failure_retained` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 1 | first stage/cause retained separately from later guard refusal | failure records |
| `observed-resume::publication-process` | `check_observed_publication_process_resume` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 8 | intent save failure, pre-write rollback, mixed Model/generated journal recovery, post-Model and post-design process exit, design I/O failure; original evidence and no duplicate Execute | real managed Task and I/O |
| `observed-resume::drain-process` | `check_observed_drains_peer_then_resumes` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 1 | drain accepted peer while first plan is blocked; resume both without mutation replay | same group |
| `observed-resume::external-process` | `check_observed_external_change_rejected` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 11 | candidate/file set/other Model/desired/display/reference/dependency/Task/IaC/evidence/approval edits retained; no rollback or AWS mutation | interrupted session |
| `observed-resume::legacy-process` | `check_legacy_session_without_observed_plan` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 2 | unchanged pre-plan state resumes; deleting a signed publication plan rejects unrecorded state without publication proof | old session shape |
| `observed-resume::remove-process` | `check_remove_controller_process_resume` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 7 | Remove approval, production evidence, accepted Execute crash and separate resume; Delete/Retain/skipped/missing/wrong token/Stack/physical proof | existing Stack update |

| `observed-resume::task-bytes` | `check_exact_task_bytes_bound` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 1 | pending plan binds full contract bytes in addition to the existing normalized session identity | Task text |

observed-resume UTはCIで毎回実行する。IT runnerとGitHub Actionsの入口は維持する。

| `observed-resume::direct-snapshot` | `check_direct_writer_keeps_noop_source_snapshot` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 1 | direct sync retains every selected source snapshot, including unchanged candidates | observation inputs |

## External deploy repair handoff

実Task/Worktree・検証loop・commit/ff-only統合・同一session受理を既存controller ITで検証する。AWSはSDK client取得境界の有限fake、障害注入は既存I/O・process境界のみ。正式ITのreceiptは既存run_it.pyから取得し、未実行をPASSにしない。

| Case ID | Check | Class | File | Execution | Contract | Inputs |
| --- | --- | --- | --- | --- | --- | --- |
| `external-repair::round-trip` | `check_external_implement_round_trip` | IT | [integrations/worktree-deploy-repair.checks.py](integrations/worktree-deploy-repair.checks.py) | pytest / 2 | Separate implement, shared SUCCESS impact wait, unexecuted decode/ValidateTemplate/CreateChangeSet/API-review handoff, actual static FAIL/retry, integration, same-session resume, request/merge/accept/execute interruption, A/A and A/B/A | Synthetic offline inputs |
| `external-repair::legacy` | `check_explicit_legacy_migration` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 3 | Explicit definition migration; old pending candidate retained and never applied; original tokens drained | Synthetic offline inputs |
| `external-repair::base-sync` | `check_sync_base_preserves_candidate` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py) | direct / 1 | Real Git inherited base advance preserves reviewed uncommitted candidate without task commit/reset | Synthetic offline inputs |
| `external-repair::problem-sequences` | `check_problem_sequences` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 4 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::unrepaired-peers-and-request-idempotency` | `check_unrepaired_peers_and_request_idempotency` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 1 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::progress-limits-and-budget` | `check_progress_limits_and_budget` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 1 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::duplicate-poll-is-not-a-new-failure` | `check_duplicate_poll_is_not_a_new_failure` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 1 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::failure-classes` | `check_failure_classes` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 6 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::effective-inputs-and-safe-events` | `check_effective_inputs_and_safe_events` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 1 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::status-helpers-preserve-task-identity` | `check_status_helpers_preserve_task_identity` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 1 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::signed-ledger-rejects-rollback-and-recovers` | `check_signed_ledger_rejects_rollback_and_recovers` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 1 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::total-budget-is-not-three-global-failures` | `check_total_budget_is_not_three_global_failures` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 1 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::ambiguous-new-and-invalid-evidence-rejected` | `check_ambiguous_new_and_invalid_evidence_rejected` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 6 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::distinct-property-and-request-id-stability` | `check_distinct_property_and_request_id_stability` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 1 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |
| `external-repair::unexecuted-diagnosis-preserves-aws-state` | `check_unexecuted_diagnosis_preserves_aws_state` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 6 | Policy/evidence/input/ledger boundary; no live AWS | Synthetic offline inputs |

| `external-repair::unexecuted-shell` | `check_unexecuted_shell_recovery` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 12 | Original ownership/live identity, protection, no execution, failed ChangeSet, empty inventory and interrupted cleanup; no invented rollback | Offline AWS operation boundary |

| `external-repair::constraint-reference-set` | `check_constraint_identity_ignores_reference_order` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 3 | Reordered references, added metadata and unproved previous constraint cannot make a new problem | Fixed provider schema |

| `external-repair::cross-task-workflow` | `check_deploy_workflow_cross_task_reset_rejected` | IT | [integrations/worktree_task.checks.py](integrations/worktree_task.checks.py) | direct / 1 | Same Stack in another real managed Task cannot reset an unfinished budget; missing ledger refuses; explicit close archives pending static FAIL but refuses overlapping new Tasks and preserves old history/counts | Real Git/lifecycle and sealed session |

| `external-repair::after-bootstrap` | `check_bootstrap_history_preserves_distinct_safe_failure` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 1 | Actual poll/repair preserve a different structured non-secret cause after bootstrap; no PUT/cleanup fallback; changing event identity cannot create NEW | Offline AWS read boundary |

| `import-worktree::properties-boundary` | `check_properties_import_git_boundary` | IT | [real Git boundaries](integrations/import-cli.checks.py#L53) | pytest / 5 | HEAD invalidation, separate CLI process and source/receipt/display os._exit(17) recovery, moved intact from properties publication matrix | Issue 14 |

## Issue 14: Import / Model / Worktree separation

The original 112 parametrized cases remain reachable. `check_properties_import_acquire_review_publish` keeps 11 Import parameters; its `head`, `subprocess`, `source-crash`, `receipt-crash`, and `display-crash` parameters move to `check_properties_import_git_boundary` unchanged. The latter retains actual `os._exit(17)` processes. CLI preflight and cross-process evidence move intact. No case is skipped or xfailed.

| Original function | Original cases | Current suite / function |
| --- | ---: | --- |
| `check_cli_preflight` | 1 | `import-worktree-contract.checks.py::check_cli_preflight` |
| `check_logs_roundtrip` | 1 | `import-model.checks.py::check_logs_roundtrip` |
| `check_config_sources` | 1 | `import-model.checks.py::check_config_sources` |
| `check_vpc_eight_instances` | 1 | `import-model.checks.py::check_vpc_eight_instances` |
| `check_quicksight_normalization` | 1 | `import-model.checks.py::check_quicksight_normalization` |
| `check_registry_services` | 1 | `import-model.checks.py::check_registry_services` |
| `check_managed_resource_addition` | 3 | `import-model.checks.py::check_managed_resource_addition` |
| `check_existing_resource_selection_rejected` | 2 | `import-model.checks.py::check_existing_resource_selection_rejected` |
| `check_optional_profile` | 1 | `import-model.checks.py::check_optional_profile` |
| `check_explicit_no_profile` | 1 | `import-model.checks.py::check_explicit_no_profile` |
| `check_single_acquisition` | 1 | `import-model.checks.py::check_single_acquisition` |
| `check_source_race` | 1 | `import-model.checks.py::check_source_race` |
| `check_create_definition_reuse` | 1 | `import-model.checks.py::check_create_definition_reuse` |
| `check_cli_faults` | 1 | `import-model.checks.py::check_cli_faults` |
| `check_inventory_parent_references` | 1 | `import-model.checks.py::check_inventory_parent_references` |
| `check_exact_scope` | 1 | `import-model.checks.py::check_exact_scope` |
| `check_external_reference_preservation` | 1 | `import-model.checks.py::check_external_reference_preservation` |
| `check_mapping_preservation` | 1 | `import-model.checks.py::check_mapping_preservation` |
| `check_shared_property_and_bindings` | 1 | `import-model.checks.py::check_shared_property_and_bindings` |
| `check_foreign_source_writes_rejected` | 5 | `import-model.checks.py::check_foreign_source_writes_rejected` |
| `check_add_identity_boundary` | 4 | `import-model.checks.py::check_add_identity_boundary` |
| `check_unacquired_property_rejection` | 1 | `import-model.checks.py::check_unacquired_property_rejection` |
| `check_repeat_without_reformat` | 1 | `import-model.checks.py::check_repeat_without_reformat` |
| `check_fixed_identity_rejection` | 1 | `import-model.checks.py::check_fixed_identity_rejection` |
| `check_empty_inventory_preserves_sources` | 1 | `import-model.checks.py::check_empty_inventory_preserves_sources` |
| `check_partial_reflection` | 1 | `import-model.checks.py::check_partial_reflection` |
| `check_native_types_preserved` | 1 | `import-model.checks.py::check_native_types_preserved` |
| `check_consumer_set_race` | 1 | `import-model.checks.py::check_consumer_set_race` |
| `check_source_transaction_rollback` | 1 | `import-model.checks.py::check_source_transaction_rollback` |
| `check_yaml_candidate_edit` | 1 | `import-model.checks.py::check_yaml_candidate_edit` |
| `check_reflection_validation_boundary` | 1 | `import-model.checks.py::check_reflection_validation_boundary` |
| `check_cross_process_evidence` | 1 | `import-worktree-contract.checks.py::check_cross_process_evidence` |
| `check_dry_run_cleanup` | 1 | `import-model.checks.py::check_dry_run_cleanup` |
| `check_evidence_and_display_recovery` | 1 | `import-model.checks.py::check_evidence_and_display_recovery` |
| `check_model_only_publication` | 6 | `model-operation-publication.checks.py::check_model_only_publication` |
| `check_partial_acquisition_cannot_complete` | 1 | `import-model.checks.py::check_partial_acquisition_cannot_complete` |
| `check_generic_acquisition_roundtrip` | 1 | `import-model.checks.py::check_generic_acquisition_roundtrip` |
| `check_intermediate_model_sources` | 1 | `model-operation-publication.checks.py::check_intermediate_model_sources` |
| `check_batch_leaf_saves` | 1 | `model-operation-publication.checks.py::check_batch_leaf_saves` |
| `check_reference_publication` | 7 | `import-model.checks.py::check_reference_publication` |
| `check_user_selected_overwrite_publication` | 6 | `import-model.checks.py::check_user_selected_overwrite_publication` |
| `check_mixed_add_refresh_single_publication` | 2 | `import-model.checks.py::check_mixed_add_refresh_single_publication` |
| `check_replace_warns_incoming_references` | 1 | `import-model.checks.py::check_replace_warns_incoming_references` |
| `check_first_resource_uses_existing_source_format` | 4 | `import-model.checks.py::check_first_resource_uses_existing_source_format` |
| `check_refresh_switches_definition_without_foreign_changes` | 1 | `import-model.checks.py::check_refresh_switches_definition_without_foreign_changes` |
| `check_approval_bound_save_guard` | 6 | `import-model.checks.py::check_approval_bound_save_guard` |
| `check_properties_import_acquire_review_publish` | 16 | `import-model.checks.py::check_properties_import_acquire_review_publish` (11) + `import-worktree-contract.checks.py::check_properties_import_git_boundary` (5) |
| `check_publication_transaction_without_host` | 10 | `import-model.checks.py::check_publication_transaction_without_host` |
| `check_saved_display_recovery_needs_no_new_approval` | 1 | `import-model.checks.py::check_saved_display_recovery_needs_no_new_approval` |
| `check_candidate_review_mismatch_rejected_without_host` | 4 | `import-model.checks.py::check_candidate_review_mismatch_rejected_without_host` |

Additional safety checks use byte snapshots for Model, Project and Task additions, edits and removals. Production guards still check Task, source paths, Validation scope, target, HMAC, Review binding, candidate and approved source hashes. The Provider replaces only repository state acquisition in-process; no CLI/environment bypass exists. Unversioned temporary generation stages keep their production semantics.

| Requirement | Case | Layer | File | Mode / Count | Verification | Reason |
| --- | --- | --- | --- | --- | --- | --- |
| `import-gitless::guards` | `check_gitless_guard_boundaries` | IT | [guards](integrations/import-model.checks.py#L996) | pytest / 7 | HEAD/base/Task/Allowed paths/scope/target/foreign source rejection, no publication side effects | Issue 14 |
| `import-gitless::snapshot` | `check_repository_snapshot_detects_real_changes` | IT | [snapshots](integrations/import-model.checks.py#L1036) | pytest / 1 | Real bytes detect additions, removals, comment edits and Task edits without changing the baseline | Issue 14 |
| `import-worktree::contract` | `check_import_managed_contract_boundaries` | IT | [real contract](integrations/import-worktree-contract.checks.py#L87) | pytest / 5 | Real Git/Worktree Task conflicts, invalid start commit, wrong owner and foreign Worktree publication rejection | Issue 14 |

| `model-worktree::source-context` | `check_model_source_context_worktree_boundary` | IT | [Model context](integrations/import-worktree-contract.checks.py#L122) | pytest / 4 | Real managed source context acceptance and HEAD/Task/ownership conflicts with unchanged base and rejected-save bytes | Issue 14 |

Model value, rollback and journal cases use `model-operation-publication.checks.py` without Git; managed source capability conflicts run above, and `worktree_task.checks.py::check_model_operation_integration` retains the real merge/delete final-candidate/finalize/cleanup checks.

## LLM diagnosis relations and mechanical retry boundaries

| ID | Function | Kind | Location | Entry / count | Responsibility | Scope |
|---|---|---|---|---|---|---|
| `cause-boundary::v5-relabel-different-proof` | `check_v5_relabel_does_not_buy_new_attempt` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 4 | Schema pointer, invalid value, label, RequestId/prose cannot create a new cause or refund attempts | Offline synthetic inputs |
| `cause-boundary::relation-contract` | `check_relation_contract_and_atomic_rejection` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 7 | Required relation/comparison/reason/current and prior evidence; failed publication is atomic | Offline synthetic inputs |
| `cause-boundary::unknown-diagnosis` | `check_unknown_is_durable_and_never_issues_request` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 2 | Persist unknown, including nonrepairable failures, without dummy causes or repair requests | Offline synthetic inputs |
| `cause-boundary::same-cross-resource` | `check_same_cause_across_resource_targets_shares_attempt_limit` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 2 | Nested and independent Resource targets share cause attempts and no-progress stops | Offline synthetic inputs |
| `cause-boundary::new-code-and-cycle` | `check_new_code_is_evidence_not_python_cause_inference` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 1 | LLM NEW with distinct code can continue; SAME recurrence and cause transfer cannot evade histories | Offline synthetic inputs |
| `cause-boundary::v5-sealed-migration` | `check_v5_signed_history_migrates_without_reset` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 2 | Retain old IDs/attempts/budget and extension-only histories; restart and signed recovery stay Human-bound | Offline synthetic inputs |
| `cause-boundary::budget-text-refused` | `check_budget_text_is_not_human_authority` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 1 | Self-issued authorization cannot extend budget or reopen a closed workflow | Offline synthetic inputs |
| `cause-boundary::observed-target-progress` | `check_only_observed_target_progress_counts` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 3 | Only nested target AWS success counts; peer/static success does not | Offline synthetic inputs |
| `cause-boundary::common-cause-target-progress` | `check_common_cause_progress_requires_repaired_target_success` | UT | [units/deploy-handoff-unit.checks.py](units/deploy-handoff-unit.checks.py) | pytest / 2 | Only actual expected success of a repaired target sharing this cause is partial progress; unrelated peer success is excluded | Offline synthetic observations and production outcome verification |

## Observed generated-file resume protection

| Origin | Function | Layer | Source | Execution | Coverage | Fixture |
| --- | --- | --- | --- | --- | --- | --- |
| `observed-views::classification` | `check_generated_classification` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 10 | before/after candidates, exact bytes, empty vs absent, added/deleted artifacts, unexplained partial state and missing evidence | isolated files |
| `observed-views::journal` | `check_generated_journal` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 6 | owned generated transaction, missing-file originals, third bytes, foreign/incomplete journal and receipt | journal records |
| `observed-views::external` | `check_generated_external_change_rejected` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 9 | Markdown append/value, JSON edits, output addition/deletion, foreign bytes in retained journal and legacy plan without output evidence; bytes retained and later DeployOrder blocked | managed controller and real publication |
| `observed-views::publication-race` | `check_generated_change_during_publication` | IT | [integrations/deploy-controller.checks.py](integrations/deploy-controller.checks.py) | pytest / 1 | external edit after validation and plan reconciliation, caught by actual publication snapshot; resume preserves edit and execution evidence | real GenerationInputs and controller |
| `observed-views::snapshot` | `check_generated_plan_snapshot` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 1 | pin views and actual JSON selection before fallible generation; empty vs absent and unexpected file evidence | raw snapshot |

## Resource impact 1023v5

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `resource-impact::addition` | `check_resource_addition` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py) | direct / 1 | 同Serviceの別logicalId追加と新Consumer、Task基準Snapshot | Resource impact |

| `resource-impact::changes` | `check_resource_changes` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py) | direct / 1 | 更新・削除・旧新参照・Resource連鎖・複数Service和集合 | Resource impact |
| `resource-impact::semantics` | `check_semantic_boundaries` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py) | direct / 1 | コメント・表示・採番・Observed・project変更 | Resource impact |
| `resource-impact::fallback` | `check_stack_context_and_fallback` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py) | direct / 1 | Stack・Context・不明参照・不正旧Model修復 | Resource impact |
| `resource-impact::routes` | `check_task_snapshot_routes` | IT | [integrations/model_impact.checks.py](integrations/model_impact.checks.py) | direct / 1 | 実managed保存・Candidate・stage/commit・最終Validation・Issue Gate・Snapshot/graph回数 | Resource impact |
| `resource-impact::internal-ids` | `check_internal_ids_and_comments` | UT | [units/model-impact-unit.checks.py](units/model-impact-unit.checks.py) | pytest / 1 | Resource/Row/Reference番号・表示と意味的差分 | Resource impact |
| `resource-impact::cycles` | `check_minimal_fallback_and_cycles` | UT | [units/model-impact-unit.checks.py](units/model-impact-unit.checks.py) | pytest / 1 | Resource/Service境界と循環停止 | Resource impact |
| `resource-impact::invalid` | `check_invalid_baseline_and_counter` | UT | [units/model-impact-unit.checks.py](units/model-impact-unit.checks.py) | pytest / 1 | 不正旧Modelと不明採番の局所fallback | Resource impact |

既存 `units/import-model-unit.checks.py::check_repair_invalid_model` は旧Snapshotのraw差分取得を許可し、変更後だけの `load_model`、旧syntax/identity/encoding不正の修復、権限・scope・race・rollback・anchor拒否の全40展開を維持する。旧Modelを完全検証することを要求しない。

`integrations/sync-model.checks.py::check_integrated_validator` の2展開はImpact再計算3回の旧期待を、共通Snapshotによる計算1回の期待へ変更。生成・候補検証・入力比較各1回と保存後readbackなしのassertionは保持。

| `resource-impact::design-source` | `check_design_requires_changed_authority` | UT | [units/model-impact-unit.checks.py](units/model-impact-unit.checks.py) | pytest / 1 | 共通Impactがあってもproject変更だけでdesign Taskを許可しない | Resource impact |

## Shared sealed evidence

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `sealed-evidence::legacy_bytes` | `check_legacy_bytes` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py) | pytest / 1 | 旧形式署名とdigest完全互換 | evidence |
| `sealed-evidence::rejected_envelopes` | `check_rejected_envelopes` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py) | pytest / 8 | 改ざん・別鍵・不正envelope拒否 | evidence |
| `sealed-evidence::store_and_key` | `check_store_and_key` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py) | pytest / 1 | 保存先互換・root分離・32byte鍵 | evidence |
| `sealed-evidence::symlink_rejection` | `check_symlink_rejection` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py) | pytest / 3 | receipt・鍵・保存先symlink拒否 | evidence |
| `sealed-evidence::private_permissions` | `check_private_permissions` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py) | pytest / 1 | 所有者と権限 | evidence |
| `sealed-evidence::atomic_failure` | `check_atomic_failure` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py) | pytest / 1 | atomic失敗時の旧証拠保持 | evidence |
| `sealed-evidence::ownership` | `check_ownership` | UT | [units/worktree-model-guard-unit.checks.py](units/worktree-model-guard-unit.checks.py) | pytest / 5 | Worktree正本とTask所有確認 | evidence |
| `sealed-evidence::dependency_boundaries` | `check_dependency_boundaries` | UT | [units/sealed-evidence-unit.checks.py](units/sealed-evidence-unit.checks.py) | pytest / 1 | 共通証拠とWorktreeの依存分離 | evidence |
| `observed-resume::signed-legacy` | `check_signed_legacy_plan` | UT | [units/deploy-observed-resume-unit.checks.py](units/deploy-observed-resume-unit.checks.py) | pytest / 1 | 署名検証後の旧managedTask除外・同フィールド改ざん拒否 | evidence |

## Worktree dependency separation (master 1024v2)

| 分類 | 旧依存 / 対象 | 現在の検証責務 |
|---|---|---|
| A | worktree_task / worktree_python / guard / managed Import boundary | 所有・Task基準・専用Python・create/merge/finalize/cleanup・中断復旧を専用ケースで検証 |
| A | Deploy managed delivery 2条件、Delete parent integration | 実checkpoint→child登録→static検証→親FF→cleanupとその証跡・再開を専用ITへ移動。parameter matrixとassertionを保持 |
| B | Model properties/repair、Impact、CloudFormation deploy/destroy、group05、JSON hash、explicit values、Import process 5条件、Deploy request/acceptance/retry/CFN cleanup 13条件 | `repository_fixtures`の通常Git候補へ変更。実Task・Model・生成・保存・rollback・プロセス終了/復旧を保持 |
| C | Import repository、Model intermediate save、retarget、sync/Issue Gate baseline | 合成所有者/worktree/mergedレコードを撤去。業務側はpublication revision能力と通常のTask Git基準を渡す。所有者・未完leaf・finalize承認・managed基準の拒否は専用UT/IT |
| D | Git init/commit/diff、Reviewの公開worktreeフィールド、Framework参照整合性 | 通常Git・証跡データの検証でありLifecycleではないため保持 |

Import `gitless_guard_boundaries[owner]` は既存 `check_import_managed_contract_boundaries[owner]`、
retarget `guarded_save[wrong-owner]` は共有factoryの `check_ownership` と
`check_model_source_context_worktree_boundary[owner]` に責務を集約する。
HEAD/Task変更、未承認パス、scope/target、非選択データ、保存前後byte、no-opとrollbackの業務assertionは保持する。
`check_git_baseline_fail_closed` のGitパス判定はsync UT、managed/unborn/故障基準はWorktree guard UT。
controllerの通常cleanup 1条件と、外部修復後のCloudFormation cleanup復旧 1条件は業務側で別々に登録する。

`support/worktree_test_policy.py` はレビュー済みの専用ケースを関数単位で固定し、
UT/IT/supportのImport・動的loader・Mock対象を推移的に調べる。改名だけでは許可しない。
非専用pytestと公式IT runnerは実行時にもGit worktree変更、Lifecycle CLI、管理領域への書込みを拒否する。
通常Gitとproductionによるread-only discoveryは許可する。別プロセスの業務fixtureも通常Gitと
publication能力だけを渡し、管理状態を生成・Mockしない。既存の唯一のIT runnerと完了receiptを使用する。

| Origin | Case | Class | Location | Entry / conditions | Responsibility | Scope |
|---|---|---|---|---|---|---|
| `worktree-separation::cleanup` | `check_external_repair_cleanup_recovery` | IT | [external repair cleanup](integrations/deploy-controller.checks.py) | pytest / 1 | 子統合後の親再開でcleanup中断・元証跡・単一Executeを保持 | Controller domain |
| `worktree-separation::candidate` | `check_model_finalize_cannot_bypass_candidate` | UT | [candidate guard](units/worktree-model-guard-unit.checks.py) | pytest / 1 | retarget承認による最終候補検証迂回を拒否 | Worktree integration |
| `worktree-separation::baseline` | `check_git_baseline_fail_closed` | UT | [baseline guard](units/worktree-model-guard-unit.checks.py) | pytest / 1 | managed基準・unborn・故障伝播 | Worktree integration |
| `worktree-separation::issue-owner` | `check_issue_gate_rejects_foreign_managed_task` | UT | [Issue owner](units/worktree-model-guard-unit.checks.py) | pytest / 1 | Issue Gateがmanaged Task不一致を伝播 | Worktree integration |
| `worktree-separation::policy` | `check_repository_policy` | UT | [policy](units/worktree-test-policy-unit.checks.py) | pytest / 1 | 全UT/IT/supportの非専用依存0 | Recurrence |
| `worktree-separation::dependencies` | `check_direct_and_indirect` | UT | [dependencies](units/worktree-test-policy-unit.checks.py) | pytest / 5 | 直接/間接/Mock/dynamic fixture依存とLifecycle形状のfixtureを拒否 | Recurrence |
| `worktree-separation::rename` | `check_filename_grants_no_authority` | UT | [rename](units/worktree-test-policy-unit.checks.py) | pytest / 1 | 改名による許可拡大を拒否 | Recurrence |
| `worktree-separation::runtime` | `check_runtime_guard` | UT | [runtime](units/worktree-test-policy-unit.checks.py) | pytest / 1 | 実操作・管理書込禁止と通常Git許可 | Recurrence |

| `worktree-separation::repair-business` | `check_external_repair_resumption` | IT | [repair resumption](integrations/deploy-controller.checks.py) | pytest / 12 | signed external result, real Git history/hash/snapshot, acceptance crash, known/new/regressed cause, unexecuted input failures, shared-success impact | Controller domain |

追加の責務分割：ImportのHEAD/CLI/source/receipt/display crash 5条件は通常Gitの `import-cli` へ移動。
Deployの14条件はworktree delivery 2条件とcontroller request/acceptance/retry 12条件へ分割し、
外部修復後のCloudFormation cleanup復旧1条件も業務側で保持する。業務fixtureは通常Gitの実commit/hashと署名付き外部結果を供給し、
worktree所有登録/配送の能力境界だけを置換する。Managed stateやLifecycleのMockは作らない。
実static FAIL→修正→PASSとcheckpoint/create/重複child拒否/FF/cleanupは専用側で引き続き検証する。

全assert文のASTを変更前後で照合し、削除したassert式は0件。所有者ケースは上記の専用側へ集約し、
業務parameter matrixのLifecycle条件だけを移動する。実行時guardはworker threadも対象にし、
静的依存違反をpytest/公式ITの実行前に拒否する。旧baseline計測には現行policyを強制しない。


## Task Contract snapshots / master-1024v3

`units/task-snapshot-unit.checks.py` uses three synthetic Tasks and counts Task byte/text
reads and directory enumeration. Its 20 conditions cover explicit selection (including
intentional isolation from unrelated malformed Tasks), implicit/catalog reuse, immutable
worker transfer with independent memo state, live content/status/newline/selector/catalog
changes, cache publication rejection, Task update invalidation, mutation I/O budgets and
Import/Model publication revision checks. Existing task-contract, approval, Issue Gate,
Deploy session and publication suites retain their safety assertions. No Git/worktree
integration or live AWS operation is used by the new suite.

## AWS Profile / Identity common authority

Profile/Accountの判定条件は `units/aws-identity-unit.checks.py` だけで管理する。
共通判定の失敗は `utils.aws.identity.IdentityError`（ValueError派生）を直接伝播する。
各機能UTは元の例外オブジェクトの同一性とCLIでの捕捉を確認し、
DeployContextError/Blocked/AcquisitionErrorへのIdentity例外ラップを行わない。
STS不一致の `AccountMismatch` コードは共通例外が所有し、既存レポート分類を維持する。
既存UTの入口は削除せず、check-deploy-contextとvalidation topologyの不正入力表
（Profile各8、execution account各9、計34展開）を削除した。通常Account不正1入力、
AWS Client内のDeploy Profile選択/競合2条件、ImportのAccount不一致1条件も移管した。
Deploy CLIの競合判定は共通関数のMock拒否へ置換した。
SDK環境由来認証識別、cache、Session再開、alias/suffix/Region/engine、Importの承認と証跡は維持する。

| 元ID | 現在の関数 | 分類 | 現在の場所 | 入口 / 展開数 | 検証責務 | 区分 |
|---|---|---|---|---|---|---|
| `aws-identity::valid-profile` | `check_valid_profile` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py) | pytest / 5 | Profile形式 | Pure |
| `aws-identity::invalid-profile` | `check_invalid_profile` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py) | pytest / 14 | 不正型/空/空白/UNSET/改行/NUL、明示値/設定/Import例外でも拒否 | Pure |
| `aws-identity::selection` | `check_profile_selection` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py) | pytest / 4 | 設定/明示/一致/default chain | Pure |
| `aws-identity::conflict` | `check_profile_conflict` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py) | pytest / 1 | 設定と明示Profile競合 | Pure |
| `aws-identity::import` | `check_import_selection` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py) | pytest / 4 | Import専用no-profile、設定不変 | Pure |
| `aws-identity::valid-account` | `check_valid_account` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py) | pytest / 2 | ASCII 12桁 | Pure |
| `aws-identity::invalid-account` | `check_invalid_account` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py) | pytest / 12 | 不正Account、明示execution key不正のfallback禁止 | Pure |
| `aws-identity::execution` | `check_execution_account` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py) | pytest / 2 | execution優先、未指定時resource、STS一致 | Pure |
| `aws-identity::sts-mismatch` | `check_sts_mismatch` | UT | [units/aws-identity-unit.checks.py](units/aws-identity-unit.checks.py) | pytest / 5 | STS不一致/欠落/不正型 | Pure |
| `aws-identity::context` | `check_identity_delegation_and_sts_reuse` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py) | pytest / 1 | Context比較委譲、IdentityError同一性、検証済みAccount返却、STS transport再利用、拒否後resource API禁止 | Mock |
| `aws-identity::multi-target` | `check_all_target_profiles_precede_aws` | UT | [units/check-model-aws-unit.checks.py](units/check-model-aws-unit.checks.py) | pytest / 1 | 全Targetの事前判定、拒否時CLI/SDK session未実行 | Mock |
| `aws-identity::import-boundary` | `check_import_profile_mode_delegation` | UT | [units/import-model-unit.checks.py](units/import-model-unit.checks.py) | pytest / 1 | Import例外引渡し、設定不変、STS維持 | Mock |
| `aws-identity::preparation` | `check_identity_failure_precedes_preparation` | UT | [units/deploy_preparation-unit.checks.py](units/deploy_preparation-unit.checks.py) | pytest / 1 | 共通判定委譲と準備/AWS前の拒否 | Mock |
| `aws-identity::runtime` | `check_runtime_identity_delegation` | UT | [units/deploy-runtime-unit.checks.py](units/deploy-runtime-unit.checks.py) | pytest / 1 | 共通Profile保存、IdentityError同一性、connection作成前の拒否 | Mock |

既存 `integrations/model-test.checks.py::check` にSTS実transport 1回の確認を追加。
共通例外と関数は `model.audit.definitions()` で依存順に埋め込み、既存の隔離Python
単独実行（Framework/PyPI importなし）を維持する。新しいIT入口は追加しない。
