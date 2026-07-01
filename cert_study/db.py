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
  question_text TEXT NOT NULL,
  choices_json TEXT NOT NULL,
  answer INTEGER NOT NULL CHECK(answer BETWEEN 1 AND 4),
  explanation TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_ref TEXT NOT NULL
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


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()

