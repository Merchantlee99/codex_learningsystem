#!/usr/bin/env python3
"""Prepare a Notion-ready wrong-note export for a finished session.

The Codex runtime should perform the actual Notion MCP write because MCP tools
are available to the agent, not to this local Python process.
"""

from __future__ import annotations

import argparse

from cert_study.db import connect
from cert_study.reporting import write_session_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_id")
    args = parser.parse_args()
    with connect() as conn:
        path = write_session_report(conn, args.session_id)
    print(path)
    print("Use this Markdown as the body of the Notion Study Sessions page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

