# 承認済みセキュリティ・パッチ管理の命名ルールを登録する

## Task contract

- Task type: `governance`
- Target: framework共通 / WAF、Network Firewall、VPC Block Public Access、SCP、Firewall Manager、SSM Patch Manager、Config Rules、TGW
- Goal: 今回humanが承認した命名patternを登録し、対象サービスのcatalog登録と命名coverageを確認する。WAF prefixはwafacl／wafrg／wafipを使用する。TGWの既存patternと前taskのcatalog追加を保持する。

## Required changes

- [R1] WAFの3型、Network Firewallの3型、SCP、FMS、SSMの5型、ConfigRule、VPC BPA ExclusionのName tagについて承認済み命名patternを登録する。SCPの環境共有時のenvironment省略、SSM AssociationNameとdocument Nameの区別、BPA Optionsの名称不要を明記する。
- [R2] 今回対象25型のcatalogが登録済みであることを確認する。不足なしの確認済みcatalog、schema、checksum、display方針は変更しない。
- [R3] 既存focused checksで名称propertyとName tagのcoverage、確定例のprovider schema適合、SSM document名の除外、TGW既存coverageを検証する。

## Acceptance checks

- [R1] `changed:framework/rules/aws-resource-naming.md`
- [R2] `exists:framework/materials/aws/EC2_VPCBlockPublicAccessOptions.properties`
- [R2] `exists:framework/materials/aws/EC2_VPCBlockPublicAccessExclusion.properties`
- [R2] `exists:framework/materials/aws/Organizations_Policy.properties`
- [R2] `exists:framework/materials/aws/FMS_Policy.properties`
- [R2] `exists:framework/materials/aws/SSM_PatchBaseline.properties`
- [R2] `exists:framework/materials/aws/SSM_Association.properties`
- [R2] `exists:framework/materials/aws/SSM_MaintenanceWindow.properties`
- [R2] `exists:framework/materials/aws/SSM_MaintenanceWindowTarget.properties`
- [R2] `exists:framework/materials/aws/SSM_MaintenanceWindowTask.properties`
- [R2] `exists:framework/materials/aws/Config_ConfigRule.properties`
- [R2] `exists:framework/materials/aws/WAFv2_WebACL.properties`
- [R2] `exists:framework/materials/aws/WAFv2_RuleGroup.properties`
- [R2] `exists:framework/materials/aws/WAFv2_IPSet.properties`
- [R2] `exists:framework/materials/aws/WAFv2_WebACLAssociation.properties`
- [R2] `exists:framework/materials/aws/WAFv2_LoggingConfiguration.properties`
- [R2] `exists:framework/materials/aws/NetworkFirewall_Firewall.properties`
- [R2] `exists:framework/materials/aws/NetworkFirewall_FirewallPolicy.properties`
- [R2] `exists:framework/materials/aws/NetworkFirewall_RuleGroup.properties`
- [R2] `exists:framework/materials/aws/NetworkFirewall_LoggingConfiguration.properties`
- [R2] `exists:framework/materials/aws/EC2_TransitGateway.properties`
- [R2] `exists:framework/materials/aws/EC2_TransitGatewayVpcAttachment.properties`
- [R2] `exists:framework/materials/aws/EC2_TransitGatewayRoute.properties`
- [R2] `exists:framework/materials/aws/EC2_TransitGatewayRouteTable.properties`
- [R2] `exists:framework/materials/aws/EC2_TransitGatewayRouteTableAssociation.properties`
- [R2] `exists:framework/materials/aws/EC2_TransitGatewayRouteTablePropagation.properties`
- [R3] `changed:framework/scripts/model_design.checks.py`

## Allowed paths

- `framework/materials/aws/Config_ConfigRule.properties`
- `framework/materials/aws/EC2_VPCBlockPublicAccessExclusion.properties`
- `framework/materials/aws/EC2_VPCBlockPublicAccessOptions.properties`
- `framework/materials/aws/FMS_Policy.properties`
- `framework/materials/aws/Organizations_Policy.properties`
- `framework/materials/aws/SSM_Association.properties`
- `framework/materials/aws/SSM_MaintenanceWindow.properties`
- `framework/materials/aws/SSM_MaintenanceWindowTarget.properties`
- `framework/materials/aws/SSM_MaintenanceWindowTask.properties`
- `framework/materials/aws/SSM_PatchBaseline.properties`
- `framework/materials/catalog.properties`
- `framework/materials/catalog.sha256`
- `framework/materials/cloudformation-schema.properties`
- `framework/materials/cloudformation-schema.sha256`
- `framework/materials/cloudformation-schema/ap-northeast-1/aws-config-configrule.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/aws-ec2-vpcblockpublicaccessexclusion.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/aws-ec2-vpcblockpublicaccessoptions.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/aws-fms-policy.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/aws-organizations-policy.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/aws-ssm-association.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/aws-ssm-maintenancewindow.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/aws-ssm-maintenancewindowtarget.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/aws-ssm-maintenancewindowtask.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/aws-ssm-patchbaseline.json`
- `framework/materials/cloudformation-schema/ap-northeast-1/index.json`
- `framework/rules/aws-resource-naming.md`
- `framework/rules/detailed-design.md`
- `framework/rules/resource-layout.json`
- `framework/scripts/cloudformation_schema.checks.py`
- `framework/scripts/design_layout.py`
- `framework/scripts/model_design.checks.py`
- `framework/scripts/model_design.py`
- `framework/scripts/policy_tables.checks.py`
- `framework/scripts/policy_tables.py`
- `tasks/active.md`

## Out of scope

- consumer repository、target別docs/model、IaC、AWS API、deploy/apply、scenario、別taskの作成・実行。
- 今回変更するのはactive task、命名ルール、既存model_design focused checksだけとする。他のAllowed pathsはtask開始前の未commit差分を保持するためだけに許可する。
- 既存resourceや既存designの名称を変更しない。Name tagを必須化しない。既存の命名除外を維持する。
- governance local loopとgit diff --checkを実行する。verification outputは完了報告だけに記載する。
