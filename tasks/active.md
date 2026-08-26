# Codex Task: Expand the generic AWS catalog

## Task contract

- Task type: `catalog-maintenance`
- Goal: 汎用blueprintの設計catalogとprovider schemaへRDS、ELBv2、CloudFront、WAFv2、ECR/ECS、Auto Scaling、DynamoDB/SQS、API Gatewayを追加する
- AWS mutation: forbidden
- AWS API execution: forbidden
- CloudFormation/Terraform execution: forbidden
- Deploy/apply: forbidden

## Required changes

- [R1] RDSのDBInstance、DBCluster、DBSubnetGroup、parameter/option group、DBProxy関連を追加する。
- [R2] ALB/NLB共通のElasticLoadBalancingV2 resourceを追加する。
- [R3] CloudFrontとWAFv2の指定resourceを追加する。
- [R4] ECR/ECS、Auto Scaling、EC2 LaunchTemplateを追加する。
- [R5] DynamoDB、SQS、API Gateway REST/HTTP APIの主要resourceを追加する。
- [R6] properties catalog lockと対応する東京region provider schema snapshotを更新する。

## Acceptance checks

- [R1] `changed:materials/aws/RDS_*.properties`
- [R2] `changed:materials/aws/ElasticLoadBalancingV2_*.properties`
- [R3] `changed:materials/aws/CloudFront_*.properties`
- [R3] `changed:materials/aws/WAFv2_*.properties`
- [R4] `changed:materials/aws/ECR_*.properties`
- [R4] `changed:materials/aws/ECS_*.properties`
- [R4] `changed:materials/aws/AutoScaling_*.properties`
- [R4] `changed:materials/aws/EC2_LaunchTemplate.properties`
- [R5] `changed:materials/aws/DynamoDB_*.properties`
- [R5] `changed:materials/aws/SQS_*.properties`
- [R5] `changed:materials/aws/ApiGateway_*.properties`
- [R5] `changed:materials/aws/ApiGatewayV2_*.properties`
- [R6] `changed:materials/catalog.sha256`
- [R6] `changed:scripts/cloudformation_schema.py`
- [R6] `check:framework.cloudformation-schema-catalog`

## Allowed paths

- `README.md`
- `materials/aws/**`
- `materials/catalog.properties`
- `materials/catalog.sha256`
- `materials/cloudformation-schema/**`
- `materials/cloudformation-schema.properties`
- `materials/cloudformation-schema.sha256`
- `scripts/cloudformation_schema.py`
- `scripts/cloudformation_schema.checks.py`
- `tasks/active.md`

## Out of scope

- project固有design、actual、IaC、scenario、scenario resultのmigration
- AWS API、deploy、apply
- 東京region以外のschema snapshot
- 指定されていないAWS serviceの追加
