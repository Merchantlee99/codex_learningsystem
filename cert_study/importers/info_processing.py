from __future__ import annotations

import json
import hashlib
import re
import zipfile
from contextlib import redirect_stderr
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

CIRCLED_CHOICES = ("①", "②", "③", "④")
CIRCLED_TO_ANSWER = {value: idx for idx, value in enumerate(CIRCLED_CHOICES, start=1)}

EXAM_ID = "KR_INFO_PROCESSING_ENGINEER"
EXAM_PAYLOAD = {
    "id": EXAM_ID,
    "name": "정보처리기사",
    "official_question_count": 100,
    "official_duration_minutes": 150,
    "pass_score": 60.0,
    "domain_min_score": 40.0,
    "notes": "private ZIP/PDF에서 변환한 로컬 CBT용 정보처리기사 문제은행입니다. 공개 repo에는 원문을 저장하지 않습니다.",
}
DOMAINS = [
    {"id": "IPE-D1", "name": "소프트웨어 설계", "official_weight": 20.0, "official_question_count": 20},
    {"id": "IPE-D2", "name": "소프트웨어 개발", "official_weight": 20.0, "official_question_count": 20},
    {"id": "IPE-D3", "name": "데이터베이스 구축", "official_weight": 20.0, "official_question_count": 20},
    {"id": "IPE-D4", "name": "프로그래밍 언어 활용", "official_weight": 20.0, "official_question_count": 20},
    {"id": "IPE-D5", "name": "정보시스템 구축관리", "official_weight": 20.0, "official_question_count": 20},
]
PAST_EXAM_CONCEPTS = [
    {
        "id": f"IPE-PAST-C-D{idx}",
        "domain_id": row["id"],
        "name": f"{row['name']} 기출",
        "review_note": f"{row['name']} 영역의 기출 오답을 원문 문항과 정답표 기준으로 복습한다.",
    }
    for idx, row in enumerate(DOMAINS, start=1)
]


@dataclass(frozen=True)
class PatternLine:
    text: str
    highlighted: bool = False


def convert_info_processing_archives(
    source: Path,
    output: Path,
    *,
    mark_active: bool = False,
    checked_at: str = "",
    min_questions: int = 90,
) -> dict[str, Any]:
    payload, report = build_info_processing_payload(
        source,
        mark_active=mark_active,
        checked_at=checked_at,
        min_questions=min_questions,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output"] = str(output)
    return report


def convert_info_processing_pattern_archives(
    source: Path,
    output: Path,
    *,
    mark_active: bool = False,
    checked_at: str = "",
    min_questions: int = 1,
) -> dict[str, Any]:
    payload, report = build_info_processing_pattern_payload(
        source,
        mark_active=mark_active,
        checked_at=checked_at,
        min_questions=min_questions,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output"] = str(output)
    return report


def build_info_processing_pattern_payload(
    source: Path,
    *,
    mark_active: bool = False,
    checked_at: str = "",
    min_questions: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    archives = archive_paths(source)
    questions: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "source": str(source),
        "archives": 0,
        "pdf_candidates": 0,
        "converted_pdfs": 0,
        "converted_questions": 0,
        "skipped": [],
    }
    for archive_path in archives:
        report["archives"] += 1
        if archive_category(archive_path.name) != "pattern_set":
            report["skipped"].append({"path": str(archive_path), "reason": "pattern_set ZIP이 아니라 제외했습니다."})
            continue
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                    continue
                report["pdf_candidates"] += 1
                parsed = parse_info_processing_pattern_pdf(
                    archive.read(info),
                    zip_name=archive_path.name,
                    pdf_name=info.filename,
                    mark_active=mark_active,
                    checked_at=checked_at,
                )
                if len(parsed) < min_questions:
                    report["skipped"].append(
                        {
                            "path": f"{archive_path.name}/{info.filename}",
                            "reason": f"품질 기준 미달: {len(parsed)}문항 변환, 최소 {min_questions}문항 필요",
                        }
                    )
                    continue
                questions.extend(parsed)
                report["converted_pdfs"] += 1
                report["converted_questions"] += len(parsed)

    payload = {
        "exam": EXAM_PAYLOAD,
        "domains": DOMAINS,
        "concepts": pattern_concepts(),
        "questions": questions,
    }
    return payload, report


def build_info_processing_payload(
    source: Path,
    *,
    mark_active: bool = False,
    checked_at: str = "",
    min_questions: int = 90,
) -> tuple[dict[str, Any], dict[str, Any]]:
    archives = archive_paths(source)
    questions: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "source": str(source),
        "archives": 0,
        "pdf_candidates": 0,
        "converted_pdfs": 0,
        "converted_questions": 0,
        "partial_pdfs": [],
        "skipped": [],
    }
    for archive_path in archives:
        report["archives"] += 1
        category = archive_category(archive_path.name)
        if category != "past_exam":
            report["skipped"].append(
                {"path": str(archive_path), "reason": "2026 pattern_set은 정답표 구조가 달라 별도 parser가 필요합니다."}
            )
            continue
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                    continue
                report["pdf_candidates"] += 1
                year, round_no = infer_year_round(archive_path.name, info.filename)
                parsed = parse_info_processing_past_exam_pdf(
                    archive.read(info),
                    year=year,
                    round_no=round_no,
                    zip_name=archive_path.name,
                    pdf_name=info.filename,
                    mark_active=mark_active,
                    checked_at=checked_at,
                )
                if len(parsed["questions"]) < min_questions:
                    report["skipped"].append(
                        {
                            "path": f"{archive_path.name}/{info.filename}",
                            "reason": f"품질 기준 미달: {len(parsed['questions'])}문항 변환, 최소 {min_questions}문항 필요",
                            "answers": parsed["answer_count"],
                        }
                    )
                    continue
                questions.extend(parsed["questions"])
                report["converted_pdfs"] += 1
                report["converted_questions"] += len(parsed["questions"])
                if len(parsed["questions"]) != 100:
                    report["partial_pdfs"].append(
                        {
                            "path": f"{archive_path.name}/{info.filename}",
                            "questions": len(parsed["questions"]),
                            "answers": parsed["answer_count"],
                        }
                    )

    payload = {
        "exam": EXAM_PAYLOAD,
        "domains": DOMAINS,
        "concepts": PAST_EXAM_CONCEPTS,
        "questions": questions,
    }
    return payload, report


def archive_paths(path: Path) -> list[Path]:
    if not path.exists():
        raise ValueError(f"경로가 없습니다: {path}")
    if path.is_file() and path.suffix.lower() != ".zip":
        raise ValueError(f"ZIP 파일 또는 ZIP 디렉터리만 변환할 수 있습니다: {path}")
    return sorted(path.glob("*.zip")) if path.is_dir() else [path]


def parse_info_processing_past_exam_pdf(
    pdf_bytes: bytes,
    *,
    year: int,
    round_no: int,
    zip_name: str,
    pdf_name: str,
    mark_active: bool = False,
    checked_at: str = "",
) -> dict[str, Any]:
    blocks, answer_text = extract_info_processing_pdf_blocks(pdf_bytes)
    answers = parse_answer_table(answer_text)
    parsed_questions = parse_info_processing_exam_blocks(
        blocks,
        answers=answers,
        year=year,
        round_no=round_no,
        source_ref=f"{zip_name}/{pdf_name}",
        mark_active=mark_active,
        checked_at=checked_at,
    )
    return {"questions": parsed_questions, "answer_count": len(answers)}


def parse_info_processing_pattern_pdf(
    pdf_bytes: bytes,
    *,
    zip_name: str,
    pdf_name: str,
    mark_active: bool = False,
    checked_at: str = "",
) -> list[dict[str, Any]]:
    lines = extract_info_processing_pattern_lines(pdf_bytes)
    category = pattern_category(zip_name, pdf_name)
    return parse_info_processing_pattern_lines(
        lines,
        source_ref=f"{zip_name}/{pdf_name}",
        category=category,
        mark_active=mark_active,
        checked_at=checked_at,
    )


def extract_info_processing_pattern_lines(pdf_bytes: bytes) -> list[PatternLine]:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValueError("정보처리기사 PDF 변환은 PyMuPDF가 필요합니다. `python3 -m pip install -e \".[pdf]\"` 후 다시 실행하세요.") from exc

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    lines: list[PatternLine] = []
    for page in document:
        raw_lines = []
        for block in page.get_text("dict", sort=True).get("blocks", []):
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = normalize_space("".join(str(span.get("text", "")) for span in spans))
                if not text:
                    continue
                y0 = min(float(span.get("bbox", [0, 0, 0, 0])[1]) for span in spans)
                x0 = min(float(span.get("bbox", [0, 0, 0, 0])[0]) for span in spans)
                highlighted = any(is_highlight_span(span) for span in spans)
                raw_lines.append((y0, x0, PatternLine(text=text, highlighted=highlighted)))
        for _y0, _x0, line in sorted(raw_lines, key=lambda item: (item[0], item[1])):
            if not is_pattern_noise_line(line.text):
                lines.append(line)
    return lines


def is_highlight_span(span: dict[str, Any]) -> bool:
    text = str(span.get("text", ""))
    if not re.search(r"[①②③④]", text):
        return False
    try:
        color = int(span.get("color", 0))
    except (TypeError, ValueError):
        color = 0
    return color not in {0, 0x000000}


def is_pattern_noise_line(text: str) -> bool:
    compact = normalize_space(text)
    if not compact:
        return True
    if compact.startswith("- ") and compact.endswith(" -"):
        return True
    if "저작권 안내" in compact or "시나공 카페" in compact:
        return True
    return False


def parse_info_processing_pattern_lines(
    lines: list[PatternLine],
    *,
    source_ref: str,
    category: str = "pattern",
    mark_active: bool = False,
    checked_at: str = "",
) -> list[dict[str, Any]]:
    chunks: list[tuple[int, list[PatternLine]]] = []
    current_number: int | None = None
    current_lines: list[PatternLine] = []
    for line in lines:
        match = re.match(r"^(\d{1,3})\.\s*(.*)$", line.text)
        if match and 1 <= int(match.group(1)) <= 300:
            if current_number is not None:
                chunks.append((current_number, current_lines))
            current_number = int(match.group(1))
            current_lines = [PatternLine(match.group(2), line.highlighted)]
            continue
        if current_number is not None:
            current_lines.append(line)
    if current_number is not None:
        chunks.append((current_number, current_lines))

    questions = []
    for number, chunk_lines in chunks:
        parsed = parse_info_processing_pattern_chunk(number, chunk_lines)
        if parsed is None:
            continue
        domain_id = infer_pattern_domain(parsed["question_text"], parsed["choices"], parsed["explanation"], category)
        answer = parsed["answer"]
        questions.append(
            {
                "id": f"IPE_PATTERN_{source_hash(source_ref)}_Q{number:03d}",
                "domain_id": domain_id,
                "concept_id": pattern_concept_id_for_domain(domain_id),
                "question_type": "single_choice",
                "question_text": parsed["question_text"],
                "choices": parsed["choices"],
                "answer": answer,
                "answer_json": {"choices": [answer]},
                "explanation": parsed["explanation"],
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
                "quality_notes": "정보처리기사 2026 대비 해설 포함 private PDF에서 변환한 문항입니다.",
                "provenance": {
                    "source_ref": source_ref,
                    "question_number": number,
                    "category": category,
                    "notice": "로컬 private_banks 안에서만 보관하는 개인 학습용 변환본입니다.",
                },
            }
        )
    return questions


def parse_info_processing_pattern_chunk(number: int, lines: list[PatternLine]) -> dict[str, Any] | None:
    prompt_parts: list[str] = []
    options: dict[int, list[str]] = {1: [], 2: [], 3: [], 4: []}
    answer: int | None = None
    explanation_parts: list[str] = []
    current_option: int | None = None
    in_explanation = False

    for line in lines:
        text = normalize_space(line.text)
        if not text:
            continue
        if re.search(r"\[\s*해설\s*\]|^해설$", text):
            in_explanation = True
            current_option = None
            trailing = normalize_space(re.sub(r".*?\[\s*해설\s*\]\s*", "", text))
            if trailing and trailing != text:
                explanation_parts.append(trailing)
            continue
        if in_explanation:
            explanation_parts.append(text)
            continue

        marker_match = re.match(r"^([①②③④])\s*(.*)$", text)
        if marker_match:
            current_option = CIRCLED_TO_ANSWER[marker_match.group(1)]
            content = normalize_space(marker_match.group(2))
            if content:
                options[current_option].append(content)
            if line.highlighted:
                answer = current_option
            continue
        if current_option is not None:
            options[current_option].append(text)
        else:
            prompt_parts.append(text)

    prompt = normalize_space(" ".join(prompt_parts))
    choices = [normalize_space(" ".join(options[idx])) for idx in range(1, 5)]
    explanation = normalize_space(" ".join(explanation_parts))
    if not prompt or any(not choice for choice in choices) or answer is None or len(explanation) < 20:
        return None
    if len(set(choices)) != 4:
        return None
    return {
        "number": number,
        "question_text": prompt,
        "choices": choices,
        "answer": answer,
        "explanation": explanation,
    }


def extract_info_processing_pdf_blocks(pdf_bytes: bytes) -> tuple[list[str], str]:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ValueError("정보처리기사 PDF 변환은 PyMuPDF가 필요합니다. `python3 -m pip install -e \".[pdf]\"` 후 다시 실행하세요.") from exc

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    blocks: list[str] = []
    answer_text_parts: list[str] = []
    for page in document:
        page_text = page.get_text("text", sort=True)
        answer_text_parts.append(page_text)
        if looks_like_answer_page(page_text):
            continue
        width = float(page.rect.width)
        raw_blocks = []
        for block in page.get_text("blocks", sort=False):
            x0, y0, _x1, y1, text, *_rest = block
            normalized = normalize_lines(text)
            if not normalized or is_noise_block(normalized, y0=y0, y1=y1):
                continue
            column = 0 if float(x0) < width / 2 else 1
            raw_blocks.append((column, float(y0), float(x0), normalized))
        for _column, _y0, _x0, text in sorted(raw_blocks, key=lambda row: (row[0], row[1], row[2])):
            blocks.append(text)
    return blocks, "\n".join(answer_text_parts)


def looks_like_answer_page(text: str) -> bool:
    return len(parse_answer_table(text)) >= 50 and bool(re.search(r"\n\s*정답\s*\n", text))


def is_noise_block(text: str, *, y0: float, y1: float) -> bool:
    compact = normalize_space(text)
    if y1 < 35 or y0 > 780:
        return True
    if compact in {"회 1", "회 2", "회 3"}:
        return True
    if compact.startswith("- ") and compact.endswith(" -"):
        return True
    if "저작권 안내" in compact:
        return True
    if "시나공 카페 회원" in compact:
        return True
    if "다음 문제를 읽고" in compact or "답란" in compact:
        return True
    if "기출문제" in compact and "정보처리기사 필기" in compact:
        return True
    return False


def parse_answer_table(text: str) -> dict[int, int]:
    answers: dict[int, int] = {}
    for number, circled in re.findall(r"(?<!\d)(\d{1,3})\.\s*([①②③④])", text):
        answers[int(number)] = CIRCLED_TO_ANSWER[circled]
    return answers


def parse_info_processing_exam_blocks(
    blocks: list[str],
    *,
    answers: dict[int, int],
    year: int,
    round_no: int,
    source_ref: str,
    mark_active: bool = False,
    checked_at: str = "",
) -> list[dict[str, Any]]:
    chunks: list[tuple[int, list[str]]] = []
    current_number: int | None = None
    current_blocks: list[str] = []
    for block in blocks:
        match = find_question_marker(block)
        if match is not None:
            if current_number is not None:
                chunks.append((current_number, current_blocks))
            current_number = int(match.group(1))
            current_blocks = [question_block_without_marker(block, match)]
        elif current_number is not None:
            current_blocks.append(block)
    if current_number is not None:
        chunks.append((current_number, current_blocks))

    questions: list[dict[str, Any]] = []
    seen_numbers: set[int] = set()
    for number, chunk_blocks in chunks:
        if number in seen_numbers:
            continue
        seen_numbers.add(number)
        if number not in answers:
            continue
        parsed = parse_question_chunk(number, "\n".join(chunk_blocks))
        if parsed is None:
            continue
        domain_id = domain_id_for_question_number(number)
        answer = answers[number]
        questions.append(
            {
                "id": f"IPE_PAST_{year}_{round_no}_Q{number:03d}",
                "domain_id": domain_id,
                "concept_id": concept_id_for_domain(domain_id),
                "question_type": "single_choice",
                "question_text": parsed["question_text"],
                "choices": parsed["choices"],
                "answer": answer,
                "answer_json": {"choices": [answer]},
                "explanation": f"{year}년 {round_no}회 정보처리기사 필기 정답표 기준 정답은 {answer}번입니다. 세부 해설은 오답노트에서 보강합니다.",
                "difficulty": "medium",
                "source_type": "licensed_private",
                "source_ref": source_ref,
                "source_license": "private-study-use",
                "source_tier": "licensed_private",
                "storage_policy": "private_only",
                "validity_status": "current" if mark_active else "needs_official_check",
                "quality_status": "active" if mark_active else "needs_review",
                "scope_version": str(year),
                "official_checked_at": checked_at if mark_active else "",
                "quality_notes": "private 기출 PDF에서 변환한 문항입니다. 공개 repo에는 원문을 저장하지 않습니다.",
                "provenance": {
                    "source_ref": source_ref,
                    "year": year,
                    "round": round_no,
                    "question_number": number,
                    "notice": "로컬 private_banks 안에서만 보관하는 개인 학습용 변환본입니다.",
                },
            }
        )
    return questions


def find_question_marker(text: str) -> re.Match[str] | None:
    for match in re.finditer(r"(?<!\d)(\d{1,3})\.\s*", text):
        number = int(match.group(1))
        if 1 <= number <= 100:
            return match
    return None


def question_block_without_marker(block: str, match: re.Match[str]) -> str:
    before = block[: match.start()]
    after = block[match.end() :]
    before_clean = normalize_lines(before)
    after_clean = normalize_lines(after)
    if before_clean.startswith(("에 대한", "의 구성", "의 ", "중 ")):
        return normalize_lines(f"{after_clean}\n{before_clean}")
    return normalize_lines(f"{before_clean}\n{after_clean}")


def parse_question_chunk(number: int, text: str) -> dict[str, Any] | None:
    lines = [line for line in normalize_lines(text).splitlines() if line.strip()]
    prompt_parts: list[str] = []
    options: dict[int, list[str]] = {1: [], 2: [], 3: [], 4: []}
    current_option: int | None = None
    carry: list[str] = []

    def assign_before_marker(marker: int, before: str) -> None:
        nonlocal current_option, carry, prompt_parts
        before = normalize_space(before)
        if marker == 1 and current_option is None:
            prompt, first_choice = split_prompt_and_first_choice([*prompt_parts, before])
            prompt_parts = [prompt]
            if first_choice:
                options[1].append(first_choice)
        elif before:
            if current_option is not None and carry:
                options[current_option].extend(carry)
                carry = []
            options[marker].append(before)
        elif carry:
            previous_carry, marker_carry = split_carry_before_empty_marker(carry)
            if current_option is not None:
                options[current_option].extend(previous_carry)
            options[marker].extend(marker_carry)
            carry = []
        current_option = marker

    for line in lines:
        marker_matches = list(re.finditer(r"[①②③④]", line))
        if not marker_matches:
            if current_option is None:
                prompt_parts.append(line)
            else:
                carry.append(line)
            continue
        cursor = 0
        for marker_match in marker_matches:
            before_marker = line[cursor : marker_match.start()]
            marker = CIRCLED_TO_ANSWER[marker_match.group(0)]
            assign_before_marker(marker, before_marker)
            cursor = marker_match.end()
        trailing = normalize_space(line[cursor:])
        if trailing:
            carry.append(trailing)
    if current_option is not None and carry:
        options[current_option].extend(carry)

    prompt = normalize_space(" ".join(prompt_parts))
    choices = [normalize_space(" ".join(options[idx])) for idx in range(1, 5)]
    if not prompt or any(not choice for choice in choices):
        return None
    if len({choice for choice in choices}) != 4:
        return None
    return {"question_text": prompt, "choices": choices}


def split_prompt_and_first_choice(parts: list[str]) -> tuple[str, str]:
    text = normalize_space(" ".join(part for part in parts if part))
    question_mark = text.rfind("?")
    if question_mark != -1:
        return normalize_space(text[: question_mark + 1]), normalize_space(text[question_mark + 1 :])
    pieces = [part for part in parts if normalize_space(part)]
    if len(pieces) <= 1:
        return normalize_space(text), ""
    return normalize_space(" ".join(pieces[:-1])), normalize_space(pieces[-1])


def split_carry_before_empty_marker(carry: list[str]) -> tuple[list[str], list[str]]:
    if len(carry) <= 1:
        return [], carry
    last_content_idx = len(carry) - 1
    while last_content_idx > 0 and re.fullmatch(r"[,.;:()\s]+", carry[last_content_idx]):
        last_content_idx -= 1
    return carry[:last_content_idx], carry[last_content_idx:]


def domain_id_for_question_number(number: int) -> str:
    index = min((number - 1) // 20, 4)
    return DOMAINS[index]["id"]


def concept_id_for_domain(domain_id: str) -> str:
    return domain_id.replace("IPE-D", "IPE-PAST-C-D")


def infer_year_round(zip_name: str, pdf_name: str) -> tuple[int, int]:
    joined = f"{pdf_name} {zip_name}"
    match = re.search(r"(20\d{2})\s*년\s*(\d+)\s*회", joined)
    if match:
        return int(match.group(1)), int(match.group(2))
    year_match = re.search(r"(20\d{2})", joined)
    return int(year_match.group(1)) if year_match else 0, 0


def normalize_lines(text: str) -> str:
    lines = [normalize_space(line) for line in text.replace("\xa0", " ").splitlines()]
    return "\n".join(line for line in lines if line)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def render_info_processing_convert_report(report: dict[str, Any]) -> str:
    lines = [
        "# 정보처리기사 private PDF 변환",
        "",
        f"- ZIP: {report['archives']}개",
        f"- PDF 후보: {report['pdf_candidates']}개",
        f"- 변환 PDF: {report['converted_pdfs']}개",
        f"- 변환 문항: {report['converted_questions']}개",
    ]
    if report.get("output"):
        lines.append(f"- 출력: {report['output']}")
    if report["partial_pdfs"]:
        lines.extend(["", "## 부분 변환"])
        for row in report["partial_pdfs"]:
            lines.append(f"- {row['path']}: {row['questions']}문항 변환 / 정답표 {row['answers']}개")
    if report["skipped"]:
        lines.extend(["", "## 제외"])
        for row in report["skipped"]:
            lines.append(f"- {row['path']}: {row['reason']}")
    return "\n".join(lines)


def inspect_info_processing_archives(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"경로가 없습니다: {path}")
    if path.is_file() and path.suffix.lower() != ".zip":
        raise ValueError(f"ZIP 파일 또는 ZIP 디렉터리만 점검할 수 있습니다: {path}")
    archives = sorted(path.glob("*.zip")) if path.is_dir() else [path]
    results = [inspect_zip_archive(archive) for archive in archives if archive.suffix.lower() == ".zip"]
    return {
        "zip_count": len(results),
        "pdf_count": sum(len(row["pdfs"]) for row in results),
        "archives": results,
    }


def inspect_zip_archive(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"파일이 없습니다: {path}")
    pdfs: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                continue
            pdfs.append(inspect_pdf_entry(archive, info))
    return {
        "path": str(path),
        "name": path.name,
        "category": archive_category(path.name),
        "pdf_count": len(pdfs),
        "pdfs": pdfs,
    }


def archive_category(filename: str) -> str:
    if filename.startswith(("2022_", "2023_", "2024_", "2025_")):
        return "past_exam"
    if filename.startswith("2026_"):
        return "pattern_set"
    return "unknown"


def pattern_category(zip_name: str, pdf_name: str) -> str:
    joined = f"{zip_name} {pdf_name}".lower()
    if "calculation" in joined or "41" in joined and "2026_must_calculation" in joined:
        return "calculation"
    if "code" in joined or "2026_must_code" in joined:
        return "code"
    if "wrong" in joined or "sentence" in joined or "wrong_sentence" in joined:
        return "wrong_sentence"
    if "type" in joined or "order" in joined or "type_order" in joined:
        return "type_order"
    if "keyword" in joined:
        return "keyword"
    return "pattern"


def pattern_concepts() -> list[dict[str, str]]:
    return [
        {
            "id": pattern_concept_id_for_domain(row["id"]),
            "domain_id": row["id"],
            "name": f"{row['name']} 2026 해설형 문항",
            "review_note": f"{row['name']} 영역의 해설형 source-backed 오답을 복습한다.",
        }
        for row in DOMAINS
    ]


def pattern_concept_id_for_domain(domain_id: str) -> str:
    return domain_id.replace("IPE-D", "IPE-PATTERN-C-D")


DOMAIN_KEYWORDS = {
    "IPE-D1": (
        "요구사항",
        "uml",
        "유스케이스",
        "클래스",
        "객체지향",
        "디자인 패턴",
        "아키텍처",
        "ui",
        "화면",
        "럼바우",
        "dfd",
        "자료 흐름도",
        "결합도",
        "응집도",
        "모듈",
        "애자일",
        "xp",
        "스크럼",
        "소프트웨어 설계",
    ),
    "IPE-D2": (
        "테스트",
        "테스트 케이스",
        "화이트박스",
        "블랙박스",
        "단위 테스트",
        "통합 테스트",
        "테스트 드라이버",
        "검사",
        "디버깅",
        "빌드",
        "형상",
        "버전",
        "git",
        "자료 구조",
        "스택",
        "큐",
        "트리",
        "정렬",
        "버블",
        "삽입",
        "선택 정렬",
        "해싱",
        "인터페이스 구현",
        "소프트웨어 개발",
    ),
    "IPE-D3": (
        "데이터베이스",
        "릴레이션",
        "튜플",
        "속성",
        "카디널리티",
        "차수",
        "정규화",
        "sql",
        "select",
        "ddl",
        "dml",
        "dcl",
        "트랜잭션",
        "인덱스",
        "뷰",
        "키",
        "무결성",
        "병행",
        "회복",
        "스키마",
        "데이터베이스 구축",
    ),
    "IPE-D4": (
        "c 언어",
        "java",
        "python",
        "프로그램",
        "printf",
        "포인터",
        "배열",
        "반복문",
        "연산자",
        "변수",
        "함수",
        "코드",
        "실행 결과",
        "운영체제",
        "프로세스",
        "스케줄링",
        "페이지",
        "세그먼트",
        "메모리",
        "프로그래밍 언어",
    ),
    "IPE-D5": (
        "네트워크",
        "프로토콜",
        "tcp",
        "udp",
        "ip",
        "라우팅",
        "보안",
        "암호",
        "암호화",
        "블록 암호",
        "스트림 암호",
        "공개키",
        "정보 보안",
        "drm",
        "저작권",
        "공격",
        "방화벽",
        "ids",
        "ips",
        "클라우드",
        "미들웨어",
        "서비스 지향",
        "soa",
        "분산 시스템",
        "cmm",
        "spice",
        "테일러링",
        "cocomo",
        "위험",
        "취약점",
        "분산",
        "신기술",
        "정보시스템",
        "구축관리",
        "서비스",
        "개인정보",
        "인증",
    ),
}


def infer_pattern_domain(question_text: str, choices: list[str], explanation: str, category: str) -> str:
    text = normalize_space(" ".join([question_text, *choices, explanation])).lower()
    scores = {
        domain_id: sum(1 for keyword in keywords if keyword in text)
        for domain_id, keywords in DOMAIN_KEYWORDS.items()
    }
    if category == "code":
        scores["IPE-D4"] += 2
    if category == "calculation":
        scores["IPE-D3"] += 1
    if any(
        keyword in text
        for keyword in ("미들웨어", "취약점", "cmm", "spice", "서비스 지향", "soa", "분산 시스템", "암호화", "블록 암호", "스트림 암호", "공개키", "정보 보안")
    ):
        scores["IPE-D5"] += 4
    if any(keyword in text for keyword in ("테스트", "형상 관리", "화이트박스", "블랙박스", "테스트 케이스")):
        scores["IPE-D2"] += 4
    best_domain, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score > 0:
        return best_domain
    if category == "calculation":
        return "IPE-D3"
    return "IPE-D1"


def source_hash(source_ref: str) -> str:
    return hashlib.sha1(source_ref.encode("utf-8")).hexdigest()[:10]


def render_info_processing_pattern_convert_report(report: dict[str, Any]) -> str:
    lines = [
        "# 정보처리기사 2026 해설형 private PDF 변환",
        "",
        f"- ZIP: {report['archives']}개",
        f"- PDF 후보: {report['pdf_candidates']}개",
        f"- 변환 PDF: {report['converted_pdfs']}개",
        f"- 변환 문항: {report['converted_questions']}개",
    ]
    if report.get("output"):
        lines.append(f"- 출력: {report['output']}")
    if report["skipped"]:
        lines.extend(["", "## 제외"])
        for row in report["skipped"]:
            lines.append(f"- {row['path']}: {row['reason']}")
    return "\n".join(lines)


def inspect_pdf_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> dict[str, Any]:
    result: dict[str, Any] = {
        "filename": info.filename,
        "size": info.file_size,
        "parser_status": "candidate_pdf",
        "page_count": None,
        "text_sample_chars": 0,
    }
    try:
        from pypdf import PdfReader

        with redirect_stderr(StringIO()):
            reader = PdfReader(BytesIO(archive.read(info)))
        result["page_count"] = len(reader.pages)
        sample_text = ""
        for page in reader.pages[:2]:
            sample_text += page.extract_text() or ""
        result["text_sample_chars"] = len(sample_text.strip())
        result["parser_status"] = "text_extractable" if result["text_sample_chars"] else "needs_ocr_or_layout_parser"
    except Exception as exc:
        result["parser_status"] = f"pdf_probe_failed:{exc.__class__.__name__}"
    return result


def render_info_processing_archive_report(report: dict[str, Any]) -> str:
    lines = [
        "# 정보처리기사 private archive 점검",
        "",
        f"- ZIP: {report['zip_count']}개",
        f"- PDF 후보: {report['pdf_count']}개",
        "",
        "## 파일별 후보",
    ]
    for archive in report["archives"]:
        lines.append(f"- {archive['name']}: {archive['category']}, PDF {archive['pdf_count']}개")
        for pdf in archive["pdfs"]:
            page_count = "?" if pdf["page_count"] is None else pdf["page_count"]
            lines.append(
                f"  - {pdf['filename']} ({pdf['size']} bytes, pages {page_count}, "
                f"text {pdf['text_sample_chars']} chars, {pdf['parser_status']})"
            )
    return "\n".join(lines)
