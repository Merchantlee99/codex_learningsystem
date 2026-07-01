from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from .engine import repeated_wrong_rows, wrong_attempt_rows
from .reporting import write_session_report


ENABLE_ENV = "CERT_STUDY_ENABLE_NOTION_SYNC"


def notion_sync_enabled() -> bool:
    return os.environ.get(ENABLE_ENV, "").lower() in {"1", "true", "yes", "on"}


def prepare_notion_sync_plan(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    session = conn.execute(
        """
        SELECT s.*, e.name AS exam_name
        FROM sessions s
        JOIN exams e ON e.id = s.exam_id
        WHERE s.id = ?
        """,
        (session_id,),
    ).fetchone()
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    if session["finished_at"] is None:
        raise ValueError("finish the session before preparing Notion sync")

    report_path = write_session_report(conn, session_id)
    wrongs = wrong_attempt_rows(conn, session_id)
    repeated = repeated_wrong_rows(conn, session["exam_id"])
    enabled = notion_sync_enabled()

    return {
        "enabled": enabled,
        "status": "ready_for_agent_write" if enabled else "disabled_public_default",
        "env_flag": ENABLE_ENV,
        "session": {
            "id": session_id,
            "exam": session["exam_name"],
            "mode": session["mode"],
            "score": session["score"],
            "correct_count": session["correct_count"],
            "judgement": session["pass_judgement"],
            "report_path": str(report_path),
        },
        "notion_targets": {
            "study_sessions": os.environ.get("CERT_STUDY_NOTION_STUDY_SESSIONS_DB", ""),
            "wrong_questions": os.environ.get("CERT_STUDY_NOTION_WRONG_QUESTIONS_DB", ""),
            "concept_reviews": os.environ.get("CERT_STUDY_NOTION_CONCEPT_REVIEWS_DB", ""),
        },
        "actions": build_actions(session, wrongs, repeated, report_path),
        "public_default_note": (
            "Notion writes are disabled by default for the public plugin. "
            "The user should choose or configure Notion databases before enabling writes."
        ),
    }


def build_actions(
    session: sqlite3.Row,
    wrongs: list[sqlite3.Row],
    repeated: list[sqlite3.Row],
    report_path: Path,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [
        {
            "type": "create_or_update_study_session_page",
            "database": "Study Sessions",
            "title": f"{session['finished_at'][:10]} {session['exam_name']} {session['mode']}",
            "properties": {
                "Exam": session["exam_name"],
                "Mode": session["mode"],
                "Score": session["score"],
                "Correct": session["correct_count"],
                "Judgement": session["pass_judgement"],
                "Local Session ID": session["id"],
                "Report Path": str(report_path),
            },
            "body_source": str(report_path),
        }
    ]
    for row in wrongs:
        actions.append(
            {
                "type": "create_wrong_question_row",
                "database": "Wrong Questions",
                "title": f"{session['exam_name']} Q{row['position']} {row['concept']}",
                "properties": {
                    "Exam": session["exam_name"],
                    "Domain": row["domain"],
                    "Concept": row["concept"],
                    "Question ID": row["question_id"],
                    "Position": row["position"],
                    "My Answer": str(row["user_answer"]),
                    "Correct Answer": str(row["correct_answer"]),
                    "Mistake Type": "개념 혼동",
                    "Local Session ID": session["id"],
                },
            }
        )
    for row in repeated:
        actions.append(
            {
                "type": "upsert_concept_review_row",
                "database": "Concept Reviews",
                "title": row["concept"],
                "properties": {
                    "Exam": session["exam_name"],
                    "Wrong Count": row["wrong_count"],
                    "Status": "복습 예정",
                },
            }
        )
    return actions


def render_plan(plan: dict[str, Any]) -> str:
    return json.dumps(plan, ensure_ascii=False, indent=2)

