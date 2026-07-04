from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from .quality import EXAM_READY_SOURCE_TIERS, required_domain_counts


GOLD_STATUS_READY = "gold"
GOLD_CANDIDATE_STATUSES = {"candidate", "needs_review", "none"}
PLACEHOLDER_EXPLANATION_PATTERNS = (
    "정답표 기준",
    "세부 해설",
    "오답노트에서 보강",
    "보강합니다",
    "공식 문서와 함께 복습",
    "품질 상태 테스트",
)
GENERIC_CONCEPT_MARKERS = (
    "-SRC-C-",
    "SOURCE-BACKED",
    "SOURCE BACKED",
    "COMMUNITY PRACTICE",
)


def is_gold_row(row: sqlite3.Row) -> bool:
    return (
        row["gold_status"] == GOLD_STATUS_READY
        and row["quality_status"] == "active"
        and row["validity_status"] == "current"
        and row["source_tier"] in EXAM_READY_SOURCE_TIERS
        and row["source_tier"] != "synthetic"
        and row["question_type"] == "single_choice"
    )


def audit_final_bank(conn: sqlite3.Connection, exam_id: str) -> dict[str, Any]:
    exam = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if exam is None:
        raise ValueError(f"지원하지 않는 시험입니다: {exam_id}")

    domains = conn.execute("SELECT * FROM domains WHERE exam_id = ? ORDER BY id", (exam_id,)).fetchall()
    required_counts = required_domain_counts(domains, int(exam["official_question_count"]))
    rows = final_question_rows(conn, exam_id)
    issues: list[dict[str, Any]] = []
    eligible_ids: set[str] = set()

    fingerprints: dict[str, str] = {}
    for row in rows:
        if row["gold_status"] != GOLD_STATUS_READY:
            continue
        row_issues = gold_row_issues(row, require_gold_status=True)
        for issue in row_issues:
            issues.append(issue)
        fingerprint = question_fingerprint(str(row["question_text"]))
        if fingerprint in fingerprints:
            issues.append(
                make_issue(
                    "error",
                    "duplicate_question_text",
                    f"{row['id']} 문항 지문이 {fingerprints[fingerprint]}와 중복됩니다.",
                    question_id=row["id"],
                )
            )
        else:
            fingerprints[fingerprint] = row["id"]
        if not row_issues:
            eligible_ids.add(row["id"])

    domain_rows = []
    for domain in domains:
        total = sum(1 for row in rows if row["domain_id"] == domain["id"])
        gold = sum(1 for row in rows if row["domain_id"] == domain["id"] and row["id"] in eligible_ids)
        required = required_counts[domain["id"]]
        status = "충분" if gold >= required else "부족"
        if status == "부족":
            issues.append(
                make_issue(
                    "error",
                    "domain_coverage_gap",
                    f"{domain['name']} gold 문항이 부족합니다: need {required}, have {gold}.",
                    domain_id=domain["id"],
                )
            )
        domain_rows.append(
            {
                "domain_id": domain["id"],
                "domain": domain["name"],
                "required_questions": required,
                "total_questions": total,
                "gold_questions": gold,
                "status": status,
            }
        )

    gold_questions = len(eligible_ids)
    if gold_questions < int(exam["official_question_count"]):
        issues.append(
            make_issue(
                "error",
                "gold_count_gap",
                f"정규 {exam['official_question_count']}문항을 구성하기에 gold 문항이 부족합니다: have {gold_questions}.",
            )
        )

    return {
        "exam_id": exam["id"],
        "exam_name": exam["name"],
        "official_question_count": exam["official_question_count"],
        "gold_questions": gold_questions,
        "ready": not any(item["severity"] == "error" for item in issues),
        "domains": domain_rows,
        "issues": issues,
    }


def final_question_rows(conn: sqlite3.Connection, exam_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
          q.*,
          c.name AS concept_name,
          c.review_note AS concept_review_note,
          d.name AS domain_name
        FROM questions q
        JOIN concepts c ON c.id = q.concept_id
        JOIN domains d ON d.id = q.domain_id
        WHERE q.exam_id = ?
        ORDER BY q.id
        """,
        (exam_id,),
    ).fetchall()


def gold_row_issues(row: sqlite3.Row, *, require_gold_status: bool) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    question_id = row["id"]
    if require_gold_status and row["gold_status"] != GOLD_STATUS_READY:
        issues.append(make_issue("error", "not_gold", "gold_status=gold가 아닙니다.", question_id=question_id))
    if row["quality_status"] != "active":
        issues.append(make_issue("error", "quality_not_active", "quality_status=active가 아닙니다.", question_id=question_id))
    if row["validity_status"] != "current":
        issues.append(make_issue("error", "validity_not_current", "validity_status=current가 아닙니다.", question_id=question_id))
    if row["source_tier"] not in EXAM_READY_SOURCE_TIERS or row["source_tier"] == "synthetic":
        issues.append(make_issue("error", "source_tier_not_allowed", "gold 문항으로 쓸 수 없는 source_tier입니다.", question_id=question_id))
    if row["question_type"] != "single_choice":
        issues.append(make_issue("error", "unsupported_question_type", "현재 gold CBT는 single_choice만 지원합니다.", question_id=question_id))

    choices = parse_json(row["choices_json"], [])
    answer_json = parse_json(row["answer_json"], {})
    answer_choices = answer_json.get("choices") if isinstance(answer_json, dict) else None
    if not isinstance(choices, list) or len(choices) != 4 or not all(isinstance(item, str) and item.strip() for item in choices):
        issues.append(make_issue("error", "invalid_choices", "선택지는 비어 있지 않은 문자열 4개여야 합니다.", question_id=question_id))
    if answer_choices != [row["answer"]]:
        issues.append(make_issue("error", "answer_mapping_mismatch", "answer와 answer_json.choices가 일치하지 않습니다.", question_id=question_id))

    explanation = str(row["explanation"] or "").strip()
    if len(explanation) < 20:
        issues.append(make_issue("error", "short_explanation", "해설이 너무 짧습니다.", question_id=question_id))
    if has_placeholder_explanation(explanation):
        issues.append(make_issue("error", "placeholder_explanation", "placeholder 해설이 남아 있습니다.", question_id=question_id))
    if has_visible_answer_leak(row):
        issues.append(make_issue("error", "visible_answer_leak", "문항/선택지에 정답 또는 해설 노출 흔적이 있습니다.", question_id=question_id))

    if not str(row["correct_rationale"] or "").strip():
        issues.append(make_issue("error", "missing_correct_rationale", "정답 근거가 없습니다.", question_id=question_id))

    distractors = parse_json(row["distractor_rationales_json"], {})
    if not isinstance(distractors, dict):
        issues.append(make_issue("error", "invalid_distractor_rationales", "오답 근거는 object여야 합니다.", question_id=question_id))
    else:
        missing = [
            str(idx)
            for idx in range(1, 5)
            if idx != row["answer"] and not str(distractors.get(str(idx), "")).strip()
        ]
        if missing:
            issues.append(
                make_issue(
                    "error",
                    "missing_distractor_rationales",
                    f"오답 선택지 해설이 부족합니다: {', '.join(missing)}.",
                    question_id=question_id,
                )
            )

    review_concepts = parse_json(row["review_concepts_json"], [])
    if not valid_string_list(review_concepts):
        issues.append(make_issue("error", "missing_review_concepts", "복습 개념 매핑이 없습니다.", question_id=question_id))

    scope_refs = parse_json(row["official_scope_refs_json"], [])
    if not valid_string_list(scope_refs):
        issues.append(make_issue("error", "missing_official_scope_refs", "공식 출제범위 참조가 없습니다.", question_id=question_id))

    if not valid_date(row["official_checked_at"]):
        issues.append(make_issue("error", "missing_official_checked_at", "official_checked_at 날짜가 없습니다.", question_id=question_id))
    if require_gold_status and not valid_date(row["gold_checked_at"]):
        issues.append(make_issue("error", "missing_gold_checked_at", "gold_checked_at 날짜가 없습니다.", question_id=question_id))

    concept_id = str(row["concept_id"] or "")
    concept_name = str(row["concept_name"] or "")
    if has_generic_concept(concept_id, concept_name):
        issues.append(make_issue("error", "generic_concept", "세부 개념이 아니라 임시/광역 개념에 매핑되어 있습니다.", question_id=question_id))
    return issues


def promote_gold_candidates(
    conn: sqlite3.Connection,
    exam_id: str,
    *,
    checked_at: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not valid_date(checked_at):
        raise ValueError("checked_at은 YYYY-MM-DD 날짜여야 합니다.")
    rows = final_question_rows(conn, exam_id)
    candidate_rows = [
        row
        for row in rows
        if row["gold_status"] in GOLD_CANDIDATE_STATUSES
        and row["quality_status"] == "active"
        and row["validity_status"] == "current"
        and row["source_tier"] in EXAM_READY_SOURCE_TIERS
        and row["source_tier"] != "synthetic"
    ]
    promotable: list[str] = []
    skipped: list[dict[str, Any]] = []
    for row in candidate_rows:
        issues = gold_row_issues(row, require_gold_status=False)
        if issues:
            skipped.append({"question_id": row["id"], "codes": [item["code"] for item in issues]})
            continue
        promotable.append(row["id"])

    if promotable and not dry_run:
        conn.executemany(
            """
            UPDATE questions
            SET gold_status = 'gold',
                gold_checked_at = ?,
                gold_notes = CASE
                  WHEN gold_notes = '' THEN 'final audit row gate passed'
                  ELSE gold_notes
                END
            WHERE id = ?
            """,
            [(checked_at, question_id) for question_id in promotable],
        )
        conn.commit()

    return {
        "exam_id": exam_id,
        "checked_at": checked_at,
        "candidates": len(candidate_rows),
        "promoted": len(promotable),
        "skipped": len(skipped),
        "dry_run": dry_run,
        "skipped_examples": skipped[:10],
    }


def export_gold_template(conn: sqlite3.Connection, exam_id: str, output: Path) -> dict[str, Any]:
    exam = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if exam is None:
        raise ValueError(f"지원하지 않는 시험입니다: {exam_id}")
    domains = conn.execute("SELECT * FROM domains WHERE exam_id = ? ORDER BY id", (exam_id,)).fetchall()
    concepts = conn.execute("SELECT * FROM concepts WHERE exam_id = ? ORDER BY id", (exam_id,)).fetchall()
    rows = final_question_rows(conn, exam_id)
    payload = {
        "exam": dict_without_internal_keys(exam),
        "domains": [dict_without_internal_keys(row) for row in domains],
        "concepts": [dict_without_internal_keys(row) for row in concepts],
        "questions": [question_export_payload(row) for row in rows],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"exam_id": exam_id, "output": str(output), "questions": len(rows)}


def question_export_payload(row: sqlite3.Row) -> dict[str, Any]:
    data = {
        "id": row["id"],
        "domain_id": row["domain_id"],
        "concept_id": row["concept_id"],
        "question_type": row["question_type"],
        "question_text": row["question_text"],
        "choices": parse_json(row["choices_json"], []),
        "answer": row["answer"],
        "answer_json": parse_json(row["answer_json"], {"choices": [row["answer"]]}),
        "explanation": row["explanation"],
        "correct_rationale": row["correct_rationale"],
        "distractor_rationales": parse_json(row["distractor_rationales_json"], {}),
        "review_concepts": parse_json(row["review_concepts_json"], []),
        "official_scope_refs": parse_json(row["official_scope_refs_json"], []),
        "difficulty": row["difficulty"],
        "source_type": row["source_type"],
        "source_ref": row["source_ref"],
        "source_license": row["source_license"],
        "source_tier": row["source_tier"],
        "storage_policy": row["storage_policy"],
        "validity_status": row["validity_status"],
        "quality_status": row["quality_status"],
        "scope_version": row["scope_version"],
        "official_checked_at": row["official_checked_at"],
        "quality_notes": row["quality_notes"],
        "gold_status": "candidate" if row["gold_status"] == "none" else row["gold_status"],
        "gold_checked_at": row["gold_checked_at"],
        "gold_notes": row["gold_notes"],
        "provenance": parse_json(row["provenance_json"], {}),
    }
    return data


def render_final_audit_report(report: dict[str, Any]) -> str:
    status = "가능" if report["ready"] else "불가"
    lines = [
        f"# {report['exam_id']} 최종 문제은행 검수",
        "",
        f"- 최종 사용 가능: {status}",
        f"- gold 문항: {report['gold_questions']}/{report['official_question_count']}",
        "",
        "## 영역별 상태",
    ]
    for row in report["domains"]:
        lines.append(
            f"- {row['domain']}: gold {row['gold_questions']}/{row['required_questions']}문항 "
            f"(전체 {row['total_questions']}문항) - {row['status']}"
        )
    lines.extend(["", "## 차단 이슈"])
    if not report["issues"]:
        lines.append("- 없음")
    else:
        for item in report["issues"][:80]:
            location = item.get("question_id") or item.get("domain_id") or "bank"
            lines.append(f"- [{item['severity']}] {item['code']} / {location}: {item['message']}")
        if len(report["issues"]) > 80:
            lines.append(f"- ... {len(report['issues']) - 80}개 이슈 생략")
    return "\n".join(lines)


def make_issue(
    severity: str,
    code: str,
    message: str,
    *,
    question_id: str | None = None,
    domain_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"severity": severity, "code": code, "message": message}
    if question_id:
        payload["question_id"] = question_id
    if domain_id:
        payload["domain_id"] = domain_id
    return payload


def parse_json(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def valid_string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


def valid_date(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def has_placeholder_explanation(value: str) -> bool:
    normalized = value.upper()
    return any(pattern.upper() in normalized for pattern in PLACEHOLDER_EXPLANATION_PATTERNS)


def has_generic_concept(concept_id: str, concept_name: str) -> bool:
    haystack = f"{concept_id} {concept_name}".upper()
    return any(marker in haystack for marker in GENERIC_CONCEPT_MARKERS)


def has_visible_answer_leak(row: sqlite3.Row) -> bool:
    haystack = f"{row['question_text']} {' '.join(parse_json(row['choices_json'], []))}"
    return bool(re.search(r"(정답|해설)\s*[:：]\s*[1-4A-D]|답\s*[:：]\s*[1-4A-D]", haystack, re.I))


def question_fingerprint(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def dict_without_internal_keys(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}
