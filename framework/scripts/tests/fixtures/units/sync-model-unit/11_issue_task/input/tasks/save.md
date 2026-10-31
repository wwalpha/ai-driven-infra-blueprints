# fixture task

## Task contract

- Task type: `migration`
- Task status: `running`

## Validation scope

- `dev/123456789012/s3`

## Allowed paths

- `tasks/save.md`
- `issues/dev/123456789012/issues.md`
- `issues/dev/123456789012/iac-issues.md`

## Modified files

- `tasks/save.md`
- `issues/dev/123456789012/issues.md`
- `issues/dev/123456789012/iac-issues.md`

## Required changes
- [R1] Save reports

## Acceptance checks
- [R1] `exists:issues/dev/123456789012/issues.md`
- [R1] `exists:issues/dev/123456789012/iac-issues.md`
