from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .info_processing import CIRCLED_TO_ANSWER
from .kdata_text import (
    concept_id_for_domain,
    concept_payload,
    domain_for_question_number,
    domain_payload,
    exam_payload,
    profile_for,
    source_hash,
)


BLOCK_TAGS = {
    "p",
    "div",
    "li",
    "td",
    "th",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "tr",
}
SKIP_TAGS = {"script", "style"}


@dataclass(frozen=True)
class HtmlBlock:
    text: str
    highlighted: bool = False


class StudyHtmlBlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[HtmlBlock] = []
        self.parts: list[str] = []
        self.highlight_depth = 0
        self.skip_depth = 0
        self.current_highlighted = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {key.lower(): value or "" for key, value in attrs}
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in BLOCK_TAGS:
            self.flush()
        style = attr_map.get("style", "").lower()
        if tag in {"b", "strong"} or "font-weight" in style and "bold" in style or is_answer_color_style(style):
            self.highlight_depth += 1
        if tag == "br":
            self.flush()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag in {"b", "strong"} and self.highlight_depth:
            self.highlight_depth -= 1
        if tag in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data: str) -> None:
        if self.skip_depth or not data.strip():
            return
        self.parts.append(data)
        if self.highlight_depth:
            self.current_highlighted = True

    def flush(self) -> None:
        text = normalize_space("".join(self.parts))
        if text:
            self.blocks.append(HtmlBlock(text=text, highlighted=self.current_highlighted))
        self.parts = []
        self.current_highlighted = False


def is_answer_color_style(style: str) -> bool:
    return "color" in style and any(token in style for token in ("ee2323", "e74c3c", "ff0000"))


def convert_adsp_html_sources(
    source: Path,
    output: Path,
    *,
    mark_active: bool = False,
    checked_at: str = "",
    min_questions: int = 1,
) -> dict[str, Any]:
    payload, report = build_adsp_html_payload(
        source,
        mark_active=mark_active,
        checked_at=checked_at,
        min_questions=min_questions,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output"] = str(output)
    return report


def inspect_adsp_html_sources(source: Path) -> dict[str, Any]:
    entries = read_html_entries(source)
    rows = []
    for entry in entries:
        questions = parse_adsp_html_questions(entry["raw_html"], entry["source_ref"])
        rows.append(
            {
                "path": entry["source_ref"],
                "chars": len(entry["raw_html"]),
                "convertible_questions": len(questions),
                "domains": domain_counts(questions),
            }
        )
    return {
        "exam_id": "ADSP",
        "source": str(source),
        "files": len(rows),
        "convertible_questions": sum(row["convertible_questions"] for row in rows),
        "items": rows,
    }


def build_adsp_html_payload(
    source: Path,
    *,
    mark_active: bool = False,
    checked_at: str = "",
    min_questions: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = profile_for("ADSP")
    entries = read_html_entries(source)
    questions: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "exam_id": profile.id,
        "source": str(source),
        "files": len(entries),
        "converted_files": 0,
        "converted_questions": 0,
        "skipped": [],
    }
    for entry in entries:
        parsed = parse_adsp_html_questions(
            entry["raw_html"],
            entry["source_ref"],
            mark_active=mark_active,
            checked_at=checked_at,
        )
        if len(parsed) < min_questions:
            report["skipped"].append(
                {
                    "path": entry["source_ref"],
                    "reason": f"품질 기준 미달: {len(parsed)}문항 변환, 최소 {min_questions}문항 필요",
                }
            )
            continue
        questions.extend(parsed)
        report["converted_files"] += 1
        report["converted_questions"] += len(parsed)

    payload = {
        "exam": exam_payload(profile),
        "domains": domain_payload(profile),
        "concepts": concept_payload(profile),
        "questions": questions,
    }
    return payload, report


def read_html_entries(source: Path) -> list[dict[str, str]]:
    if not source.exists():
        raise ValueError(f"경로가 없습니다: {source}")
    paths = [source] if source.is_file() else sorted(source.rglob("*.html")) + sorted(source.rglob("*.htm"))
    entries = []
    for path in paths:
        if path.suffix.lower() not in {".html", ".htm"}:
            continue
        entries.append({"source_ref": str(path), "raw_html": path.read_text(encoding="utf-8", errors="replace")})
    return entries


def parse_adsp_html_questions(
    raw_html: str,
    source_ref: str,
    *,
    mark_active: bool = False,
    checked_at: str = "",
) -> list[dict[str, Any]]:
    if has_split_question_answer_anchors(raw_html):
        parsed = parse_anchor_backed_questions(raw_html, source_ref)
    else:
        blocks = html_blocks(raw_html)
        if any(block.text.startswith("Q:") for block in blocks):
            parsed = parse_q_style_questions(blocks)
        else:
            parsed = parse_numbered_highlight_questions(blocks)
    return [
        question_payload(item, source_ref, mark_active=mark_active, checked_at=checked_at)
        for item in parsed
        if item["question_text"]
        and len(item["choices"]) == 4
        and all(item["choices"])
        and item["answer"]
        and len(item["explanation"]) >= 20
    ]


def has_split_question_answer_anchors(raw_html: str) -> bool:
    return bool(re.search(r"""<a\s+name=["']a1["']""", raw_html, re.I)) and bool(
        re.search(r"""<a\s+name=["']answer1["']""", raw_html, re.I)
    )


def html_blocks(raw_html: str) -> list[HtmlBlock]:
    parser = StudyHtmlBlockParser()
    parser.feed(raw_html)
    parser.flush()
    return parser.blocks


def parse_anchor_backed_questions(raw_html: str, source_ref: str) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    question_chunks = anchor_chunks(raw_html, "a", stop_anchor_prefix="answer")
    answer_chunks = anchor_chunks(raw_html, "answer")
    for number, chunk in question_chunks.items():
        answer_chunk = answer_chunks.get(number, "")
        parsed = parse_question_blocks(number, html_blocks(chunk))
        answer, explanation = parse_answer_and_explanation(answer_chunk)
        if answer:
            parsed["answer"] = answer
        if explanation:
            parsed["explanation"] = explanation
        parsed["source_parser"] = "anchor_backed"
        parsed["source_ref"] = source_ref
        questions.append(parsed)
    return questions


def anchor_chunks(raw_html: str, prefix: str, *, stop_anchor_prefix: str | None = None) -> dict[int, str]:
    pattern = re.compile(rf"""<a\s+name=["']{re.escape(prefix)}(\d+)["']\s*>\s*</a>""", re.I)
    matches = list(pattern.finditer(raw_html))
    chunks: dict[int, str] = {}
    for idx, match in enumerate(matches):
        number = int(match.group(1))
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_html)
        if stop_anchor_prefix:
            stop = re.search(rf"""<a\s+name=["']{re.escape(stop_anchor_prefix)}\d+["']""", raw_html[match.end() : end], re.I)
            if stop:
                end = match.end() + stop.start()
        chunks[number] = raw_html[match.start() : end]
    return chunks


def parse_answer_and_explanation(raw_html: str) -> tuple[int | None, str]:
    if not raw_html:
        return None, ""
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw_html))
    answer_match = re.search(r"정답\s*[:：]\s*([1-4①②③④])", normalize_space(text))
    answer = normalize_answer(answer_match.group(1)) if answer_match else None
    blocks = html_blocks(raw_html)
    explanation_parts: list[str] = []
    recording = False
    for block in blocks:
        text = clean_text(block.text)
        if not text:
            continue
        if re.search(r"정답\s*[:：]", text):
            continue
        if "문제확인" in text:
            continue
        if re.match(r"^해설\s*[:：]?", text):
            recording = True
            text = re.sub(r"^해설\s*[:：]?\s*", "", text).strip()
            if text:
                explanation_parts.append(text)
            continue
        if recording:
            if re.match(r"^\d{1,3}\.\s*정답", text):
                break
            explanation_parts.append(text)
    return answer, clean_explanation(" ".join(explanation_parts))


def parse_q_style_questions(blocks: list[HtmlBlock]) -> list[dict[str, Any]]:
    chunks: list[tuple[int, list[HtmlBlock]]] = []
    current: list[HtmlBlock] = []
    number = 0
    for block in blocks:
        if block.text.startswith("Q:"):
            if current:
                chunks.append((number, current))
            number += 1
            current = [block]
            continue
        if current:
            current.append(block)
    if current:
        chunks.append((number, current))
    questions = []
    for number, chunk in chunks:
        parsed = parse_question_blocks(number, chunk)
        parsed["source_parser"] = "q_style"
        questions.append(parsed)
    return questions


def parse_numbered_highlight_questions(blocks: list[HtmlBlock]) -> list[dict[str, Any]]:
    chunks: list[tuple[int, list[HtmlBlock]]] = []
    current_number: int | None = None
    current_blocks: list[HtmlBlock] = []
    for block in blocks:
        match = numbered_question_match(block.text)
        if match is not None:
            if current_number is not None:
                chunks.append((current_number, current_blocks))
            current_number = int(match.group(1))
            current_blocks = [HtmlBlock(match.group(2), block.highlighted)]
            continue
        if current_number is not None:
            current_blocks.append(block)
    if current_number is not None:
        chunks.append((current_number, current_blocks))

    questions = []
    for number, chunk in chunks:
        parsed = parse_question_blocks(number, chunk)
        parsed["source_parser"] = "numbered_highlight"
        questions.append(parsed)
    return questions


def numbered_question_match(text: str) -> re.Match[str] | None:
    match = re.match(r"^(?:문제\s*)?0?(\d{1,3})[.]\s+(.+)$", text)
    if match is None:
        return None
    number = int(match.group(1))
    if not 1 <= number <= 60:
        return None
    if re.match(r"^(정답|해설|풀이)", match.group(2)):
        return None
    return match


def parse_question_blocks(number: int, blocks: list[HtmlBlock]) -> dict[str, Any]:
    question_parts: list[str] = []
    choices: dict[int, list[str]] = {1: [], 2: [], 3: [], 4: []}
    answer: int | None = None
    explanation_parts: list[str] = []
    state = "prompt"

    for block in blocks:
        text = clean_text(block.text)
        if not text:
            continue
        if state in {"explain", "after_answer"} and numbered_question_match(text):
            break
        if text.startswith("Q:"):
            question_parts = [clean_text(re.sub(r"^Q:\s*", "", text))]
            state = "choices"
            continue
        answer_match = re.search(r"정답\s*[:：]?\s*([1-4①②③④])", text)
        if answer_match:
            answer = normalize_answer(answer_match.group(1))
            state = "after_answer"
            trailing = clean_explanation(text[answer_match.end() :])
            if trailing:
                explanation_parts.append(trailing)
            continue
        if re.match(r"^(해설|풀이)\s*[:：]?", text):
            state = "explain"
            trailing = clean_explanation(re.sub(r"^(해설|풀이)\s*[:：]?\s*", "", text))
            if trailing:
                explanation_parts.append(trailing)
            continue
        choice_matches = list(re.finditer(r"([①②③④]|[1-4]\))\s*", text))
        if choice_matches and state in {"prompt", "choices", "after_answer"}:
            before = clean_text(text[: choice_matches[0].start()])
            if before and not question_parts:
                question_parts.append(before)
            for idx, match in enumerate(choice_matches):
                choice_number = normalize_answer(match.group(1))
                if not 1 <= choice_number <= 4:
                    continue
                end = choice_matches[idx + 1].start() if idx + 1 < len(choice_matches) else len(text)
                content = clean_text(text[match.end() : end])
                if content:
                    choices[choice_number].append(content)
                if block.highlighted:
                    answer = choice_number
            state = "choices"
            continue
        if state == "prompt":
            question_parts.append(text)
        elif state == "choices" and all(choices[index] for index in range(1, 5)):
            state = "explain"
            explanation_parts.append(text)
        elif state in {"explain", "after_answer"}:
            if should_stop_explanation(text):
                break
            explanation_parts.append(text)

    return {
        "number": number,
        "question_text": clean_question(" ".join(question_parts)),
        "choices": [clean_choice(" ".join(choices[index])) for index in range(1, 5)],
        "answer": answer,
        "explanation": clean_explanation(" ".join(explanation_parts)),
    }


def normalize_answer(token: str) -> int:
    token = token.strip()
    if token in CIRCLED_TO_ANSWER:
        return CIRCLED_TO_ANSWER[token]
    return int(token[0])


def question_payload(
    item: dict[str, Any],
    source_ref: str,
    *,
    mark_active: bool,
    checked_at: str,
) -> dict[str, Any]:
    profile = profile_for("ADSP")
    number = int(item["number"])
    domain = domain_for_question_number(profile, number)
    slug = source_hash(f"{source_ref}:{item.get('source_parser', '')}")
    answer = int(item["answer"])
    return {
        "id": f"ADSP_HTML_{slug}_Q{number:03d}",
        "domain_id": domain.id,
        "concept_id": concept_id_for_domain(profile, domain.id),
        "question_type": "single_choice",
        "question_text": item["question_text"],
        "choices": item["choices"],
        "answer": answer,
        "answer_json": {"choices": [answer]},
        "explanation": item["explanation"],
        "difficulty": "medium",
        "source_type": "licensed_private",
        "source_ref": source_ref,
        "source_license": "private-study-use",
        "source_tier": "licensed_private",
        "storage_policy": "private_only",
        "validity_status": "current" if mark_active else "needs_official_check",
        "quality_status": "active" if mark_active else "needs_review",
        "scope_version": "2026",
        "official_checked_at": checked_at if mark_active else "",
        "quality_notes": "ADSP private HTML 원천에서 문항/정답/해설을 함께 변환했습니다.",
        "provenance": {
            "source_ref": source_ref,
            "question_number": number,
            "profile": profile.id,
            "parser": item.get("source_parser", "adsp_html"),
            "notice": "로컬 private_banks 안에서만 보관하는 개인 학습용 변환본입니다.",
        },
    }


def clean_question(text: str) -> str:
    cleaned = clean_text(text)
    cleaned = re.sub(r"^문제\s*\d{1,3}[.)]?\s*", "", cleaned)
    return cleaned


def clean_choice(text: str) -> str:
    return clean_text(text)


def clean_explanation(text: str) -> str:
    cleaned = clean_text(text)
    cleaned = re.sub(r"^(해설|풀이)\s*[:：]?\s*", "", cleaned)
    cleaned = split_stop_markers(cleaned)
    return cleaned


def clean_text(text: str) -> str:
    cleaned = html.unescape(text)
    cleaned = cleaned.replace("\xa0", " ")
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = cleaned.replace("📝", " ").replace("📖", " ").replace("🌼", " ")
    cleaned = re.sub(r"\s*정답\s*확인\s*", " ", cleaned)
    cleaned = re.sub(r"\s*문제\s*확인\s*", " ", cleaned)
    return normalize_space(cleaned)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def should_stop_explanation(text: str) -> bool:
    return any(marker in text for marker in ("구독하기", "저작자표시", "태그목록", "댓글", "카테고리의 다른 글"))


def split_stop_markers(text: str) -> str:
    for marker in ("공유하기", "게시글 관리", "구독하기", "저작자표시", "태그목록", "댓글", "카테고리의 다른 글"):
        if marker in text:
            text = text.split(marker, 1)[0]
    return normalize_space(text)


def domain_counts(questions: list[dict[str, Any]]) -> dict[str, int]:
    result = {"ADSP-D1": 0, "ADSP-D2": 0, "ADSP-D3": 0}
    profile = profile_for("ADSP")
    for question in questions:
        if question.get("domain_id"):
            domain_id = str(question["domain_id"])
        else:
            domain_id = domain_for_question_number(profile, int(question["number"])).id
        if domain_id in result:
            result[domain_id] += 1
    return result


def render_adsp_html_inspect_report(report: dict[str, Any]) -> str:
    lines = [
        "# ADSP private HTML 원천 점검",
        "",
        f"- 파일: {report['files']}개",
        f"- 변환 가능 문항: {report['convertible_questions']}개",
        "",
        "## 파일별 후보",
    ]
    for row in report["items"]:
        counts = ", ".join(f"{domain} {count}" for domain, count in row["domains"].items())
        lines.append(f"- {row['path']}: text {row['chars']} chars, questions {row['convertible_questions']} ({counts})")
    return "\n".join(lines)


def render_adsp_html_convert_report(report: dict[str, Any]) -> str:
    lines = [
        "# ADSP private HTML 원천 변환",
        "",
        f"- 파일: {report['files']}개",
        f"- 변환 파일: {report['converted_files']}개",
        f"- 변환 문항: {report['converted_questions']}개",
    ]
    if report.get("output"):
        lines.append(f"- 출력: {report['output']}")
    if report["skipped"]:
        lines.extend(["", "## 제외"])
        for row in report["skipped"]:
            lines.append(f"- {row['path']}: {row['reason']}")
    return "\n".join(lines)
