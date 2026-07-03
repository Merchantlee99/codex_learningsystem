from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any


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
