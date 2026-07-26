# Terraform implementation location

Terraform is available only when an active task and the target environment select Terraform as their single IaC engine.

- reusable modules: `infra/terraform/modules/`
- environment composition: `infra/terraform/environments/<environment>/`
- do not manage one environment with both Terraform and CloudFormation
- update detailed design and `llm/designs/` before Terraform
- require `terraform fmt -check`, `terraform validate`, and `terraform plan`
- apply only when the active task prompt explicitly authorizes it
- do not commit state files or plan binaries; document secure remote state before use

The current web-nginx sample remains CloudFormation-based. This migration intentionally creates no Terraform resource.
