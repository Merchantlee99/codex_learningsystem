from __future__ import annotations

import json
import random
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable

from .gold import gold_row_issues
from .quality import (
    SOURCE_BACKED_BLOCKED_QUALITY_STATUSES,
    is_exam_ready_mode,
    is_exam_ready_row,
    is_source_backed_mode,
    is_source_backed_row,
)

RECENT_EXCLUSION_DAYS = 1
REVIEW_MODES = {"review-cbt", "review", "due-review"}
WEAK_MODES = {"weak-cbt", "weak", "weak-review"}


@dataclass(frozen=True)
class QuestionView:
    session_id: str
    position: int
    total: int
    question_id: str
    domain: str
    concept: str
    question_type: str
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

    questions = select_questions(conn, exam_id=exam_id, count=requested_count, mode=mode, seed=seed)
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
        supported = ", ".join(
            item["id"] for item in conn.execute("SELECT id FROM exams ORDER BY id").fetchall()
        ) or "없음"
        raise ValueError(f"지원하지 않는 시험입니다: {exam_id}. 현재 실제 문제은행: {supported}")
    return row


def select_questions(
    conn: sqlite3.Connection,
    *,
    exam_id: str,
    count: int,
    mode: str = "custom-cbt",
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
    selected_fingerprints: set[str] = set()
    for domain in domains:
        rows = question_candidates(conn, exam_id=exam_id, domain_id=domain["id"], mode=mode)
        need = counts[domain["id"]]
        if len(rows) < need:
            if is_exam_ready_mode(mode):
                raise ValueError(
                    f"exam-ready 문항이 부족합니다: {domain['name']} need {need}, have {len(rows)}. "
                    "quality_status=active, validity_status=current, gold_status=gold인 문제를 보강하세요."
                )
            raise ValueError(f"not enough questions for {domain['name']}: need {need}, have {len(rows)}")
        ranked = rank_question_candidates(rows, mode=mode, rng=rng)
        domain_selected = take_distinct_questions(ranked, need, selected_fingerprints)
        selected.extend(domain_selected)
    rng.shuffle(selected)
    return selected


def question_candidates(conn: sqlite3.Connection, *, exam_id: str, domain_id: str, mode: str = "custom-cbt") -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT
          q.*,
          (SELECT COUNT(*) FROM attempts a WHERE a.question_id = q.id) AS attempt_count,
          (
            SELECT COUNT(*)
            FROM attempts a
            WHERE a.question_id = q.id AND a.is_correct = 0
          ) AS wrong_count,
          (SELECT MAX(a.created_at) FROM attempts a WHERE a.question_id = q.id) AS last_attempt_at,
          (
            SELECT COUNT(*)
            FROM session_questions sq
            WHERE sq.question_id = q.id
          ) AS seen_count,
          (
            SELECT MAX(s.started_at)
            FROM session_questions sq
            JOIN sessions s ON s.id = sq.session_id
            WHERE sq.question_id = q.id
          ) AS last_seen_at,
          rq.next_review_at,
          COALESCE(rq.review_stage, 0) AS review_stage,
          COALESCE(rq.last_result, '') AS last_review_result,
          (
            SELECT COUNT(*)
            FROM attempts ca
            JOIN questions cq ON cq.id = ca.question_id
            WHERE cq.concept_id = q.concept_id
              AND ca.is_correct = 0
          ) AS concept_wrong_count,
          (
            SELECT c.name
            FROM concepts c
            WHERE c.id = q.concept_id
          ) AS concept_name
        FROM questions q
        LEFT JOIN review_queue rq ON rq.question_id = q.id
        WHERE q.exam_id = ? AND q.domain_id = ?
        ORDER BY q.id
        """,
        (exam_id, domain_id),
    ).fetchall()
    rows = [row for row in rows if row["quality_status"] not in SOURCE_BACKED_BLOCKED_QUALITY_STATUSES]
    if is_exam_ready_mode(mode):
        return [row for row in rows if is_exam_ready_row(row) and not gold_row_issues(row, require_gold_status=True)]
    if is_source_backed_mode(mode):
        return [row for row in rows if is_source_backed_row(row)]
    return rows


def rank_question_candidates(rows: list[sqlite3.Row], *, mode: str, rng: random.Random) -> list[sqlite3.Row]:
    ranked = list(rows)
    rng.shuffle(ranked)
    ranked.sort(key=lambda row: question_priority(row, mode=mode))
    return ranked


def take_distinct_questions(
    ranked: list[sqlite3.Row],
    need: int,
    selected_fingerprints: set[str],
) -> list[sqlite3.Row]:
    if need <= 0:
        return []
    selected: list[sqlite3.Row] = []
    deferred: list[sqlite3.Row] = []
    for row in ranked:
        fingerprint = question_fingerprint(row)
        if fingerprint in selected_fingerprints:
            deferred.append(row)
            continue
        selected.append(row)
        selected_fingerprints.add(fingerprint)
        if len(selected) == need:
            return selected

    for row in deferred:
        selected.append(row)
        selected_fingerprints.add(question_fingerprint(row))
        if len(selected) == need:
            return selected
    return selected


def question_fingerprint(row: sqlite3.Row) -> str:
    return re.sub(r"\s+", " ", row["question_text"]).strip().lower()


def question_priority(row: sqlite3.Row, *, mode: str) -> tuple[object, ...]:
    attempt_count = int(row["attempt_count"] or 0)
    seen_count = int(row["seen_count"] or 0)
    wrong_count = int(row["wrong_count"] or 0)
    concept_wrong_count = int(row["concept_wrong_count"] or 0)
    review_stage = int(row["review_stage"] or 0)
    last_attempt_at = row["last_attempt_at"] or ""
    last_seen_at = row["last_seen_at"] or ""
    due_review = bool(row["next_review_at"] and row["next_review_at"] <= today_iso())
    recent = is_recent_activity(last_seen_at or last_attempt_at)
    last_activity_at = max(last_attempt_at, last_seen_at)
    weakness = max(wrong_count, concept_wrong_count)

    if mode in REVIEW_MODES:
        bucket = review_bucket(seen_count, weakness, due_review, recent, row["last_review_result"])
    elif mode in WEAK_MODES:
        bucket = weak_bucket(seen_count, weakness, due_review, recent)
    else:
        bucket = default_bucket(seen_count, weakness, due_review, recent)

    return (
        bucket,
        -int(due_review),
        -weakness,
        -review_stage,
        last_activity_at or "0000-00-00T00:00:00",
        row["id"],
    )


def default_bucket(seen_count: int, weakness: int, due_review: bool, recent: bool) -> int:
    if seen_count == 0:
        return 0
    if recent:
        return 4
    if due_review:
        return 1
    if weakness > 0:
        return 2
    return 3


def review_bucket(
    seen_count: int,
    weakness: int,
    due_review: bool,
    recent: bool,
    last_review_result: str,
) -> int:
    if due_review and last_review_result != "correct":
        return 0
    if weakness > 0 and not recent:
        return 1
    if seen_count == 0:
        return 2
    if recent:
        return 4
    return 3


def weak_bucket(seen_count: int, weakness: int, due_review: bool, recent: bool) -> int:
    if weakness > 0 and not recent:
        return 0
    if due_review:
        return 1
    if seen_count == 0:
        return 2
    if recent:
        return 4
    return 3


def is_recent_activity(last_activity_at: str) -> bool:
    if not last_activity_at:
        return False
    cutoff = datetime.now() - timedelta(days=RECENT_EXCLUSION_DAYS)
    try:
        return datetime.fromisoformat(last_activity_at) >= cutoff
    except ValueError:
        return False


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
          q.question_type,
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
        question_type=row["question_type"],
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


def submit_answer(conn: sqlite3.Connection, session_id: str, answer: int | list[int] | str) -> tuple[bool, QuestionView | None]:
    current = get_next_unanswered(conn, session_id)
    if current is None:
        raise ValueError("session has no unanswered questions")
    question = conn.execute("SELECT * FROM questions WHERE id = ?", (current.question_id,)).fetchone()
    if question is None:
        raise RuntimeError(f"missing question: {current.question_id}")
    choices = json.loads(question["choices_json"])
    user_choices = normalize_user_answer(answer, question_type=question["question_type"], choice_count=len(choices))
    correct_choices = correct_answer_choices(question)
    is_correct = int(user_choices == correct_choices)
    user_answer_json = json.dumps({"choices": user_choices}, ensure_ascii=False)
    correct_answer_json = json.dumps({"choices": correct_choices}, ensure_ascii=False)
    attempt_id = f"att-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO attempts
        (
          id,
          session_id,
          question_id,
          user_answer,
          correct_answer,
          user_answer_json,
          correct_answer_json,
          is_correct,
          mistake_reason,
          created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            attempt_id,
            session_id,
            current.question_id,
            user_choices[0] if user_choices else 0,
            correct_choices[0] if correct_choices else 0,
            user_answer_json,
            correct_answer_json,
            is_correct,
            "" if is_correct else infer_mistake_reason(conn, current.question_id),
            now_iso(),
        ),
    )
    conn.commit()
    return bool(is_correct), get_next_unanswered(conn, session_id)


def normalize_user_answer(answer: int | list[int] | str, *, question_type: str, choice_count: int) -> list[int]:
    if isinstance(answer, str):
        parts = [part.strip() for part in re.split(r"[,\\s]+", answer.strip()) if part.strip()]
    elif isinstance(answer, list):
        parts = answer
    else:
        parts = [answer]
    if not parts:
        raise ValueError("answer is required")
    choices: list[int] = []
    for part in parts:
        try:
            choice = int(part)
        except (TypeError, ValueError) as exc:
            raise ValueError("answer must be a number or comma-separated numbers") from exc
        if choice < 1 or choice > choice_count:
            raise ValueError(f"answer must be between 1 and {choice_count}")
        if choice not in choices:
            choices.append(choice)
    choices.sort()
    if question_type == "single_choice" and len(choices) != 1:
        raise ValueError("single_choice answer must contain exactly one choice")
    if question_type == "multiple_response" and len(choices) < 1:
        raise ValueError("multiple_response answer must contain at least one choice")
    if question_type not in {"single_choice", "multiple_response"}:
        raise ValueError(f"unsupported question_type: {question_type}")
    return choices


def correct_answer_choices(question: sqlite3.Row) -> list[int]:
    try:
        payload = json.loads(question["answer_json"])
    except (TypeError, ValueError):
        payload = {}
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        choices = [question["answer"]]
    return sorted({int(choice) for choice in choices})


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
          q.question_type,
          a.user_answer,
          a.correct_answer,
          a.user_answer_json,
          a.correct_answer_json,
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
    next_correct_review = (date.today() + timedelta(days=7)).isoformat()
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
    for row in correct_review_attempt_rows(conn, session_id):
        conn.execute(
            """
            UPDATE review_queue
            SET
              next_review_at = ?,
              review_stage = review_stage + 1,
              last_result = 'correct',
              updated_at = ?
            WHERE question_id = ?
            """,
            (next_correct_review, updated_at, row["question_id"]),
        )


def correct_review_attempt_rows(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT a.question_id
        FROM attempts a
        JOIN review_queue rq ON rq.question_id = a.question_id
        WHERE a.session_id = ? AND a.is_correct = 1
        """,
        (session_id,),
    ).fetchall()
