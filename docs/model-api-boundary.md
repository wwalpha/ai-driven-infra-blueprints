# Model API boundary and consumer dependency inventory

This is an API ownership reference, not a Guard exception list. A listed dependency does not permit arbitrary access to the same module. Keep checks and authorization at their existing callers. No Runtime/CI allowlist is introduced.

## Boundary decisions

- A: existing named Model operations retained after checking their uses (including submodule APIs). Reference resolution, acquisition, authorization, rendering, validation and change planning remain Model-owned operations; consumers retain business decisions.
- B: structural enumeration is through ModelView; Key identity/ownership uses the shared contract. Read-only Snapshot fields used for scalar lookups, source traces and fixed-input comparison are data, not setters. They retain their original error and performance behavior.
- C: missing structural operations: ModelView.resource_groups(grouped_types) now owns grouping, parent resolution and cycle detection; the caller still chooses which resource types are grouped. `publish_transaction` publicly names the existing transaction implementation. It is the identical callable, not a new writer; Sync retains publication_lock, task authorization, input comparison, journal/rollback and ordering. The generic prepare/publish APIs cannot replace this validated generation transaction without changing its journal and file-set semantics.
- D: side-effect-free contracts, value helpers, types, exceptions and constants. Model grammar parsers remain in Model even when pure. Markdown LINK patterns are display contracts, not Model Key grammars.
- E: implementation dependencies within framework/scripts/model are legitimate internal dependencies; they are outside the consumer table. Tests are synthetic consumers and fixture builders, not Runtime consumers.

No external ModelSnapshot `_replace`, reconstruction or authoritative-state mutation remains in Runtime consumers. Comparison's own memo dictionaries and CloudFormation YAML source locations are not ModelSnapshot state. `utils/iac_values.py` splits a CloudFormation stack/logical address, not a Model Row ID. Property paths and rendered Markdown syntax remain display/business parsing. Key literals used to name a diagnostic, read a specific business property or identify an authorized output remain legitimate scalar lookups.

Design's selection of service notes and grouped tables remains rendering policy; it uses ModelView for ownership and grouping. Existing explicit re-exports listed below are retained for API compatibility.

## Inventory method and coverage

Every AST Import/ImportFrom binding under framework/scripts was enumerated, with alias references and member accesses collected from its consuming source. The table records actual use lines and operations, not just module names. Dynamic script-loader calls are listed separately. Model implementation and synthetic tests are excluded from the Runtime consumer count. These counts are import bindings, not violations and not unique APIs. Each row has a disposition; none is deferred or an unresolved violation.

Runtime Model import bindings: **399**, shared contracts included below: **140**. Consumer source files with Model bindings: **102**. Internal Model Python files: **63**. Categories (including contracts): A=288, B=19, C=1, D=231.

### aws-compare-services/cloudformation-stacks.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.AcquisitionError` | D | 61,66,76,89 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 5 | `model` | B | 16,24,39 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`, `key_kind`. |

### aws-compare-services/cloudwatch-logs.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.one` | A | 14 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/codebuild.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.one` | A | 15 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/codepipeline.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `model.adapters.aws.MISSING` | D | 20 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### aws-compare-services/config.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.one` | A | 18,26 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/data-firehose.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.Unresolved` | D | 23,26 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.one` | A | 35 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/datazone.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `model.adapters.aws.Unresolved` | D | 40 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 5 | `model.adapters.aws.execution_account` | A | 28 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 5 | `model.adapters.aws.one` | A | 29 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/ec2.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.AcquisitionError` | D | 71 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.Unresolved` | D | 34 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.one` | A | 45 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/glue.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 4 | `model.adapters.aws.one` | A | 26 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/guardduty.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `model.adapters.aws.one` | A | 37,86 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/iam.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.AcquisitionError` | D | 80,87,95 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.one` | A | 33 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/kms.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.Unresolved` | D | 42,48 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.one` | A | 19 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/lambda.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `model.adapters.aws.MISSING` | D | 73,76 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 5 | `model.adapters.aws.Unresolved` | D | 29 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 5 | `model.adapters.aws.one` | A | 35,63,66 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/macie.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 4 | `model.adapters.aws.one` | A | 36 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/quicksight.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 7 | `model.adapters.aws.AcquisitionError` | D | 81 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 7 | `model.adapters.aws.IdentityError` | D | 36,54 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 7 | `model.adapters.aws.Unresolved` | D | 28,37,39,45,53,55,69,82,94,113,123,125,152 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 7 | `model.adapters.aws.execution_account` | A | 32,34,38,47,50 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/route53.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.Unresolved` | D | 62 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.one` | A | 43,63 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 4 | `model.importing.sdk_inventory.route53_pages` | A | 55 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |
| 4 | `model.importing.sdk_inventory.route53_projection` | A | 67 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |

### aws-compare-services/s3.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 7 | `model.adapters.aws.MISSING` | D | 25 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 7 | `model.adapters.aws.AcquisitionError` | D | 90,131,135 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 7 | `model.adapters.aws.Field` | D | 25 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 7 | `model.adapters.aws.one` | A | 39 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/secrets-manager.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.Unresolved` | D | 20 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### aws-compare-services/security-group.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.MISSING` | D | 199 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.AcquisitionError` | D | 152 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.Unresolved` | D | 48,52,125,137,162 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.one` | A | 90,138,206 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 3 | `model.adapters.aws.select` | A | 72,199,203 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/sqs.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws` | A | 46,47 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 使用操作: `policy`, `stable`. |
| 5 | `model.adapters.aws.MISSING` | D | 41,48,49 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 5 | `model.adapters.aws.Unresolved` | D | 45,51 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### aws-compare-services/transit-gateway.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.one` | A | 24 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/vpc-endpoint.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.Unresolved` | D | 24 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.one` | A | 35 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws-compare-services/vpc.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.adapters.aws.MISSING` | D | 14,109 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.AcquisitionError` | D | 71 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.Field` | D | 14 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.Unresolved` | D | 73,80,90,98,101,127 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 3 | `model.adapters.aws.one` | A | 39,102,104 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |

### aws_mapping_compare.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 7 | `model.importing.inventory` | A | 93 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 使用操作: `cloudcontrol_value`. |

### aws_mapping_display.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 11 | `model.display` | A | 299 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `catalog_display_rows`. |
| 12 | `model.projection` | A | 300 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `resource_rows`. |
| 13 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 306,317,390 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 13 | `contracts.model.RESOURCE_TYPE_KEY` | D | 256,279,281,305,323,324,389 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 13 | `contracts.model.key_parts` | D | 266,271 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 13 | `contracts.model.row_resource` | D | 232,236 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 21 | `model.reference_nodes.parse` | A | 316 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 26 | `model` | B | 249,255,258,265,269,280,301,360 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`, `key_kind`, `row_has_resource_prefix`. |

### check-design-naming.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `contracts.model.RESOURCE_MODE_CREATE` | D | 18,19 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 8 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 18 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 9 | `model.validations.naming.design_naming_errors` | A | 28 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |

### cloudformation-destroy.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 26 | `model.adapters.observed.destroy_plan` | A | 67 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 26 | `model.adapters.observed.sync_destroyed` | A | 753 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 27 | `model.core.stack_model` | A | 55 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 28 | `model.files.load_model` | A | 55 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### comparison/deferral.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 87 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 3 | `contracts.model.RESOURCE_TYPE_KEY` | D | 70 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |

### comparison/design_link.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `model.projection.reference_attribute` | A | 73,88 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |

### comparison/inputs.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 10 | `model.environment_values` | A | 1252 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 使用操作: `mapping_for`. |
| 11 | `model.identity` | A | 385,438 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 使用操作: `Resolver`. |
| 12 | `model.sources` | A | 83,121,405 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `Scope`, `load_model`, `project_root`. |
| 14 | `contracts.model.CFN_LOGICAL_ID_KEY` | D | 840 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 14 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 794 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 14 | `contracts.model.MODEL_UNSET` | D | 793 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 14 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 396 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 14 | `contracts.model.RESOURCE_MODE_CREATE` | D | 734,867 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 14 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 455,711 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 14 | `contracts.model.RESOURCE_TYPE_KEY` | D | 418,432,442,458,461,496,497,512,515,520,521,522,526,528,534,539,700,707,725,730,732,739,745,759,769,774,779,851,906,1196 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 14 | `contracts.model.row_resource` | D | 1193,1195 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 35 | `model.adapters.observed.mapped_resource` | A | 487 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 35 | `model.adapters.observed.resource_index` | A | 257 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 36 | `model.core.ReferenceResolutionError` | D | 118,444 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 36 | `model.core.stack_model` | A | 277 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 37 | `model.files.load_model` | A | 186 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 38 | `model.literal_values.value_shape` | D | 1262,1264 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 39 | `model.projection.reference_attribute` | A | 417,432,520,538,731,758 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 40 | `model.reference_nodes.is_reference` | A | 383 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 40 | `model.reference_nodes.parse` | A | 410 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 41 | `model.reference_values.resolve` | A | 409 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 42 | `model.sources.model_exists` | A | 272 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 42 | `model.sources.model_paths` | A | 375 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 64 | `model` | B | 103,206,208 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`, `invocation_reads`. |

### comparison/model_reference.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `contracts.model.REFERENCE_RESOURCE_TYPE_KEY` | D | 284 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 3 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 127,302 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 3 | `contracts.model.RESOURCE_TYPE_KEY` | D | 119,284,287,295 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 10 | `model.identity.Resolver` | A | 39 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 11 | `model.reference_nodes.is_reference` | A | 90 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 11 | `model.reference_nodes.nodes` | A | 202 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 11 | `model.reference_nodes.parse` | A | 104 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 11 | `model.reference_nodes.receiving_property` | A | 98,175,249,308 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 11 | `model.reference_nodes.resolve` | A | 105 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 18 | `model.references.declarations` | A | 35 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 18 | `model.references.usages` | A | 68 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |

### comparison/reference_evidence.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `contracts.model.CFN_LOGICAL_ID_KEY` | D | 130 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 5 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 35,193 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 5 | `contracts.model.MODEL_UNSET` | D | 35,194 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 5 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 125 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 5 | `contracts.model.RESOURCE_TYPE_KEY` | D | 124 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 14 | `model.adapters.observed.identifier_source` | A | 136 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 15 | `model.format.REFERENCE_NAME_SUFFIXES` | D | 182 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 16 | `model.projection.reference_attribute` | A | 41,71,96,436,454 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |

### comparison/references.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 7 | `model.projection.reference_attribute` | A | 81,250,291,297,382,398,406,536,558 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |

### comparison/resource.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `contracts.model.CFN_LOGICAL_ID_KEY` | D | 20,24 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |

### comparison/rows.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `model.literal_values.projection_conflicts` | D | 37 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 6 | `model.literal_values.value_shape` | D | 45 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### comparison/rules/cloud_trail.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `model.display.display_rows` | A | 41 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |

### comparison/rules/ec2.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 19,56,72,108,113 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 6 | `contracts.model.MODEL_UNSET` | D | 19,72 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |

### comparison/rules/kms.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `contracts.model.RESOURCE_TYPE_KEY` | D | 19 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |

### comparison/rules/quick_sight.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `model.importing.references.known` | A | 23 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |

### comparison/rules/route53.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `contracts.model.CFN_LOGICAL_ID_KEY` | D | 39,133,191 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 5 | `contracts.model.RESOURCE_TYPE_KEY` | D | 24 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 5 | `contracts.model.key_parts` | D | 59 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 5 | `contracts.model.row_resource` | D | 30,59,181 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 11 | `model.core.literal` | D | 34 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 17 | `model` | B | 27,178 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`. |

### comparison/runner.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 11 | `model.environment_values` | A | 617,618,853,857,858 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 使用操作: `identity`, `mapping_for`, `project`, `row_contexts`. |
| 12 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 192 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 12 | `contracts.model.RESOURCE_TYPE_KEY` | D | 202,347 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 18 | `model.core.ReferenceResolutionError` | D | 312 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 19 | `model.literal_values.value_shape` | D | 710 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 20 | `model.sources.project_root` | A | 159 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### comparison/values.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `model.environment_values` | A | 78 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 使用操作: `project`. |
| 9 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 262,329 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 9 | `contracts.model.MODEL_UNSET` | D | 264 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 11 | `model.literal_values.literal_errors` | D | 271 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 12 | `model.literal_values.typed_value` | D | 281 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 12 | `model.literal_values.value_shape` | D | 270,276,280 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 13 | `model.reference_nodes.is_reference` | A | 128,287 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |

### deploy/cli_guidance.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 15 | `contracts.model.REFERENCE_PENDING_DEPLOY` | D | 193 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 15 | `contracts.model.REFERENCE_UNRESOLVED` | D | 194 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 16 | `model.core.ReferenceDiagnosticError` | D | 272,279 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### deploy/contract_correction.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 16 | `model.dependency_index.revision` | A | 467,648 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 17 | `model.render.owned_artifacts` | A | 87 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 18 | `model.sources.load_model` | A | 78 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 18 | `model.sources.publication_lock` | A | 767 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 18 | `model.sources.source_scope` | A | 82 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### deploy/contracts.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 7 | `model.importing.repository.task_start_commit` | A | 52 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |

### deploy/controller.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 23 | `model.core.ARTIFACT_PROPERTIES` | D | 248 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 24 | `model.projection.deployment_bucket` | A | 264,269 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 25 | `model.references.has_reference` | A | 261,268 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |

### deploy/correction_scope.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `contracts.model.key_parts` | D | 160 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 8 | `contracts.model.row_resource` | D | 160 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 9 | `model.format.parse` | A | 149,152 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 10 | `model.observed.verify_observed_outputs` | A | 182 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 11 | `model.render.owned_artifacts` | A | 131 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 12 | `model.sources.load_model` | A | 115,148 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 12 | `model.sources.source_scope` | A | 148 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### deploy/deferred.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `contracts.model.CFN_LOGICAL_ID_KEY` | D | 29 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 5 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 25 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 5 | `contracts.model.key_parts` | D | 58,130 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 6 | `model.configuration.foreign_observation` | A | 60,130 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 7 | `model.references.usages` | A | 50 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 8 | `model.sources.load_model` | A | 118 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 8 | `model.sources.raw_model` | A | 23,47 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 12 | `model` | B | 22 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`. |

### deploy/delivery.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 19 | `model.core.ARTIFACT_PROPERTIES` | D | 233 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### deploy/failures.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 9 | `contracts.model.REFERENCE_PENDING_DEPLOY` | D | 37 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 10 | `model.core.ReferenceDiagnosticError` | D | 34 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### deploy/generation_resume.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 9 | `contracts.model.CFN_LOGICAL_ID_KEY` | D | 220 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 9 | `contracts.model.REFERENCE_PENDING_DEPLOY` | D | 190,590,676 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 9 | `contracts.model.RESOURCE_MODE_CREATE` | D | 215,216 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 16 | `model.core.ReferenceResolutionError` | D | 675 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 17 | `model.identity.Resolver` | A | 550 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 18 | `model.importing.scope.read_context` | A | 280 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |
| 19 | `model.sources.publication_lock` | A | 155,536 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 19 | `model.sources.safe` | A | 121,125 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 19 | `model.sources.scope_for` | A | 196,280 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 19 | `model.sources.session_reads` | A | 265,299 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 19 | `model.sources.source_scope` | A | 285,306 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### deploy/git_publication.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 14 | `model.format.parse` | A | 215 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 15 | `model.observed.verify_observed_outputs` | A | 58 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### deploy/inputs.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 10 | `model.core.deployment_settings` | A | 146 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 10 | `model.core.positive_integer` | D | 111 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 10 | `model.core.stack_context` | A | 44,51,107,113,116 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 10 | `model.core.stack_model` | A | 143 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 10 | `model.core.validate_model_keys` | A | 88 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 10 | `model.core.validate_stack_field` | A | 110 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 10 | `model.core.validate_stack_metadata` | A | 89 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 19 | `model.format.owner` | A | 71 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 20 | `model.references.declarations` | A | 90 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 21 | `model.sources.raw_model` | A | 137 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 29 | `model` | B | 39,54,62,64,66,70,83,102 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`, `key_kind`. |
| 30 | `model.key_parts` | A | 65,67,85 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |

### deploy/model_cache.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `model.sources` | A | 135,136,154,155,162 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `Scope`, `model_session`. |
| 9 | `model.dependency_index.logical_models` | A | 163 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 9 | `model.dependency_index.revision` | A | 71,73,171,174 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 9 | `model.dependency_index.verify_snapshot` | A | 149 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 10 | `model.importing.scope.read_context` | A | 99,143 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |
| 14 | `model.load_model_in_session` | A | 158 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 14 | `model.read_source_in_session` | A | 139 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 14 | `model.rebase_snapshot` | A | 132 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 14 | `model.update_observed_snapshot` | A | 186 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |

### deploy/observed.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 285,459,520,559 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 8 | `contracts.model.RESOURCE_TYPE_KEY` | D | 480 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 15 | `model.adapters.aws.Unresolved` | D | 208 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 15 | `model.adapters.aws.service_module` | A | 193 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 16 | `model.adapters.observed.active_outputs` | A | 476,484 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 16 | `model.adapters.observed.ambiguous` | A | 73,405,546,627,629,657 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 16 | `model.adapters.observed.identifier_source` | A | 470 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 16 | `model.adapters.observed.observed_destinations` | A | 303,575 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 16 | `model.adapters.observed.own_key` | A | 285,533 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 16 | `model.adapters.observed.propagate_references` | A | 288,562 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 16 | `model.adapters.observed.resolve_resources` | A | 238,341 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 16 | `model.adapters.observed.static_export_handle` | A | 543 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 36 | `model.dependency_index` | A | 216 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `load`. |

### deploy/observed_resume.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 10 | `model.adapters.observed` | A | 619 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 使用操作: `publish_observed`. |
| 12 | `contracts.model.key_parts` | D | 362,373 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 12 | `contracts.model.row_resource` | D | 362,380 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 13 | `model.format.parse` | A | 354,355,356 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 13 | `model.format.patch` | A | 390,391 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 14 | `model.observed.verify_observed_outputs` | A | 353,409,517 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 15 | `model.sources.load_model` | A | 36 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 15 | `model.sources.publication_lock` | A | 407,595 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 15 | `model.sources.safe` | A | 111,170,200,345,508,534 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 15 | `model.sources.source_scope` | A | 32,427,536 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 28 | `model.dependency_index` | A | 605 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `update`. |

### deploy/preparation.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 22 | `contracts.model.CFN_LOGICAL_ID_KEY` | D | 140,142 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 22 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 121,154 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 22 | `contracts.model.RESOURCE_MODE_CREATE` | D | 146,147 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 29 | `model.adapters.observed.resolve_resources` | A | 106 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 |
| 30 | `model.dependency_index.inventory` | A | 302,304,518,528 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 31 | `model.dependency_index.revision` | A | 301,305,367,510 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 32 | `model.render.owned_artifacts` | A | 189 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 33 | `model.sources.load_model` | A | 186 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 33 | `model.sources.model_session` | A | 102 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 33 | `model.sources.raw_model` | A | 136 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 41 | `model` | B | 137 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`. |
| 52 | `model.dependency_index` | A | 103,135 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `check_change_inventory`, `owners`. |

### deploy/run_context.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 12 | `model.dependency_index.revision` | A | 104,112,179 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### deploy/s3_delivery.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 38 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 8 | `contracts.model.MODEL_UNSET` | D | 37 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 15 | `model.references.has_reference` | A | 208 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |

### deploy/scope.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 7 | `model.adapters.observed` | A | 137 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 使用操作: `resolve_resources`. |
| 8 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 60,85,153,193 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 10 | `model.change_plan.ServiceChange` | D | 213 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 11 | `model.format.owner` | A | 206 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 12 | `model.sources.FileReads` | D | 236 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 12 | `model.sources.load_model` | A | 188 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 13 | `model.validations.change_inputs.check_change_inputs` | A | 231 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 20 | `model` | B | 192,198,210,227 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`, `key_kind`. |
| 22 | `model.row_resource` | A | 162,165,211,224 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |

### deploy/secret_bootstrap.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `model.adapters.observed` | A | 169 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 使用操作: `resolve_resources`. |
| 11 | `contracts.model.CFN_LOGICAL_ID_KEY` | D | 347 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 11 | `contracts.model.RESOURCE_MODE_CREATE` | D | 211,212,346 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |

### deploy/steps.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 17 | `contracts.model.REFERENCE_PENDING_DEPLOY` | D | 663,664 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 20 | `model.sources.model_session` | A | 844,879 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### design/array_display.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 10 | `model.core.LINK` | D | 135 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### design/catalog.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 15 | `model.reference_nodes.is_reference` | A | 79,92,98,115 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 15 | `model.reference_nodes.parse` | A | 80,93,99,116 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |

### design/common.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `model.core.LINK` | D | 63 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### design/compact_rows.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `model.core.LINK` | D | 25,79 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 6 | `model.core.literal` | D | 92,101,111,120 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### design/document.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 19 | `model.display` | A | 175,235,246,254,259,402,407,441,680 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `ReferenceTable`, `reference_rows`. |
| 20 | `model.identity` | A | 357,396,592,688,709 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 使用操作: `display_anchor`. |
| 21 | `model.projection` | A | 580 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `bound_resource_anchors`. |
| 22 | `model.references` | A | 242 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 使用操作: `codebuild_reference_errors`. |
| 23 | `model.render` | A | 247,295,337 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `generate_markdown`, `service_note_markdown`. |
| 24 | `model.sources` | A | 165,613,614 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `design_project_root`, `load_model`, `model_exists`. |
| 26 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 369,591,708 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 26 | `contracts.model.RESOURCE_TYPE_KEY` | D | 590,707 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 28 | `model.core.SnapshotValues` | D | 172,231,234,271,272,289,334,623,748,749 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 38 | `model` | B | 273,328,593,685,710 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`. |

### design/layout.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 10 | `model.core` | A | 706 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `literal`. |
| 11 | `model.display` | A | 757 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `display_rows`. |
| 12 | `model.identity` | A | 201 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 使用操作: `display_anchor`. |
| 13 | `model.sources` | A | 187,188 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `load_model`, `model_exists`. |
| 15 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 392,1093,1113 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 15 | `contracts.model.MODEL_UNSET` | D | 392,1092 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 15 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 1123,1155,1170,1207,1213 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 15 | `contracts.model.RESOURCE_MODE_CREATE` | D | 179,180,220,239,640,656 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 15 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 180,228,364,736,803 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 15 | `contracts.model.RESOURCE_TYPE_KEY` | D | 1122,1138,1202,1207,1213 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 24 | `model.core.ReferenceResolutionError` | D | 810,879,1013,1100,1169 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 24 | `model.core.literal` | D | 850,1161 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 24 | `model.core.positive_integer` | D | 302,441 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 25 | `model.reference_nodes.nodes` | A | 706,1161 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 38 | `model` | B | 204,481 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`, `key_kind`. |

### design/policy_tables.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 16 | `model.projection` | A | 418,425,433,456 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `display_document`, `generated_document`, `reference_context_for`. |
| 17 | `model.render` | A | 726 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `generate_markdown`. |
| 19 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 268 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 19 | `contracts.model.MODEL_UNSET` | D | 268 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 21 | `model.core.literal` | D | 244,267 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 22 | `model.identity.Resolver` | A | 459 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 23 | `model.reference_nodes.is_reference` | A | 482,522,529,538,541,562,575 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 23 | `model.reference_nodes.nodes` | A | 449 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 23 | `model.reference_nodes.project` | A | 587,601 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 23 | `model.reference_nodes.reference_document` | A | 587,601 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 24 | `model.sources.scope_for` | A | 451 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### design/services/cloudtrail.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `contracts.model.MODEL_REF_KEY` | D | 70 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 6 | `contracts.model.REFERENCE_PENDING_DEPLOY` | D | 44 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 6 | `contracts.model.REFERENCE_UNRESOLVED` | D | 44 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 6 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 100,111,158 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 12 | `model.core.LINK` | D | 153 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 12 | `model.core.ReferenceResolutionError` | D | 57,114 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 12 | `model.core.literal` | D | 65,67,104,139,142,144,146,157,159 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 12 | `model.core.require_reference_diagnostics` | A | 40,56 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |

### design/services/codebuild.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `contracts.model.RESOURCE_MODE_CREATE` | D | 47,86 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 5 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 73,126 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 6 | `model.core.LINK` | D | 60,68 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 6 | `model.core.ReferenceResolutionError` | D | 80,109,127 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 6 | `model.core.literal` | D | 54 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### design/services/codepipeline.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `model.core.LINK` | D | 110 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 6 | `model.core.literal` | D | 81 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 7 | `model.reference_nodes.is_reference` | A | 87,103 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 7 | `model.reference_nodes.parse` | A | 88,195 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |

### design/services/config.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 19 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 6 | `model.core.literal` | D | 13 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### design/services/ec2/display.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 101,122 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |

### design/services/ec2/security_groups.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 10 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 481 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 10 | `contracts.model.RESOURCE_TYPE_KEY` | D | 473,477 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 11 | `model.core.literal` | D | 447,449,489,490 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### design/services/glue.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `model.core.literal` | D | 19 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### design/services/guardduty.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `model.core.literal` | D | 48 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### design/services/kms.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `model.references` | A | 44,46 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 使用操作: `is_reference`, `kms_observation`. |
| 4 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 52,58 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 4 | `contracts.model.RESOURCE_TYPE_KEY` | D | 33,35 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 6 | `model` | A | 40 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `parse_reference_field`. |

### design/services/route53.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 3 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 77 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 3 | `contracts.model.MODEL_REF_KEY` | D | 67 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 3 | `contracts.model.REFERENCE_LOGICAL_ID_KEY` | D | 68 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 3 | `contracts.model.RESOURCE_TYPE_KEY` | D | 89 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 9 | `model.core.ReferenceDiagnosticError` | D | 74 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 10 | `model.reference_nodes.nodes` | A | 38 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 10 | `model.reference_nodes.parse` | A | 54,65 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 10 | `model.reference_nodes.reference_document` | A | 46 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 11 | `model.reference_values.reference_value` | A | 62 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 13 | `model` | A | 92 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `parse_reference_field`. |

### iac_evaluation.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 10 | `contracts.model.CFN_LOGICAL_ID_KEY` | D | 112,114 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 10 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 168 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 10 | `contracts.model.MODEL_UNSET` | D | 168 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 10 | `contracts.model.RESOURCE_TYPE_KEY` | D | 73,125,130,134 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |

### import_guard.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 11 | `model.core` | A | 217 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `report_reference_warnings`. |
| 12 | `model.importing.evidence` | A | 327,331 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 使用操作: `read_proof`. |
| 13 | `model.importing.repository` | A | 66,78,87,218,401 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 使用操作: `changed_paths`, `has_baseline`, `task_start_commit`, `working_revision`. |
| 14 | `model.operations` | A | 282,305,370 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `validate_candidates`, `verify_model_operation`, `verify_model_refactor`. |
| 15 | `model.sources` | A | 189 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `safe`. |
| 20 | `model.change_scope.index_stage` | A | 167,173 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### issues/cfn_lint.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `model.sources` | A | 248 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `model_paths`. |
| 9 | `contracts.model.CFN_LOGICAL_ID_KEY` | D | 206,208,277,279 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 9 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 193,199,200 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 9 | `contracts.model.RESOURCE_TYPE_KEY` | D | 194 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 16 | `model` | B | 138 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`. |

### issues/materials.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 4 | `contracts.model.CFN_LOGICAL_ID_KEY` | D | 342 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 4 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 341 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 4 | `contracts.model.RESOURCE_MODE_CREATE` | D | 333 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 4 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 251,322 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 4 | `contracts.model.RESOURCE_TYPE_KEY` | D | 78,98,116 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 19 | `model.validations.naming.NAMING_EXEMPT_PROPERTIES` | D | 324,331 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 19 | `model.validations.naming.naming_rule_files` | A | 135 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 19 | `model.validations.naming.naming_target_matches` | A | 178 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 19 | `model.validations.naming.naming_targets` | A | 170 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 19 | `model.validations.naming.provider_naming_errors` | A | 289 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 19 | `model.validations.naming.value_available` | A | 188,262,279 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |

### issues/publication.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `model.sources` | A | 83 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `publication_lock`. |

### issues/reader.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 7 | `model.validations.naming.NamingRuleIndex` | A | 18,110 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |

### issues/review.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 11 | `contracts.model.RESOURCE_MODE_CREATE` | D | 339,466,479 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 11 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 567,876 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 13 | `model.core.literal` | D | 281,599 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 14 | `model.validations.naming.NAMING_EXEMPT_PROPERTIES` | D | 338 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 14 | `model.validations.naming.NamingRuleIndex` | A | 172,291,310,387,449,526,575,884,966 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 14 | `model.validations.naming.check_iam_role_suffix` | A | 393 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 14 | `model.validations.naming.provider_naming_errors` | A | 325 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 14 | `model.validations.naming.value_available` | A | 282 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |

### issues/review_progress.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 9 | `model.sources.publication_lock` | A | 339,358,392,456,511,535,580 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### issues/runner.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 9 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 177 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 9 | `contracts.model.RESOURCE_TYPE_KEY` | D | 163 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 12 | `model.core.ReferenceResolutionError` | D | 453 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 13 | `model.references.codebuild_reference_errors` | A | 181 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 14 | `model.validations.naming.NamingRuleIndex` | A | 636 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 24 | `model` | B | 162 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`. |

### json_intrinsics.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 102,175 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 9 | `model.reference_nodes.is_reference` | A | 106,121,156 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 9 | `model.reference_nodes.nodes` | A | 168 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 9 | `model.reference_nodes.parse` | A | 107,123,157 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |

### sync-model.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 17 | `model.change_plan` | A | 196 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `task_plan`. |
| 18 | `model.impact` | A | 180,181 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `scope_diagnostic`, `task_impact`. |
| 19 | `model.importing.scope` | A | 185 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 使用操作: `selected`. |
| 20 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 246 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 20 | `contracts.model.REFERENCE_PENDING_DEPLOY` | D | 243 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 21 | `model.core.ReferenceResolutionError` | D | 231,233,241 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### sync_runtime.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 12 | `model.importing.cli` | A | 529 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 使用操作: `recover_display`. |
| 13 | `model.importing.scope` | A | 519 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 使用操作: `readable`. |
| 14 | `model.projection` | A | 299,302,325,360 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `generated_document`, `reference_context_for`, `reference_resolver`. |
| 15 | `model.sources` | A | 182,183,293,697 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `FileReads`, `model_stage`, `raw_model`, `source_scope`. |
| 20 | `contracts.model.REFERENCE_PENDING_DEPLOY` | D | 422,927,1028,1029 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 20 | `contracts.model.REFERENCE_UNRESOLVED` | D | 980,1030 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 20 | `contracts.model.row_resource` | D | 322,357 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 26 | `model.change_scope.change_reads` | A | 562,698 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 26 | `model.change_scope.index_stage` | A | 699 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 27 | `model.core.ReferenceDiagnosticError` | D | 330,365,402,721,729 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 27 | `model.core.ReferenceResolutionError` | D | 407,1032 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 27 | `model.core.require_reference_diagnostics` | A | 376 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 32 | `model.format.JSON_LINK` | D | 304 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 33 | `model.importing.scope.scoped` | A | 583,1041 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |
| 34 | `model.importing.scope.selected` | A | 518,520,530,566,1143 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |
| 35 | `model.projection.resource_row_scope` | A | 269 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 36 | `model.render.generate_files` | A | re-export | 互換 re-export。呼び出し側の公開名を保持（削除による API 変更を避ける）。 |
| 37 | `model.render.render_validated_model` | A | 382 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 38 | `model.sources.load_model` | A | 159,715 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 38 | `model.sources.model_exists` | A | 157 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 38 | `model.sources.publication_lock` | A | 567,667,802 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 38 | `model.sources.safe` | A | 135,338,821 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 44 | `model.sources.model_paths` | A | 222 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 45 | `model.validations.policies.validate_kms_policy_accounts` | A | re-export | 互換 re-export。呼び出し側の公開名を保持（削除による API 変更を避ける）。 |
| 48 | `model.validations.schema.validate_required_properties` | A | re-export | 互換 re-export。呼び出し側の公開名を保持（削除による API 変更を避ける）。 |
| 88 | `model` | B | 208,303,310 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`, `key_kind`, `parse_reference_field`. |
| 89 | `model.publish_transaction` | C | 846 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |

### task_contract_core.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 15 | `contracts.model.key_parts` | D | 859 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 15 | `contracts.model.row_resource` | D | 860 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |

### task_contract_runtime.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 10 | `model.importing.scope.read_consumers` | A | 129 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |
| 10 | `model.importing.scope.require_write_scope` | A | 135 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |
| 10 | `model.importing.scope.restrict` | A | 129 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |
| 10 | `model.importing.scope.selected` | A | 117 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 |
| 16 | `model.sources.source_scope` | A | 127 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### utils/arn_components.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 42 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 5 | `contracts.model.MODEL_UNSET` | D | 42 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |

### utils/arn_values.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 61 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 6 | `contracts.model.MODEL_UNSET` | D | 61 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |

### utils/cloudformation/environment.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 80 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 12 | `model.environment_values.inspect` | A | 136 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 12 | `model.environment_values.mapping_for` | A | 127 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 12 | `model.environment_values.state` | A | 25 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |

### utils/json_format.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `contracts.model.MODEL_REF_KEY` | D | 31 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |

### validation/acceptance.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 19 | `model.change_plan` | A | 154 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `task_plan`. |
| 19 | `model.references` | A | 176 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 使用操作: `diagnose`. |
| 19 | `model.sources` | A | 157,175,178,182 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `raw_model`, `source_scope`. |

### validation/change.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 5 | `model.projection` | A | 110,230 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `reference_context_for`, `validate_json_documents`. |
| 6 | `model.validations.change_inputs` | A | 92 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `check_change_inputs`. |
| 7 | `contracts.model.REFERENCE_PENDING_DEPLOY` | D | 182 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 7 | `contracts.model.RESOURCE_TYPE_KEY` | D | 233,238,246 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 7 | `contracts.model.key_parts` | D | 228 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 10 | `model.change_scope.change_reads` | A | 71 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 11 | `model.core.ReferenceResolutionError` | D | 180 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 12 | `model.identity.Resolver` | A | 190 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 12 | `model.identity.display_anchor` | A | 89 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 13 | `model.reference_values.ProducerValues` | A | 243 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 17 | `model` | B | 217,227,229 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`, `key_kind`. |
| 18 | `model.change_plan` | A | 77,84,132,143,144,146,148 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `ChangePlan`, `collect_contracts`, `compare`, `comparison_snapshot`, `resource_map`, `task_plan`. |
| 18 | `model.reference_snapshot` | A | 33 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 18 | `model.references` | A | 41,193 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 使用操作: `declarations`, `diagnose`. |

### validation/cloudformation.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 8 | `model.adapters.observed` | A | 481 | 既存の取得／Observed 対応 API。応答の取得・識別・正規化を再実装しない。 使用操作: `validate_mapping_targets`. |
| 9 | `model.core` | A | 475,490 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `deployment_settings`, `stack_model`. |
| 10 | `model.projection` | A | 476 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `deployment_bucket`. |
| 13 | `model.core.properties` | A | 489 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 14 | `model.files.read_model` | A | 489 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 15 | `model.sources.model_exists` | A | 486 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### validation/design.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 19 | `model.files` | A | 1087 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `read_model`. |
| 20 | `model.projection` | A | 718 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `bound_resource_anchors`. |
| 21 | `model.render` | A | 615,616 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `display_name`, `resource_presentation`. |
| 22 | `model.sources` | A | 349,975 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `model_exists`. |
| 23 | `model.sources` | A | 112,617 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `Scope`, `load_model`. |
| 26 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 660 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 26 | `contracts.model.MODEL_UNSET` | D | 660 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 26 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 726,751 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 26 | `contracts.model.RESOURCE_MODE_CREATE` | D | 436 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 26 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 577,1001 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 26 | `contracts.model.RESOURCE_TYPE_KEY` | D | 725,751 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 26 | `contracts.model.key_parts` | D | 998 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 26 | `contracts.model.row_resource` | D | 998 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 48 | `model.core.ReferenceDiagnosticError` | D | 118,760 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 48 | `model.core.ReferenceResolutionError` | D | 248,650,924,983 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 48 | `model.core.properties` | A | 500,502,982 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 |
| 57 | `model` | B | 728,755,995 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`, `key_kind`. |

### validation/design_links.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 10 | `model.importing.references` | A | 547 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 使用操作: `Resolver`. |
| 11 | `model.importing.scope` | A | 156,481 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 使用操作: `outside_design`. |
| 12 | `model.projection` | A | 523 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `reference_resolver`. |
| 13 | `model.references` | A | 526,566 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 使用操作: `diagnose`, `has_reference`. |
| 14 | `model.sources` | A | 518,569 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `load_model`, `scope_for`. |
| 16 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 735,737 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 16 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 542 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 16 | `contracts.model.RESOURCE_TYPE_KEY` | D | 732,782 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 16 | `contracts.model.row_resource` | D | 550,869 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 43 | `model.core.LINK` | D | 866,887 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 43 | `model.core.ReferenceDiagnosticError` | D | 119 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 43 | `model.core.ReferenceResolutionError` | D | 91,493,591,616,694,739 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 43 | `model.core.literal` | D | 512,784,902 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 49 | `model.reference_nodes.nodes` | A | 512 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 49 | `model.reference_nodes.receiving_property` | A | 877 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 50 | `model.reference_presentation.Presentation` | D | 864 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 53 | `model` | B | 541,549,773,778,883 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`. |

### validation/design_tables.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 10 | `model.core` | A | 92 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `properties`. |
| 11 | `model.files` | A | 114 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `load_model`. |
| 13 | `contracts.model.MODEL_PENDING_DEPLOY` | D | 97,167,335,340,1077,1159,1314 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 13 | `contracts.model.MODEL_UNSET` | D | 335,340,1159,1197 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 13 | `contracts.model.RESOURCE_LOGICAL_ID_KEY` | D | 129,695,818,825,849,856 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 13 | `contracts.model.RESOURCE_MODE_CREATE` | D | 197,709,1021,1035,1254 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 13 | `contracts.model.RESOURCE_MODE_IMPORT` | D | 128,226,246,257,1023,1037 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 13 | `contracts.model.RESOURCE_TYPE_KEY` | D | 694,812,834 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 50 | `model.core.ReferenceDiagnosticError` | D | 381 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 50 | `model.core.ReferenceResolutionError` | D | 207,384,623,651,793,822,928,1323,1341 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 50 | `model.core.literal` | D | 134,1107,1113 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 51 | `model.literal_values.literal_errors` | D | 1079 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |
| 52 | `model.projection.bound_resource_anchors` | A | 690 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 52 | `model.projection.is_import_expression` | A | 992 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 |
| 53 | `model.reference_nodes.nodes` | A | 1107,1113 | 参照・識別子・環境値の解析／解決を Model に委譲。結果の業務判断は呼び出し側。 |
| 58 | `model` | B | 126,136,137,697 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`, `row_has_resource_prefix`. |

### validation/findings.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 7 | `contracts.model.REFERENCE_PENDING_DEPLOY` | D | 36,559,708,716,756,763 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 7 | `contracts.model.REFERENCE_UNRESOLVED` | D | 35,559,707,715,757 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 9 | `model.core.ReferenceDiagnosticError` | D | 489,700 | 型・例外・定数・純粋な値処理。Snapshot の構成／変更を行わない。 |

### validation/loop.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 24 | `model.importing.evidence` | A | 500,592 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 使用操作: `copy_import_proof`, `discard_import_proof`. |

### validation/project.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 9 | `model.core` | A | 118 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ReferenceResolutionError`. |
| 10 | `model.importing.scope` | A | 185,218 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 使用操作: `selected`, `view_targets`. |
| 11 | `model.sources` | A | 72,86,105,119,153 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `FileReads`, `load_model`, `model_exists`, `source_scope`. |
| 20 | `model.change_plan.assemble` | A | 79 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 20 | `model.change_plan.task_plan` | A | 90 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 21 | `model.impact.scope_diagnostic` | A | 142 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### validation/runner.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 19 | `model.change_plan` | A | 1202 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `task_plan`. |
| 20 | `model.core` | A | 75 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `properties`. |
| 21 | `model.core` | A | 248 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ReferenceDiagnosticError`. |
| 22 | `model.sources` | A | 370,787 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `load_model`, `publication_lock`. |
| 23 | `model.validations.full_inputs` | A | 786 | 既存の Model 投影・描画・検証／設定 API。返却結果の配置・判定・実行制御は利用側。 使用操作: `check_model_inputs`. |
| 30 | `contracts.model.RESOURCE_MODE_CREATE` | D | 1483 | 共有契約。Model の起動・I/O・認可を伴わない定数／Key 操作。 |
| 72 | `model` | B | 1620 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`. |

### validation/task.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 10 | `model.importing.repository` | A | 93 | 取得・保存の許可範囲、証跡、既存 Import 操作を Model に委譲。呼び出し側は実行を制御。 使用操作: `task_start_commit`. |
| 11 | `model.observed` | A | 435 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `verify_observed_outputs`. |
| 15 | `model.core.properties` | A | re-export | 互換 re-export。呼び出し側の公開名を保持（削除による API 変更を避ける）。 |
| 16 | `model.impact.task_impact` | A | 355 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### validation_cache.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 11 | `model.files` | A | 117 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `read_model`. |
| 12 | `model.sources` | A | 84,85 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `model_exists`, `source_inputs`. |

### validation_scope.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 6 | `model.sources` | A | 14 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `model_paths`. |

### worktree_checkpoint.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 17 | `model.observed.verify_observed_outputs` | A | 40 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |
| 18 | `model.sources.source_scope` | A | 55 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 |

### worktree_runtime.py

| Import line | Dependency | Class | Use lines | Disposition |
| ---: | --- | :---: | --- | --- |
| 14 | `model.sources` | A | 64,65 | Model の読み取り、入力追跡、変更計画、検証済み公開・整合性確認を既存 API に委譲。 使用操作: `Scope`, `load_model`. |
| 27 | `model` | B | 69 | 既存公開 API／ModelView／Model Key 契約を利用。内部構造の再解析・再構成を行わない。 使用操作: `ModelView`. |

## Dynamic Model loading

These existing lazy loads preserve initialization order. AWS adapter Model is an acquisition/comparison facade, not ModelSnapshot reconstruction. All remain existing named operations (A), or scalar selector/Field contracts (D).

| Consumer | Line | Module | Use and reason |
| --- | ---: | --- | --- |
| `aws_mapping_catalog.py` | 44 | `model.adapters.aws` | `comparator = module("model/adapters/aws.py", "model.adapters.aws")`; existing mapping acquisition/selection or verified Observed validation. |
| `aws_mapping_catalog.py` | 112 | `model.adapters.aws` | `comparator = module("model/adapters/aws.py", "model.adapters.aws")`; existing mapping acquisition/selection or verified Observed validation. |
| `aws_mapping_compare.py` | 40 | `model.adapters.aws` | `m = module("model/adapters/aws.py", "model.adapters.aws")`; existing mapping acquisition/selection or verified Observed validation. |
| `aws_mapping_compare.py` | 114 | `model.adapters.aws` | `m = module("model/adapters/aws.py", "model.adapters.aws")`; existing mapping acquisition/selection or verified Observed validation. |
| `deploy/s3_delivery.py` | 159 | `model.adapters.aws` | `models[path] = module("model/adapters/aws.py", "model.adapters.aws").Model(`; existing mapping acquisition/selection or verified Observed validation. |
| `utils/cli_deploy.py` | 91 | `model.observed` | `verify_observed_outputs = module(`; existing mapping acquisition/selection or verified Observed validation. |
| `utils/mapping_runtime.py` | 11 | `model.adapters.aws` | `comparator = module("model/adapters/aws.py", "model.adapters.aws")`; existing mapping acquisition/selection or verified Observed validation. |

## Static consumer gate (Phase 5)

`framework/scripts/tests/units/model-encapsulation-unit.checks.py` runs automatically through the existing Framework UT discovery. Its standard-library AST helper is `tests/support/model_encapsulation.py`; it imports no Model code and executes no scanned source. The inventory above records the Phase 4 review, not a permanent exception list or a line-number-based allowlist.

The gate rejects private qualified Model symbols (including aliases and literal script-loader references), direct structural enumeration/index entrypoints, ModelSnapshot construction and `dataclasses.replace`/`copy.replace` of recognized snapshots, external `_replace` access, ModelView private state, assignment/deletion/augmented assignment and mutating methods on recognized Snapshot state and its aliases. Literal `getattr`/`setattr` access is included. Type imports alone remain allowed.

Known structural parser patterns are also rejected: Key-variable splitting on `.`, Row identity extraction using `rpartition('-')`, structural-prefix tests on Model Key expressions and capturing regexes that extract Model Row/Resource/Reference identities. Noncapturing regular expressions used only to restrict permitted Task/Deferred fields are business authorization policy and remain allowed; they neither resolve ownership nor reconstruct Model structure. Display strings, literal business-property lookups, property-path parsing, unrelated dataclass replacement and independent copies of values remain allowed.

Model implementation sources, `contracts/model.py` and synthetic test fixtures are implementation/test boundaries rather than Runtime consumers. Every other Framework Python source is checked; no existing-violation file or line exceptions are stored. The real-source gate currently finds zero violations. Snapshot tracking covers known Model loader calls, annotated parameters, conventional snapshot parameters and simple assignments/aliases within lexical function scopes. This is a regression gate for known AST patterns, not an interprocedural Python type checker or a proof about arbitrary dynamic code.

The first real-source run found `FileReads.fork()` reconstructing a ModelSnapshot to deep-copy warnings. That exact operation now lives in Model's `copy_snapshot_warnings()` API. A lazy package import preserves the lower-level FileReads/Model initialization order. Only diagnostic dictionaries are copied; authority, dependency identity, caches, warnings contents and fork conditions retain the previous behavior. No Runtime monkey patch or new dependency is introduced.

Guard tests feed prohibited and permitted synthetic sources to the same repository-scan function, assert violations raise AssertionError and check the production Framework tree. Regressions in the guard's failure path therefore fail UT rather than merely proving that a visitor was called.
