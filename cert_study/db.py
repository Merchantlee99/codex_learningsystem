from __future__ import annotations

import sqlite3
from pathlib import Path

from .paths import db_path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS exams (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  official_question_count INTEGER NOT NULL,
  official_duration_minutes INTEGER NOT NULL,
  pass_score REAL NOT NULL,
  domain_min_score REAL NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS domains (
  id TEXT PRIMARY KEY,
  exam_id TEXT NOT NULL REFERENCES exams(id),
  name TEXT NOT NULL,
  official_weight REAL NOT NULL,
  official_question_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS concepts (
  id TEXT PRIMARY KEY,
  exam_id TEXT NOT NULL REFERENCES exams(id),
  domain_id TEXT NOT NULL REFERENCES domains(id),
  name TEXT NOT NULL,
  review_note TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
  id TEXT PRIMARY KEY,
  exam_id TEXT NOT NULL REFERENCES exams(id),
  domain_id TEXT NOT NULL REFERENCES domains(id),
  concept_id TEXT NOT NULL REFERENCES concepts(id),
  question_type TEXT NOT NULL DEFAULT 'single_choice',
  question_text TEXT NOT NULL,
  choices_json TEXT NOT NULL,
  answer_json TEXT NOT NULL DEFAULT '{"choices":[1]}',
  answer INTEGER NOT NULL CHECK(answer BETWEEN 1 AND 4),
  explanation TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  source_license TEXT NOT NULL DEFAULT 'unknown',
  source_tier TEXT NOT NULL DEFAULT 'unknown',
  storage_policy TEXT NOT NULL DEFAULT 'raw_allowed',
  validity_status TEXT NOT NULL DEFAULT 'current',
  quality_status TEXT NOT NULL DEFAULT 'active',
  scope_version TEXT NOT NULL DEFAULT '',
  official_checked_at TEXT NOT NULL DEFAULT '',
  quality_notes TEXT NOT NULL DEFAULT '',
  correct_rationale TEXT NOT NULL DEFAULT '',
  distractor_rationales_json TEXT NOT NULL DEFAULT '{}',
  review_concepts_json TEXT NOT NULL DEFAULT '[]',
  official_scope_refs_json TEXT NOT NULL DEFAULT '[]',
  gold_status TEXT NOT NULL DEFAULT 'none',
  gold_checked_at TEXT NOT NULL DEFAULT '',
  gold_notes TEXT NOT NULL DEFAULT '',
  provenance_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  exam_id TEXT NOT NULL REFERENCES exams(id),
  mode TEXT NOT NULL,
  requested_count INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  score REAL,
  correct_count INTEGER,
  pass_judgement TEXT
);

CREATE TABLE IF NOT EXISTS session_questions (
  session_id TEXT NOT NULL REFERENCES sessions(id),
  question_id TEXT NOT NULL REFERENCES questions(id),
  position INTEGER NOT NULL,
  PRIMARY KEY(session_id, question_id),
  UNIQUE(session_id, position)
);

CREATE TABLE IF NOT EXISTS attempts (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  question_id TEXT NOT NULL REFERENCES questions(id),
  user_answer INTEGER NOT NULL CHECK(user_answer BETWEEN 1 AND 4),
  correct_answer INTEGER NOT NULL CHECK(correct_answer BETWEEN 1 AND 4),
  user_answer_json TEXT NOT NULL DEFAULT '{}',
  correct_answer_json TEXT NOT NULL DEFAULT '{}',
  is_correct INTEGER NOT NULL CHECK(is_correct IN (0, 1)),
  mistake_reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(session_id, question_id)
);

CREATE TABLE IF NOT EXISTS review_queue (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL REFERENCES questions(id),
  concept_id TEXT NOT NULL REFERENCES concepts(id),
  next_review_at TEXT NOT NULL,
  review_stage INTEGER NOT NULL DEFAULT 1,
  last_result TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(question_id)
);
"""

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS questions_backfill_answer_json_after_insert
AFTER INSERT ON questions
WHEN NEW.question_type = 'single_choice'
  AND (NEW.answer_json = '{"choices":[1]}' OR NEW.answer_json = '')
BEGIN
  UPDATE questions
  SET answer_json = '{"choices":[' || NEW.answer || ']}'
  WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS questions_backfill_answer_json_after_update
AFTER UPDATE OF answer ON questions
WHEN NEW.question_type = 'single_choice'
BEGIN
  UPDATE questions
  SET answer_json = '{"choices":[' || NEW.answer || ']}'
  WHERE id = NEW.id;
END;
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    ensure_schema_extensions(conn)
    conn.executescript(TRIGGERS)
    backfill_v2_columns(conn)
    conn.commit()


def ensure_schema_extensions(conn: sqlite3.Connection) -> None:
    ensure_columns(
        conn,
        "questions",
        {
            "question_type": "TEXT NOT NULL DEFAULT 'single_choice'",
            "answer_json": "TEXT NOT NULL DEFAULT '{\"choices\":[1]}'",
            "source_license": "TEXT NOT NULL DEFAULT 'unknown'",
            "source_tier": "TEXT NOT NULL DEFAULT 'unknown'",
            "storage_policy": "TEXT NOT NULL DEFAULT 'raw_allowed'",
            "validity_status": "TEXT NOT NULL DEFAULT 'current'",
            "quality_status": "TEXT NOT NULL DEFAULT 'active'",
            "scope_version": "TEXT NOT NULL DEFAULT ''",
            "official_checked_at": "TEXT NOT NULL DEFAULT ''",
            "quality_notes": "TEXT NOT NULL DEFAULT ''",
            "correct_rationale": "TEXT NOT NULL DEFAULT ''",
            "distractor_rationales_json": "TEXT NOT NULL DEFAULT '{}'",
            "review_concepts_json": "TEXT NOT NULL DEFAULT '[]'",
            "official_scope_refs_json": "TEXT NOT NULL DEFAULT '[]'",
            "gold_status": "TEXT NOT NULL DEFAULT 'none'",
            "gold_checked_at": "TEXT NOT NULL DEFAULT ''",
            "gold_notes": "TEXT NOT NULL DEFAULT ''",
            "provenance_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )
    ensure_columns(
        conn,
        "attempts",
        {
            "user_answer_json": "TEXT NOT NULL DEFAULT '{}'",
            "correct_answer_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    )


def ensure_columns(conn: sqlite3.Connection, table: str, definitions: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in definitions.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def backfill_v2_columns(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE questions
        SET answer_json = '{"choices":[' || answer || ']}'
        WHERE question_type = 'single_choice'
          AND (answer_json IS NULL OR answer_json = '' OR answer_json = '{"choices":[1]}')
        """
    )
    conn.execute(
        """
        UPDATE attempts
        SET user_answer_json = '{"choices":[' || user_answer || ']}'
        WHERE user_answer_json IS NULL OR user_answer_json = '' OR user_answer_json = '{}'
        """
    )
    conn.execute(
        """
        UPDATE attempts
        SET correct_answer_json = '{"choices":[' || correct_answer || ']}'
        WHERE correct_answer_json IS NULL OR correct_answer_json = '' OR correct_answer_json = '{}'
        """
    )
    conn.execute(
        """
        UPDATE questions
        SET source_tier = CASE
          WHEN source_type IN ('synthetic', 'synthetic_recent_scope') THEN 'synthetic'
          WHEN source_type IN ('official_sample_link', 'official_public_sample') THEN 'official_sample'
          WHEN source_type IN ('public_license', 'open_license') THEN 'open_license'
          WHEN source_type IN ('licensed_private') THEN 'licensed_private'
          WHEN source_type IN ('user_owned_summary', 'user_owned_raw', 'personal_wrong_note', 'restored_summary') THEN 'user_owned'
          ELSE source_tier
        END
        WHERE source_tier IS NULL OR source_tier = '' OR source_tier = 'unknown'
        """
    )
    conn.execute(
        """
        UPDATE questions
        SET quality_status = CASE
          WHEN validity_status IN ('needs_official_check', 'unknown') THEN 'needs_review'
          WHEN validity_status IN ('outdated') THEN 'outdated'
          ELSE 'active'
        END
        WHERE quality_status IS NULL
           OR quality_status = ''
           OR (quality_status = 'active' AND validity_status IN ('needs_official_check', 'unknown', 'outdated'))
        """
    )
