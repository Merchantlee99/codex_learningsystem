from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


PUBLIC_SOURCE_TYPES = {
    "synthetic",
    "synthetic_recent_scope",
    "official_sample_link",
    "official_public_sample",
    "public_license",
    "open_license",
}
PRIVATE_SOURCE_TYPES = {
    "user_owned_summary",
    "user_owned_raw",
    "licensed_private",
    "personal_wrong_note",
    "restored_summary",
}
FORBIDDEN_SOURCE_TYPES = {
    "actual_exam_dump",
    "credential_assessment_material",
    "commercial_book_verbatim",
    "web_scraped_verbatim",
}
GOLD_STATUSES = {"none", "candidate", "gold", "rejected", "needs_review"}


def import_bank_file(conn: sqlite3.Connection, path: Path, *, private: bool = False) -> dict[str, int | str]:
    payload = load_payload(path)
    exam = require_dict(payload, "exam")
    domains = require_list(payload, "domains")
    concepts = require_list(payload, "concepts")
    questions = require_list(payload, "questions")

    exam_id = require_text(exam, "id")
    validate_question_sources(questions, private=private)

    conn.execute(
        """
        INSERT OR REPLACE INTO exams
        (id, name, official_question_count, official_duration_minutes, pass_score, domain_min_score, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            exam_id,
            require_text(exam, "name"),
            int(exam.get("official_question_count", len(questions))),
            int(exam.get("official_duration_minutes", 90)),
            float(exam.get("pass_score", 60.0)),
            float(exam.get("domain_min_score", 0.0)),
            str(exam.get("notes", "")),
        ),
    )

    conn.executemany(
        "INSERT OR REPLACE INTO domains (id, exam_id, name, official_weight, official_question_count) VALUES (?, ?, ?, ?, ?)",
        [
            (
                require_text(row, "id"),
                exam_id,
                require_text(row, "name"),
                float(row.get("official_weight", 0.0)),
                int(row.get("official_question_count", 0)),
            )
            for row in domains
        ],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO concepts (id, exam_id, domain_id, name, review_note) VALUES (?, ?, ?, ?, ?)",
        [
            (
                require_text(row, "id"),
                exam_id,
                require_text(row, "domain_id"),
                require_text(row, "name"),
                require_text(row, "review_note"),
            )
            for row in concepts
        ],
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO questions
        (
          id,
          exam_id,
          domain_id,
          concept_id,
          question_type,
          question_text,
          choices_json,
          answer_json,
          answer,
          explanation,
          difficulty,
          source_type,
          source_ref,
          source_license,
          source_tier,
          storage_policy,
          validity_status,
          quality_status,
          scope_version,
          official_checked_at,
          quality_notes,
          correct_rationale,
          distractor_rationales_json,
          review_concepts_json,
          official_scope_refs_json,
          gold_status,
          gold_checked_at,
          gold_notes,
          provenance_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [normalize_question(row, exam_id) for row in questions],
    )
    conn.commit()
    return {"exam_id": exam_id, "domains": len(domains), "concepts": len(concepts), "questions": len(questions)}


def load_payload(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        payload = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ValueError("YAML import는 PyYAML이 설치되어 있어야 합니다. JSON importer는 기본 지원합니다.") from exc
        payload = yaml.safe_load(text)
    else:
        raise ValueError("지원하는 importer 확장자는 .json, .yaml, .yml 입니다.")
    if not isinstance(payload, dict):
        raise ValueError("문제은행 파일 최상위는 object여야 합니다.")
    return payload


def validate_question_sources(questions: list[Any], *, private: bool) -> None:
    for row in questions:
        if not isinstance(row, dict):
            raise ValueError("questions 항목은 object 목록이어야 합니다.")
        source_type = require_text(row, "source_type")
        if source_type in FORBIDDEN_SOURCE_TYPES:
            raise ValueError(f"가져올 수 없는 source_type입니다: {source_type}")
        if source_type in PRIVATE_SOURCE_TYPES and not private:
            raise ValueError(f"{source_type} 문제는 --private 옵션으로만 로컬 import할 수 있습니다.")
        if source_type not in PUBLIC_SOURCE_TYPES and source_type not in PRIVATE_SOURCE_TYPES:
            raise ValueError(f"알 수 없는 source_type입니다: {source_type}")


def normalize_question(row: dict[str, Any], exam_id: str) -> tuple[Any, ...]:
    question_type = str(row.get("question_type", "single_choice")).strip() or "single_choice"
    if question_type != "single_choice":
        raise ValueError(f"{row.get('id', '<unknown>')} 현재 importer는 single_choice만 CBT로 가져옵니다.")
    choices = row.get("choices")
    if not isinstance(choices, list) or len(choices) != 4 or not all(isinstance(item, str) for item in choices):
        raise ValueError(f"{row.get('id', '<unknown>')} choices는 문자열 4개여야 합니다.")
    answer = normalize_single_choice_answer(row)
    source_type = require_text(row, "source_type")
    source_ref = require_text(row, "source_ref")
    validity_status = optional_text(row, "validity_status", "current")
    gold_status = normalize_gold_status(row)
    distractor_rationales = normalize_json_object(row, "distractor_rationales", "distractor_rationales_json")
    review_concepts = normalize_json_list(row, "review_concepts", "review_concepts_json")
    official_scope_refs = normalize_json_list(row, "official_scope_refs", "official_scope_refs_json")
    correct_rationale = optional_loose_text(row, "correct_rationale", "")
    gold_checked_at = optional_loose_text(row, "gold_checked_at", "")
    if gold_status == "gold":
        validate_gold_declared_question(
            row,
            answer=answer,
            correct_rationale=correct_rationale,
            distractor_rationales=distractor_rationales,
            review_concepts=review_concepts,
            official_scope_refs=official_scope_refs,
            gold_checked_at=gold_checked_at,
        )
    return (
        require_text(row, "id"),
        exam_id,
        require_text(row, "domain_id"),
        require_text(row, "concept_id"),
        question_type,
        require_text(row, "question_text"),
        json.dumps(choices, ensure_ascii=False),
        json.dumps({"choices": [answer]}, ensure_ascii=False),
        answer,
        require_text(row, "explanation"),
        str(row.get("difficulty", "medium")),
        source_type,
        source_ref,
        optional_text(row, "source_license", default_source_license(source_type)),
        optional_text(row, "source_tier", default_source_tier(source_type)),
        optional_text(row, "storage_policy", default_storage_policy(source_type)),
        validity_status,
        optional_text(row, "quality_status", default_quality_status(validity_status)),
        str(row.get("scope_version", "")),
        str(row.get("official_checked_at", "")),
        str(row.get("quality_notes", "")),
        correct_rationale,
        json.dumps(distractor_rationales, ensure_ascii=False, sort_keys=True),
        json.dumps(review_concepts, ensure_ascii=False),
        json.dumps(official_scope_refs, ensure_ascii=False),
        gold_status,
        gold_checked_at,
        optional_loose_text(row, "gold_notes", ""),
        normalize_provenance_json(row, source_ref=source_ref),
    )


def normalize_single_choice_answer(row: dict[str, Any]) -> int:
    answer_from_int = row.get("answer")
    answer_json = row.get("answer_json")
    answer_from_json: int | None = None
    if answer_json is not None:
        if isinstance(answer_json, str):
            try:
                answer_json = json.loads(answer_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{row.get('id', '<unknown>')} answer_json은 JSON object여야 합니다.") from exc
        if not isinstance(answer_json, dict):
            raise ValueError(f"{row.get('id', '<unknown>')} answer_json은 object여야 합니다.")
        choices = answer_json.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError(f"{row.get('id', '<unknown>')} answer_json.choices는 정답 번호 1개여야 합니다.")
        answer_from_json = int(choices[0])

    if answer_from_int is None:
        answer = answer_from_json or 0
    elif answer_from_json is None:
        answer = int(answer_from_int)
    else:
        answer = int(answer_from_int)
        if answer != answer_from_json:
            raise ValueError(f"{row.get('id', '<unknown>')} answer와 answer_json이 서로 다릅니다.")

    if answer < 1 or answer > 4:
        raise ValueError(f"{row.get('id', '<unknown>')} answer는 1~4여야 합니다.")
    return answer


def default_source_license(source_type: str) -> str:
    if source_type in {"synthetic", "synthetic_recent_scope"}:
        return "synthetic"
    if source_type in {"official_sample_link", "official_public_sample"}:
        return "official-public"
    if source_type in PRIVATE_SOURCE_TYPES:
        return "user-owned"
    return "unknown"


def default_storage_policy(source_type: str) -> str:
    if source_type in PRIVATE_SOURCE_TYPES:
        return "private_only"
    if source_type == "official_sample_link":
        return "link_only"
    return "raw_allowed"


def default_source_tier(source_type: str) -> str:
    if source_type in {"synthetic", "synthetic_recent_scope"}:
        return "synthetic"
    if source_type in {"official_sample_link", "official_public_sample"}:
        return "official_sample"
    if source_type in {"public_license", "open_license"}:
        return "open_license"
    if source_type == "licensed_private":
        return "licensed_private"
    if source_type in PRIVATE_SOURCE_TYPES:
        return "user_owned"
    return "unknown"


def default_quality_status(validity_status: str) -> str:
    if validity_status in {"needs_official_check", "unknown"}:
        return "needs_review"
    if validity_status == "outdated":
        return "outdated"
    return "active"


def normalize_provenance_json(row: dict[str, Any], *, source_ref: str) -> str:
    value = row.get("provenance", row.get("provenance_json", {"source_ref": source_ref}))
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = {"note": value}
    elif isinstance(value, dict):
        parsed = value
    else:
        raise ValueError(f"{row.get('id', '<unknown>')} provenance는 object 또는 JSON 문자열이어야 합니다.")
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True)


def normalize_gold_status(row: dict[str, Any]) -> str:
    value = str(row.get("gold_status", "none")).strip() or "none"
    if value not in GOLD_STATUSES:
        raise ValueError(f"{row.get('id', '<unknown>')} gold_status는 {', '.join(sorted(GOLD_STATUSES))} 중 하나여야 합니다.")
    return value


def normalize_json_object(row: dict[str, Any], key: str, legacy_key: str) -> dict[str, Any]:
    value = row.get(key, row.get(legacy_key, {}))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{row.get('id', '<unknown>')} {key}는 JSON object여야 합니다.") from exc
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError(f"{row.get('id', '<unknown>')} {key}는 object여야 합니다.")
    return {str(k): v for k, v in value.items()}


def normalize_json_list(row: dict[str, Any], key: str, legacy_key: str) -> list[Any]:
    value = row.get(key, row.get(legacy_key, []))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{row.get('id', '<unknown>')} {key}는 JSON array여야 합니다.") from exc
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValueError(f"{row.get('id', '<unknown>')} {key}는 list여야 합니다.")
    return value


def validate_gold_declared_question(
    row: dict[str, Any],
    *,
    answer: int,
    correct_rationale: str,
    distractor_rationales: dict[str, Any],
    review_concepts: list[Any],
    official_scope_refs: list[Any],
    gold_checked_at: str,
) -> None:
    question_id = row.get("id", "<unknown>")
    if not correct_rationale.strip():
        raise ValueError(f"{question_id} gold 문항은 correct_rationale이 필요합니다.")
    missing = [
        str(idx)
        for idx in range(1, 5)
        if idx != answer and not str(distractor_rationales.get(str(idx), "")).strip()
    ]
    if missing:
        raise ValueError(f"{question_id} gold 문항은 오답 선택지 해설이 필요합니다: {', '.join(missing)}")
    if not all(isinstance(item, str) and item.strip() for item in review_concepts):
        raise ValueError(f"{question_id} gold 문항은 review_concepts가 필요합니다.")
    if not all(isinstance(item, str) and item.strip() for item in official_scope_refs):
        raise ValueError(f"{question_id} gold 문항은 official_scope_refs가 필요합니다.")
    if not gold_checked_at.strip():
        raise ValueError(f"{question_id} gold 문항은 gold_checked_at이 필요합니다.")


def require_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key}는 object여야 합니다.")
    return value


def require_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key}는 list여야 합니다.")
    return value


def require_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key}는 비어 있지 않은 문자열이어야 합니다.")
    return value


def optional_text(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key}는 비어 있지 않은 문자열이어야 합니다.")
    return value


def optional_loose_text(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{key}는 문자열이어야 합니다.")
    return value.strip()
