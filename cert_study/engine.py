from __future__ import annotations

import json
import random
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable


@dataclass(frozen=True)
class QuestionView:
    session_id: str
    position: int
    total: int
    question_id: str
    domain: str
    concept: str
    question_text: str
    choices: list[str]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_iso() -> str:
    return date.today().isoformat()


def session_id_for(exam_id: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{exam_id.lower()}-{stamp}-{uuid.uuid4().hex[:6]}"


def create_session(
    conn: sqlite3.Connection,
    *,
    exam_id: str,
    count: int | None,
    mode: str,
    seed: int | None = None,
) -> QuestionView:
    exam = get_exam(conn, exam_id)
    requested_count = int(count or exam["official_question_count"])
    if requested_count <= 0:
        raise ValueError("count must be greater than 0")

    questions = select_questions(conn, exam_id=exam_id, count=requested_count, seed=seed)
    session_id = session_id_for(exam_id)
    conn.execute(
        """
        INSERT INTO sessions (id, exam_id, mode, requested_count, started_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, exam_id, mode, requested_count, now_iso()),
    )
    conn.executemany(
        "INSERT INTO session_questions (session_id, question_id, position) VALUES (?, ?, ?)",
        [(session_id, row["id"], idx) for idx, row in enumerate(questions, start=1)],
    )
    conn.commit()
    first = get_question_view(conn, session_id, 1)
    if first is None:
        raise RuntimeError("session created without questions")
    return first


def get_exam(conn: sqlite3.Connection, exam_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown exam: {exam_id}")
    return row


def select_questions(
    conn: sqlite3.Connection,
    *,
    exam_id: str,
    count: int,
    seed: int | None = None,
) -> list[sqlite3.Row]:
    domains = conn.execute(
        "SELECT * FROM domains WHERE exam_id = ? ORDER BY official_weight ASC, id ASC",
        (exam_id,),
    ).fetchall()
    if not domains:
        raise ValueError(f"exam has no domains: {exam_id}")
    counts = allocate_domain_counts(domains, count)
    rng = random.Random(seed if seed is not None else datetime.now().timestamp())
    selected: list[sqlite3.Row] = []
    for domain in domains:
        rows = conn.execute(
            "SELECT * FROM questions WHERE exam_id = ? AND domain_id = ? ORDER BY id",
            (exam_id, domain["id"]),
        ).fetchall()
        need = counts[domain["id"]]
        if len(rows) < need:
            raise ValueError(f"not enough questions for {domain['name']}: need {need}, have {len(rows)}")
        shuffled = list(rows)
        rng.shuffle(shuffled)
        selected.extend(shuffled[:need])
    rng.shuffle(selected)
    return selected


def allocate_domain_counts(domains: Iterable[sqlite3.Row], count: int) -> dict[str, int]:
    domain_rows = list(domains)
    raw = [(row, count * float(row["official_weight"]) / 100.0) for row in domain_rows]
    counts = {row["id"]: int(value) for row, value in raw}
    remainder = count - sum(counts.values())
    ranked = sorted(raw, key=lambda item: (item[1] - int(item[1]), item[0]["official_weight"]), reverse=True)
    for idx in range(remainder):
        counts[ranked[idx % len(ranked)][0]["id"]] += 1
    return counts


def get_question_view(conn: sqlite3.Connection, session_id: str, position: int) -> QuestionView | None:
    row = conn.execute(
        """
        SELECT
          sq.session_id,
          sq.position,
          q.id AS question_id,
          q.question_text,
          q.choices_json,
          d.name AS domain,
          c.name AS concept,
          (SELECT COUNT(*) FROM session_questions WHERE session_id = sq.session_id) AS total
        FROM session_questions sq
        JOIN questions q ON q.id = sq.question_id
        JOIN domains d ON d.id = q.domain_id
        JOIN concepts c ON c.id = q.concept_id
        WHERE sq.session_id = ? AND sq.position = ?
        """,
        (session_id, position),
    ).fetchone()
    if row is None:
        return None
    return QuestionView(
        session_id=row["session_id"],
        position=row["position"],
        total=row["total"],
        question_id=row["question_id"],
        domain=row["domain"],
        concept=row["concept"],
        question_text=row["question_text"],
        choices=json.loads(row["choices_json"]),
    )


def get_next_unanswered(conn: sqlite3.Connection, session_id: str) -> QuestionView | None:
    row = conn.execute(
        """
        SELECT sq.position
        FROM session_questions sq
        LEFT JOIN attempts a ON a.session_id = sq.session_id AND a.question_id = sq.question_id
        WHERE sq.session_id = ? AND a.id IS NULL
        ORDER BY sq.position
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return get_question_view(conn, session_id, row["position"])


def submit_answer(conn: sqlite3.Connection, session_id: str, answer: int) -> tuple[bool, QuestionView | None]:
    if answer < 1 or answer > 4:
        raise ValueError("answer must be between 1 and 4")
    current = get_next_unanswered(conn, session_id)
    if current is None:
        raise ValueError("session has no unanswered questions")
    question = conn.execute("SELECT * FROM questions WHERE id = ?", (current.question_id,)).fetchone()
    if question is None:
        raise RuntimeError(f"missing question: {current.question_id}")
    is_correct = int(answer == question["answer"])
    attempt_id = f"att-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO attempts
        (id, session_id, question_id, user_answer, correct_answer, is_correct, mistake_reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attempt_id,
            session_id,
            current.question_id,
            answer,
            question["answer"],
            is_correct,
            "" if is_correct else infer_mistake_reason(conn, current.question_id),
            now_iso(),
        ),
    )
    conn.commit()
    return bool(is_correct), get_next_unanswered(conn, session_id)


def infer_mistake_reason(conn: sqlite3.Connection, question_id: str) -> str:
    row = conn.execute(
        """
        SELECT c.name, c.review_note
        FROM questions q
        JOIN concepts c ON c.id = q.concept_id
        WHERE q.id = ?
        """,
        (question_id,),
    ).fetchone()
    if row is None:
        return "개념 확인 필요"
    return f"{row['name']} 개념을 정확히 구분하지 못했을 가능성이 큽니다. {row['review_note']}"


def finish_session(conn: sqlite3.Connection, session_id: str, *, allow_incomplete: bool = False) -> dict[str, object]:
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    total = conn.execute("SELECT COUNT(*) AS n FROM session_questions WHERE session_id = ?", (session_id,)).fetchone()["n"]
    answered = conn.execute("SELECT COUNT(*) AS n FROM attempts WHERE session_id = ?", (session_id,)).fetchone()["n"]
    if answered < total and not allow_incomplete:
        raise ValueError(f"session incomplete: answered {answered}/{total}")
    correct = conn.execute(
        "SELECT COUNT(*) AS n FROM attempts WHERE session_id = ? AND is_correct = 1",
        (session_id,),
    ).fetchone()["n"]
    score = round((correct / total) * 100, 2) if total else 0.0
    judgement = judge_session(conn, session_id, score)
    conn.execute(
        """
        UPDATE sessions
        SET finished_at = ?, score = ?, correct_count = ?, pass_judgement = ?
        WHERE id = ?
        """,
        (now_iso(), score, correct, judgement, session_id),
    )
    schedule_reviews(conn, session_id)
    conn.commit()
    return {
        "session_id": session_id,
        "total": total,
        "answered": answered,
        "correct": correct,
        "score": score,
        "judgement": judgement,
    }


def judge_session(conn: sqlite3.Connection, session_id: str, score: float) -> str:
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    exam = get_exam(conn, session["exam_id"])
    if score < float(exam["pass_score"]):
        return "불합격권"
    domain_scores = domain_score_rows(conn, session_id)
    if session["requested_count"] == exam["official_question_count"]:
        for row in domain_scores:
            if row["score"] < exam["domain_min_score"]:
                return f"과락 위험: {row['domain']}"
        return "합격권"
    return "합격권(커스텀 세트 참고 판정)"


def domain_score_rows(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
          d.name AS domain,
          COUNT(sq.question_id) AS total,
          COALESCE(SUM(a.is_correct), 0) AS correct,
          ROUND(COALESCE(SUM(a.is_correct), 0) * 100.0 / COUNT(sq.question_id), 2) AS score
        FROM session_questions sq
        JOIN questions q ON q.id = sq.question_id
        JOIN domains d ON d.id = q.domain_id
        LEFT JOIN attempts a ON a.session_id = sq.session_id AND a.question_id = sq.question_id
        WHERE sq.session_id = ?
        GROUP BY d.id, d.name
        ORDER BY d.id
        """,
        (session_id,),
    ).fetchall()


def wrong_attempt_rows(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
          sq.position,
          q.id AS question_id,
          q.question_text,
          q.choices_json,
          q.explanation,
          a.user_answer,
          a.correct_answer,
          a.mistake_reason,
          d.name AS domain,
          c.name AS concept,
          c.review_note
        FROM attempts a
        JOIN session_questions sq ON sq.session_id = a.session_id AND sq.question_id = a.question_id
        JOIN questions q ON q.id = a.question_id
        JOIN domains d ON d.id = q.domain_id
        JOIN concepts c ON c.id = q.concept_id
        WHERE a.session_id = ? AND a.is_correct = 0
        ORDER BY sq.position
        """,
        (session_id,),
    ).fetchall()


def repeated_wrong_rows(conn: sqlite3.Connection, exam_id: str, limit: int = 5) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT c.name AS concept, COUNT(*) AS wrong_count
        FROM attempts a
        JOIN questions q ON q.id = a.question_id
        JOIN concepts c ON c.id = q.concept_id
        WHERE q.exam_id = ? AND a.is_correct = 0
        GROUP BY c.id, c.name
        HAVING COUNT(*) >= 1
        ORDER BY wrong_count DESC, c.name ASC
        LIMIT ?
        """,
        (exam_id, limit),
    ).fetchall()


def schedule_reviews(conn: sqlite3.Connection, session_id: str) -> None:
    next_review = (date.today() + timedelta(days=3)).isoformat()
    updated_at = now_iso()
    for row in wrong_attempt_rows(conn, session_id):
        conn.execute(
            """
            INSERT INTO review_queue (id, question_id, concept_id, next_review_at, review_stage, last_result, updated_at)
            VALUES (?, ?, (SELECT concept_id FROM questions WHERE id = ?), ?, 1, 'wrong', ?)
            ON CONFLICT(question_id) DO UPDATE SET
              next_review_at = excluded.next_review_at,
              review_stage = review_queue.review_stage + 1,
              last_result = 'wrong',
              updated_at = excluded.updated_at
            """,
            (f"rev-{uuid.uuid4().hex[:12]}", row["question_id"], row["question_id"], next_review, updated_at),
        )

