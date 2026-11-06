# Python function design

Use these guidelines when newly implementing Python code, substantially changing an existing Python function, or refactoring Python code. They guide design decisions; they do not replace existing safety, validation, or Python structure rules.

## Responsibility and length

- A function should generally have one clear responsibility. Consider separating independent responsibilities such as input acquisition, data transformation, validation, control flow, persistence, and result construction.
- An orchestration function may call multiple operations in order. Do not embed detailed business processing in it without a valid reason.
- For new or substantially changed functions, use approximately 150 lines as a guideline for considering whether responsibilities should be separated. Never split a function solely to reduce its line count.
- Simple data definitions and operations that become harder to understand when split may be exceptions. Existing long functions need not be changed in bulk.

## Conditions and extraction

- Organize complex conditions into meaningful decisions, use early returns to reduce unnecessary nesting, and consider sharing repeated condition checks. Do not split conditions into so many small functions that the flow becomes difficult to follow.
- Consider extracting a function especially when a block has an independent responsibility, is reused, gains meaning from a name, benefits from independent unit testing, or limits the impact of changes. Weigh these benefits against increased dependencies, arguments, and call hierarchy complexity.
- Do not add meaningless abstractions or helpers whose only purpose is reducing function length.

## Reuse

- Check existing functions before creating a helper, and do not duplicate shared processing. Do not add abstractions for speculative future extension.
- Do not mechanically extract code with one caller and no independent responsibility, or create a class merely to extract functions.

## Preserve behavior

When refactoring, generally preserve the public API, inputs and outputs, processing order, exception types and handling, diagnostics, side effects, and existing safety and validation conditions. Consider existing consumers that depend on function location or name, including AST inspection, name references, and code generation. Handle necessary behavior changes separately from refactoring.

## Test and Validation Design Policy

Tests and validation must exercise executable behavior or data contracts; explain the behavior or contract each new test verifies. Review natural-language documentation in code review, not with static phrase matching. Do not add document-only validators.

Do not create tests or validators that fix the wording of Skills, Prompts, Rules, Runbooks, README, AGENTS.md or other natural-language documents; their headings, sections, anchors, command examples or ordering; LLM instructions; read routing or required phrases. Do not use document mutation tests to prove instructions correct, restore removed checks under another name or location, or test this policy through Markdown string matching.

Permitted checks include Python results, return values, exceptions and state transitions; actual SDK/CLI behavior; Model, Schema, IaC and configuration data contracts; runtime security, Human consent and AWS mutation controls; required file existence; parsing, generation and validation of structured Markdown data actually consumed by the software; and resolution of entrypoints and references needed at runtime.
