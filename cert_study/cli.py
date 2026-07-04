from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .db import connect, initialize
from .engine import create_session, finish_session, get_next_unanswered, submit_answer, today_iso
from .gold import audit_final_bank, export_gold_template, promote_gold_candidates, render_final_audit_report
from .importer import import_bank_file
from .enrichers.sqld_gold import enrich_sqld_gold_file
from .importers.chathuranga_saa import (
    convert_chathuranga_saa_markdown,
    inspect_chathuranga_saa_markdown,
    render_chathuranga_convert_report,
    render_chathuranga_inspect_report,
)
from .importers.gcp_gail import SOURCE_REPOSITORY, convert_gail_exam_data_file
from .importers.info_processing import (
    convert_info_processing_archives,
    inspect_info_processing_archives,
    render_info_processing_archive_report,
    render_info_processing_convert_report,
)
from .importers.kdata_text import (
    convert_kdata_text_sources,
    inspect_kdata_text_sources,
    render_kdata_convert_report,
    render_kdata_inspect_report,
)
from .notion_sync import prepare_notion_sync_plan, render_plan
from .paths import db_path
from .quality import coverage_report, promote_gcp_gail_questions, render_coverage_report
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

    coverage = sub.add_parser("coverage", help="공식 출제 비중 기준으로 gold exam-ready 문제은행 품질을 점검합니다.")
    coverage.add_argument("--exam", default="SQLD")
    coverage.set_defaults(func=cmd_coverage)

    audit = sub.add_parser("audit", help="최종 학습 가능 상태를 검수합니다.")
    audit_sub = audit.add_subparsers(required=True)

    audit_final = audit_sub.add_parser("final", help="gold 문제은행이 바로 학습 가능한지 검수합니다.")
    audit_final.add_argument("--exam", default="SQLD")
    audit_final.set_defaults(func=cmd_audit_final)

    bank = sub.add_parser("bank", help="개인 문제은행 import를 관리합니다.")
    bank_sub = bank.add_subparsers(required=True)

    bank_import = bank_sub.add_parser("import", help="JSON/YAML 문제은행 파일을 로컬 SQLite에 가져옵니다.")
    bank_import.add_argument("path", type=Path)
    bank_import.add_argument("--private", action="store_true", help="개인 소유 요약/오답 기반 문제은행 import를 허용합니다.")
    bank_import.set_defaults(func=cmd_bank_import)

    bank_promote_gold = bank_sub.add_parser(
        "promote-gold",
        help="근거 필드가 완성된 candidate 문항을 gold_status=gold로 승격합니다.",
    )
    bank_promote_gold.add_argument("--exam", required=True)
    bank_promote_gold.add_argument("--checked-at", required=True, help="검수일. 예: 2026-07-04")
    bank_promote_gold.add_argument("--dry-run", action="store_true", help="승격 가능 여부만 확인하고 DB를 수정하지 않습니다.")
    bank_promote_gold.set_defaults(func=cmd_bank_promote_gold)

    bank_export_gold = bank_sub.add_parser(
        "export-gold-template",
        help="현재 DB의 문항을 gold 검수용 JSON 템플릿으로 내보냅니다. 출력 파일은 private_banks/gold_banks/에 두는 것을 권장합니다.",
    )
    bank_export_gold.add_argument("--exam", required=True)
    bank_export_gold.add_argument("output", type=Path)
    bank_export_gold.set_defaults(func=cmd_bank_export_gold_template)

    bank_enrich_sqld = bank_sub.add_parser(
        "enrich-sqld-gold",
        help="SQLD source-backed JSON을 세부 개념/정답근거/오답근거가 있는 gold JSON으로 보강합니다.",
    )
    bank_enrich_sqld.add_argument("source", type=Path)
    bank_enrich_sqld.add_argument("output", type=Path)
    bank_enrich_sqld.add_argument("--checked-at", required=True, help="검수일. 예: 2026-07-04")
    bank_enrich_sqld.add_argument(
        "--prefer-source-contains",
        default="",
        help="특정 원천 파일명이 포함된 문항을 먼저 배치합니다. 예: sqld_2025_58.html",
    )
    bank_enrich_sqld.add_argument("--limit", type=int, help="보강할 최대 문항 수입니다.")
    bank_enrich_sqld.set_defaults(func=cmd_bank_enrich_sqld_gold)

    bank_convert_gcp = bank_sub.add_parser(
        "convert-gcp-gail",
        help="로컬 GCP Generative AI Leader exam-data.ts를 import-ready JSON으로 변환합니다.",
    )
    bank_convert_gcp.add_argument("source", type=Path, help="gail-exam-preparation/lib/exam-data.ts 경로")
    bank_convert_gcp.add_argument("output", type=Path, help="생성할 import-ready JSON 경로")
    bank_convert_gcp.add_argument("--source-ref", default=SOURCE_REPOSITORY, help="출처로 남길 URL 또는 식별자")
    bank_convert_gcp.set_defaults(func=cmd_bank_convert_gcp_gail)

    bank_promote_gcp = bank_sub.add_parser(
        "promote-gcp-gail",
        help="공식 문서 URL이 있는 GCP GAIL open-license 문항을 exam-ready 후보로 승격합니다.",
    )
    bank_promote_gcp.add_argument("--checked-at", required=True, help="검수일. 예: 2026-07-03")
    bank_promote_gcp.set_defaults(func=cmd_bank_promote_gcp_gail)

    bank_inspect_info = bank_sub.add_parser(
        "inspect-info-processing",
        help="정보처리기사 private ZIP/PDF 후보를 점검합니다. 원문은 import하지 않습니다.",
    )
    bank_inspect_info.add_argument("path", type=Path)
    bank_inspect_info.set_defaults(func=cmd_bank_inspect_info_processing)

    bank_convert_info = bank_sub.add_parser(
        "convert-info-processing",
        help="정보처리기사 private ZIP/PDF 기출을 내부 CBT import-ready JSON으로 변환합니다.",
    )
    bank_convert_info.add_argument("source", type=Path)
    bank_convert_info.add_argument("output", type=Path)
    bank_convert_info.add_argument(
        "--mark-active",
        action="store_true",
        help="검수 완료로 보고 exam-ready 후보가 되도록 active/current 상태로 저장합니다.",
    )
    bank_convert_info.add_argument("--checked-at", default="", help="--mark-active 사용 시 검수일. 예: 2026-07-03")
    bank_convert_info.add_argument(
        "--min-questions",
        type=int,
        default=90,
        help="PDF 한 개에서 최소 몇 문항 이상 변환되어야 포함할지 정합니다. 기본값은 90입니다.",
    )
    bank_convert_info.set_defaults(func=cmd_bank_convert_info_processing)

    bank_inspect_kdata = bank_sub.add_parser(
        "inspect-kdata",
        help="SQLD/ADSP private 텍스트/PDF/HTML 원천의 변환 가능 문항 수를 점검합니다.",
    )
    bank_inspect_kdata.add_argument("--exam", required=True, choices=["SQLD", "ADSP"])
    bank_inspect_kdata.add_argument("source", type=Path)
    bank_inspect_kdata.set_defaults(func=cmd_bank_inspect_kdata)

    bank_convert_kdata = bank_sub.add_parser(
        "convert-kdata",
        help="SQLD/ADSP private 텍스트/PDF/HTML 원천을 내부 CBT import-ready JSON으로 변환합니다.",
    )
    bank_convert_kdata.add_argument("--exam", required=True, choices=["SQLD", "ADSP"])
    bank_convert_kdata.add_argument("source", type=Path)
    bank_convert_kdata.add_argument("output", type=Path)
    bank_convert_kdata.add_argument(
        "--mark-active",
        action="store_true",
        help="검수 완료로 보고 exam-ready 후보가 되도록 active/current 상태로 저장합니다.",
    )
    bank_convert_kdata.add_argument("--checked-at", default="", help="--mark-active 사용 시 검수일. 예: 2026-07-03")
    bank_convert_kdata.add_argument(
        "--min-questions",
        type=int,
        default=1,
        help="파일 한 개에서 최소 몇 문항 이상 변환되어야 포함할지 정합니다. 기본값은 1입니다.",
    )
    bank_convert_kdata.set_defaults(func=cmd_bank_convert_kdata)

    bank_inspect_saa = bank_sub.add_parser(
        "inspect-chathuranga-saa",
        help="MIT 라이선스 Chathuranga SAA-C03 Markdown 원천의 변환 가능 문항 수를 점검합니다.",
    )
    bank_inspect_saa.add_argument("source", type=Path)
    bank_inspect_saa.set_defaults(func=cmd_bank_inspect_chathuranga_saa)

    bank_convert_saa = bank_sub.add_parser(
        "convert-chathuranga-saa",
        help="MIT 라이선스 Chathuranga SAA-C03 Markdown 원천을 내부 CBT import-ready JSON으로 변환합니다.",
    )
    bank_convert_saa.add_argument("source", type=Path)
    bank_convert_saa.add_argument("output", type=Path)
    bank_convert_saa.add_argument(
        "--mark-active",
        action="store_true",
        help="검수 완료로 보고 exam-ready 후보가 되도록 active/current 상태로 저장합니다.",
    )
    bank_convert_saa.add_argument("--checked-at", default="", help="--mark-active 사용 시 검수일. 예: 2026-07-04")
    bank_convert_saa.set_defaults(func=cmd_bank_convert_chathuranga_saa)

    session = sub.add_parser("session", help="CBT 세션을 관리합니다.")
    session_sub = session.add_subparsers(required=True)

    start = session_sub.add_parser("start", help="CBT 세션을 시작합니다.")
    start.add_argument("--exam", default="SQLD")
    start.add_argument("--count", type=int)
    start.add_argument("--regular", action="store_true", help="시험의 정규 문항 수를 사용합니다.")
    start.add_argument(
        "--mode",
        default="custom-cbt",
        choices=["custom-cbt", "review-cbt", "weak-cbt", "exam-ready", "source-backed"],
        help="custom-cbt는 미노출 우선, review-cbt는 복습 예정/오답 우선, weak-cbt는 취약 개념 우선, exam-ready는 gold 문항만, source-backed는 검수 전이라도 출처 기반 문항만 출제합니다.",
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
              COUNT(
                DISTINCT CASE
                  WHEN q.quality_status = 'active'
                   AND q.validity_status = 'current'
                   AND q.gold_status = 'gold'
                   AND q.source_tier IN ('official_sample', 'open_license', 'user_owned', 'licensed_private')
                   AND q.question_type = 'single_choice'
                  THEN q.id
                END
              ) AS exam_ready_count,
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
            f"{row['exam']} | 총 {row['available_count']}문항 | exam-ready {row['exam_ready_count']}문항 | 정규 {row['official_count']}문항 | "
            f"{rounds:g}회분 | 미노출 {unseen}문항 | 풀이 {row['attempted_count']}문항 | "
            f"복습예정 {row['due_review_count']}문항"
        )
    print("")
    for row in rows:
        print(f"{row['exam']} | {row['domain']} | {row['questions']}문항")
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        print(render_coverage_report(coverage_report(conn, args.exam)))
    return 0


def cmd_audit_final(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        report = audit_final_bank(conn, args.exam)
    print(render_final_audit_report(report))
    return 0 if report["ready"] else 2


def cmd_bank_import(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        result = import_bank_file(conn, args.path, private=args.private)
    print(
        f"문제은행 import 완료: {result['exam_id']} "
        f"도메인 {result['domains']}개, 개념 {result['concepts']}개, 문항 {result['questions']}개"
    )
    return 0


def cmd_bank_promote_gold(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        result = promote_gold_candidates(
            conn,
            args.exam,
            checked_at=args.checked_at,
            dry_run=bool(args.dry_run),
        )
    print(
        f"gold 승격 점검 완료: {result['exam_id']} 후보 {result['candidates']}문항, "
        f"승격 가능 {result['promoted']}문항, 제외 {result['skipped']}문항"
    )
    if result["skipped_examples"]:
        print("제외 예시:")
        for row in result["skipped_examples"]:
            print(f"- {row['question_id']}: {', '.join(row['codes'])}")
    return 0


def cmd_bank_export_gold_template(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        result = export_gold_template(conn, args.exam, args.output)
    print(f"gold 검수 템플릿 생성 완료: {result['output']} ({result['questions']}문항)")
    return 0


def cmd_bank_enrich_sqld_gold(args: argparse.Namespace) -> int:
    result = enrich_sqld_gold_file(
        args.source,
        args.output,
        checked_at=args.checked_at,
        prefer_source_contains=args.prefer_source_contains,
        limit=args.limit,
    )
    print(
        f"SQLD gold 보강 완료: {result['output']} "
        f"문항 {result['questions']}개, 개념 {result['concepts']}개, 검수일 {result['checked_at']}"
    )
    return 0


def cmd_bank_convert_gcp_gail(args: argparse.Namespace) -> int:
    payload = convert_gail_exam_data_file(args.source, args.output, source_ref=args.source_ref)
    print(
        f"GCP Generative AI Leader 변환 완료: {args.output} "
        f"개념 {len(payload['concepts'])}개, 문항 {len(payload['questions'])}개"
    )
    return 0


def cmd_bank_promote_gcp_gail(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        result = promote_gcp_gail_questions(conn, checked_at=args.checked_at)
    print(
        f"GCP Generative AI Leader 승격 완료: 후보 {result['candidates']}문항, "
        f"승격 {result['promoted']}문항, 제외 {result['skipped']}문항"
    )
    return 0


def cmd_bank_inspect_info_processing(args: argparse.Namespace) -> int:
    print(render_info_processing_archive_report(inspect_info_processing_archives(args.path)))
    return 0


def cmd_bank_convert_info_processing(args: argparse.Namespace) -> int:
    report = convert_info_processing_archives(
        args.source,
        args.output,
        mark_active=bool(args.mark_active),
        checked_at=args.checked_at,
        min_questions=args.min_questions,
    )
    print(render_info_processing_convert_report(report))
    return 0


def cmd_bank_inspect_kdata(args: argparse.Namespace) -> int:
    report = inspect_kdata_text_sources(args.source, exam_id=args.exam)
    print(render_kdata_inspect_report(report))
    return 0


def cmd_bank_convert_kdata(args: argparse.Namespace) -> int:
    report = convert_kdata_text_sources(
        args.source,
        args.output,
        exam_id=args.exam,
        mark_active=bool(args.mark_active),
        checked_at=args.checked_at,
        min_questions=args.min_questions,
    )
    print(render_kdata_convert_report(report))
    return 0


def cmd_bank_inspect_chathuranga_saa(args: argparse.Namespace) -> int:
    print(render_chathuranga_inspect_report(inspect_chathuranga_saa_markdown(args.source)))
    return 0


def cmd_bank_convert_chathuranga_saa(args: argparse.Namespace) -> int:
    report = convert_chathuranga_saa_markdown(
        args.source,
        args.output,
        mark_active=bool(args.mark_active),
        checked_at=args.checked_at,
    )
    print(render_chathuranga_convert_report(report))
    return 0


def cmd_session_start(args: argparse.Namespace) -> int:
    with ready_conn() as conn:
        if args.regular:
            count = None
            mode = "exam-ready" if args.mode == "exam-ready" else "regular-mock"
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
