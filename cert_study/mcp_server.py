from __future__ import annotations

import json
import sys
from typing import Any

from .db import connect, initialize
from .engine import create_session, finish_session, get_next_unanswered, submit_answer
from .notion_sync import prepare_notion_sync_plan, render_plan
from .reporting import render_question, render_session_report, write_session_report
from .seed_sqld import seed as seed_sqld


PROTOCOL_VERSION = "2024-11-05"


TOOLS: list[dict[str, Any]] = [
    {
        "name": "init_study_db",
        "description": "Initialize the local SQLite study database and seed SQLD synthetic training questions.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "start_session",
        "description": "Start a CBT-style certification study session and return the first question.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "exam": {"type": "string", "default": "SQLD"},
                "count": {"type": "integer", "minimum": 1},
                "regular": {"type": "boolean", "default": False},
                "seed": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "submit_answer",
        "description": "Submit a 1-4 answer for the current session and return the next question when available.",
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
        "description": "Finish a completed session, write reports, and return the detailed result report.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "allow_incomplete": {"type": "boolean", "default": False},
                "prepare_notion_sync": {"type": "boolean", "default": True},
            },
            "required": ["session_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "prepare_notion_sync",
        "description": "Prepare a disabled-by-default Notion sync plan for a finished session.",
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
                "serverInfo": {"name": "cert-study", "version": "0.2.0"},
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
        except Exception as exc:  # MCP tool errors should be visible to the caller.
            return result(message, {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True})
    return error(message, -32601, f"method not found: {method}")


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "init_study_db":
        with connect() as conn:
            initialize(conn)
            seed_sqld(conn)
        return text_result("initialized local study database")

    if name == "start_session":
        with ready_conn() as conn:
            regular = bool(arguments.get("regular", False))
            view = create_session(
                conn,
                exam_id=arguments.get("exam", "SQLD"),
                count=None if regular else arguments.get("count", 20),
                mode="regular-mock" if regular else "custom-cbt",
                seed=arguments.get("seed"),
            )
        return text_result(f"session_id: {view.session_id}\n\n{render_question(view)}", {"session_id": view.session_id})

    if name == "submit_answer":
        with ready_conn() as conn:
            _correct, next_view = submit_answer(conn, arguments["session_id"], int(arguments["answer"]))
        if next_view is None:
            return text_result(
                "answer recorded\n\n모든 문제에 답했습니다. finish_session을 호출해 결과를 생성하세요.",
                {"done": True},
            )
        return text_result(f"answer recorded\n\n{render_question(next_view)}", {"done": False})

    if name == "finish_session":
        with ready_conn() as conn:
            finish_session(conn, arguments["session_id"], allow_incomplete=bool(arguments.get("allow_incomplete", False)))
            report_path = write_session_report(conn, arguments["session_id"])
            report = render_session_report(conn, arguments["session_id"])
            sync_plan = None
            if arguments.get("prepare_notion_sync", True):
                sync_plan = prepare_notion_sync_plan(conn, arguments["session_id"])
        text = f"{report}\nreport_path: {report_path}"
        if sync_plan is not None:
            text += "\n\n## Notion Sync Plan\n" + render_plan(sync_plan)
        return text_result(text, {"report_path": str(report_path), "notion_sync": sync_plan})

    if name == "prepare_notion_sync":
        with ready_conn() as conn:
            plan = prepare_notion_sync_plan(conn, arguments["session_id"])
        return text_result(render_plan(plan), plan)

    raise ValueError(f"unknown tool: {name}")


def ready_conn():
    conn = connect()
    initialize(conn)
    seed_sqld(conn)
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

