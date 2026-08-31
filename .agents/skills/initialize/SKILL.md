---
name: initialize
description: 未初期化のAWS Blueprint repositoryを、既存の01_initialize workflowに従って初期化するときに使用する。
---

Repository rootの`framework/prompts/codex/01_initialize.md`を全文読み、その内容だけを正文として実行する。Skill呼び出しに続く入力はworkflowへのhuman inputとして扱う。prompt本文を複製、再解釈、拡張しない。prompt fileが存在しない場合はrepositoryを変更せず停止する。
