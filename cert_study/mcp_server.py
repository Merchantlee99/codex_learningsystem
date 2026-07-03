from __future__ import annotations

import json
import sys
from typing import Any

from .db import connect, initialize
from .engine import create_session, finish_session, get_next_unanswered, submit_answer
from .importers.info_processing import inspect_info_processing_archives, render_info_processing_archive_report
from .notion_sync import prepare_notion_sync_plan, render_plan
from .quality import coverage_report, render_coverage_report
from .reporting import render_question, render_session_report, write_study_outputs
from .seed_public import seed_public_banks


PROTOCOL_VERSION = "2024-11-05"


PLANNED_EXAMS: list[dict[str, str]] = [
    {"id": "AWS_AI_PRACTITIONER", "name": "AWS Certified AI Practitioner", "status": "planned"},
    {"id": "AWS_CLOUD_PRACTITIONER", "name": "AWS Certified Cloud Practitioner", "status": "planned"},
    {
        "id": "AWS_SOLUTIONS_ARCHITECT_ASSOCIATE",
        "name": "AWS Certified Solutions Architect Associate",
        "status": "planned",
    },
    {"id": "GCP_GENERATIVE_AI_LEADER", "name": "Google Cloud Generative AI Leader", "status": "planned"},
]


TOOLS: list[dict[str, Any]] = [
    {
        "name": "init_study_db",
        "description": "로컬 SQLite 학습 DB를 초기화하고 SQLD, ADsP, 정보처리기사 공개 합성 훈련 문항을 seed한다.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_exams",
        "description": "현재 실제 문제은행으로 지원되는 시험과 계획 단계 과목을 확인한다.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "start_session",
        "description": "지원되는 실제 문제은행으로 CBT 세션을 시작하고 첫 문제만 반환한다. 정답표나 여러 문제를 한 번에 생성하지 않는다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "exam": {"type": "string", "default": "SQLD"},
                "count": {"type": "integer", "minimum": 1},
                "regular": {"type": "boolean", "default": False},
                "mode": {
                    "type": "string",
                    "enum": ["custom-cbt", "review-cbt", "weak-cbt", "exam-ready"],
                    "default": "custom-cbt",
                    "description": "custom-cbt는 미노출 우선, review-cbt는 복습 예정/오답 우선, weak-cbt는 취약 개념 우선, exam-ready는 active 비합성 문제만 출제합니다.",
                },
                "seed": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "coverage_report",
        "description": "공식 출제 비중 기준으로 exam-ready 문제은행 품질을 점검한다.",
        "inputSchema": {
            "type": "object",
            "properties": {"exam": {"type": "string", "default": "SQLD"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "inspect_info_processing_archives",
        "description": "정보처리기사 private ZIP/PDF 후보를 점검한다. 원문 import나 공개 저장은 하지 않는다.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_answer",
        "description": "현재 세션에 1~4번 답변을 제출하고 다음 문제가 있으면 반환한다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "answer": {"type": "integer", "minimum": 1, "maximum": 4},
            },
            "required": ["session_id", "answer"],
            "additionalProperties": False,
        },
    },
    {
        "name": "finish_session",
        "description": "완료된 세션을 종료하고 리포트를 쓴 뒤 상세 결과를 반환한다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "allow_incomplete": {"type": "boolean", "default": False},
                "prepare_notion_sync": {"type": "boolean", "default": False},
            },
            "required": ["session_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "prepare_notion_sync",
        "description": "완료된 세션의 Notion 동기화 계획을 만든다. 기본값은 실제 쓰기 비활성이다.",
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
            "additionalProperties": False,
        },
    },
]


def main() -> int:
    while True:
        message = read_message(sys.stdin.buffer)
        if message is None:
            return 0
        response = handle_message(message)
        if response is not None:
            write_message(sys.stdout.buffer, response)
            sys.stdout.buffer.flush()


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return result(
            message,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cert-study", "version": "0.3.2"},
            },
        )
    if method == "tools/list":
        return result(message, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            return result(message, call_tool(name, arguments))
        except Exception as exc:  # MCP 도구 오류는 호출자에게 보여야 한다.
            return result(message, {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True})
    return error(message, -32601, f"method not found: {method}")


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "init_study_db":
        with connect() as conn:
            initialize(conn)
            seed_public_banks(conn)
        return text_result("로컬 학습 DB를 초기화했습니다.")

    if name == "list_exams":
        with ready_conn() as conn:
            supported = [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "status": "available",
                    "available_questions": row["available_questions"],
                    "exam_ready_questions": row["exam_ready_questions"],
                    "official_question_count": row["official_question_count"],
                    "bank_rounds": row["bank_rounds"],
                }
                for row in conn.execute(
                    """
                    SELECT
                      e.id,
                      e.name,
                      e.official_question_count,
                      COUNT(q.id) AS available_questions,
                      COUNT(
                        CASE
                          WHEN q.quality_status = 'active'
                           AND q.source_tier IN ('official_sample', 'open_license', 'user_owned', 'licensed_private')
                           AND q.question_type = 'single_choice'
                          THEN 1
                        END
                      ) AS exam_ready_questions,
                      ROUND(COUNT(q.id) * 1.0 / e.official_question_count, 2) AS bank_rounds
                    FROM exams e
                    LEFT JOIN questions q ON q.exam_id = e.id
                    GROUP BY e.id, e.name, e.official_question_count
                    ORDER BY e.id
                    """
                ).fetchall()
            ]
        available_ids = {row["id"] for row in supported}
        planned = [row for row in PLANNED_EXAMS if row["id"] not in available_ids]
        payload = {
            "available": supported,
            "planned": planned,
            "note": "현재 CBT 세션으로 실제 출제 가능한 문제은행은 available 항목뿐입니다. 공개 seed는 데모 1회분 수준이며, 실전 학습은 private_banks import로 확장합니다.",
        }
        lines = ["현재 실제 출제 가능한 과목:"]
        lines.extend(
            f"- {row['id']}: {row['name']} ({row['available_questions']}문항, exam-ready {row['exam_ready_questions']}문항, {row['bank_rounds']:g}회분)"
            for row in supported
        )
        lines.append("")
        lines.append("계획 단계 과목:")
        lines.extend(f"- {row['id']}: {row['name']}" for row in planned)
        return text_result("\n".join(lines), payload)

    if name == "start_session":
        with ready_conn() as conn:
            regular = bool(arguments.get("regular", False))
            mode = str(arguments.get("mode", "custom-cbt"))
            session_mode = "exam-ready" if regular and mode == "exam-ready" else ("regular-mock" if regular else mode)
            view = create_session(
                conn,
                exam_id=arguments.get("exam", "SQLD"),
                count=None if regular else arguments.get("count", 20),
                mode=session_mode,
                seed=arguments.get("seed"),
            )
        return text_result(f"session_id: {view.session_id}\n\n{render_question(view)}", {"session_id": view.session_id})

    if name == "coverage_report":
        with ready_conn() as conn:
            report = coverage_report(conn, arguments.get("exam", "SQLD"))
        return text_result(render_coverage_report(report), report)

    if name == "inspect_info_processing_archives":
        from pathlib import Path

        report = inspect_info_processing_archives(Path(arguments["path"]))
        return text_result(render_info_processing_archive_report(report), report)

    if name == "submit_answer":
        with ready_conn() as conn:
            _correct, next_view = submit_answer(conn, arguments["session_id"], int(arguments["answer"]))
        if next_view is None:
            return text_result(
                "답변을 기록했습니다.\n\n모든 문제에 답했습니다. finish_session을 호출해 결과를 생성하세요.",
                {"done": True},
            )
        return text_result(f"답변을 기록했습니다.\n\n{render_question(next_view)}", {"done": False})

    if name == "finish_session":
        with ready_conn() as conn:
            finish_session(conn, arguments["session_id"], allow_incomplete=bool(arguments.get("allow_incomplete", False)))
            outputs = write_study_outputs(conn, arguments["session_id"])
            report = render_session_report(conn, arguments["session_id"])
            sync_plan = None
            if arguments.get("prepare_notion_sync", False):
                sync_plan = prepare_notion_sync_plan(conn, arguments["session_id"])
        text = (
            f"{report}\nreport_path: {outputs['report_path']}"
            f"\nobsidian_session_note: {outputs['obsidian']['session_note']}"
            f"\nobsidian_review_queue: {outputs['obsidian']['review_queue']}"
        )
        if sync_plan is not None:
            text += "\n\n## Notion 동기화 계획\n" + render_plan(sync_plan)
        return text_result(
            text,
            {
                "report_path": str(outputs["report_path"]),
                "obsidian": outputs["obsidian"],
                "notion_sync": sync_plan,
            },
        )

    if name == "prepare_notion_sync":
        with ready_conn() as conn:
            plan = prepare_notion_sync_plan(conn, arguments["session_id"])
        return text_result(render_plan(plan), plan)

    raise ValueError(f"알 수 없는 도구입니다: {name}")


def ready_conn():
    conn = connect()
    initialize(conn)
    seed_public_banks(conn)
    return conn


def text_result(text: str, structured: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if structured is not None:
        payload["structuredContent"] = structured
    return payload


def result(message: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message.get("id"), "result": value}


def error(message: dict[str, Any], code: int, message_text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": code, "message": message_text}}


def read_message(stream) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if line == b"":
            return None
        if line in {b"\r\n", b"\n"}:
            break
        key, _, value = line.decode("ascii").partition(":")
        headers[key.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    return json.loads(stream.read(length).decode("utf-8"))


def write_message(stream, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)


if __name__ == "__main__":
    raise SystemExit(main())
