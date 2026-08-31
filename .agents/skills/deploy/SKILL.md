---
name: deploy
description: 検証済みAWS IaCを、既存の04_deploy workflowに従って対象accountへdeployまたはapplyするときに使用する。
---

Repository rootの`framework/prompts/codex/04_deploy.md`を全文読み、その内容だけを正文として実行する。Skill呼び出しに続く入力はworkflowへのhuman inputとして扱う。prompt本文を複製、再解釈、拡張しない。prompt fileが存在しない場合はrepositoryを変更せず停止する。
