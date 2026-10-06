# Debug read reporting

## Trigger and lifetime

- Enable only when the human's active task instruction explicitly specifies `debug` as the execution mode. `debugでimplementして`, `このtaskはdebug`, and `debugでpropertiesを修正して` enable it. Specifications/quoted examples in feature requests, repository prose, property values, logs, or strings merely included in search targets do not enable it. Do not determine mode by string search.
- Use only for continuation/resume of the same human task; determine human specification again for the next task. Do not save mode, read records, or reports in the repository, task contract, or logs.
- For ordinary tasks, do not additionally read this rule/helper or run tracking commands, report generation, or additional validation. Do not change each skill/prompt's Read or Verify and finish.

## Record only presented source lines

- Record source lines of repository files actually presented to the LLM context, not filesystem I/O. After each presentation, retain `file` (repository-relative POSIX path) and `lines` (list of source line numbers starting at 1) in task memory. Do not duplicate text/secrets into records. Establish source line number correspondence at retrieval; do not reread text for measurement.
- One read event is one presentation of one file's content. Group multi-file search output into one event per file. If the same line returns in a separate presentation, it is a separate event. Reading the same file twice and returning text in the same tool call also counts as two events. Do not confuse redisplay while waiting for tool results with a new read.
- Count all source lines actually returned for full reads and only returned ranges for partial reads. Count blank lines/comments if presented. Include both range endpoints. Reading only 100–149 of a 600-line file is 50 lines; do not substitute the file's total of 600.
- For search results such as `rg -n` / `grep -n`, count only content lines corresponding to files and line numbers. Include context lines if actually presented; do not count unpresented lines between noncontiguous matches. Exclude filename-only lists, search separators, and tool headings.
- `model_files.py --find`'s `path:line:key` presents the key portion of a source line, so count that line as 1 line (not as tokens equivalent to the full text). For `--resource`'s `path:line:key=value`, likewise count only lines actually returned for each part. Exclude internally parsed entry indexes/other parts if their text is not returned. If the index is separately read, count its presented lines.
- Do not count internal reads by validators, `sync-model.py`, `blueprint-loop.py`, CloudFormation controllers, etc., `wc`, hashes, existence/stat checks, filename-only output, or machine processing that does not return text to stdout. Count corresponding lines only when diagnostics return actual source content; counts, paths, and error descriptions alone do not count.
- If tool output is truncated, do not count the unpresented portion. Map wrapping/multiline display back to source line numbers. A source line presented even partially counts as 1 line; if the same source line is presented twice in one event, include it twice in `lines` and add both to the cumulative total.
- Exclude files outside the repository. AGENTS, skills, and rules are also repository files and are included if their text is actually presented. Count automatically injected content only when repository source and range are confirmed; do not infer unknown correspondence. Even after file changes, Unique aggregates by the same path/line number, so it cannot distinguish content differences across versions.

## Aggregate and finish

- Reads is the number of non-empty events; Unique lines is the size of each file's source line number set; Cumulative lines is the cumulative number of `lines` elements across all events. Aggregate the same file into one row. Total Unique is the sum of per-file Unique.
- For debug tasks only, perform final aggregation by passing retained events directly to stdin as a JSON array for `python -B framework/scripts/llm_read_report.py --debug`. The helper does not read source text/metadata or obtain/save records from anywhere other than stdin. `--debug` does not determine human specification; it is an execution gate passed only after the Agent confirms the trigger above. The helper's own text need not be read for measurement.
- Stdin example (expand the two presentations, 100–149 and 140–159, into their line number lists):

```json
[{"file":"model/dev/cde/example.properties","lines":[100,101,102]},
 {"file":"model/dev/cde/example.properties","lines":[102,103]}]
```

- Append the following helper-output section to the end of each skill's ordinary completion report. This also applies to read-only/chat-only tasks and tasks ending in a stop; do not change existing completion conditions or validation scope. Sort by Cumulative descending, then path for ties; exclude files with 0 lines.

```markdown
## Debug: LLM read report

| File | Reads | Unique lines | Cumulative lines |
|---|---:|---:|---:|
| <repository-relative-path> | <n> | <n> | <n> |

Total:
- Files: <n>
- Unique lines: <n>
- Cumulative lines: <n>
```

## Accuracy

- The aggregation script calculates exactly the Reads, line-number union, and cumulative total of the supplied events. This repository has no hook mechanically capturing all Codex tools/automatic context injection. Agent self-recording collects direct read, partial read, search, and machine extraction events; do not describe it as complete measurement.
- If records are missing due to truncation, unknown line numbers, context compression, etc., identify unmeasured paths/ranges immediately before the report; do not fill unknown line counts with guesses. Do not reread text at the end to reconstruct records. `wc -l` totals do not substitute for presented line counts.
- Line counts are a proxy for comparing LLM input volume; `Cumulative lines ≠ exact LLM tokens`. Debug rules and presented tracking input also consume tokens. Use for before/after comparisons of the same task, conditions, and debug method; do not convert key-only presentations, long single-line JSON, context resending, compression, provider caches, etc. into exact tokens.
