# Architecture

The system intentionally avoids a web app. Codex chat is the interface.

```text
User answer in chat
  -> Codex runs CLI
  -> SQLite records answer
  -> CLI returns next question
  -> finish command generates report
  -> optional Notion MCP sync writes readable notes
```

## Components

```text
cert_study/
  cli.py          command interface
  db.py           SQLite schema and connection
  engine.py       session selection, answer recording, scoring, review scheduling
  reporting.py    Markdown report rendering
  seed_sqld.py    SQLD synthetic question seed

skills/cert-study/SKILL.md
  Codex behavior contract for CBT sessions

scripts/sync_notion.py
  Notion-ready Markdown export helper

tests/
  harness checks for core behavior
```

## Source of Truth

SQLite is the source of truth.

Notion is a projection for reading and review. This avoids slow Notion queries during CBT and keeps scoring deterministic.

## Extension Path

Add a new exam by adding:

1. exam metadata
2. domain metadata
3. concept metadata
4. synthetic or user-owned question bank
5. scoring rules if different
6. harness test for official question count and pass-line reporting

## Harness Contract

Minimum checks before publishing changes:

```bash
python3 -m unittest discover -s tests
```

Expected coverage:

- DB initialization
- SQLD bank size
- domain allocation
- session answer progression
- scoring
- report content
- Notion export file creation

