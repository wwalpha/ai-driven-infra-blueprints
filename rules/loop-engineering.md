# Loop Engineering Rules

loop engineering は mandatory とする。「各 change」は editor save ごとではなく、coherent logical change set ごとを意味する。

## Local loop

各 coherent logical change 後に次を決定的に確認する。

- active task prompt exists
- changed paths are within prompt scope
- `materials/aws/` unchanged from task baseline
- required directory/file structure exists
- legacy GitHub workflow directory absent
- obsolete design LLM helper directory absent
- resource design table schema valid
- row numbering valid
- resource grouping valid
- relative links and explicit anchors valid
- design/LLM grouping and references consistent
- generated ARN absent from `llm/actuals/`
- formatting/static checks pass

## Full task loop

task completion では次を実行する。

1. local loop
2. selected IaC validation/plan（task に relevant な場合のみ）
3. active task prompt が明示許可した場合だけ deploy/apply
4. deployment が発生した場合だけ actuals collection
5. detailed design と LLM actuals update
6. local loop rerun
7. infrastructure behavior が変わった場合は scenario test
8. `tests/results/<task-id>/` へ evidence 保存
9. success まで bounded retry

## Retry and stop

- 同じ logical failure class の automatic correction は最大3 iteration。
- material progress なしで同じ error が2回続いた場合は停止する。
- missing human input を値の発明で直さない。
- out-of-scope file change で停止する。
- unauthorized delete/replacement で停止する。
- `materials/aws/` が baseline と異なる場合は停止する。
- pass のために failing check を抑制しない。

validate/plan 後に human review を要求しない repository rule と、Codex sandbox / OS permission control は別の仕組みである。permission が必要な操作は repository rule にかかわらず platform control に従う。
