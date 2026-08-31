---
name: implement
description: 承認済みAWS詳細設計を、既存の03_implement workflowに従ってIaCへ実装しlocal static validationするときに使用する。
---

Repository rootの`framework/prompts/codex/03_implement.md`を全文読み、その内容だけを正文として実行する。Skill呼び出しに続く入力はworkflowへのhuman inputとして扱う。prompt本文を複製、再解釈、拡張しない。prompt fileが存在しない場合はrepositoryを変更せず停止する。
