from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SOURCE_REPOSITORY = "https://github.com/ludovicobesana/gail-exam-preparation"

SECTION_META = {
    "fundamentals": {
        "id": "GCP-GAIL-D1",
        "name": "Fundamentals of GenAI",
        "weight": 30,
        "official_question_count": 15,
    },
    "google-cloud-offerings": {
        "id": "GCP-GAIL-D2",
        "name": "Google Cloud's GenAI offerings",
        "weight": 35,
        "official_question_count": 18,
    },
    "improve-output": {
        "id": "GCP-GAIL-D3",
        "name": "Techniques to improve GenAI output",
        "weight": 20,
        "official_question_count": 10,
    },
    "business-strategies": {
        "id": "GCP-GAIL-D4",
        "name": "Business strategies for GenAI solutions",
        "weight": 15,
        "official_question_count": 7,
    },
}

SECTION_ALIASES = {
    "ai-ml-fundamentals": "fundamentals",
}


def convert_gail_exam_data_file(source: Path, output: Path, *, source_ref: str = SOURCE_REPOSITORY) -> dict[str, Any]:
    payload = convert_gail_practice_questions_text(source.read_text(encoding="utf-8"), source_ref=source_ref)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def convert_gail_practice_questions_text(text: str, *, source_ref: str = SOURCE_REPOSITORY) -> dict[str, Any]:
    array_text = extract_array(text, "PRACTICE_QUESTIONS")
    blocks = extract_object_blocks(array_text)
    concepts: dict[str, dict[str, str]] = {}
    questions: list[dict[str, Any]] = []

    for position, block in enumerate(blocks, start=1):
        original_id = extract_string(block, "id")
        section_id = extract_string(block, "sectionId")
        topic_id = extract_string(block, "topicId")
        question_text = extract_string(block, "question")
        options = extract_string_array(block, "options")
        correct_index = extract_int(block, "correctIndex")
        explanation = extract_string(block, "explanation")
        why_others_wrong = extract_optional_string_array(block, "whyOthersWrong")
        official_doc = extract_optional_string(block, "officialDoc")
        difficulty = extract_optional_string(block, "difficulty") or "medium"

        canonical_section_id = SECTION_ALIASES.get(section_id, section_id)
        if canonical_section_id not in SECTION_META:
            raise ValueError(f"알 수 없는 GAIL sectionId입니다: {section_id}")
        if len(options) != 4:
            raise ValueError(f"{original_id} options는 문자열 4개여야 합니다.")
        if correct_index < 0 or correct_index > 3:
            raise ValueError(f"{original_id} correctIndex는 0~3이어야 합니다.")

        domain_id = SECTION_META[canonical_section_id]["id"]
        concept_id = f"GCP-GAIL-C-{slug(canonical_section_id)}-{slug(topic_id)}"
        if concept_id not in concepts:
            concepts[concept_id] = {
                "id": concept_id,
                "domain_id": domain_id,
                "name": topic_id.replace("-", " ").title(),
                "review_note": f"{SECTION_META[canonical_section_id]['name']} 영역의 {topic_id} 개념을 공식 문서와 함께 복습한다.",
            }

        answer = correct_index + 1
        review_concept = topic_id.replace("-", " ").title()
        questions.append(
            {
                "id": f"GCP_GAIL_{position:03d}_{id_part(canonical_section_id)}_{id_part(topic_id)}_{id_part(original_id)}",
                "domain_id": domain_id,
                "concept_id": concept_id,
                "question_type": "single_choice",
                "question_text": question_text,
                "choices": options,
                "answer": answer,
                "answer_json": {"choices": [answer]},
                "explanation": explanation,
                "correct_rationale": explanation,
                "distractor_rationales": distractor_rationales(answer, why_others_wrong),
                "review_concepts": [review_concept],
                "official_scope_refs": [
                    f"GCP-GAIL-{canonical_section_id}-{topic_id}",
                    official_doc or "GCP Generative AI Leader exam guide",
                ],
                "difficulty": difficulty,
                "source_type": "public_license",
                "source_ref": source_ref,
                "source_license": "MIT",
                "source_tier": "open_license",
                "storage_policy": "raw_allowed",
                "validity_status": "needs_official_check",
                "quality_status": "needs_review",
                "scope_version": "2026",
                "official_checked_at": "",
                "quality_notes": "공식 Google Cloud 시험 가이드 대조 전입니다.",
                "gold_status": "candidate",
                "gold_checked_at": "",
                "gold_notes": "",
                "provenance": {
                    "repository": source_ref,
                    "path": "lib/exam-data.ts",
                    "position": position,
                    "original_id": original_id,
                    "section_id": section_id,
                    "canonical_section_id": canonical_section_id,
                    "topic_id": topic_id,
                    "official_doc": official_doc,
                    "notice": "비공식 커뮤니티 문제이므로 공식 Google Cloud 시험 가이드와 함께 검토한다.",
                },
            }
        )

    if not questions:
        raise ValueError("PRACTICE_QUESTIONS에서 변환 가능한 문항을 찾지 못했습니다.")

    return {
        "exam": {
            "id": "GCP_GENERATIVE_AI_LEADER",
            "name": "Google Cloud Generative AI Leader",
            "official_question_count": 50,
            "official_duration_minutes": 90,
            "pass_score": 70,
            "domain_min_score": 0,
            "notes": "MIT 라이선스 커뮤니티 연습문항 변환본입니다. 실제 시험 대비 전 공식 가이드 기준 검토가 필요합니다.",
        },
        "domains": [
            {
                "id": meta["id"],
                "name": meta["name"],
                "official_weight": meta["weight"],
                "official_question_count": meta["official_question_count"],
            }
            for meta in SECTION_META.values()
        ],
        "concepts": list(concepts.values()),
        "questions": questions,
    }


def extract_array(text: str, name: str) -> str:
    marker = re.search(rf"\b{name}\b[^=]*=", text)
    if marker is None:
        raise ValueError(f"{name} 배열을 찾지 못했습니다.")
    start = text.find("[", marker.end())
    if start == -1:
        raise ValueError(f"{name} 배열 시작을 찾지 못했습니다.")
    end = find_matching(text, start, "[", "]")
    return text[start + 1 : end]


def extract_object_blocks(array_text: str) -> list[str]:
    blocks: list[str] = []
    idx = 0
    while idx < len(array_text):
        start = array_text.find("{", idx)
        if start == -1:
            break
        end = find_matching(array_text, start, "{", "}")
        blocks.append(array_text[start : end + 1])
        idx = end + 1
    return blocks


def find_matching(text: str, start: int, opener: str, closer: str) -> int:
    depth = 0
    quote: str | None = None
    escaped = False
    for idx in range(start, len(text)):
        char = text[idx]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'", "`"}:
            quote = char
            continue
        if char == opener:
            depth += 1
            continue
        if char == closer:
            depth -= 1
            if depth == 0:
                return idx
    raise ValueError(f"{opener}{closer} 범위를 닫는 문자를 찾지 못했습니다.")


def extract_string(block: str, field: str) -> str:
    value = extract_optional_string(block, field)
    if value is None:
        raise ValueError(f"{field} 문자열을 찾지 못했습니다.")
    return value


def extract_optional_string(block: str, field: str) -> str | None:
    match = re.search(rf"\b{field}\s*:\s*(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')", block, re.S)
    if match is None:
        return None
    return decode_js_string(match.group(1))


def extract_string_array(block: str, field: str) -> list[str]:
    marker = re.search(rf"\b{field}\s*:", block)
    if marker is None:
        raise ValueError(f"{field} 배열을 찾지 못했습니다.")
    start = block.find("[", marker.end())
    if start == -1:
        raise ValueError(f"{field} 배열 시작을 찾지 못했습니다.")
    end = find_matching(block, start, "[", "]")
    array_text = block[start + 1 : end]
    return [decode_js_string(item.group(0)) for item in re.finditer(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", array_text)]


def extract_optional_string_array(block: str, field: str) -> list[str]:
    marker = re.search(rf"\b{field}\s*:", block)
    if marker is None:
        return []
    start = block.find("[", marker.end())
    if start == -1:
        return []
    end = find_matching(block, start, "[", "]")
    array_text = block[start + 1 : end]
    return [decode_js_string(item.group(0)) for item in re.finditer(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'", array_text)]


def distractor_rationales(answer: int, why_others_wrong: list[str]) -> dict[str, str]:
    wrong_indexes = [idx for idx in range(1, 5) if idx != answer]
    result: dict[str, str] = {}
    for position, idx in enumerate(wrong_indexes):
        if position < len(why_others_wrong) and why_others_wrong[position].strip():
            result[str(idx)] = why_others_wrong[position].strip()
        else:
            result[str(idx)] = "이 선택지는 문제 요구 조건을 만족하지 못하므로 정답이 아닙니다."
    return result


def extract_int(block: str, field: str) -> int:
    match = re.search(rf"\b{field}\s*:\s*(-?\d+)", block)
    if match is None:
        raise ValueError(f"{field} 숫자를 찾지 못했습니다.")
    return int(match.group(1))


def decode_js_string(token: str) -> str:
    if token.startswith("'"):
        token = '"' + token[1:-1].replace('"', '\\"') + '"'
    return json.loads(token)


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def id_part(value: str) -> str:
    return slug(value).replace("-", "_")
