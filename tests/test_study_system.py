from __future__ import annotations

import os
import tempfile
import unittest
import json
import zipfile
from pathlib import Path

from cert_study.db import connect, initialize
from cert_study.engine import create_session, finish_session, get_next_unanswered, submit_answer
from cert_study.importer import import_bank_file
from cert_study.importers.gcp_gail import convert_gail_practice_questions_text
from cert_study.importers.info_processing import inspect_info_processing_archives
from cert_study.mcp_server import call_tool, handle_message
from cert_study.notion_sync import prepare_notion_sync_plan
from cert_study.quality import coverage_report, promote_gcp_gail_questions
from cert_study.reporting import render_session_report, write_session_report
from cert_study.seed_public import seed_public_banks


class StudySystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("CERT_STUDY_HOME")
        os.environ["CERT_STUDY_HOME"] = self.tmp.name
        self.conn = connect()
        initialize(self.conn)
        seed_public_banks(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        if self.old_home is None:
            os.environ.pop("CERT_STUDY_HOME", None)
        else:
            os.environ["CERT_STUDY_HOME"] = self.old_home
        self.tmp.cleanup()

    def test_sqld_seed_bank_has_official_count(self) -> None:
        count = self.conn.execute("SELECT COUNT(*) AS n FROM questions WHERE exam_id = 'SQLD'").fetchone()["n"]
        self.assertEqual(count, 50)

    def test_public_seed_banks_cover_adsp_and_info_processing(self) -> None:
        counts = {
            row["exam_id"]: row["n"]
            for row in self.conn.execute(
                "SELECT exam_id, COUNT(*) AS n FROM questions GROUP BY exam_id ORDER BY exam_id"
            ).fetchall()
        }

        self.assertEqual(counts["SQLD"], 50)
        self.assertEqual(counts["ADSP"], 50)
        self.assertEqual(counts["KR_INFO_PROCESSING_ENGINEER"], 100)

    def test_custom_20_question_session_uses_sqld_domain_ratio(self) -> None:
        first = create_session(self.conn, exam_id="SQLD", count=20, mode="custom-cbt", seed=7)
        rows = self.conn.execute(
            """
            SELECT d.name AS domain, COUNT(*) AS n
            FROM session_questions sq
            JOIN questions q ON q.id = sq.question_id
            JOIN domains d ON d.id = q.domain_id
            WHERE sq.session_id = ?
            GROUP BY d.name
            """,
            (first.session_id,),
        ).fetchall()
        by_domain = {row["domain"]: row["n"] for row in rows}
        self.assertEqual(by_domain["데이터 모델링의 이해"], 4)
        self.assertEqual(by_domain["SQL 기본 및 활용"], 16)

    def test_custom_session_prefers_unseen_questions_before_repeating(self) -> None:
        first = create_session(self.conn, exam_id="SQLD", count=10, mode="custom-cbt", seed=11)
        first_ids = set(session_question_ids(self.conn, first.session_id))
        answer_all_with_correct_answers(self.conn, first.session_id)
        finish_session(self.conn, first.session_id)

        second = create_session(self.conn, exam_id="SQLD", count=10, mode="custom-cbt", seed=11)
        second_ids = set(session_question_ids(self.conn, second.session_id))

        self.assertTrue(first_ids.isdisjoint(second_ids))

    def test_custom_session_avoids_recently_started_unanswered_questions(self) -> None:
        first = create_session(self.conn, exam_id="SQLD", count=10, mode="custom-cbt", seed=21)
        first_ids = set(session_question_ids(self.conn, first.session_id))

        second = create_session(self.conn, exam_id="SQLD", count=10, mode="custom-cbt", seed=21)
        second_ids = set(session_question_ids(self.conn, second.session_id))

        self.assertTrue(first_ids.isdisjoint(second_ids))

    def test_review_mode_prioritizes_due_wrong_questions(self) -> None:
        first = create_session(self.conn, exam_id="SQLD", count=10, mode="custom-cbt", seed=12)
        current = get_next_unanswered(self.conn, first.session_id)
        self.assertIsNotNone(current)
        wrong_question_id = current.question_id
        correct = correct_answer_for(self.conn, wrong_question_id)
        submit_answer(self.conn, first.session_id, 2 if correct != 2 else 1)
        answer_all_with_correct_answers(self.conn, first.session_id)
        finish_session(self.conn, first.session_id)
        self.conn.execute(
            "UPDATE review_queue SET next_review_at = '2000-01-01' WHERE question_id = ?",
            (wrong_question_id,),
        )
        self.conn.commit()

        review = create_session(self.conn, exam_id="SQLD", count=20, mode="review-cbt", seed=13)

        self.assertIn(wrong_question_id, session_question_ids(self.conn, review.session_id))

    def test_perfect_session_scores_100_and_passes(self) -> None:
        first = create_session(self.conn, exam_id="SQLD", count=10, mode="custom-cbt", seed=1)
        answer_all_with_correct_answers(self.conn, first.session_id)
        result = finish_session(self.conn, first.session_id)
        self.assertEqual(result["correct"], 10)
        self.assertEqual(result["score"], 100.0)
        self.assertIn("합격권", result["judgement"])

    def test_wrong_note_report_contains_answers_explanation_and_obsidian_notes(self) -> None:
        first = create_session(self.conn, exam_id="SQLD", count=5, mode="custom-cbt", seed=2)
        current = get_next_unanswered(self.conn, first.session_id)
        self.assertIsNotNone(current)
        correct = correct_answer_for(self.conn, current.question_id)
        wrong = 2 if correct != 2 else 1
        submit_answer(self.conn, first.session_id, wrong)
        answer_all_with_correct_answers(self.conn, first.session_id)

        finish_session(self.conn, first.session_id)
        report_path = write_session_report(self.conn, first.session_id)
        report = report_path.read_text(encoding="utf-8")

        self.assertIn("## 점수", report)
        self.assertIn("합격선", report)
        self.assertIn("## 틀린 문제", report)
        self.assertIn("내 답:", report)
        self.assertIn("정답:", report)
        self.assertIn("해설:", report)
        self.assertIn("내가 틀린 이유:", report)
        self.assertIn("## 오늘 복습할 개념", report)
        obsidian_dir = Path(self.tmp.name) / "obsidian_vault" / "certifications" / "SQLD"
        session_notes = list((obsidian_dir / "sessions").glob("*.md"))
        concept_notes = list((obsidian_dir / "concepts").glob("*.md"))
        self.assertEqual(len(session_notes), 1)
        self.assertGreaterEqual(len(concept_notes), 1)
        self.assertTrue((obsidian_dir / "review-queue.md").exists())
        obsidian_note = session_notes[0].read_text(encoding="utf-8")
        self.assertIn("type: study-session", obsidian_note)
        self.assertIn("[[certifications/SQLD/concepts/", obsidian_note)

    def test_custom_report_uses_exam_official_question_count(self) -> None:
        first = create_session(
            self.conn,
            exam_id="KR_INFO_PROCESSING_ENGINEER",
            count=5,
            mode="custom-cbt",
            seed=9,
        )
        answer_all_with_correct_answers(self.conn, first.session_id)
        finish_session(self.conn, first.session_id)

        report = render_session_report(self.conn, first.session_id)

        self.assertIn("정규 100문항", report)
        self.assertNotIn("정규 50문항", report)

    def test_notion_sync_plan_is_disabled_by_default(self) -> None:
        first = create_session(self.conn, exam_id="SQLD", count=5, mode="custom-cbt", seed=3)
        current = get_next_unanswered(self.conn, first.session_id)
        self.assertIsNotNone(current)
        correct = correct_answer_for(self.conn, current.question_id)
        submit_answer(self.conn, first.session_id, 2 if correct != 2 else 1)
        answer_all_with_correct_answers(self.conn, first.session_id)
        finish_session(self.conn, first.session_id)

        os.environ.pop("CERT_STUDY_ENABLE_NOTION_SYNC", None)
        plan = prepare_notion_sync_plan(self.conn, first.session_id)

        self.assertFalse(plan["enabled"])
        self.assertEqual(plan["status"], "disabled_public_default")
        self.assertGreaterEqual(len(plan["actions"]), 2)

    def test_plugin_manifest_declares_skill_and_mcp(self) -> None:
        manifest = json.loads((Path(__file__).resolve().parents[1] / ".codex-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["name"], "codex-learning-system")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["mcpServers"], "./.mcp.json")

    def test_mcp_config_runs_from_plugin_root(self) -> None:
        config = json.loads((Path(__file__).resolve().parents[1] / ".mcp.json").read_text())
        server = config["mcpServers"]["cert-study"]

        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["command"], "python3")
        self.assertEqual(server["cwd"], ".")
        self.assertEqual(server["args"], ["-m", "cert_study.mcp_server"])

    def test_mcp_tools_list_and_start_session(self) -> None:
        tools_response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tool_names = {tool["name"] for tool in tools_response["result"]["tools"]}
        self.assertIn("list_exams", tool_names)
        self.assertIn("start_session", tool_names)
        self.assertIn("prepare_notion_sync", tool_names)
        start_tool = next(tool for tool in tools_response["result"]["tools"] if tool["name"] == "start_session")
        self.assertIn("mode", start_tool["inputSchema"]["properties"])

        exams = call_tool("list_exams", {})
        available_ids = {row["id"] for row in exams["structuredContent"]["available"]}
        self.assertIn("SQLD", available_ids)
        self.assertIn("ADSP", available_ids)
        self.assertIn("KR_INFO_PROCESSING_ENGINEER", available_ids)
        sqld = next(row for row in exams["structuredContent"]["available"] if row["id"] == "SQLD")
        self.assertEqual(sqld["available_questions"], 50)
        self.assertEqual(sqld["bank_rounds"], 1.0)
        planned_ids = {row["id"] for row in exams["structuredContent"]["planned"]}
        self.assertIn("AWS_AI_PRACTITIONER", planned_ids)

        call_tool("init_study_db", {})
        result = call_tool("start_session", {"exam": "SQLD", "count": 5, "seed": 4})
        text = result["content"][0]["text"]
        self.assertIn("session_id:", text)
        self.assertIn("[1/5]", text)
        self.assertNotIn("[2/5]", text)
        self.assertNotIn("정답:", text)
        self.assertNotIn("정답표", text)

    def test_adsp_and_info_processing_sessions_start_one_question_only(self) -> None:
        call_tool("init_study_db", {})

        for exam in ("ADSP", "KR_INFO_PROCESSING_ENGINEER"):
            result = call_tool("start_session", {"exam": exam, "count": 5, "seed": 4})
            text = result["content"][0]["text"]
            self.assertIn("session_id:", text)
            self.assertIn("[1/5]", text)
            self.assertNotIn("[2/5]", text)
            self.assertNotIn("정답:", text)
            self.assertNotIn("정답표", text)

    def test_unsupported_exam_does_not_start_ad_hoc_generation(self) -> None:
        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "start_session",
                    "arguments": {"exam": "AWS_AI_PRACTITIONER", "count": 5},
                },
            }
        )

        self.assertTrue(response["result"]["isError"])
        text = response["result"]["content"][0]["text"]
        self.assertIn("지원하지 않는 시험", text)
        self.assertIn("SQLD", text)
        self.assertIn("ADSP", text)

    def test_skill_forbids_batch_generation_and_answer_keys(self) -> None:
        skill_text = (Path(__file__).resolve().parents[1] / "skills" / "cert-study" / "SKILL.md").read_text()

        self.assertIn("문제 N개 줘", skill_text)
        self.assertIn("일반 답변으로 문제를 만들지 말고", skill_text)
        self.assertIn("세션 종료 전에는 정답표", skill_text)
        self.assertIn("공개 repo에 기본 포함된 합성 문제은행은 SQLD, ADsP, 정보처리기사", skill_text)
        self.assertIn("`available`에 없으면 문제를 임의 생성하지 말고", skill_text)

    def test_private_bank_import_requires_private_flag(self) -> None:
        payload = {
            "exam": {
                "id": "PRIVATE_TEST",
                "name": "개인 문제은행 테스트",
                "official_question_count": 1,
                "official_duration_minutes": 10,
                "pass_score": 60,
                "domain_min_score": 0,
            },
            "domains": [{"id": "P-D1", "name": "개인 영역", "official_weight": 100, "official_question_count": 1}],
            "concepts": [{"id": "P-C1", "domain_id": "P-D1", "name": "개인 개념", "review_note": "개인 요약"}],
            "questions": [
                {
                    "id": "P-Q1",
                    "domain_id": "P-D1",
                    "concept_id": "P-C1",
                    "question_text": "개인 요약으로 만든 문항은 어떤 source_type으로 import하는가?",
                    "choices": ["user_owned_summary", "actual_exam_dump", "web_scraped_verbatim", "commercial_book_verbatim"],
                    "answer": 1,
                    "explanation": "원문 복제가 아니라 개인 요약이면 user_owned_summary로 private import한다.",
                    "source_type": "user_owned_summary",
                    "source_ref": "개인 요약",
                }
            ],
        }
        path = Path(self.tmp.name) / "private_bank.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        with self.assertRaises(ValueError):
            import_bank_file(self.conn, path, private=False)

        result = import_bank_file(self.conn, path, private=True)
        self.assertEqual(result["exam_id"], "PRIVATE_TEST")
        count = self.conn.execute("SELECT COUNT(*) AS n FROM questions WHERE exam_id = 'PRIVATE_TEST'").fetchone()["n"]
        self.assertEqual(count, 1)

    def test_importer_accepts_v2_metadata_and_keeps_cbt_flow(self) -> None:
        payload = {
            "exam": {
                "id": "V2_TEST",
                "name": "v2 문제은행 테스트",
                "official_question_count": 1,
                "official_duration_minutes": 10,
                "pass_score": 60,
                "domain_min_score": 0,
            },
            "domains": [{"id": "V2-D1", "name": "공개 라이선스 영역", "official_weight": 100, "official_question_count": 1}],
            "concepts": [{"id": "V2-C1", "domain_id": "V2-D1", "name": "출처 메타데이터", "review_note": "출처와 보관 정책을 확인한다."}],
            "questions": [
                {
                    "id": "V2-Q1",
                    "domain_id": "V2-D1",
                    "concept_id": "V2-C1",
                    "question_type": "single_choice",
                    "question_text": "MIT 라이선스 공개 연습문항을 가져올 때 남겨야 하는 정보는?",
                    "choices": ["원문 삭제 여부만", "출처/라이선스/보관정책/유효성 상태", "정답 번호만", "세션 점수만"],
                    "answer_json": {"choices": [2]},
                    "explanation": "공개 라이선스라도 출처, 라이선스, 보관 정책, 유효성 상태를 함께 남겨야 한다.",
                    "difficulty": "easy",
                    "source_type": "public_license",
                    "source_ref": "unit-test",
                    "source_license": "MIT",
                    "storage_policy": "raw_allowed",
                    "validity_status": "current",
                    "provenance": {"repository": "unit-test/repo", "path": "exam-data.ts"},
                }
            ],
        }
        path = Path(self.tmp.name) / "v2_bank.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        import_bank_file(self.conn, path)

        row = self.conn.execute("SELECT * FROM questions WHERE id = 'V2-Q1'").fetchone()
        self.assertEqual(row["answer"], 2)
        self.assertEqual(json.loads(row["answer_json"]), {"choices": [2]})
        self.assertEqual(row["question_type"], "single_choice")
        self.assertEqual(row["source_license"], "MIT")
        self.assertEqual(row["storage_policy"], "raw_allowed")
        self.assertEqual(row["validity_status"], "current")
        self.assertEqual(json.loads(row["provenance_json"])["repository"], "unit-test/repo")

        first = create_session(self.conn, exam_id="V2_TEST", count=1, mode="custom-cbt", seed=1)
        is_correct, next_view = submit_answer(self.conn, first.session_id, 2)
        result = finish_session(self.conn, first.session_id)

        self.assertTrue(is_correct)
        self.assertIsNone(next_view)
        self.assertEqual(result["correct"], 1)

    def test_gcp_gail_converter_outputs_importable_v2_payload(self) -> None:
        ts_text = """
export const PRACTICE_QUESTIONS: Question[] = [
  {
    id: "q1",
    sectionId: "fundamentals",
    topicId: "llm-basics",
    question: "What is the best use of a foundation model?",
    options: [
      "Only fixed rule execution",
      "Reusable base for many generative AI tasks",
      "Network routing",
      "Storage lifecycle management"
    ],
    correctIndex: 1,
    explanation: "A foundation model is reused across many downstream generative AI tasks.",
    whyOthersWrong: [
      "Fixed rules are not foundation models.",
      "Network routing is unrelated.",
      "Storage lifecycle management is unrelated."
    ],
    officialDoc: "https://cloud.google.com/vertex-ai/generative-ai/docs/learn/overview",
    difficulty: "easy",
  },
]
"""
        payload = convert_gail_practice_questions_text(
            ts_text,
            source_ref="https://github.com/ludovicobesana/gail-exam-preparation",
        )
        path = Path(self.tmp.name) / "gcp_gail.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        result = import_bank_file(self.conn, path)
        row = self.conn.execute("SELECT * FROM questions WHERE id = 'GCP_GAIL_001_fundamentals_llm_basics_q1'").fetchone()

        self.assertEqual(result["exam_id"], "GCP_GENERATIVE_AI_LEADER")
        self.assertEqual(result["questions"], 1)
        self.assertEqual(row["answer"], 2)
        self.assertEqual(row["source_type"], "public_license")
        self.assertEqual(row["source_license"], "MIT")
        self.assertEqual(row["storage_policy"], "raw_allowed")
        self.assertEqual(row["validity_status"], "needs_official_check")

    def test_exam_ready_mode_uses_only_active_internal_quality_questions(self) -> None:
        payload = exam_ready_payload(
            [
                ("Q-ACTIVE-1", "open_license", "active", "current", 1),
                ("Q-ACTIVE-2", "open_license", "active", "current", 2),
                ("Q-SYNTHETIC", "synthetic", "active", "current", 3),
                ("Q-REVIEW", "open_license", "needs_review", "needs_official_check", 4),
            ]
        )
        path = Path(self.tmp.name) / "exam_ready_bank.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        import_bank_file(self.conn, path)

        first = create_session(self.conn, exam_id="EXAM_READY_TEST", count=2, mode="exam-ready", seed=1)
        selected = set(session_question_ids(self.conn, first.session_id))

        self.assertEqual(selected, {"Q-ACTIVE-1", "Q-ACTIVE-2"})

    def test_exam_ready_mode_fails_when_real_quality_bank_is_not_enough(self) -> None:
        with self.assertRaisesRegex(ValueError, "exam-ready"):
            create_session(self.conn, exam_id="SQLD", count=5, mode="exam-ready", seed=1)

    def test_coverage_report_marks_exam_ready_gap(self) -> None:
        payload = exam_ready_payload(
            [
                ("Q-ACTIVE-1", "open_license", "active", "current", 1),
                ("Q-ACTIVE-2", "open_license", "active", "current", 2),
                ("Q-REVIEW", "open_license", "needs_review", "needs_official_check", 3),
            ],
            official_count=5,
        )
        path = Path(self.tmp.name) / "coverage_bank.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        import_bank_file(self.conn, path)

        report = coverage_report(self.conn, "EXAM_READY_TEST")

        self.assertFalse(report["ready"])
        self.assertEqual(report["exam_ready_questions"], 2)
        self.assertEqual(report["official_question_count"], 5)
        self.assertEqual(report["domains"][0]["status"], "부족")

    def test_mcp_coverage_report_tool_exposes_quality_state(self) -> None:
        call_tool("init_study_db", {})
        result = call_tool("coverage_report", {"exam": "SQLD"})

        text = result["content"][0]["text"]
        self.assertIn("SQLD", text)
        self.assertIn("exam-ready", text)
        self.assertIn("부족", text)

    def test_gcp_promotion_turns_official_doc_candidates_into_exam_ready(self) -> None:
        payload = convert_gail_practice_questions_text(
            """
export const PRACTICE_QUESTIONS: Question[] = [
  {
    id: "q1",
    sectionId: "fundamentals",
    topicId: "llm-basics",
    question: "What is the best use of a foundation model?",
    options: ["A", "B", "C", "D"],
    correctIndex: 1,
    explanation: "A foundation model can be reused across many tasks.",
    whyOthersWrong: ["A", "C", "D"],
    officialDoc: "https://cloud.google.com/vertex-ai/generative-ai/docs/learn/overview",
    difficulty: "easy",
  },
]
""",
            source_ref="https://github.com/ludovicobesana/gail-exam-preparation",
        )
        path = Path(self.tmp.name) / "gcp_gail.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        import_bank_file(self.conn, path)

        before = coverage_report(self.conn, "GCP_GENERATIVE_AI_LEADER")
        result = promote_gcp_gail_questions(self.conn, checked_at="2026-07-03")
        after = coverage_report(self.conn, "GCP_GENERATIVE_AI_LEADER")

        self.assertEqual(before["exam_ready_questions"], 0)
        self.assertEqual(result["promoted"], 1)
        self.assertEqual(after["exam_ready_questions"], 1)
        row = self.conn.execute(
            "SELECT quality_status, validity_status, official_checked_at FROM questions WHERE exam_id = 'GCP_GENERATIVE_AI_LEADER'"
        ).fetchone()
        self.assertEqual(row["quality_status"], "active")
        self.assertEqual(row["validity_status"], "current")
        self.assertEqual(row["official_checked_at"], "2026-07-03")

    def test_info_processing_archive_inspector_counts_private_pdf_candidates(self) -> None:
        zip_path = Path(self.tmp.name) / "2025_info_processing_written.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            archive.writestr("2025년1회_정보처리기사필기기출문제.pdf", b"%PDF-1.4\n")
            archive.writestr("readme.txt", "ignore")

        result = inspect_info_processing_archives(zip_path)

        self.assertEqual(result["zip_count"], 1)
        self.assertEqual(result["pdf_count"], 1)
        self.assertEqual(result["archives"][0]["category"], "past_exam")
        self.assertEqual(result["archives"][0]["pdfs"][0]["filename"], "2025년1회_정보처리기사필기기출문제.pdf")

    def test_info_processing_archive_inspector_rejects_missing_path(self) -> None:
        with self.assertRaises(ValueError):
            inspect_info_processing_archives(Path(self.tmp.name) / "missing")

    def test_info_processing_archive_inspector_rejects_non_zip_file(self) -> None:
        text_path = Path(self.tmp.name) / "notes.txt"
        text_path.write_text("not a zip", encoding="utf-8")

        with self.assertRaises(ValueError):
            inspect_info_processing_archives(text_path)

    def test_mcp_finish_session_returns_obsidian_paths_without_default_notion_plan(self) -> None:
        call_tool("init_study_db", {})
        start = call_tool("start_session", {"exam": "SQLD", "count": 3, "seed": 5})
        session_id = start["structuredContent"]["session_id"]
        with connect() as conn:
            answer_all_with_correct_answers(conn, session_id)

        result = call_tool("finish_session", {"session_id": session_id})

        text = result["content"][0]["text"]
        structured = result["structuredContent"]
        self.assertIn("obsidian_session_note:", text)
        self.assertIn("obsidian_review_queue:", text)
        self.assertIsNone(structured["notion_sync"])
        self.assertTrue(Path(structured["obsidian"]["session_note"]).exists())


def correct_answer_for(conn, question_id: str) -> int:
    return conn.execute("SELECT answer FROM questions WHERE id = ?", (question_id,)).fetchone()["answer"]


def session_question_ids(conn, session_id: str) -> list[str]:
    return [
        row["question_id"]
        for row in conn.execute(
            "SELECT question_id FROM session_questions WHERE session_id = ? ORDER BY position",
            (session_id,),
        ).fetchall()
    ]


def answer_all_with_correct_answers(conn, session_id: str) -> None:
    while True:
        current = get_next_unanswered(conn, session_id)
        if current is None:
            return
        submit_answer(conn, session_id, correct_answer_for(conn, current.question_id))


def exam_ready_payload(
    question_rows: list[tuple[str, str, str, str, int]],
    *,
    official_count: int = 2,
) -> dict:
    return {
        "exam": {
            "id": "EXAM_READY_TEST",
            "name": "실전 품질 모드 테스트",
            "official_question_count": official_count,
            "official_duration_minutes": 10,
            "pass_score": 60,
            "domain_min_score": 0,
        },
        "domains": [{"id": "ER-D1", "name": "품질 영역", "official_weight": 100, "official_question_count": official_count}],
        "concepts": [{"id": "ER-C1", "domain_id": "ER-D1", "name": "품질 개념", "review_note": "실전 출제 가능한 문제만 고른다."}],
        "questions": [
            {
                "id": question_id,
                "domain_id": "ER-D1",
                "concept_id": "ER-C1",
                "question_type": "single_choice",
                "question_text": f"{question_id} 문항",
                "choices": ["1", "2", "3", "4"],
                "answer_json": {"choices": [answer]},
                "explanation": "품질 상태 테스트 문항입니다.",
                "difficulty": "medium",
                "source_type": "public_license" if source_tier != "synthetic" else "synthetic",
                "source_ref": "unit-test",
                "source_license": "MIT" if source_tier != "synthetic" else "synthetic",
                "source_tier": source_tier,
                "storage_policy": "raw_allowed",
                "validity_status": validity_status,
                "quality_status": quality_status,
                "scope_version": "2026",
                "official_checked_at": "2026-07-03" if quality_status == "active" else "",
                "quality_notes": "unit test",
            }
            for question_id, source_tier, quality_status, validity_status, answer in question_rows
        ],
    }


if __name__ == "__main__":
    unittest.main()
