from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .gcp_gail import SECTION_META


QUESTION_HEADING_RE = re.compile(
    r"^(?P<prefix>Google Generative AI Leader Question|AI Leader Exam Question)\s+(?P<number>\d+)\s*$",
    re.I,
)
CHOICE_RE = re.compile(r"^[❏✓]\s*(?P<label>[A-D])\.\s*(?P<text>.+)$")
ANSWER_SECTION_MARKERS = (
    "Generative AI Leader Questions and Answers",
    "Certification Practice Exam Questions Answered",
)


@dataclass(frozen=True)
class HtmlQuestionStem:
    number: int
    heading: str
    question_text: str
    choices: dict[str, str]


@dataclass(frozen=True)
class HtmlAnswerBlock:
    number: int
    answer_label: str
    explanation: str


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
            return
        if tag in {"h1", "h2", "h3", "h4", "p", "li", "br", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if tag in {"h1", "h2", "h3", "h4", "p", "li", "div"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        normalized = normalize_spaces(data)
        if normalized:
            self.parts.append(normalized)

    def text(self) -> str:
        raw = " ".join(self.parts)
        lines = [normalize_spaces(line) for line in raw.split("\n")]
        return "\n".join(line for line in lines if line)


def inspect_gcp_gail_html_sources(source: Path) -> dict[str, Any]:
    files = html_files(source)
    rows = []
    total_candidates = 0
    total_convertible = 0
    for path in files:
        parsed = parse_gcp_gail_html_file(path)
        rows.append(
            {
                "path": str(path),
                "source_ref": parsed["source_ref"],
                "candidate_questions": parsed["candidate_questions"],
                "convertible_questions": len(parsed["questions"]),
                "skipped": parsed["skipped"],
            }
        )
        total_candidates += int(parsed["candidate_questions"])
        total_convertible += len(parsed["questions"])
    return {
        "source": str(source),
        "files": rows,
        "candidate_questions": total_candidates,
        "convertible_questions": total_convertible,
    }


def convert_gcp_gail_html_sources(
    source: Path,
    output: Path,
    *,
    mark_active: bool,
    checked_at: str,
    min_questions: int = 1,
) -> dict[str, Any]:
    files = html_files(source)
    converted_questions: list[dict[str, Any]] = []
    concepts: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    file_rows = []

    for path in files:
        parsed = parse_gcp_gail_html_file(path)
        accepted = 0
        skipped_duplicates = 0
        for question in parsed["questions"]:
            fingerprint = question_fingerprint(question["question_text"])
            if fingerprint in seen:
                skipped_duplicates += 1
                continue
            seen.add(fingerprint)
            concept_name = infer_concept_name(question)
            prepared = build_question_payload(
                question,
                concept_name=concept_name,
                source_slug=source_slug(path, parsed["source_ref"]),
                source_ref=parsed["source_ref"],
                local_path=str(path),
                mark_active=mark_active,
                checked_at=checked_at,
            )
            concept = concept_payload(prepared["concept_id"], prepared["domain_id"], concept_name)
            concepts[concept["id"]] = concept
            converted_questions.append(prepared)
            accepted += 1
        file_rows.append(
            {
                "path": str(path),
                "source_ref": parsed["source_ref"],
                "candidate_questions": parsed["candidate_questions"],
                "converted_questions": accepted,
                "skipped_duplicates": skipped_duplicates,
                "skipped": parsed["skipped"],
            }
        )

    if len(converted_questions) < min_questions:
        raise ValueError(f"변환 문항이 최소 기준보다 적습니다: {len(converted_questions)}/{min_questions}")

    payload = {
        "exam": {
            "id": "GCP_GENERATIVE_AI_LEADER",
            "name": "Google Cloud Generative AI Leader",
            "official_question_count": 50,
            "official_duration_minutes": 90,
            "pass_score": 70,
            "domain_min_score": 0,
            "notes": "공개 웹 연습문항을 로컬 private_banks 전용으로 변환한 GAIL 학습 문제은행입니다.",
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
        "concepts": sorted(concepts.values(), key=lambda item: item["id"]),
        "questions": converted_questions,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "source": str(source),
        "output": str(output),
        "files": file_rows,
        "questions": len(converted_questions),
        "concepts": len(concepts),
        "mark_active": mark_active,
        "checked_at": checked_at,
    }


def parse_gcp_gail_html_file(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = visible_text(raw)
    source_ref = canonical_url(raw) or path.name
    answer_start = answer_section_start(text)
    if answer_start == -1:
        return {
            "source_ref": source_ref,
            "candidate_questions": 0,
            "questions": [],
            "skipped": [{"reason": "answer_section_not_found"}],
        }

    stem_text = text[:answer_start]
    answer_text = text[answer_start:]
    stems = parse_stems(stem_text)
    answers = parse_answers(answer_text)
    questions = []
    skipped = []
    for number, stem in sorted(stems.items()):
        answer = answers.get(number)
        if answer is None:
            skipped.append({"number": number, "reason": "answer_not_found"})
            continue
        if sorted(stem.choices) != ["A", "B", "C", "D"]:
            skipped.append({"number": number, "reason": "choices_not_four"})
            continue
        if answer.answer_label not in stem.choices:
            skipped.append({"number": number, "reason": "answer_choice_missing"})
            continue
        questions.append(
            {
                "number": number,
                "heading": stem.heading,
                "question_text": stem.question_text,
                "choices": [stem.choices[label] for label in ["A", "B", "C", "D"]],
                "answer": ord(answer.answer_label) - ord("A") + 1,
                "explanation": answer.explanation,
            }
        )
    return {
        "source_ref": source_ref,
        "candidate_questions": len(stems),
        "questions": questions,
        "skipped": skipped,
    }


def parse_stems(text: str) -> dict[int, HtmlQuestionStem]:
    result: dict[int, HtmlQuestionStem] = {}
    for heading, lines in question_blocks(text):
        match = QUESTION_HEADING_RE.match(heading)
        if not match:
            continue
        number = int(match.group("number"))
        question_parts: list[str] = []
        choices: dict[str, str] = {}
        current_choice: str | None = None
        for line in lines:
            choice_match = CHOICE_RE.match(line)
            if choice_match:
                current_choice = choice_match.group("label").upper()
                choices[current_choice] = clean_text(choice_match.group("text"))
                continue
            if current_choice and len(choices) < 4:
                choices[current_choice] = clean_text(f"{choices[current_choice]} {line}")
                continue
            if not choices:
                question_parts.append(line)
        question_text = clean_text(" ".join(question_parts))
        if question_text and choices:
            result[number] = HtmlQuestionStem(
                number=number,
                heading=heading,
                question_text=question_text,
                choices=choices,
            )
    return result


def parse_answers(text: str) -> dict[int, HtmlAnswerBlock]:
    result: dict[int, HtmlAnswerBlock] = {}
    for heading, lines in question_blocks(text):
        match = QUESTION_HEADING_RE.match(heading)
        if not match:
            continue
        number = int(match.group("number"))
        answer_label = ""
        explanation_parts: list[str] = []
        found_answer = False
        for line in lines:
            choice_match = CHOICE_RE.match(line)
            if choice_match and line.startswith("✓"):
                answer_label = choice_match.group("label").upper()
                found_answer = True
                continue
            if found_answer:
                explanation_parts.append(line)
        explanation = clean_explanation(" ".join(explanation_parts))
        if answer_label and explanation:
            result[number] = HtmlAnswerBlock(
                number=number,
                answer_label=answer_label,
                explanation=explanation,
            )
    return result


def question_blocks(text: str) -> list[tuple[str, list[str]]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    result: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_lines: list[str] = []
    for line in lines:
        if QUESTION_HEADING_RE.match(line):
            if current_heading:
                result.append((current_heading, current_lines))
            current_heading = line
            current_lines = []
            continue
        if current_heading:
            current_lines.append(line)
    if current_heading:
        result.append((current_heading, current_lines))
    return result


def build_question_payload(
    question: dict[str, Any],
    *,
    concept_name: str,
    source_slug: str,
    source_ref: str,
    local_path: str,
    mark_active: bool,
    checked_at: str,
) -> dict[str, Any]:
    domain_id = infer_domain_id(question)
    concept_id = f"{domain_id}-C-{slug(concept_name)}"
    answer = int(question["answer"])
    question_hash = source_hash(f"{source_ref}:{question['number']}:{question['question_text']}")
    return {
        "id": f"GCP_GAIL_TSS_{source_slug}_{int(question['number']):03d}_{question_hash}",
        "domain_id": domain_id,
        "concept_id": concept_id,
        "question_type": "single_choice",
        "question_text": question["question_text"],
        "choices": question["choices"],
        "answer": answer,
        "answer_json": {"choices": [answer]},
        "explanation": question["explanation"],
        "difficulty": "medium",
        "source_type": "licensed_private",
        "source_ref": source_ref,
        "source_license": "private-study-use",
        "source_tier": "licensed_private",
        "storage_policy": "private_only",
        "validity_status": "current" if mark_active else "needs_official_check",
        "quality_status": "active" if mark_active else "needs_review",
        "scope_version": "GAIL-2025-05-14",
        "official_checked_at": checked_at if mark_active else "",
        "quality_notes": "공개 웹 연습문항을 private_banks 전용으로 변환했습니다. 원문은 공개 repo에 저장하지 않습니다.",
        "provenance": {
            "source_ref": source_ref,
            "local_path": local_path,
            "question_number": question["number"],
            "heading": question["heading"],
            "notice": "로컬 private_banks 안에서만 보관하는 개인 학습용 변환본입니다.",
        },
    }


def concept_payload(concept_id: str, domain_id: str, name: str) -> dict[str, str]:
    return {
        "id": concept_id,
        "domain_id": domain_id,
        "name": name,
        "review_note": f"{name} 개념을 Google Cloud Generative AI Leader 공식 가이드 기준으로 복습한다.",
    }


def infer_domain_id(question: dict[str, Any]) -> str:
    text = haystack(question)
    if d1_forced_match(text):
        return "GCP-GAIL-D1"
    if d2_forced_match(text):
        return "GCP-GAIL-D2"
    if d4_forced_match(text):
        return "GCP-GAIL-D4"
    scores = {
        "GCP-GAIL-D1": score(
            text,
            "machine learning",
            "supervised",
            "unsupervised",
            "reinforcement",
            "foundation model",
            "diffusion",
            "structured data",
            "unstructured data",
            "labeled",
            "unlabeled",
            "data quality",
            "gemma",
            "imagen",
            "veo",
            "multimodal",
            "model layer",
        ),
        "GCP-GAIL-D2": score(
            text,
            "vertex ai",
            "agent builder",
            "agent platform",
            "gemini for google workspace",
            "gemini enterprise",
            "model garden",
            "google ai studio",
            "bigquery",
            "gemini code assist",
            "conversational agents",
            "agent assist",
            "conversational insights",
            "document ai",
            "cloud vision",
            "speech-to-text",
            "text-to-speech",
        ),
        "GCP-GAIL-D3": score(
            text,
            "prompt",
            "few shot",
            "zero shot",
            "chain-of-thought",
            "react",
            "grounding",
            "rag",
            "hallucination",
            "temperature",
            "top k",
            "top-p",
            "safety settings",
            "output length",
            "knowledge cutoff",
            "retrieval",
        ),
        "GCP-GAIL-D4": score(
            text,
            "responsible ai",
            "fairness",
            "bias",
            "privacy",
            "explainable",
            "transparency",
            "accountability",
            "saif",
            "secure ai",
            "security command center",
            "governance",
            "stakeholder",
            "business requirement",
            "measure the impact",
            "roi",
            "malicious",
            "misuse",
        ),
    }
    priority = ["GCP-GAIL-D4", "GCP-GAIL-D3", "GCP-GAIL-D2", "GCP-GAIL-D1"]
    return max(priority, key=lambda domain_id: (scores[domain_id], -priority.index(domain_id)))


def d1_forced_match(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "primary use of generative ai",
            "automated code synthesis",
            "image generation",
            "video generation",
            "diffusion model",
            "which foundation model",
            "google foundation model",
            "generative model most likely",
            "structured data",
            "unstructured data",
            "relational database",
            "data lake",
            "data warehouse",
            "data format",
            "natural groupings",
            "there are no existing labels",
            "on device deployment",
            "offline operation",
            "model layer",
            "restricted to models they can deploy",
        )
    )


def d2_forced_match(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "gemini for workspace",
            "gemini for google workspace",
            "vertex ai model garden",
            "model garden",
            "gemini in bigquery",
            "conversational insights",
            "agent assist",
            "conversational agents",
            "vertex ai agent builder",
            "build a production ready generative ai agent",
            "external tool the agent calls",
            "google ai studio",
            "vertex ai studio",
        )
    )


def d4_forced_match(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "responsible ai",
            "fairness assessment",
            "systemic bias",
            "transparency",
            "accountability",
            "privacy risk",
            "secure ai framework",
            "saif",
            "high value claims",
            "audit",
            "governance",
        )
    )


def infer_concept_name(question: dict[str, Any]) -> str:
    text = haystack(question)
    concept_checks = [
        ("Responsible AI, fairness, and transparency", ("responsible ai", "fairness", "bias", "transparency", "explainable")),
        ("Secure AI and SAIF", ("saif", "secure ai", "security command center", "malicious", "misuse")),
        ("Grounding and RAG", ("grounding", "rag", "retrieval", "knowledge base")),
        ("Prompt engineering techniques", ("prompt", "few shot", "zero shot", "chain-of-thought", "react")),
        ("Sampling and safety settings", ("temperature", "top k", "top-p", "safety settings", "output length")),
        ("Google Cloud gen AI offerings", ("vertex ai", "agent builder", "agent platform", "model garden", "google ai studio")),
        ("Gemini and Workspace AI", ("gemini for google workspace", "workspace", "gemini app", "gemini enterprise")),
        ("Customer engagement AI", ("conversational agents", "agent assist", "conversational insights", "contact center")),
        ("Machine learning approaches", ("supervised", "unsupervised", "reinforcement")),
        ("Foundation model types", ("foundation model", "diffusion", "multimodal", "imagen", "veo", "gemma")),
        ("Data types and quality", ("structured data", "unstructured data", "labeled", "unlabeled", "data quality")),
    ]
    for name, keywords in concept_checks:
        if any(keyword in text for keyword in keywords):
            return name
    domain_id = infer_domain_id(question)
    domain_name = next(meta["name"] for meta in SECTION_META.values() if meta["id"] == domain_id)
    return domain_name


def score(text: str, *keywords: str) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def haystack(question: dict[str, Any]) -> str:
    return normalize_spaces(
        " ".join(
            [
                str(question.get("question_text", "")),
                *[str(choice) for choice in question.get("choices", [])],
                str(question.get("explanation", "")),
            ]
        )
    ).lower()


def html_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(path for path in source.rglob("*") if path.suffix.lower() in {".html", ".htm"})


def visible_text(raw: str) -> str:
    parser = VisibleTextParser()
    parser.feed(raw)
    return parser.text()


def canonical_url(raw: str) -> str:
    patterns = (
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, raw, re.I)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def answer_section_start(text: str) -> int:
    positions = [text.find(marker) for marker in ANSWER_SECTION_MARKERS if text.find(marker) != -1]
    return min(positions) if positions else -1


def clean_explanation(value: str) -> str:
    value = re.sub(r"\bAll exam questions come from .+?certificationexams\.pro\b", " ", value)
    value = re.sub(r"\bCameron’s Certification Exam Tip\b", " 시험 팁: ", value)
    value = re.sub(r"\bCameron's Certification Exam Tip\b", " 시험 팁: ", value)
    return clean_text(value)


def clean_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\ufffd", "'")
    return normalize_spaces(value)


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def question_fingerprint(value: str) -> str:
    return normalize_spaces(value).lower()


def source_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def source_slug(path: Path, source_ref: str) -> str:
    base = source_ref.rstrip("/").split("/")[-1] or path.stem
    return slug(base)[:36] or "source"


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def render_gcp_gail_html_inspect_report(report: dict[str, Any]) -> str:
    lines = [
        "# GCP GAIL private HTML 원천 점검",
        "",
        f"- 원천: {report['source']}",
        f"- 후보 문항: {report['candidate_questions']}개",
        f"- 변환 가능 문항: {report['convertible_questions']}개",
        "",
        "## 파일별",
    ]
    for row in report["files"]:
        lines.append(
            f"- {row['path']}: 후보 {row['candidate_questions']}개, 변환 가능 {row['convertible_questions']}개, "
            f"제외 {len(row['skipped'])}개"
        )
    return "\n".join(lines)


def render_gcp_gail_html_convert_report(report: dict[str, Any]) -> str:
    lines = [
        "# GCP GAIL private HTML 변환",
        "",
        f"- 출력: {report['output']}",
        f"- 문항: {report['questions']}개",
        f"- 개념: {report['concepts']}개",
        f"- active/current 표시: {'예' if report['mark_active'] else '아니오'}",
        "",
        "## 파일별",
    ]
    for row in report["files"]:
        lines.append(
            f"- {row['path']}: 변환 {row['converted_questions']}개, 중복 제외 {row['skipped_duplicates']}개, "
            f"파싱 제외 {len(row['skipped'])}개"
        )
    return "\n".join(lines)
