# task-20260807-generic-blueprint Result

## Outcome

- removed the web-nginx design, LLM data, actuals, CloudFormation implementation, scenario scripts, historical tasks, and old migration evidence from the active blueprint tree
- added `blueprint.properties` as the single project/environment/account/region/IaC source of truth
- replaced the migration-specific validator with dynamic design/LLM discovery and task-allowed path checks
- added catalog provenance, counts, SHA-256 lock, and a standard-library lock maintenance command
- rewrote initial setup guidance for an unconfigured generic blueprint
- preserved all 81 `materials/aws/*.properties` files byte-for-byte

## Verification

- Python source compilation: PASS
- shell syntax: PASS
- catalog lock: PASS, 81 files and 1,146 properties
- generic local loop: PASS, 2,549 checks
- `git diff --check`: PASS
- `materials/aws` diff: empty
- AWS and Terraform mutations: not run and not authorized
