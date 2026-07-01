from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(os.environ.get("CERT_STUDY_HOME", Path(__file__).resolve().parents[1]))


def data_dir() -> Path:
    path = project_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "study.sqlite"


def reports_dir() -> Path:
    path = project_root() / "reports" / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def notion_exports_dir() -> Path:
    path = project_root() / "notion_exports"
    path.mkdir(parents=True, exist_ok=True)
    return path

