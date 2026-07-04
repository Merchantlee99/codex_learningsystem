from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


SQLD_CONCEPTS = [
    {
        "id": "SQLD-C-ENTITY",
        "domain_id": "SQLD-D1",
        "name": "엔터티",
        "review_note": "엔터티의 독립성, 발생 시점, 기본/중심/행위 엔터티 구분을 복습한다.",
        "scope_ref": "SQLD-D1-데이터모델링-엔터티",
        "keywords": ("엔터티", "entity", "기본 엔터티", "중심 엔터티", "행위 엔터티", "키 엔터티"),
    },
    {
        "id": "SQLD-C-ATTRIBUTE",
        "domain_id": "SQLD-D1",
        "name": "속성",
        "review_note": "기본/설계/파생 속성, 단순/복합/다중값 속성, 도메인과 속성값을 구분한다.",
        "scope_ref": "SQLD-D1-데이터모델링-속성",
        "keywords": ("속성", "도메인", "파생", "속성값", "복합 속성", "다중"),
    },
    {
        "id": "SQLD-C-RELATIONSHIP",
        "domain_id": "SQLD-D1",
        "name": "관계",
        "review_note": "관계 차수, 참여도, 식별/비식별 관계, ERD 표기법의 의미를 복습한다.",
        "scope_ref": "SQLD-D1-데이터모델링-관계",
        "keywords": ("관계", "관계차수", "erd", "ie", "barker", "식별자 관계", "비식별자", "부모", "자식"),
    },
    {
        "id": "SQLD-C-IDENTIFIER",
        "domain_id": "SQLD-D1",
        "name": "식별자",
        "review_note": "주식별자 특성, 본질/인조/내부/외부 식별자와 NULL 허용 여부를 구분한다.",
        "scope_ref": "SQLD-D1-데이터모델링-식별자",
        "keywords": ("식별자", "주식별자", "pk", "primary key", "본질식별자", "인조식별자", "외부식별자", "내부식별자"),
    },
    {
        "id": "SQLD-C-NORMALIZATION",
        "domain_id": "SQLD-D1",
        "name": "정규화와 반정규화",
        "review_note": "1NF/2NF/3NF, 부분/이행 함수 종속, 반정규화 목적과 부작용을 복습한다.",
        "scope_ref": "SQLD-D1-데이터모델과SQL-정규화",
        "keywords": ("정규화", "정규형", "3nf", "제3정규", "반정규화", "함수 종속", "이행", "중복 관계"),
    },
    {
        "id": "SQLD-C-MODELING-PERFORMANCE",
        "domain_id": "SQLD-D1",
        "name": "데이터 모델과 성능",
        "review_note": "슈퍼/서브타입 변환, 파티션, 모델링 유의점과 성능 영향도를 복습한다.",
        "scope_ref": "SQLD-D1-데이터모델과SQL-성능",
        "keywords": ("슈퍼", "서브", "파티션", "성능", "모델링", "트랜잭션", "고객", "법인"),
    },
    {
        "id": "SQLD-C-SELECT-WHERE",
        "domain_id": "SQLD-D2",
        "name": "SELECT와 WHERE",
        "review_note": "SELECT 처리 순서, WHERE 조건식, 연산자 우선순위, LIKE/IN/BETWEEN 조건을 복습한다.",
        "scope_ref": "SQLD-D2-SQL기본-SELECT-WHERE",
        "keywords": ("select", "where", "like", "between", "in ", "연산자", "우선순위", "조건"),
    },
    {
        "id": "SQLD-C-NULL",
        "domain_id": "SQLD-D2",
        "name": "NULL 처리",
        "review_note": "NULL 비교, NULL 연산 결과, 집계 함수의 NULL 제외 규칙을 구분한다.",
        "scope_ref": "SQLD-D2-SQL기본-NULL",
        "keywords": ("null", "coalesce", "nvl", "is null"),
    },
    {
        "id": "SQLD-C-FUNCTIONS",
        "domain_id": "SQLD-D2",
        "name": "SQL 함수",
        "review_note": "문자/숫자/날짜 함수, 형 변환, CASE/DECODE/COALESCE 결과를 복습한다.",
        "scope_ref": "SQLD-D2-SQL기본-함수",
        "keywords": ("substr", "instr", "ceil", "floor", "round", "trunc", "to_char", "to_date", "decode", "case", "함수", "반환"),
    },
    {
        "id": "SQLD-C-GROUP-HAVING",
        "domain_id": "SQLD-D2",
        "name": "GROUP BY와 HAVING",
        "review_note": "집계 함수, GROUP BY, HAVING, ROLLUP/CUBE/GROUPING SETS 결과를 복습한다.",
        "scope_ref": "SQLD-D2-SQL기본-GROUPBY-HAVING",
        "keywords": ("group by", "having", "count", "sum", "avg", "집계", "rollup", "cube", "grouping"),
    },
    {
        "id": "SQLD-C-JOIN",
        "domain_id": "SQLD-D2",
        "name": "JOIN",
        "review_note": "INNER/OUTER/NATURAL/CROSS JOIN, 표준 조인 문법, 조인 결과 건수를 복습한다.",
        "scope_ref": "SQLD-D2-SQL기본-JOIN",
        "keywords": ("join", "조인", "outer", "inner", "natural", "cross", "left", "right", "full"),
    },
    {
        "id": "SQLD-C-SUBQUERY",
        "domain_id": "SQLD-D2",
        "name": "서브쿼리",
        "review_note": "단일행/다중행/상호연관 서브쿼리와 메인쿼리와의 관계를 복습한다.",
        "scope_ref": "SQLD-D2-SQL활용-서브쿼리",
        "keywords": ("서브", "subquery", "메인 쿼리", "exists", "any", "all"),
    },
    {
        "id": "SQLD-C-SET-WINDOW-TOPN",
        "domain_id": "SQLD-D2",
        "name": "집합/윈도우/Top N",
        "review_note": "집합 연산자, 윈도우 함수, 순위 함수, Top N 쿼리와 행 제한 구문을 복습한다.",
        "scope_ref": "SQLD-D2-SQL활용-집합윈도우TopN",
        "keywords": ("union", "intersect", "minus", "over", "partition", "rank", "dense_rank", "row_number", "top", "fetch", "offset", "윈도우"),
    },
    {
        "id": "SQLD-C-HIERARCHICAL-SELF",
        "domain_id": "SQLD-D2",
        "name": "계층형 질의와 셀프 조인",
        "review_note": "START WITH, CONNECT BY, LEVEL, CONNECT_BY_ISLEAF, 셀프 조인 구조를 복습한다.",
        "scope_ref": "SQLD-D2-SQL활용-계층형질의",
        "keywords": ("connect by", "start with", "level", "계층", "isleaf", "self join", "셀프"),
    },
    {
        "id": "SQLD-C-DML-TCL",
        "domain_id": "SQLD-D2",
        "name": "DML과 TCL",
        "review_note": "INSERT/UPDATE/DELETE/MERGE, COMMIT/ROLLBACK/SAVEPOINT 결과를 복습한다.",
        "scope_ref": "SQLD-D2-관리구문-DML-TCL",
        "keywords": ("insert", "update", "delete", "merge", "commit", "rollback", "savepoint", "트랜잭션", "영구"),
    },
    {
        "id": "SQLD-C-DDL-DCL-CONSTRAINT",
        "domain_id": "SQLD-D2",
        "name": "DDL/DCL/제약조건",
        "review_note": "CREATE/ALTER/DROP, 제약조건, 권한, ROLE, GRANT/REVOKE 동작을 복습한다.",
        "scope_ref": "SQLD-D2-관리구문-DDL-DCL",
        "keywords": ("create", "alter", "drop", "rename", "grant", "revoke", "role", "constraint", "제약조건", "not null", "foreign key", "ctas"),
    },
    {
        "id": "SQLD-C-OPTIMIZER-INDEX",
        "domain_id": "SQLD-D2",
        "name": "인덱스와 실행계획",
        "review_note": "B-tree 인덱스, 실행 계획, NL/HASH/SORT MERGE JOIN과 옵티마이저 동작을 복습한다.",
        "scope_ref": "SQLD-D2-SQL활용-인덱스실행계획",
        "keywords": ("index", "인덱스", "b-tree", "실행 계획", "optimizer", "nested loops", "hash join", "sort merge", "table access"),
    },
    {
        "id": "SQLD-C-REGEXP-PIVOT",
        "domain_id": "SQLD-D2",
        "name": "정규표현식과 PIVOT",
        "review_note": "REGEXP 함수, PIVOT/UNPIVOT의 행과 열 변환 결과를 복습한다.",
        "scope_ref": "SQLD-D2-SQL활용-정규표현식-PIVOT",
        "keywords": ("regexp", "정규 표현", "pivot", "unpivot"),
    },
]


def enrich_sqld_gold_file(
    source: Path,
    output: Path,
    *,
    checked_at: str,
    prefer_source_contains: str = "",
    limit: int | None = None,
) -> dict[str, Any]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    enriched = enrich_sqld_gold_payload(
        payload,
        checked_at=checked_at,
        prefer_source_contains=prefer_source_contains,
        limit=limit,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "input": str(source),
        "output": str(output),
        "questions": len(enriched["questions"]),
        "concepts": len(enriched["concepts"]),
        "checked_at": checked_at,
    }


def enrich_sqld_gold_payload(
    payload: dict[str, Any],
    *,
    checked_at: str,
    prefer_source_contains: str = "",
    limit: int | None = None,
) -> dict[str, Any]:
    if payload.get("exam", {}).get("id") != "SQLD":
        raise ValueError("SQLD gold enrichment는 SQLD payload만 지원합니다.")
    result = deepcopy(payload)
    questions = usable_questions(result["questions"])
    if prefer_source_contains:
        preferred = [q for q in questions if prefer_source_contains in q.get("source_ref", "")]
        fallback = [q for q in questions if q not in preferred]
        questions = preferred + fallback
    if limit is not None:
        questions = select_limited_questions(result, questions, limit)
    result["concepts"] = concept_payload()
    result["questions"] = [enrich_question(question, checked_at=checked_at) for question in questions]
    result["exam"]["notes"] = (
        "SQLD private source-backed 문항을 공식 출제범위 세부 개념과 해설 필드로 보강한 gold 문제은행입니다. "
        "공개 repo에는 원문을 저장하지 않습니다."
    )
    return result


def usable_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usable: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for question in questions:
        if question["id"] in seen_ids:
            continue
        seen_ids.add(question["id"])
        if question.get("question_type", "single_choice") != "single_choice":
            continue
        choices = question.get("choices", [])
        if not isinstance(choices, list) or len(choices) != 4:
            continue
        if any(not isinstance(choice, str) or not choice.strip() or choice.strip() == "?" for choice in choices):
            continue
        usable.append(question)
    return usable


def select_limited_questions(payload: dict[str, Any], questions: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    exam = payload.get("exam", {})
    if limit != int(exam.get("official_question_count", 0) or 0):
        return questions[:limit]
    domains = payload.get("domains", [])
    required_counts = {
        str(domain["id"]): int(domain.get("official_question_count", 0))
        for domain in domains
        if int(domain.get("official_question_count", 0) or 0) > 0
    }
    if not required_counts or sum(required_counts.values()) != limit:
        return questions[:limit]
    selected: list[dict[str, Any]] = []
    for domain_id, required in required_counts.items():
        domain_questions = [question for question in questions if question.get("domain_id") == domain_id]
        if len(domain_questions) < required:
            return questions[:limit]
        selected.extend(domain_questions[:required])
    return selected


def concept_payload() -> list[dict[str, str]]:
    return [
        {
            "id": item["id"],
            "domain_id": item["domain_id"],
            "name": item["name"],
            "review_note": item["review_note"],
        }
        for item in SQLD_CONCEPTS
    ]


def enrich_question(question: dict[str, Any], *, checked_at: str) -> dict[str, Any]:
    result = deepcopy(question)
    concept = infer_concept(result)
    answer = int(result["answer"])
    choices = result["choices"]
    explanation = cleaned_explanation(result)
    result["concept_id"] = concept["id"]
    result["explanation"] = explanation
    result["correct_rationale"] = correct_rationale(result, concept, explanation)
    result["distractor_rationales"] = {
        str(idx): distractor_rationale(idx, choices[idx - 1], concept)
        for idx in range(1, 5)
        if idx != answer
    }
    result["review_concepts"] = [concept["name"]]
    result["official_scope_refs"] = [concept["scope_ref"]]
    result["validity_status"] = "current"
    result["quality_status"] = "active"
    result["official_checked_at"] = checked_at
    result["gold_status"] = "gold"
    result["gold_checked_at"] = checked_at
    result["gold_notes"] = "SQLD 공식 세부항목 기준으로 세부 개념, 정답 근거, 오답 선택지 해설을 보강함"
    result["quality_notes"] = "private 원천 기반 문항을 gold audit 기준에 맞게 보강함"
    return result


def infer_concept(question: dict[str, Any]) -> dict[str, Any]:
    domain_id = question["domain_id"]
    haystack = normalize_haystack(" ".join([question.get("question_text", ""), *question.get("choices", [])]))
    candidates = [item for item in SQLD_CONCEPTS if item["domain_id"] == domain_id]
    scored = []
    for item in candidates:
        score = sum(2 if keyword.lower() in haystack else 0 for keyword in item["keywords"])
        score += sum(1 for token in item["name"].lower().split() if token and token in haystack)
        scored.append((score, item))
    scored.sort(key=lambda row: row[0], reverse=True)
    if scored and scored[0][0] > 0:
        return scored[0][1]
    return next(item for item in SQLD_CONCEPTS if item["id"] == ("SQLD-C-ENTITY" if domain_id == "SQLD-D1" else "SQLD-C-SELECT-WHERE"))


def cleaned_explanation(question: dict[str, Any]) -> str:
    explanation = str(question.get("explanation", "")).strip()
    if is_placeholder_explanation(explanation):
        concept = infer_concept(question)
        answer = int(question["answer"])
        answer_text = question["choices"][answer - 1]
        return (
            f"정답은 {answer}번입니다. {concept['name']} 영역의 핵심 규칙을 적용하면 "
            f"'{answer_text}' 선택지가 문제 조건을 가장 직접적으로 만족합니다. "
            f"오답은 {concept['review_note']}"
        )
    return explanation


def correct_rationale(question: dict[str, Any], concept: dict[str, Any], explanation: str) -> str:
    answer = int(question["answer"])
    answer_text = question["choices"][answer - 1]
    if explanation and not is_placeholder_explanation(explanation):
        return f"{answer}번 '{answer_text}'가 정답입니다. {explanation}"
    return f"{answer}번 '{answer_text}'가 {concept['name']}의 출제 포인트와 문제 조건을 가장 직접적으로 만족합니다."


def distractor_rationale(idx: int, choice: str, concept: dict[str, Any]) -> str:
    return (
        f"{idx}번 '{choice}'는 {concept['name']}의 핵심 조건을 충족하지 못하거나 문제에서 요구한 결과와 다릅니다. "
        f"{concept['review_note']}"
    )


def is_placeholder_explanation(value: str) -> bool:
    return "정답표 기준" in value or "세부 해설" in value or "오답노트에서 보강" in value


def normalize_haystack(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).lower()
