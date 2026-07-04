from __future__ import annotations

import sqlite3

from .seed_sqld import seed as seed_sqld


def seed_public_banks(conn: sqlite3.Connection) -> None:
    """Seed the public SQLD demo bank that can live in the portfolio repo."""
    seed_sqld(conn)
