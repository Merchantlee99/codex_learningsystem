from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .db import connect, initialize
from .engine import create_session, finish_session, get_next_unanswered, submit_answer
from .notion_sync import prepare_notion_sync_plan, render_plan
from .paths import db_path
from .reporting import render_question, render_session_report, write_session_report
from .seed_sqld import seed as seed_sqld


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, sqlite3.Error) as exc:
        print(f"error: {exc}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cert-study", description="Codex-native certification CBT study system.")
    sub = parser.add_subparsers(required=True)

    init = sub.add_parser("init", help="Initialize SQLite DB and seed SQLD training data.")
    init.add_argument("--reset", action="store_true", help="Remove existing local DB before initialization.")
    init.set_defaults(func=cmd_init)

    stats = sub.add_parser("stats", help="Show question-bank stats.")
    stats.set_defaults(func=cmd_stats)

    session = sub.add_parser("session", help="Manage CBT sessions.")
    session_sub = session.add_subparsers(required=True)

    start = session_sub.add_parser("start", help="Start a CBT session.")
    start.add_argument("--exam", default="SQLD")
    start.add_argument("--count", type=int)
    start.add_argument("--regular", action="store_true", help="Use official question count for the exam.")
    start.add_argument("--mode", default="custom-cbt")
    start.add_argument("--seed", type=int, help="Deterministic question selection seed.")
    start.set_defaults(func=cmd_session_start)

    answer = session_sub.add_parser("answer", help="Submit an answer for the next unanswered question.")
    answer.add_argument("session_id")
    answer.add_argument("answer", type=int)
    answer.set_defaults(func=cmd_session_answer)

    current = session_sub.add_parser("current", help="Show the next unanswered question.")
    current.add_argument("session_id")
    current.set_defaults(func=cmd_session_current)

    finish = session_sub.add_parser("finish", help="Finish a session and write reports.")
    finish.add_argument("session_id")
    finish.add_argument("--allow-incomplete", action="store_true")
    finish.set_defaults(func=cmd_session_finish)

    report = sub.add_parser("report", help="Render an existing session report.")
    report.add_argument("session_id")
    report.set_defaults(func=cmd_report)

    notion = sub.add_parser("notion", help="Prepare disabled-by-default Notion sync plans.")
    notion_sub = notion.add_subparsers(required=True)

    notion_plan = notion_sub.add_parser("plan", help="Prepare a Notion sync plan for a finished session.")
    notion_plan.add_argument("session_id")
    notion_plan.set_defaults(func=cmd_notion_plan)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    if args.reset and db_path().exists():
        db_path().unlink()
    with connect() as conn:
        initialize(conn)
        seed_sqld(conn)
    print(f"initialized: {db_path()}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        rows = conn.execute(
            """
            SELECT e.id AS exam, d.name AS domain, COUNT(q.id) AS questions
            FROM exams e
            JOIN domains d ON d.exam_id = e.id
            LEFT JOIN questions q ON q.domain_id = d.id
            GROUP BY e.id, d.id, d.name
            ORDER BY e.id, d.id
            """
        ).fetchall()
    for row in rows:
        print(f"{row['exam']} | {row['domain']} | {row['questions']} questions")
    return 0


def cmd_session_start(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        if args.regular:
            count = None
            mode = "regular-mock"
        else:
            count = args.count or 20
            mode = args.mode
        view = create_session(conn, exam_id=args.exam, count=count, mode=mode, seed=args.seed)
    print(f"session_id: {view.session_id}")
    print("")
    print(render_question(view))
    return 0


def cmd_session_answer(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        _is_correct, next_view = submit_answer(conn, args.session_id, args.answer)
    print("answer recorded")
    print("")
    if next_view is None:
        print("모든 문제에 답했습니다. 결과를 보려면 다음 명령을 실행하세요.")
        print(f"python -m cert_study session finish {args.session_id}")
    else:
        print(render_question(next_view))
    return 0


def cmd_session_current(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        view = get_next_unanswered(conn, args.session_id)
    if view is None:
        print("no unanswered questions")
        return 0
    print(render_question(view))
    return 0


def cmd_session_finish(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        result = finish_session(conn, args.session_id, allow_incomplete=args.allow_incomplete)
        report_path = write_session_report(conn, args.session_id)
        report = render_session_report(conn, args.session_id)
    print(report)
    print(f"report_path: {report_path}")
    print(f"score_summary: {result['correct']}/{result['total']} ({result['score']}점) - {result['judgement']}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        print(render_session_report(conn, args.session_id))
    return 0


def cmd_notion_plan(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        print(render_plan(prepare_notion_sync_plan(conn, args.session_id)))
    return 0


def ready_conn():
    if not Path(db_path()).exists():
        raise ValueError("database is missing. Run: python -m cert_study init")
    return connect()
