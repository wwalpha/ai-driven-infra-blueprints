# task-20260807-copilot-instruction-separation Result

## Outcome

- added environment-only personal custom instructions that bind a user-supplied SharePoint folder, read `README.md`, and then follow the user's request without assuming repository content
- made `README.md` the repository-wide instruction without Microsoft Copilot-specific settings or behavior
- added the per-use initial service-design Ask prompt
- added the user-maintained `docs/system-overview.md` template
- added no questionnaire, conversation-log, or session-state files

## Verification

- Python source compilation: PASS
- shell syntax: PASS
- catalog lock: PASS, 81 files and 1,146 properties
- generic local loop: PASS, 2,492 checks
- `git diff --check`: PASS
- `materials/aws` diff: empty
- AWS and Terraform mutations: not run and not authorized
