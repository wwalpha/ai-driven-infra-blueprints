---
name: add-target
description: 初期化済みのAWS Blueprint repositoryへ、既存の02_add-target workflowに従ってtargetを1件追加するときに使用する。
---

Repository rootの`framework/prompts/codex/02_add-target.md`を全文読み、その内容だけを正文として実行する。Skill呼び出しに続く入力はworkflowへのhuman inputとして扱う。prompt本文を複製、再解釈、拡張しない。prompt fileが存在しない場合はrepositoryを変更せず停止する。
