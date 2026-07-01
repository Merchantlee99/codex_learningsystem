#!/usr/bin/env python3
"""Prepare a disabled-by-default Notion sync plan for a finished session.

The Codex runtime should perform the actual Notion MCP write because MCP tools
are available to the agent, not to this local Python process.
"""

from __future__ import annotations

import argparse

from cert_study.db import connect
from cert_study.notion_sync import prepare_notion_sync_plan, render_plan


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_id")
    args = parser.parse_args()
    with connect() as conn:
        plan = prepare_notion_sync_plan(conn, args.session_id)
    print(render_plan(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
