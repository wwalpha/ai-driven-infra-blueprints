---
name: scenario-test
description: AWS application behaviorを、既存の06_scenario-test workflowに従って独立したscenario-test taskとして検証するときに使用する。
---

Repository rootの`framework/prompts/codex/06_scenario-test.md`を全文読み、その内容だけを正文として実行する。Skill呼び出しに続く入力はworkflowへのhuman inputとして扱う。prompt本文を複製、再解釈、拡張しない。prompt fileが存在しない場合はrepositoryを変更せず停止する。
