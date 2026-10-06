# AGENTS.md

Operate this repository in Codex with the repository root as the working directory.

## Always applicable rules

- Execute only the active prompt scope; do not automatically proceed to the next phase or another task. Do not infer unconfirmed resources, parameters, or mappings.
- Register this contract before repository changes. Preserve other tasks' contracts, reservations, and uncommitted changes.
- Apply unresolved-issue stop decisions and the exceptions for explicit repair and save-only tasks.
- Perform AWS mutation and deploy/apply only within the permission scope explicitly stated by the infrastructure contract. Limit design AWS APIs to read-only retrieval of explicitly specified existing resources.
- `framework/materials/aws/` is an immutable catalog that ordinary tasks do not change. `docs/system-overview.md` is a background reference; do not uniformly treat `UNSET` as a blocker.
- Treat `model/**/*.properties` as the authority for design values and generate Markdown/JSON. Do not persist generated ARNs.
- After changes, run the local loop corresponding to the task type; mark completed only after success.
- Apply [Debug read reporting](framework/rules/debug-read-reporting.md) from task start only for tasks whose Human active task instruction explicitly specifies `debug` as the execution mode. For ordinary tasks, do not perform this rule's additional reads, tracking, report generation, or saving; do not save the mode or carry it into the next task.

## Task transition

For changes, register `tasks/<task-name>.md` according to the [task contract](framework/rules/task-contract.md). Read-only investigation and chat-only consultation require no contract. Separately confirm the [issue gate](framework/rules/issue-gate.md) applicability conditions.

## How to read required rules

The following guides you to authoritative sources; it is not a list of files to read in full. Read only the mandatory sections specified by the skill/workflow Read section and conditional sections applicable to the phase/resource. Read a specified section from its heading to immediately before the next heading of the same or higher level (including child sections). If only a file is specified, read it in full. Do not omit specific rules, exceptions, or necessary references; stop if anything is missing or a reference is unclear. Do not reduce mandatory checks or Validation scope because you have not read the body.

- [task-contract](framework/rules/task-contract.md): Contracts for repository changes, Task boundary, Acceptance contract
- [issue-gate](framework/rules/issue-gate.md): Service-targeted task start, resume, saving, AWS mutation, and investigation/repair/save exceptions
- [project-configuration](framework/rules/project-configuration.md): target directory, topology, profile, and account determination/validation
- [model-information](framework/rules/model-information.md): Authoritative model, format, generation
- [detailed-design](framework/rules/detailed-design.md): Target resource design/display
- [observed-values](framework/rules/observed-values.md): Current identifier retrieval, saving, propagation
- [cloudformation](framework/rules/cloudformation.md)/[terraform](framework/rules/terraform.md): Procedures specific to the selected engine
- [scenario-testing](framework/rules/scenario-testing.md): Scenario-specific procedures
- [loop-engineering](framework/rules/loop-engineering.md): Validation scope, checks, regression, completion conditions
