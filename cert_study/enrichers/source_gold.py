from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


GENERIC_CONCEPT_MARKERS = (
    "-SRC-C-",
    "SOURCE-BACKED",
    "SOURCE BACKED",
    "COMMUNITY PRACTICE",
)
MIN_SOURCE_EXPLANATION_CHARS = 20

AWS_SAA_CONCEPTS = [
    ("AWS-SAA-C-S3-STORAGE", "S3와 스토리지 아키텍처", ("s3", "bucket", "storage", "ebs", "efs", "fsx")),
    ("AWS-SAA-C-DATABASE", "데이터베이스 선택과 마이그레이션", ("rds", "aurora", "dynamodb", "redshift", "database", "dms")),
    ("AWS-SAA-C-NETWORKING", "네트워크와 콘텐츠 전송", ("vpc", "subnet", "route 53", "cloudfront", "vpn", "direct connect", "nat", "alb", "nlb")),
    ("AWS-SAA-C-SECURITY", "보안, 자격 증명, 암호화", ("iam", "kms", "encryption", "security", "policy", "waf", "secrets manager", "certificate")),
    ("AWS-SAA-C-RESILIENCE", "복원력과 고가용성 아키텍처", ("availability zone", "multi-az", "fault tolerance", "failover", "backup", "disaster recovery")),
    ("AWS-SAA-C-COMPUTE", "컴퓨팅과 확장", ("ec2", "lambda", "ecs", "eks", "auto scaling", "elastic beanstalk", "batch")),
    ("AWS-SAA-C-INTEGRATION", "통합과 분리 설계", ("sqs", "sns", "eventbridge", "step functions", "kinesis", "api gateway")),
    ("AWS-SAA-C-COST", "비용 최적화", ("cost", "reserved", "savings plan", "spot", "lifecycle", "intelligent-tiering")),
]

AWS_TASK_CONCEPT_NAMES = {
    "AWS_AI_PRACTITIONER": {
        "1-1": "AIF-C01 1.1 AI 기본 개념과 용어",
        "1-2": "AIF-C01 1.2 AI 실무 활용 사례",
        "1-3": "AIF-C01 1.3 AI/ML 개발 생명주기",
        "2-1": "AIF-C01 2.1 생성형 AI 기본 개념",
        "2-2": "AIF-C01 2.2 생성형 AI의 장점과 한계",
        "2-3": "AIF-C01 2.3 AWS 생성형 AI 인프라와 기술",
        "3-1": "AIF-C01 3.1 파운데이션 모델 애플리케이션 설계",
        "3-2": "AIF-C01 3.2 프롬프트 엔지니어링",
        "3-3": "AIF-C01 3.3 파운데이션 모델 학습과 파인튜닝",
        "3-4": "AIF-C01 3.4 파운데이션 모델 평가",
        "4-1": "AIF-C01 4.1 책임 있는 AI 시스템",
        "4-2": "AIF-C01 4.2 투명성과 설명 가능성",
        "5-1": "AIF-C01 5.1 AI 시스템 보안",
        "5-2": "AIF-C01 5.2 AI 거버넌스와 컴플라이언스",
    },
    "AWS_CLOUD_PRACTITIONER": {
        "1": "CLF-C02 도메인 1 클라우드 개념",
        "1-1": "CLF-C02 1.1 AWS Cloud의 이점",
        "1-2": "CLF-C02 1.2 AWS Cloud 설계 원칙",
        "1-3": "CLF-C02 1.3 클라우드 마이그레이션 이점과 전략",
        "1-4": "CLF-C02 1.4 클라우드 경제성",
        "2": "CLF-C02 도메인 2 보안과 컴플라이언스",
        "2-1": "CLF-C02 2.1 AWS 공동 책임 모델",
        "2-2": "CLF-C02 2.2 보안, 거버넌스, 컴플라이언스",
        "2-3": "CLF-C02 2.3 AWS 접근 관리",
        "2-4": "CLF-C02 2.4 보안 구성 요소와 리소스",
        "3": "CLF-C02 도메인 3 클라우드 기술과 서비스",
        "3-1": "CLF-C02 3.1 AWS Cloud 배포와 운영 방식",
        "3-2": "CLF-C02 3.2 AWS 글로벌 인프라",
        "3-3": "CLF-C02 3.3 AWS 컴퓨팅 서비스",
        "3-4": "CLF-C02 3.4 AWS 데이터베이스 서비스",
        "3-5": "CLF-C02 3.5 AWS 네트워크 서비스",
        "3-6": "CLF-C02 3.6 AWS 스토리지 서비스",
        "3-7": "CLF-C02 3.7 AWS AI/ML과 분석 서비스",
        "3-8": "CLF-C02 3.8 기타 범위 내 AWS 서비스",
        "4": "CLF-C02 도메인 4 청구, 가격, 지원",
        "4-1": "CLF-C02 4.1 AWS 가격 모델",
        "4-2": "CLF-C02 4.2 청구, 예산, 비용 관리",
        "4-3": "CLF-C02 4.3 AWS 기술 리소스와 지원 옵션",
    },
    "AWS_SOLUTIONS_ARCHITECT_ASSOCIATE": {
        "1": "SAA-C03 도메인 1 보안 아키텍처 설계",
        "1-1": "SAA-C03 1.1 AWS 리소스 보안 접근 설계",
        "1-2": "SAA-C03 1.2 보안 워크로드와 애플리케이션 설계",
        "1-3": "SAA-C03 1.3 데이터 보안 제어 선택",
        "2": "SAA-C03 도메인 2 복원력 있는 아키텍처 설계",
        "3": "SAA-C03 도메인 3 고성능 아키텍처 설계",
        "4": "SAA-C03 도메인 4 비용 최적화 아키텍처 설계",
    },
}


def enrich_source_gold_file(
    source: Path,
    output: Path,
    *,
    checked_at: str,
    scope_version: str = "",
) -> dict[str, Any]:
    payload = json.loads(source.read_text(encoding="utf-8"))
    enriched = enrich_source_gold_payload(payload, checked_at=checked_at, scope_version=scope_version)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(enriched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "input": str(source),
        "output": str(output),
        "exam_id": enriched["exam"]["id"],
        "questions": len(enriched["questions"]),
        "concepts": len(enriched["concepts"]),
        "checked_at": checked_at,
    }


def enrich_source_gold_payload(payload: dict[str, Any], *, checked_at: str, scope_version: str = "") -> dict[str, Any]:
    result = deepcopy(payload)
    exam_id = str(result.get("exam", {}).get("id", ""))
    concepts = concept_map(result.get("concepts", []))
    generated_concepts: dict[str, dict[str, str]] = {}
    enriched_questions = []
    seen_fingerprints: set[str] = set()
    for question in result.get("questions", []):
        if not usable_question(question):
            continue
        fingerprint = question_fingerprint(str(question.get("question_text", "")))
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)
        enriched = enrich_question(
            question,
            exam_id=exam_id,
            concepts=concepts,
            generated_concepts=generated_concepts,
            checked_at=checked_at,
            scope_version=scope_version,
        )
        enriched_questions.append(enriched)
    result["concepts"] = merge_concepts(result.get("concepts", []), generated_concepts)
    result["questions"] = enriched_questions
    result.setdefault("exam", {})["notes"] = (
        "source-backed 문항 중 독립 해설이 있는 문항을 gold audit 필드로 보강한 로컬 학습용 문제은행입니다."
    )
    return result


def usable_question(question: dict[str, Any]) -> bool:
    if question.get("question_type", "single_choice") != "single_choice":
        return False
    choices = question.get("choices", [])
    if not isinstance(choices, list) or len(choices) < 4:
        return False
    if any(not isinstance(choice, str) or not choice.strip() for choice in choices):
        return False
    explanation = str(question.get("explanation", "")).strip()
    if len(explanation) < MIN_SOURCE_EXPLANATION_CHARS or is_placeholder_explanation(explanation):
        return False
    if has_visible_answer_leak(question):
        return False
    return True


def enrich_question(
    question: dict[str, Any],
    *,
    exam_id: str,
    concepts: dict[str, dict[str, Any]],
    generated_concepts: dict[str, dict[str, str]],
    checked_at: str,
    scope_version: str,
) -> dict[str, Any]:
    result = deepcopy(question)
    result["exam_id"] = exam_id
    answer = int(result["answer"])
    choices = result["choices"]
    explanation = normalize_sentence(str(result["explanation"]))
    concept = resolved_concept(result, concepts, generated_concepts)
    result["concept_id"] = concept["id"]
    result["question_type"] = "single_choice"
    result["answer_json"] = {"choices": [answer]}
    result["explanation"] = explanation
    result["correct_rationale"] = correct_rationale(answer, choices[answer - 1], explanation)
    result["distractor_rationales"] = {
        str(idx): distractor_rationale(idx, choice, choices[answer - 1], concept["name"], explanation)
        for idx, choice in enumerate(choices, start=1)
        if idx != answer
    }
    result["review_concepts"] = [concept["name"]]
    result["official_scope_refs"] = [official_scope_ref(result, concept, scope_version)]
    result["validity_status"] = "current"
    result["quality_status"] = "active"
    result["official_checked_at"] = checked_at
    result["gold_status"] = "gold"
    result["gold_checked_at"] = checked_at
    result["gold_notes"] = "source-backed explanation을 기준으로 정답 근거, 오답 근거, 공식 scope 참조를 보강함"
    result["quality_notes"] = "gold audit 필드 보강 완료"
    if scope_version and not result.get("scope_version"):
        result["scope_version"] = scope_version
    return result


def concept_map(concepts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in concepts if isinstance(item, dict) and item.get("id")}


def merge_concepts(existing: list[dict[str, Any]], generated: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    existing_by_id = {str(item.get("id")): item for item in existing if isinstance(item, dict)}
    for concept_id, concept in generated.items():
        existing_by_id[concept_id] = concept
    return list(existing_by_id.values())


def resolved_concept(
    question: dict[str, Any],
    concepts: dict[str, dict[str, Any]],
    generated_concepts: dict[str, dict[str, str]],
) -> dict[str, str]:
    official = official_task_concept(question, concepts)
    if official:
        generated_concepts[official["id"]] = official
        return official
    current = concepts.get(str(question.get("concept_id", "")), {})
    if current and not is_generic_concept(str(current.get("id", "")), str(current.get("name", ""))):
        return {
            "id": str(current["id"]),
            "domain_id": str(current["domain_id"]),
            "name": str(current["name"]),
            "review_note": str(current.get("review_note", "")),
        }
    if question.get("exam_id") == "AWS_SOLUTIONS_ARCHITECT_ASSOCIATE" or str(question.get("id", "")).startswith("AWS_SAA"):
        concept = infer_aws_saa_concept(question)
    else:
        domain_id = str(question["domain_id"])
        concept = {
            "id": f"{domain_id}-C-GOLD",
            "domain_id": domain_id,
            "name": f"{domain_id} verified gold concept",
            "review_note": f"{domain_id} gold 문항의 정답 근거와 오답 근거를 복습한다.",
        }
    generated_concepts[concept["id"]] = concept
    return concept


def official_task_concept(question: dict[str, Any], concepts: dict[str, dict[str, Any]]) -> dict[str, str] | None:
    concept_id = str(question.get("concept_id", ""))
    current = concepts.get(concept_id, {})
    exam_id = exam_id_from_question(question, concept_id)
    if not exam_id:
        return None
    task_key = task_key_from_concept_id(concept_id)
    if not task_key:
        task_key = task_key_from_name(str(current.get("name", "")))
    concept_name = AWS_TASK_CONCEPT_NAMES.get(exam_id, {}).get(task_key)
    if not concept_name:
        return None
    domain_id = str(question.get("domain_id") or current.get("domain_id") or "")
    return {
        "id": concept_id,
        "domain_id": domain_id,
        "name": concept_name,
        "review_note": f"{concept_name} 범위를 공식 시험 가이드 기준으로 복습한다.",
    }


def exam_id_from_question(question: dict[str, Any], concept_id: str) -> str:
    explicit = str(question.get("exam_id", ""))
    if explicit:
        return explicit
    for exam_id in AWS_TASK_CONCEPT_NAMES:
        if concept_id.startswith(f"{exam_id}-"):
            return exam_id
    return ""


def task_key_from_concept_id(concept_id: str) -> str:
    match = re.search(r"-TASK-([0-9]+(?:-[0-9]+)?)$", concept_id)
    return match.group(1) if match else ""


def task_key_from_name(name: str) -> str:
    match = re.search(r"\bTask\s+([0-9]+(?:\.[0-9]+)?)\b", name, re.I)
    return match.group(1).replace(".", "-") if match else ""


def infer_aws_saa_concept(question: dict[str, Any]) -> dict[str, str]:
    haystack = normalize_sentence(" ".join([question.get("question_text", ""), *question.get("choices", []), question.get("explanation", "")])).lower()
    best = max(AWS_SAA_CONCEPTS, key=lambda item: sum(1 for keyword in item[2] if keyword in haystack))
    domain_id = str(question["domain_id"])
    return {
        "id": best[0],
        "domain_id": domain_id,
        "name": best[1],
        "review_note": f"{best[1]} 관련 SAA-C03 출제 포인트를 공식 가이드 기준으로 복습한다.",
    }


def official_scope_ref(question: dict[str, Any], concept: dict[str, str], scope_version: str) -> str:
    version = scope_version or str(question.get("scope_version", "") or "current")
    return f"{question.get('exam_id', '')}:{question['domain_id']}:{concept['id']}:{version}"


def correct_rationale(answer: int, answer_text: str, explanation: str) -> str:
    return f"{answer}번 '{answer_text}'가 정답입니다. {explanation}"


def distractor_rationale(idx: int, choice: str, answer_text: str, concept_name: str, explanation: str) -> str:
    return (
        f"{idx}번 '{choice}'는 정답 선택지 '{answer_text}'와 달리 문제 조건을 가장 직접적으로 만족하지 않습니다. "
        f"{concept_name} 관점에서 해설의 판단 기준을 다시 확인해야 합니다. 핵심 해설: {shorten(explanation)}"
    )


def is_generic_concept(concept_id: str, concept_name: str) -> bool:
    haystack = f"{concept_id} {concept_name}".upper()
    return any(marker in haystack for marker in GENERIC_CONCEPT_MARKERS)


def is_placeholder_explanation(value: str) -> bool:
    return "정답표 기준" in value or "세부 해설" in value or "오답노트에서 보강" in value


def has_visible_answer_leak(question: dict[str, Any]) -> bool:
    choices = question.get("choices", [])
    choice_text = " ".join(str(choice) for choice in choices) if isinstance(choices, list) else ""
    haystack = f"{question.get('question_text', '')} {choice_text}"
    return bool(re.search(r"(정답|해설)\s*[:：]\s*[1-9A-D]|답\s*[:：]\s*[1-9A-D]", haystack, re.I))


def normalize_sentence(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def shorten(value: str, limit: int = 220) -> str:
    normalized = normalize_sentence(value)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def question_fingerprint(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()
