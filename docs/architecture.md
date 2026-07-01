# Architecture

The system intentionally avoids a web app. Codex chat is the interface, and the repo is packaged as a Codex plugin.

```text
User answer in chat
  -> Codex calls plugin MCP tool
  -> SQLite records answer
  -> MCP tool returns next question
  -> finish tool generates report
  -> optional disabled-by-default Notion sync plan
```

## Components

```text
.codex-plugin/plugin.json
  Codex plugin manifest

.mcp.json
  Local stdio MCP server declaration

cert_study/
  cli.py          command interface
  db.py           SQLite schema and connection
  engine.py       session selection, answer recording, scoring, review scheduling
  mcp_server.py   stdio MCP server used by Codex plugin loading
  notion_sync.py  Notion write-plan harness, disabled by default
  reporting.py    Markdown report rendering
  seed_sqld.py    SQLD synthetic question seed

skills/cert-study/SKILL.md
  Codex behavior contract for CBT sessions

scripts/sync_notion.py
  disabled-by-default Notion sync-plan helper

tests/
  harness checks for core behavior
```

## Source of Truth

SQLite is the source of truth.

Notion is a projection for reading and review. This avoids slow Notion queries during CBT and keeps scoring deterministic.

The public plugin does not automatically write to Notion. It prepares a sync plan through `prepare_notion_sync`; actual Notion MCP writes require user-selected database targets and `CERT_STUDY_ENABLE_NOTION_SYNC=1`.

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
python3 /Users/isanginn/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```

Expected coverage:

- DB initialization
- SQLD bank size
- domain allocation
- session answer progression
- scoring
- report content
- Notion export file creation
- plugin manifest shape
- Notion sync disabled-by-default behavior

