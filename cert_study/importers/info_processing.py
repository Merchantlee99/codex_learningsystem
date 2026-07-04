from __future__ import annotations

import json
import re
import zipfile
from contextlib import redirect_stderr
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
