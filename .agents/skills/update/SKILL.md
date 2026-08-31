---
name: update
description: Humanが変更した既存AWS詳細設計を、既存の05_update workflowに従ってmodel、IaC、AWSへ反映するときに使用する。
---

Repository rootの`framework/prompts/codex/05_update.md`を全文読み、その内容だけを正文として実行する。Skill呼び出しに続く入力はworkflowへのhuman inputとして扱う。prompt本文を複製、再解釈、拡張しない。prompt fileが存在しない場合はrepositoryを変更せず停止する。
