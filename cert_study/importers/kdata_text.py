from __future__ import annotations

import ast
import hashlib
import html
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .info_processing import CIRCLED_TO_ANSWER, parse_answer_table, parse_question_chunk


SUPPORTED_SUFFIXES = {".txt", ".md", ".html", ".htm", ".pdf"}


@dataclass(frozen=True)
class DomainProfile:
    id: str
    name: str
    official_weight: float
    official_question_count: int


@dataclass(frozen=True)
class ExamProfile:
    id: str
    name: str
    official_question_count: int
    official_duration_minutes: int
    pass_score: float
    domain_min_score: float
    notes: str
    domains: tuple[DomainProfile, ...]


EXAM_PROFILES = {
    "SQLD": ExamProfile(
        id="SQLD",
        name="SQLD",
        official_question_count=50,
        official_duration_minutes=90,
        pass_score=60.0,
        domain_min_score=40.0,
        notes="KDATA SQL 개발자 공식 시험 구조 기준의 private source-backed 문제은행입니다.",
        domains=(
            DomainProfile("SQLD-D1", "데이터 모델링의 이해", 20.0, 10),
            DomainProfile("SQLD-D2", "SQL 기본 및 활용", 80.0, 40),
        ),
    ),
    "ADSP": ExamProfile(
        id="ADSP",
        name="ADsP",
        official_question_count=50,
        official_duration_minutes=90,
        pass_score=60.0,
        domain_min_score=40.0,
        notes="KDATA 데이터분석 준전문가 공식 시험 구조 기준의 private source-backed 문제은행입니다.",
        domains=(
            DomainProfile("ADSP-D1", "데이터 이해", 20.0, 10),
            DomainProfile("ADSP-D2", "데이터 분석 기획", 20.0, 10),
            DomainProfile("ADSP-D3", "데이터 분석", 60.0, 30),
        ),
    ),
}


def convert_kdata_text_sources(
    source: Path,
    output: Path,
    *,
    exam_id: str,
    mark_active: bool = False,
    checked_at: str = "",
    min_questions: int = 1,
) -> dict[str, Any]:
    payload, report = build_kdata_text_payload(
        source,
        exam_id=exam_id,
        mark_active=mark_active,
        checked_at=checked_at,
        min_questions=min_questions,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output"] = str(output)
    return report


def build_kdata_text_payload(
    source: Path,
    *,
    exam_id: str,
    mark_active: bool = False,
    checked_at: str = "",
    min_questions: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = profile_for(exam_id)
    entries = read_source_entries(source)
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
        parsed_questions = parse_kdata_text_questions(
            entry["text"],
            profile=profile,
            source_ref=entry["source_ref"],
            mark_active=mark_active,
            checked_at=checked_at,
        )
        if len(parsed_questions) < min_questions:
            report["skipped"].append(
                {
                    "path": entry["source_ref"],
                    "reason": f"품질 기준 미달: {len(parsed_questions)}문항 변환, 최소 {min_questions}문항 필요",
                }
            )
            continue
        questions.extend(parsed_questions)
        report["converted_files"] += 1
        report["converted_questions"] += len(parsed_questions)

    payload = {
        "exam": exam_payload(profile),
        "domains": domain_payload(profile),
        "concepts": concept_payload(profile),
        "questions": questions,
    }
    return payload, report


def inspect_kdata_text_sources(source: Path, *, exam_id: str) -> dict[str, Any]:
    profile = profile_for(exam_id)
    entries = read_source_entries(source)
    rows: list[dict[str, Any]] = []
    for entry in entries:
        answers = parse_answer_map(entry["text"])
        parsed = parse_kdata_text_questions(entry["text"], profile=profile, source_ref=entry["source_ref"])
        rows.append(
            {
                "path": entry["source_ref"],
                "chars": len(entry["text"]),
                "answers": len(answers),
                "convertible_questions": len(parsed),
            }
        )
    return {
        "exam_id": profile.id,
        "source": str(source),
        "files": len(rows),
        "convertible_questions": sum(row["convertible_questions"] for row in rows),
        "answers": sum(row["answers"] for row in rows),
        "items": rows,
    }


def read_source_entries(source: Path) -> list[dict[str, str]]:
    if not source.exists():
        raise ValueError(f"경로가 없습니다: {source}")
    if source.is_file():
        return read_single_source(source)
    entries: list[dict[str, str]] = []
    for path in sorted(source.rglob("*")):
        if path.is_file() and (path.suffix.lower() in SUPPORTED_SUFFIXES or path.suffix.lower() == ".zip"):
            entries.extend(read_single_source(path))
    return entries


def read_single_source(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        entries: list[dict[str, str]] = []
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                inner_suffix = Path(info.filename).suffix.lower()
                if info.is_dir() or inner_suffix not in SUPPORTED_SUFFIXES:
                    continue
                entries.append(
                    {
                        "source_ref": f"{path.name}/{info.filename}",
                        "text": text_from_bytes(archive.read(info), inner_suffix),
                    }
                )
        return entries
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"지원하지 않는 원천 파일입니다: {path}")
    return [{"source_ref": str(path), "text": text_from_bytes(path.read_bytes(), suffix)}]


def text_from_bytes(data: bytes, suffix: str) -> str:
    if suffix == ".pdf":
        return pdf_text(data)
    text = data.decode("utf-8", errors="replace")
    if suffix in {".html", ".htm"}:
        text = html_to_text(text)
    return text


def pdf_text(data: bytes) -> str:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValueError("PDF 변환은 PyMuPDF가 필요합니다. `python3 -m pip install -e \".[pdf]\"` 후 다시 실행하세요.") from exc
    document = fitz.open(stream=data, filetype="pdf")
    return "\n".join(page.get_text("text", sort=True) for page in document)


def html_to_text(text: str) -> str:
    extracted = "\n".join(
        part
        for part in (
            highlighted_answer_section(text),
            javascript_exam_data_text(text),
        )
        if part
    )
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    visible = html.unescape(text)
    return f"{visible}\n\n{extracted}" if extracted else visible


def parse_kdata_text_questions(
    text: str,
    *,
    profile: ExamProfile,
    source_ref: str,
    mark_active: bool = False,
    checked_at: str = "",
) -> list[dict[str, Any]]:
    answers = parse_answer_map(text)
    chunks = split_question_chunks(text)
    source_slug = source_hash(source_ref)
    questions: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()

    for number, chunk in chunks:
        if number in seen_numbers or number not in answers:
            continue
        seen_numbers.add(number)
        normalized_chunk = normalize_choice_markers(chunk)
        parsed = parse_leading_choice_question_chunk(normalized_chunk) or parse_question_chunk(number, normalized_chunk)
        if parsed is None:
            continue
        parsed["question_text"] = clean_extracted_text(parsed["question_text"])
        parsed_choices, inline_explanation = clean_choices_and_inline_explanation(parsed["choices"])
        parsed["choices"] = parsed_choices
        source_explanation = explanation_from_chunk(normalized_chunk)
        domain = domain_for_question_number(profile, number)
        answer = answers[number]
        questions.append(
            {
                "id": f"{profile.id}_SRC_{source_slug}_Q{number:03d}",
                "domain_id": domain.id,
                "concept_id": concept_id_for_domain(profile, domain.id),
                "question_type": "single_choice",
                "question_text": parsed["question_text"],
                "choices": parsed["choices"],
                "answer": answer,
                "answer_json": {"choices": [answer]},
                "explanation": normalize_explanation_text(source_explanation or inline_explanation)
                or f"{profile.name} private 원천의 정답표 기준 정답은 {answer}번입니다. 세부 해설은 오답노트에서 보강합니다.",
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
                "quality_notes": "private 원천에서 변환한 문항입니다. 공개 repo에는 원문을 저장하지 않습니다.",
                "provenance": {
                    "source_ref": source_ref,
                    "question_number": number,
                    "profile": profile.id,
                    "notice": "로컬 private_banks 안에서만 보관하는 개인 학습용 변환본입니다.",
                },
            }
        )
    return questions


def split_question_chunks(text: str) -> list[tuple[int, str]]:
    lines = [line.rstrip() for line in text.splitlines()]
    chunks: list[tuple[int, list[str]]] = []
    current_number: int | None = None
    current_lines: list[str] = []

    for line in lines:
        if re.match(r"^\s*(정답|답안|해답|answer)\s*$", line, re.I):
            break
        if re.match(r"^\s*(정답표|답안표)\s*$", line, re.I):
            break
        if current_number is not None and current_number > 1 and re.match(r"^\s*1\s*[.)]\s*정\s*답\s*[:：]", line):
            break
        marker = re.match(r"^\s*(?:■\s*)?문제\s*(\d{1,3})[.)]\s*(.*)$", line)
        if marker is None:
            marker = re.match(r"^\s*(?:■\s*)?(\d{1,3})[.]\s*(.*)$", line)
        marker_number = int(marker.group(1)) if marker else None
        starts_next_question = (
            marker is not None
            and marker_number is not None
            and 1 <= marker_number <= 100
            and (current_number is None or marker_number > current_number)
        )
        if starts_next_question:
            if current_number is not None:
                chunks.append((current_number, current_lines))
            current_number = marker_number
            current_lines = [marker.group(2)]
            continue
        if current_number is not None:
            current_lines.append(line)
    if current_number is not None:
        chunks.append((current_number, current_lines))
    return [(number, "\n".join(chunk_lines)) for number, chunk_lines in chunks]


def parse_answer_map(text: str) -> dict[int, int]:
    answer_text = answer_section(text)
    answers = parse_answer_table(answer_text)
    for number, answer in re.findall(r"(?<!\d)(\d{1,3})\s*[.)]\s*([1-4A-Da-d①②③④])", answer_text):
        answers[int(number)] = normalize_answer_token(answer)
    for number, answer in re.findall(r"(?:문제\s*)?(\d{1,3})\s*(?:번)?\s*[.)]?\s*정\s*답\s*[:：]?\s*([1-4A-Da-d①②③④])", text):
        answers[int(number)] = normalize_answer_token(answer)
    for number, answer in re.findall(r"(?:문제\s*)?(\d{1,3})\s*(?:번)?\s*[.)]?\s*정답\s*[:：]?\s*([1-4A-Da-d①②③④])", text):
        answers[int(number)] = normalize_answer_token(answer)
    if not answers:
        bare = re.search(r"(?:정답|답안|해답|answer)\s*[:：]\s*([1-4A-Da-d①②③④])", text, re.I)
        if bare:
            answers[1] = normalize_answer_token(bare.group(1))
    return answers


def highlighted_answer_section(raw_html: str) -> str:
    chunks = split_raw_html_question_chunks(raw_html)
    if not chunks:
        return ""
    answers: list[tuple[int, int]] = []
    for number, chunk in chunks:
        answer = highlighted_answer_in_chunk(chunk)
        if answer is not None:
            answers.append((number, answer))
    if not answers:
        return ""
    lines = ["정답"]
    lines.extend(f"{number}. {answer}" for number, answer in answers)
    return "\n".join(lines)


def split_raw_html_question_chunks(raw_html: str) -> list[tuple[int, str]]:
    pattern = re.compile(r"(?:■\s*)?문제\s*(\d{1,3})[.)]?", re.I)
    matches = list(pattern.finditer(raw_html))
    chunks: list[tuple[int, str]] = []
    for idx, match in enumerate(matches):
        number = int(match.group(1))
        if not 1 <= number <= 100:
            continue
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_html)
        chunks.append((number, raw_html[match.start() : end]))
    return chunks


def highlighted_answer_in_chunk(chunk: str) -> int | None:
    highlight_matches = re.finditer(
        r"""(?is)<(?P<tag>span|b|strong)[^>]*(?:color\s*:\s*#?(?:ee2323|e74c3c|ff0000)|font-weight\s*:\s*bold)[^>]*>.*?</(?P=tag)>""",
        chunk,
    )
    for match in highlight_matches:
        text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", match.group(0)))
        token = re.search(r"[①②③④]|(?<!\d)[1-4](?!\d)", text)
        if token:
            return normalize_answer_token(token.group(0))
    fallback = re.search(
        r"""(?is)(?:color\s*:\s*#?(?:ee2323|e74c3c|ff0000)|font-weight\s*:\s*bold).*?([①②③④])""",
        chunk,
    )
    if fallback:
        return normalize_answer_token(fallback.group(1))
    return None


def javascript_exam_data_text(raw_html: str) -> str:
    marker = re.search(r"\bconst\s+examData\s*=", raw_html)
    if marker is None:
        return ""
    start = raw_html.find("[", marker.end())
    if start == -1:
        return ""
    end = find_matching_bracket(raw_html, start, "[", "]")
    if end == -1:
        return ""
    array_text = raw_html[start : end + 1]
    try:
        rows = parse_js_exam_data_array(array_text)
    except ValueError:
        return ""
    if not rows:
        return ""
    answer_lines = ["정답"]
    question_lines: list[str] = []
    for idx, row in enumerate(rows, start=1):
        question_text = clean_js_question_text(str(row["q"]), fallback_number=idx)
        question_lines.append(f"{idx}. {question_text}")
        if row.get("c"):
            question_lines.append(str(row["c"]))
        for choice in row["o"]:
            question_lines.append(normalize_js_choice(str(choice)))
        if row.get("h"):
            question_lines.append(f"해설: {row['h']}")
        answer_lines.append(f"{idx}. {int(row['a'])}")
    return "\n".join(question_lines + [""] + answer_lines)


def parse_js_exam_data_array(array_text: str) -> list[dict[str, Any]]:
    pythonish = array_text
    pythonish = re.sub(r"(?m)([{,]\s*)(q|o|a|h|c)\s*:", r"\1'\2':", pythonish)
    pythonish = re.sub(r",\s*([}\]])", r"\1", pythonish)
    try:
        parsed = ast.literal_eval(pythonish)
    except (SyntaxError, ValueError) as exc:
        raise ValueError("examData 배열을 파싱하지 못했습니다.") from exc
    if not isinstance(parsed, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        question = item.get("q")
        options = item.get("o")
        answer = item.get("a")
        if not isinstance(question, str) or not isinstance(options, list) or len(options) != 4:
            continue
        if not all(isinstance(option, str) for option in options):
            continue
        try:
            answer_int = int(answer)
        except (TypeError, ValueError):
            continue
        if not 1 <= answer_int <= 4:
            continue
        rows.append({"q": question, "o": options, "a": answer_int, "h": str(item.get("h", "")), "c": str(item.get("c", ""))})
    return rows


def find_matching_bracket(text: str, start: int, opener: str, closer: str) -> int:
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
        if char in {'"', "'"}:
            quote = char
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return idx
    return -1


def clean_js_question_text(value: str, *, fallback_number: int) -> str:
    value = normalize_space(value)
    return re.sub(r"^\s*\d{1,3}\s*[.)]\s*", "", value) or f"문제 {fallback_number}"


def normalize_js_choice(value: str) -> str:
    value = normalize_space(value)
    match = re.match(r"^([①②③④])\s*(.*)$", value)
    if match:
        return f"{match.group(1)} {match.group(2)}".strip()
    match = re.match(r"^([1-4A-Da-d])\s*[.)]\s*(.*)$", value)
    if match:
        marker = {"1": "①", "2": "②", "3": "③", "4": "④", "A": "①", "B": "②", "C": "③", "D": "④"}[
            match.group(1).upper()
        ]
        return f"{marker} {match.group(2)}".strip()
    return value


def explanation_from_chunk(chunk: str) -> str:
    match = re.search(r"(?:해설|풀이)\s*[:：]\s*(.+)$", chunk, re.S)
    if match is None:
        return ""
    explanation = clean_extracted_text(match.group(1))
    explanation = re.split(r"\s*정답\s*$", explanation, maxsplit=1)[0].strip()
    return explanation


def answer_section(text: str) -> str:
    matches = list(re.finditer(r"(정답|답안|해답|answer)", text, re.I))
    if not matches:
        return text
    return text[matches[-1].start() :]


def normalize_answer_token(token: str) -> int:
    token = token.strip()
    if token in CIRCLED_TO_ANSWER:
        return CIRCLED_TO_ANSWER[token]
    letter_answers = {"A": 1, "B": 2, "C": 3, "D": 4}
    if token.upper() in letter_answers:
        return letter_answers[token.upper()]
    return int(token)


def normalize_choice_markers(text: str) -> str:
    replacements = {"1": "①", "2": "②", "3": "③", "4": "④", "A": "①", "B": "②", "C": "③", "D": "④"}
    normalized_lines: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^(\s*)([1-4A-Da-d])\s*[.)]\s+(.*)$", line)
        if match:
            marker = replacements[match.group(2).upper()]
            normalized_lines.append(f"{match.group(1)}{marker} {match.group(3)}")
        else:
            normalized_lines.append(line)
    return "\n".join(normalized_lines)


def parse_leading_choice_question_chunk(text: str) -> dict[str, Any] | None:
    normalized = normalize_space_preserving_markers(text)
    marker_positions = ordered_marker_positions(normalized)
    if len(marker_positions) != 4:
        return None

    prompt = normalize_space(normalized[: marker_positions[0][1]])
    choices: list[str] = []
    for idx, (_marker, start) in enumerate(marker_positions):
        content_start = start + 1
        content_end = marker_positions[idx + 1][1] if idx + 1 < len(marker_positions) else len(normalized)
        choices.append(normalize_space(normalized[content_start:content_end]))

    if not prompt or any(not choice for choice in choices):
        return None
    if len(set(choices)) != 4:
        return None
    return {"question_text": prompt, "choices": choices}


def ordered_marker_positions(text: str) -> list[tuple[str, int]]:
    positions: list[tuple[str, int]] = []
    cursor = 0
    for marker in ("①", "②", "③", "④"):
        found = text.find(marker, cursor)
        if found == -1:
            return []
        positions.append((marker, found))
        cursor = found + 1
    return positions


def normalize_space_preserving_markers(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def clean_extracted_text(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"\s*정\s*답\s*확\s*인\s*[🌼⭐★]*", " ", cleaned)
    cleaned = re.sub(r"\s*(해설|풀이|답안)\s*(보기|확인)\s*[🌼⭐★]*", " ", cleaned)
    cleaned = cleaned.replace("🌼", " ")
    return normalize_space(cleaned)


def clean_choices_and_inline_explanation(choices: list[str]) -> tuple[list[str], str]:
    cleaned_choices: list[str] = []
    inline_explanations: list[str] = []
    for choice in choices:
        cleaned = clean_extracted_text(choice)
        match = re.search(r"\s*(?:해설|풀이)\s*[:：]\s*", cleaned)
        if match:
            inline_explanations.append(cleaned[match.end() :])
            cleaned = cleaned[: match.start()]
        cleaned_choices.append(normalize_space(cleaned))
    return cleaned_choices, normalize_explanation_text(" ".join(inline_explanations))


def normalize_explanation_text(text: str) -> str:
    cleaned = clean_extracted_text(text)
    cleaned = re.sub(r"^(?:해설|풀이)\s*[:：]\s*", "", cleaned)
    cleaned = re.sub(r"^(?:해설|풀이)\s*[:：]\s*", "", cleaned)
    return normalize_space(cleaned)


def exam_payload(profile: ExamProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "official_question_count": profile.official_question_count,
        "official_duration_minutes": profile.official_duration_minutes,
        "pass_score": profile.pass_score,
        "domain_min_score": profile.domain_min_score,
        "notes": profile.notes,
    }


def domain_payload(profile: ExamProfile) -> list[dict[str, Any]]:
    return [
        {
            "id": domain.id,
            "name": domain.name,
            "official_weight": domain.official_weight,
            "official_question_count": domain.official_question_count,
        }
        for domain in profile.domains
    ]


def concept_payload(profile: ExamProfile) -> list[dict[str, str]]:
    return [
        {
            "id": concept_id_for_domain(profile, domain.id),
            "domain_id": domain.id,
            "name": f"{domain.name} source-backed",
            "review_note": f"{domain.name} 영역의 source-backed 오답을 정답표와 함께 복습한다.",
        }
        for domain in profile.domains
    ]


def domain_for_question_number(profile: ExamProfile, number: int) -> DomainProfile:
    cumulative = 0
    for domain in profile.domains:
        cumulative += domain.official_question_count
        if number <= cumulative:
            return domain
    return profile.domains[-1]


def concept_id_for_domain(profile: ExamProfile, domain_id: str) -> str:
    suffix = domain_id.split("-")[-1]
    return f"{profile.id}-SRC-C-{suffix}"


def profile_for(exam_id: str) -> ExamProfile:
    normalized = exam_id.upper()
    if normalized not in EXAM_PROFILES:
        raise ValueError(f"KDATA 텍스트 변환은 SQLD 또는 ADSP만 지원합니다: {exam_id}")
    return EXAM_PROFILES[normalized]


def source_hash(source_ref: str) -> str:
    return hashlib.sha1(source_ref.encode("utf-8")).hexdigest()[:10]


def render_kdata_inspect_report(report: dict[str, Any]) -> str:
    lines = [
        f"# {report['exam_id']} private 원천 점검",
        "",
        f"- 파일: {report['files']}개",
        f"- 정답 후보: {report['answers']}개",
        f"- 변환 가능 문항: {report['convertible_questions']}개",
        "",
        "## 파일별 후보",
    ]
    for row in report["items"]:
        lines.append(f"- {row['path']}: text {row['chars']} chars, answers {row['answers']}, questions {row['convertible_questions']}")
    return "\n".join(lines)


def render_kdata_convert_report(report: dict[str, Any]) -> str:
    lines = [
        f"# {report['exam_id']} private 원천 변환",
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
