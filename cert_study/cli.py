from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .db import connect, initialize
from .engine import create_session, finish_session, get_next_unanswered, submit_answer, today_iso
from .importer import import_bank_file
from .notion_sync import prepare_notion_sync_plan, render_plan
from .paths import db_path
from .reporting import render_question, render_session_report, write_study_outputs
from .seed_public import seed_public_banks


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, sqlite3.Error) as exc:
        print(f"error: {exc}")
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cert-study", description="Codex 기반 자격증 CBT 학습 시스템.")
    sub = parser.add_subparsers(required=True)

    init = sub.add_parser("init", help="SQLite DB를 초기화하고 공개 합성 훈련 문제은행을 seed합니다.")
    init.add_argument("--reset", action="store_true", help="초기화 전에 기존 로컬 DB를 삭제합니다.")
    init.set_defaults(func=cmd_init)

    stats = sub.add_parser("stats", help="문제은행 통계를 보여줍니다.")
    stats.set_defaults(func=cmd_stats)

    bank = sub.add_parser("bank", help="개인 문제은행 import를 관리합니다.")
    bank_sub = bank.add_subparsers(required=True)

    bank_import = bank_sub.add_parser("import", help="JSON/YAML 문제은행 파일을 로컬 SQLite에 가져옵니다.")
    bank_import.add_argument("path", type=Path)
    bank_import.add_argument("--private", action="store_true", help="개인 소유 요약/오답 기반 문제은행 import를 허용합니다.")
    bank_import.set_defaults(func=cmd_bank_import)

    session = sub.add_parser("session", help="CBT 세션을 관리합니다.")
    session_sub = session.add_subparsers(required=True)

    start = session_sub.add_parser("start", help="CBT 세션을 시작합니다.")
    start.add_argument("--exam", default="SQLD")
    start.add_argument("--count", type=int)
    start.add_argument("--regular", action="store_true", help="시험의 정규 문항 수를 사용합니다.")
    start.add_argument(
        "--mode",
        default="custom-cbt",
        choices=["custom-cbt", "review-cbt", "weak-cbt"],
        help="custom-cbt는 미노출 우선, review-cbt는 복습 예정/오답 우선, weak-cbt는 취약 개념 우선입니다.",
    )
    start.add_argument("--seed", type=int, help="문항 선택을 재현하기 위한 seed입니다.")
    start.set_defaults(func=cmd_session_start)

    answer = session_sub.add_parser("answer", help="다음 미응답 문제에 답을 제출합니다.")
    answer.add_argument("session_id")
    answer.add_argument("answer", type=int)
    answer.set_defaults(func=cmd_session_answer)

    current = session_sub.add_parser("current", help="다음 미응답 문제를 보여줍니다.")
    current.add_argument("session_id")
    current.set_defaults(func=cmd_session_current)

    finish = session_sub.add_parser("finish", help="세션을 종료하고 리포트를 작성합니다.")
    finish.add_argument("session_id")
    finish.add_argument("--allow-incomplete", action="store_true")
    finish.set_defaults(func=cmd_session_finish)

    report = sub.add_parser("report", help="기존 세션 리포트를 렌더링합니다.")
    report.add_argument("session_id")
    report.set_defaults(func=cmd_report)

    notion = sub.add_parser("notion", help="기본 비활성 Notion 동기화 계획을 준비합니다.")
    notion_sub = notion.add_subparsers(required=True)

    notion_plan = notion_sub.add_parser("plan", help="완료된 세션의 Notion 동기화 계획을 만듭니다.")
    notion_plan.add_argument("session_id")
    notion_plan.set_defaults(func=cmd_notion_plan)

    return parser


def cmd_init(args: argparse.Namespace) -> int:
    if args.reset and db_path().exists():
        db_path().unlink()
    with connect() as conn:
        initialize(conn)
        seed_public_banks(conn)
    print(f"초기화 완료: {db_path()}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        summaries = conn.execute(
            """
            SELECT
              e.id AS exam,
              e.name AS name,
              e.official_question_count AS official_count,
              COUNT(DISTINCT q.id) AS available_count,
              COUNT(DISTINCT sq.question_id) AS seen_count,
              COUNT(DISTINCT a.question_id) AS attempted_count,
              COUNT(DISTINCT CASE WHEN rq.next_review_at <= ? THEN rq.question_id END) AS due_review_count
            FROM exams e
            LEFT JOIN questions q ON q.exam_id = e.id
            LEFT JOIN session_questions sq ON sq.question_id = q.id
            LEFT JOIN attempts a ON a.question_id = q.id
            LEFT JOIN review_queue rq ON rq.question_id = q.id
            GROUP BY e.id, e.name, e.official_question_count
            ORDER BY e.id
            """,
            (today_iso(),),
        ).fetchall()
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
    for row in summaries:
        rounds = round(row["available_count"] / row["official_count"], 2) if row["official_count"] else 0
        unseen = row["available_count"] - row["seen_count"]
        print(
            f"{row['exam']} | 총 {row['available_count']}문항 | 정규 {row['official_count']}문항 | "
            f"{rounds:g}회분 | 미노출 {unseen}문항 | 풀이 {row['attempted_count']}문항 | "
            f"복습예정 {row['due_review_count']}문항"
        )
    print("")
    for row in rows:
        print(f"{row['exam']} | {row['domain']} | {row['questions']}문항")
    return 0


def cmd_bank_import(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        result = import_bank_file(conn, args.path, private=args.private)
    print(
        f"문제은행 import 완료: {result['exam_id']} "
        f"도메인 {result['domains']}개, 개념 {result['concepts']}개, 문항 {result['questions']}개"
    )
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
    print("답변을 기록했습니다.")
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
        print("미응답 문제가 없습니다.")
        return 0
    print(render_question(view))
    return 0


def cmd_session_finish(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        result = finish_session(conn, args.session_id, allow_incomplete=args.allow_incomplete)
        outputs = write_study_outputs(conn, args.session_id)
        report = render_session_report(conn, args.session_id)
    print(report)
    print(f"report_path: {outputs['report_path']}")
    print(f"obsidian_session_note: {outputs['obsidian']['session_note']}")
    print(f"obsidian_review_queue: {outputs['obsidian']['review_queue']}")
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
        raise ValueError("database가 없습니다. 먼저 실행하세요: python -m cert_study init")
    conn = connect()
    initialize(conn)
    seed_public_banks(conn)
    return conn
