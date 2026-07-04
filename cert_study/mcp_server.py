from __future__ import annotations

import json
import sys
from typing import Any

from .db import connect, initialize
from .engine import create_session, finish_session, get_next_unanswered, submit_answer
from .gold import (
    audit_final_bank,
    audit_final_state,
    audit_readiness,
    render_final_audit_report,
    render_final_state_report,
    render_readiness_report,
)
from .notion_sync import prepare_notion_sync_plan, render_plan
from .quality import coverage_report, render_coverage_report
from .reporting import render_question, render_session_report, write_study_outputs
from .seed_public import seed_public_banks


PROTOCOL_VERSION = "2024-11-05"


TOOLS: list[dict[str, Any]] = [
    {
        "name": "init_study_db",
        "description": "로컬 SQLite 학습 DB를 초기화하고 SQLD 공개 데모 문항을 seed한다.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_exams",
        "description": "현재 로컬 DB에 실제 문제은행이 있는 시험을 확인한다.",
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
                    "enum": ["custom-cbt", "review-cbt", "weak-cbt", "exam-ready", "final-mock", "source-backed"],
                    "default": "custom-cbt",
                    "description": "custom-cbt는 미노출 우선, review-cbt는 복습 예정/오답 우선, weak-cbt는 취약 개념 우선, exam-ready/final-mock은 gold 문항만, source-backed는 검수 전이라도 출처 기반 문항만 출제합니다.",
                },
                "seed": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "coverage_report",
        "description": "공식 출제 비중 기준으로 gold exam-ready 문제은행 품질을 점검한다.",
        "inputSchema": {
            "type": "object",
            "properties": {"exam": {"type": "string", "default": "SQLD"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "final_audit_report",
        "description": "gold 문제은행이 placeholder 해설, 임시 개념, 출제범위 누락 없이 바로 학습 가능한지 점검한다.",
        "inputSchema": {
            "type": "object",
            "properties": {"exam": {"type": "string", "default": "SQLD"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "readiness_audit_report",
        "description": "전체 과목이 정규 시험 대비 기준을 충족하는지 점검한다.",
        "inputSchema": {
            "type": "object",
            "properties": {"min_rounds": {"type": "integer", "default": 3, "minimum": 1}},
            "additionalProperties": False,
        },
    },
    {
        "name": "final_state_report",
        "description": "최종 사용 가능 상태인지 판정하고 과목별 gold 보강/추가 수집 부족분을 산출한다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_rounds": {"type": "integer", "default": 3, "minimum": 1},
                "exams": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_answer",
        "description": "현재 세션에 답변을 제출하고 다음 문제가 있으면 반환한다. 복수정답은 '1,3' 또는 [1,3]으로 제출한다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "answer": {
                    "oneOf": [
                        {"type": "integer", "minimum": 1},
                        {"type": "string"},
                        {"type": "array", "items": {"type": "integer", "minimum": 1}, "minItems": 1},
                    ]
                },
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
                "serverInfo": {"name": "cert-study", "version": "0.5.3"},
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
                           AND q.validity_status = 'current'
                           AND q.gold_status = 'gold'
                           AND q.source_tier IN ('official_sample', 'open_license', 'user_owned', 'licensed_private')
                           AND q.question_type IN ('single_choice', 'multiple_response')
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
        payload = {
            "available": supported,
            "planned": [],
            "note": "현재 CBT 세션으로 실제 출제 가능한 문제은행은 available 항목뿐입니다. 공개 기본값은 SQLD 데모이며, 다른 과목은 로컬 import 후에만 나타납니다.",
        }
        lines = ["현재 실제 출제 가능한 과목:"]
        lines.extend(
            f"- {row['id']}: {row['name']} ({row['available_questions']}문항, exam-ready {row['exam_ready_questions']}문항, {row['bank_rounds']:g}회분)"
            for row in supported
        )
        return text_result("\n".join(lines), payload)

    if name == "start_session":
        with ready_conn() as conn:
            regular = bool(arguments.get("regular", False))
            mode = str(arguments.get("mode", "custom-cbt"))
            session_mode = "exam-ready" if regular and mode == "exam-ready" else ("final-mock" if regular else mode)
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

    if name == "final_audit_report":
        with ready_conn() as conn:
            report = audit_final_bank(conn, arguments.get("exam", "SQLD"))
        return text_result(render_final_audit_report(report), report)

    if name == "readiness_audit_report":
        with ready_conn() as conn:
            report = audit_readiness(conn, min_rounds=int(arguments.get("min_rounds", 3)))
        return text_result(render_readiness_report(report), report)

    if name == "final_state_report":
        with ready_conn() as conn:
            report = audit_final_state(
                conn,
                min_rounds=int(arguments.get("min_rounds", 3)),
                exam_ids=arguments.get("exams"),
            )
        return text_result(render_final_state_report(report), report)

    if name == "submit_answer":
        with ready_conn() as conn:
            _correct, next_view = submit_answer(conn, arguments["session_id"], arguments["answer"])
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
