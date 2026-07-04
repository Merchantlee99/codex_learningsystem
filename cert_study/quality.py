from __future__ import annotations

import sqlite3
from typing import Any


EXAM_READY_MODE = "exam-ready"
EXAM_READY_SOURCE_TIERS = {"official_sample", "open_license", "user_owned", "licensed_private"}
EXAM_READY_QUALITY_STATUSES = {"active"}
EXAM_READY_GOLD_STATUS = "gold"
SOURCE_BACKED_MODES = {"source-backed", "source_backed", "source-backed-cbt", "real-cbt", "private-cbt"}
SYNTHETIC_SOURCE_TYPES = {"synthetic", "synthetic_recent_scope"}
SOURCE_BACKED_BLOCKED_QUALITY_STATUSES = {"needs_repair", "broken", "outdated"}
GCP_GAIL_ALLOWED_DOC_HOSTS = (
    "https://cloud.google.com/",
    "https://ai.google.dev/",
    "https://notebooklm.google/",
)


def is_exam_ready_mode(mode: str) -> bool:
    return mode in {EXAM_READY_MODE, "exam_ready", "exam-ready-cbt"}


def is_source_backed_mode(mode: str) -> bool:
    return mode in SOURCE_BACKED_MODES


def is_exam_ready_row(row: sqlite3.Row) -> bool:
    return (
        row["quality_status"] in EXAM_READY_QUALITY_STATUSES
        and row["validity_status"] == "current"
        and row["gold_status"] == EXAM_READY_GOLD_STATUS
        and row["source_tier"] in EXAM_READY_SOURCE_TIERS
        and row["question_type"] == "single_choice"
    )


def is_source_backed_row(row: sqlite3.Row) -> bool:
    return (
        row["source_type"] not in SYNTHETIC_SOURCE_TYPES
        and row["source_tier"] != "synthetic"
        and row["quality_status"] not in SOURCE_BACKED_BLOCKED_QUALITY_STATUSES
        and row["question_type"] == "single_choice"
    )


def coverage_report(conn: sqlite3.Connection, exam_id: str) -> dict[str, Any]:
    exam = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if exam is None:
        raise ValueError(f"지원하지 않는 시험입니다: {exam_id}")
    domains = conn.execute("SELECT * FROM domains WHERE exam_id = ? ORDER BY id", (exam_id,)).fetchall()
    total_exam_ready = exam_ready_question_count(conn, exam_id)
    required_counts = required_domain_counts(domains, int(exam["official_question_count"]))
    domain_rows: list[dict[str, Any]] = []

    for domain in domains:
        counts = conn.execute(
            """
            SELECT
              COUNT(q.id) AS total,
              COUNT(CASE WHEN q.quality_status = 'active' THEN 1 END) AS active,
              COUNT(
                CASE
                  WHEN q.quality_status = 'active'
                   AND q.validity_status = 'current'
                   AND q.gold_status = 'gold'
                   AND q.source_tier IN ('official_sample', 'open_license', 'user_owned', 'licensed_private')
                   AND q.question_type = 'single_choice'
                  THEN 1
                END
              ) AS exam_ready
            FROM questions q
            WHERE q.exam_id = ? AND q.domain_id = ?
            """,
            (exam_id, domain["id"]),
        ).fetchone()
        actual_weight = round((counts["exam_ready"] * 100.0 / total_exam_ready), 2) if total_exam_ready else 0.0
        official_weight = float(domain["official_weight"])
        required = required_counts[domain["id"]]
        gap = counts["exam_ready"] - required
        if counts["exam_ready"] < required:
            status = "부족"
        elif abs(actual_weight - official_weight) >= 10:
            status = "비중주의"
        else:
            status = "충분"
        domain_rows.append(
            {
                "domain_id": domain["id"],
                "domain": domain["name"],
                "official_weight": official_weight,
                "actual_weight": actual_weight,
                "required_questions": required,
                "total_questions": counts["total"],
                "active_questions": counts["active"],
                "exam_ready_questions": counts["exam_ready"],
                "gap": gap,
                "status": status,
            }
        )

    ready = total_exam_ready >= int(exam["official_question_count"]) and all(
        row["status"] != "부족" for row in domain_rows
    )
    return {
        "exam_id": exam["id"],
        "exam_name": exam["name"],
        "official_question_count": exam["official_question_count"],
        "exam_ready_questions": total_exam_ready,
        "ready": ready,
        "domains": domain_rows,
    }


def exam_ready_question_count(conn: sqlite3.Connection, exam_id: str) -> int:
    return conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM questions
        WHERE exam_id = ?
          AND quality_status = 'active'
          AND validity_status = 'current'
          AND gold_status = 'gold'
          AND source_tier IN ('official_sample', 'open_license', 'user_owned', 'licensed_private')
          AND question_type = 'single_choice'
        """,
        (exam_id,),
    ).fetchone()["n"]


def required_domain_counts(domains: list[sqlite3.Row], official_count: int) -> dict[str, int]:
    raw = [(row, official_count * float(row["official_weight"]) / 100.0) for row in domains]
    counts = {row["id"]: int(value) for row, value in raw}
    remainder = official_count - sum(counts.values())
    ranked = sorted(raw, key=lambda item: (item[1] - int(item[1]), item[0]["official_weight"]), reverse=True)
    for idx in range(remainder):
        counts[ranked[idx % len(ranked)][0]["id"]] += 1
    return counts


def render_coverage_report(report: dict[str, Any]) -> str:
    status = "가능" if report["ready"] else "부족"
    lines = [
        f"# {report['exam_id']} 문제은행 품질 점검",
        "",
        f"- exam-ready 상태: {status}",
        f"- exam-ready 문항: {report['exam_ready_questions']}/{report['official_question_count']}",
        "",
        "## 영역별 커버리지",
    ]
    for row in report["domains"]:
        lines.append(
            f"- {row['domain']}: exam-ready {row['exam_ready_questions']}/{row['required_questions']}문항, "
            f"공식 {row['official_weight']:g}% / 현재 {row['actual_weight']:g}% - {row['status']}"
        )
    return "\n".join(lines)


def promote_gcp_gail_questions(
    conn: sqlite3.Connection,
    *,
    checked_at: str,
    exam_id: str = "GCP_GENERATIVE_AI_LEADER",
) -> dict[str, int | str]:
    candidates = conn.execute(
        """
        SELECT id, provenance_json
        FROM questions
        WHERE exam_id = ?
          AND source_tier = 'open_license'
          AND source_license = 'MIT'
          AND quality_status = 'needs_review'
          AND validity_status = 'needs_official_check'
        """,
        (exam_id,),
    ).fetchall()
    promotable = [row["id"] for row in candidates if has_allowed_official_doc(row["provenance_json"])]
    if promotable:
        conn.executemany(
            """
            UPDATE questions
            SET
              quality_status = 'active',
              validity_status = 'current',
              official_checked_at = ?,
              gold_status = CASE
                WHEN correct_rationale != ''
                 AND distractor_rationales_json != '{}'
                 AND review_concepts_json != '[]'
                 AND official_scope_refs_json != '[]'
                THEN 'gold'
                ELSE gold_status
              END,
              gold_checked_at = CASE
                WHEN correct_rationale != ''
                 AND distractor_rationales_json != '{}'
                 AND review_concepts_json != '[]'
                 AND official_scope_refs_json != '[]'
                THEN ?
                ELSE gold_checked_at
              END,
              quality_notes = '공식 문서 URL과 시험 도메인 매핑을 확인해 exam-ready 후보로 승격함'
            WHERE id = ?
            """,
            [(checked_at, checked_at, question_id) for question_id in promotable],
        )
        conn.commit()
    return {
        "exam_id": exam_id,
        "checked_at": checked_at,
        "candidates": len(candidates),
        "promoted": len(promotable),
        "skipped": len(candidates) - len(promotable),
    }


def has_allowed_official_doc(provenance_json: str) -> bool:
    try:
        import json

        provenance = json.loads(provenance_json)
    except (TypeError, ValueError):
        return False
    official_doc = provenance.get("official_doc")
    if not isinstance(official_doc, str):
        return False
    return any(official_doc.startswith(host) for host in GCP_GAIL_ALLOWED_DOC_HOSTS)
