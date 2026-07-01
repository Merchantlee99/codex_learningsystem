# Codex Learning System Instructions

This repo is a Codex-native CBT study plugin. Keep the implementation focused on the study loop:

```text
start session -> show one question -> record answer -> finish -> score/report -> schedule review
```

## Operating Rules

- Keep `.codex-plugin/plugin.json` and `.mcp.json` valid whenever plugin-facing behavior changes.
- Use `python3 -m cert_study ...` for all local study operations.
- Prefer plugin MCP tools for Codex-facing workflows and CLI commands for manual smoke tests.
- Treat `data/study.sqlite` as local mutable state and do not commit it.
- Treat `reports/sessions/*.md` and `notion_exports/*.md` as user learning records and do not commit them.
- Do not add paid workbook content, copied 기출, or real exam dumps.
- When generating questions, mark them as synthetic and ground them in exam concepts.
- When syncing to Notion, use SQLite/session reports as the source of truth. Public default must stay disabled and plan-only unless the user explicitly configures Notion targets.
- Keep app UI out of scope unless the user explicitly asks for it.

## Verification

Before claiming a code change works, run:

```bash
python3 -m unittest discover -s tests
python3 /Users/isanginn/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```

For CLI behavior, also run a small session smoke test:

```bash
python3 -m cert_study init --reset
python3 -m cert_study session start --exam SQLD --count 5 --seed 1
```
