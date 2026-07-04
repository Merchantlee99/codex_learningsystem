from __future__ import annotations

import os
import tempfile
import unittest
import json
import zipfile
from pathlib import Path

from cert_study.db import connect, initialize
from cert_study.enrichers.sqld_gold import enrich_sqld_gold_payload
from cert_study.engine import create_session, finish_session, get_next_unanswered, submit_answer
from cert_study.importer import import_bank_file
from cert_study.importers.chathuranga_saa import convert_chathuranga_saa_markdown, inspect_chathuranga_saa_markdown
from cert_study.importers.gcp_gail import convert_gail_practice_questions_text
from cert_study.importers.info_processing import inspect_info_processing_archives, parse_info_processing_exam_blocks
from cert_study.importers.kdata_text import convert_kdata_text_sources, inspect_kdata_text_sources
from cert_study.mcp_server import call_tool, handle_message
from cert_study.notion_sync import prepare_notion_sync_plan
from cert_study.gold import audit_final_bank, promote_gold_candidates, render_final_audit_report
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

    def test_public_seed_bank_is_sqld_only_demo(self) -> None:
        counts = {
            row["exam_id"]: row["n"]
            for row in self.conn.execute(
                "SELECT exam_id, COUNT(*) AS n FROM questions GROUP BY exam_id ORDER BY exam_id"
            ).fetchall()
        }

        self.assertEqual(set(counts), {"SQLD"})
        self.assertEqual(counts["SQLD"], 50)

    def test_public_sqld_seed_is_marked_as_synthetic_template_content(self) -> None:
        row = self.conn.execute(
            """
            SELECT
              COUNT(*) AS total,
              COUNT(CASE WHEN source_type = 'synthetic' THEN 1 END) AS synthetic_count,
              COUNT(CASE WHEN source_tier = 'synthetic' THEN 1 END) AS synthetic_tier_count,
              COUNT(CASE WHEN source_license = 'synthetic' THEN 1 END) AS synthetic_license_count,
              COUNT(CASE WHEN source_ref LIKE '%실제 기출%' AND source_ref LIKE '%복제하지 않았습니다%' THEN 1 END) AS provenance_count
            FROM questions
            WHERE exam_id = 'SQLD'
            """
        ).fetchone()
        notes = self.conn.execute("SELECT notes FROM exams WHERE id = 'SQLD'").fetchone()["notes"]

        self.assertEqual(row["total"], 50)
        self.assertEqual(row["synthetic_count"], 50)
        self.assertEqual(row["synthetic_tier_count"], 50)
        self.assertEqual(row["synthetic_license_count"], 50)
        self.assertEqual(row["provenance_count"], 50)
        self.assertIn("템플릿 데모", notes)
        self.assertIn("복제하지 않았습니다", notes)

    def test_source_backed_mode_filters_out_synthetic_questions(self) -> None:
        concept_by_domain = {
            row["domain_id"]: row["id"]
            for row in self.conn.execute(
                "SELECT id, domain_id FROM concepts WHERE exam_id = 'SQLD' GROUP BY domain_id"
            ).fetchall()
        }
        rows = []
        for idx, domain_id in enumerate(sorted(concept_by_domain), start=1):
            for offset in range(3):
                rows.append(
                    {
                        "id": f"SQLD-PRIVATE-Q{idx}-{offset}",
                        "exam_id": "SQLD",
                        "domain_id": domain_id,
                        "concept_id": concept_by_domain[domain_id],
                        "question_text": f"private source backed question {idx}-{offset}",
                        "choices_json": json.dumps(["A", "B", "C", "D"]),
                        "answer": 1,
                        "explanation": "private source backed explanation",
                        "difficulty": "medium",
                        "source_type": "licensed_private",
                        "source_ref": "private-fixture",
                        "source_tier": "licensed_private",
                        "quality_status": "needs_review",
                    }
                )
        self.conn.executemany(
            """
            INSERT INTO questions
            (id, exam_id, domain_id, concept_id, question_text, choices_json, answer, explanation, difficulty,
             source_type, source_ref, source_tier, quality_status)
            VALUES
            (:id, :exam_id, :domain_id, :concept_id, :question_text, :choices_json, :answer, :explanation,
             :difficulty, :source_type, :source_ref, :source_tier, :quality_status)
            """,
            rows,
        )
        self.conn.commit()

        first = create_session(
            self.conn,
            exam_id="SQLD",
            count=2,
            mode="source-backed",
            seed=10,
        )
        selected = self.conn.execute(
            """
            SELECT q.source_type, q.source_tier
            FROM session_questions sq
            JOIN questions q ON q.id = sq.question_id
            WHERE sq.session_id = ?
            """,
            (first.session_id,),
        ).fetchall()

        self.assertEqual({row["source_type"] for row in selected}, {"licensed_private"})
        self.assertEqual({row["source_tier"] for row in selected}, {"licensed_private"})

    def test_source_backed_mode_excludes_known_broken_questions(self) -> None:
        concept = self.conn.execute("SELECT id FROM concepts WHERE id = 'SQLD-C-SELECT'").fetchone()["id"]
        rows = [
            {
                "id": "SQLD-BROKEN-Q1",
                "exam_id": "SQLD",
                "domain_id": "SQLD-D2",
                "concept_id": concept,
                "question_text": "수리 필요로 표시된 문항입니다.",
                "choices_json": json.dumps(["A", "B", "C", "D"]),
                "answer": 1,
                "explanation": "수리 필요 문항은 source-backed 세션에서 제외한다.",
                "difficulty": "medium",
                "source_type": "licensed_private",
                "source_ref": "broken-fixture",
                "source_tier": "licensed_private",
                "quality_status": "needs_repair",
            },
            {
                "id": "SQLD-GOOD-Q1",
                "exam_id": "SQLD",
                "domain_id": "SQLD-D2",
                "concept_id": concept,
                "question_text": "출제 가능한 문항입니다.",
                "choices_json": json.dumps(["A", "B", "C", "D"]),
                "answer": 1,
                "explanation": "출제 가능한 private 문항입니다.",
                "difficulty": "medium",
                "source_type": "licensed_private",
                "source_ref": "broken-fixture",
                "source_tier": "licensed_private",
                "quality_status": "needs_review",
            },
        ]
        self.conn.executemany(
            """
            INSERT INTO questions
            (id, exam_id, domain_id, concept_id, question_text, choices_json, answer, explanation, difficulty,
             source_type, source_ref, source_tier, quality_status)
            VALUES
            (:id, :exam_id, :domain_id, :concept_id, :question_text, :choices_json, :answer, :explanation,
             :difficulty, :source_type, :source_ref, :source_tier, :quality_status)
            """,
            rows,
        )
        self.conn.commit()

        first = create_session(self.conn, exam_id="SQLD", count=1, mode="source-backed", seed=31)
        selected = session_question_ids(self.conn, first.session_id)

        self.assertIn("SQLD-GOOD-Q1", selected)
        self.assertNotIn("SQLD-BROKEN-Q1", selected)

    def test_custom_mode_excludes_known_broken_questions(self) -> None:
        concept = self.conn.execute("SELECT id FROM concepts WHERE id = 'SQLD-C-SELECT'").fetchone()["id"]
        self.conn.execute(
            """
            INSERT INTO questions
            (id, exam_id, domain_id, concept_id, question_text, choices_json, answer, explanation, difficulty,
             source_type, source_ref, source_tier, quality_status)
            VALUES
            (?, 'SQLD', 'SQLD-D2', ?, '수리 필요로 표시된 일반 모드 문항입니다.', ?, 1,
             '수리 필요 문항은 일반 CBT에서도 제외한다.', 'medium',
             'licensed_private', 'broken-fixture', 'licensed_private', 'needs_repair')
            """,
            ("SQLD-BROKEN-CUSTOM-Q1", concept, json.dumps(["A", "B", "C", "D"])),
        )
        self.conn.commit()

        session = create_session(self.conn, exam_id="SQLD", count=20, mode="custom-cbt", seed=32)
        selected = session_question_ids(self.conn, session.session_id)

        self.assertNotIn("SQLD-BROKEN-CUSTOM-Q1", selected)

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

    def test_session_avoids_duplicate_question_text_when_possible(self) -> None:
        concept = self.conn.execute("SELECT id FROM concepts WHERE id = 'SQLD-C-SELECT'").fetchone()["id"]
        rows = [
            {
                "id": "SQLD-DUP-Q1",
                "exam_id": "SQLD",
                "domain_id": "SQLD-D2",
                "concept_id": concept,
                "question_text": "동일 지문을 가진 중복 문항입니다.",
                "choices_json": json.dumps(["A", "B", "C", "D"]),
                "answer": 1,
                "explanation": "중복 회피 테스트입니다.",
                "difficulty": "medium",
                "source_type": "licensed_private",
                "source_ref": "duplicate-fixture",
                "source_tier": "licensed_private",
                "quality_status": "active",
            },
            {
                "id": "SQLD-DUP-Q2",
                "exam_id": "SQLD",
                "domain_id": "SQLD-D2",
                "concept_id": concept,
                "question_text": "동일 지문을 가진 중복 문항입니다.",
                "choices_json": json.dumps(["A", "B", "C", "D"]),
                "answer": 1,
                "explanation": "중복 회피 테스트입니다.",
                "difficulty": "medium",
                "source_type": "licensed_private",
                "source_ref": "duplicate-fixture",
                "source_tier": "licensed_private",
                "quality_status": "active",
            },
            {
                "id": "SQLD-DUP-Q3",
                "exam_id": "SQLD",
                "domain_id": "SQLD-D2",
                "concept_id": concept,
                "question_text": "중복되지 않은 대체 문항입니다.",
                "choices_json": json.dumps(["A", "B", "C", "D"]),
                "answer": 1,
                "explanation": "중복 회피 테스트입니다.",
                "difficulty": "medium",
                "source_type": "licensed_private",
                "source_ref": "duplicate-fixture",
                "source_tier": "licensed_private",
                "quality_status": "active",
            },
        ]
        self.conn.executemany(
            """
            INSERT INTO questions
            (id, exam_id, domain_id, concept_id, question_text, choices_json, answer, explanation, difficulty,
             source_type, source_ref, source_tier, quality_status)
            VALUES
            (:id, :exam_id, :domain_id, :concept_id, :question_text, :choices_json, :answer, :explanation,
             :difficulty, :source_type, :source_ref, :source_tier, :quality_status)
            """,
            rows,
        )
        self.conn.execute(
            """
            UPDATE questions
            SET quality_status = 'active',
                validity_status = 'current',
                official_checked_at = '2026-07-04',
                correct_rationale = '정답 선택지는 요구 조건을 직접 만족합니다.',
                distractor_rationales_json = '{"2":"2번은 요구 조건을 만족하지 못합니다.","3":"3번은 요구 조건을 만족하지 못합니다.","4":"4번은 요구 조건을 만족하지 못합니다."}',
                review_concepts_json = '["SELECT"]',
                official_scope_refs_json = '["SQLD-D2-SELECT"]',
                gold_status = 'gold',
                gold_checked_at = '2026-07-04'
            WHERE id IN ('SQLD-DUP-Q1', 'SQLD-DUP-Q2', 'SQLD-DUP-Q3')
            """
        )
        self.conn.commit()

        session = create_session(self.conn, exam_id="SQLD", count=2, mode="exam-ready", seed=30)
        selected_texts = [
            row["question_text"]
            for row in self.conn.execute(
                """
                SELECT q.question_text
                FROM session_questions sq
                JOIN questions q ON q.id = sq.question_id
                WHERE sq.session_id = ?
                ORDER BY sq.position
                """,
                (session.session_id,),
            ).fetchall()
        ]

        self.assertEqual(len(selected_texts), len(set(selected_texts)))

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
            exam_id="SQLD",
            count=5,
            mode="custom-cbt",
            seed=9,
        )
        answer_all_with_correct_answers(self.conn, first.session_id)
        finish_session(self.conn, first.session_id)

        report = render_session_report(self.conn, first.session_id)

        self.assertIn("정규 50문항", report)

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
        self.assertIn("final_audit_report", tool_names)
        self.assertIn("prepare_notion_sync", tool_names)
        start_tool = next(tool for tool in tools_response["result"]["tools"] if tool["name"] == "start_session")
        self.assertIn("mode", start_tool["inputSchema"]["properties"])

        exams = call_tool("list_exams", {})
        available_ids = {row["id"] for row in exams["structuredContent"]["available"]}
        self.assertIn("SQLD", available_ids)
        self.assertNotIn("ADSP", available_ids)
        self.assertNotIn("KR_INFO_PROCESSING_ENGINEER", available_ids)
        sqld = next(row for row in exams["structuredContent"]["available"] if row["id"] == "SQLD")
        self.assertEqual(sqld["available_questions"], 50)
        self.assertEqual(sqld["bank_rounds"], 1.0)
        self.assertEqual(exams["structuredContent"]["planned"], [])

        call_tool("init_study_db", {})
        result = call_tool("start_session", {"exam": "SQLD", "count": 5, "seed": 4})
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

    def test_skill_forbids_batch_generation_and_answer_keys(self) -> None:
        skill_text = (Path(__file__).resolve().parents[1] / "skills" / "cert-study" / "SKILL.md").read_text()

        self.assertIn("문제 N개 줘", skill_text)
        self.assertIn("일반 답변으로 문제를 만들지 말고", skill_text)
        self.assertIn("세션 종료 전에는 정답표", skill_text)
        self.assertIn("공개 repo에 기본 포함된 합성 문제은행은 SQLD 하나다", skill_text)
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

    def test_exam_ready_mode_uses_only_gold_internal_quality_questions(self) -> None:
        payload = exam_ready_payload(
            [
                ("Q-ACTIVE-1", "open_license", "active", "current", 1),
                ("Q-ACTIVE-2", "open_license", "active", "current", 2),
                ("Q-SYNTHETIC", "synthetic", "active", "current", 3),
                ("Q-REVIEW", "open_license", "needs_review", "needs_official_check", 4),
                ("Q-NON-GOLD", "open_license", "active", "current", 1, "candidate"),
            ]
        )
        path = Path(self.tmp.name) / "exam_ready_bank.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        import_bank_file(self.conn, path)

        first = create_session(self.conn, exam_id="EXAM_READY_TEST", count=2, mode="exam-ready", seed=1)
        selected = set(session_question_ids(self.conn, first.session_id))

        self.assertEqual(selected, {"Q-ACTIVE-1", "Q-ACTIVE-2"})

    def test_final_audit_blocks_placeholder_explanation_and_generic_concept(self) -> None:
        payload = exam_ready_payload(
            [
                ("Q-ACTIVE-1", "open_license", "active", "current", 1),
                ("Q-ACTIVE-2", "open_license", "active", "current", 2),
            ],
            concept_id="ER-SRC-C-D1",
            explanation="정답표 기준 정답은 1번입니다. 세부 해설은 오답노트에서 보강합니다.",
        )
        path = Path(self.tmp.name) / "bad_gold_bank.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        import_bank_file(self.conn, path)

        report = audit_final_bank(self.conn, "EXAM_READY_TEST")
        rendered = render_final_audit_report(report)

        self.assertFalse(report["ready"])
        self.assertIn("placeholder_explanation", {issue["code"] for issue in report["issues"]})
        self.assertIn("generic_concept", {issue["code"] for issue in report["issues"]})
        self.assertIn("최종 사용 가능", rendered)

    def test_final_audit_passes_gold_bank_with_rationales_and_scope_refs(self) -> None:
        payload = exam_ready_payload(
            [
                ("Q-ACTIVE-1", "open_license", "active", "current", 1),
                ("Q-ACTIVE-2", "open_license", "active", "current", 2),
            ]
        )
        path = Path(self.tmp.name) / "good_gold_bank.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        import_bank_file(self.conn, path)

        report = audit_final_bank(self.conn, "EXAM_READY_TEST")

        self.assertTrue(report["ready"])
        self.assertEqual(report["gold_questions"], 2)
        self.assertEqual(report["issues"], [])

    def test_promote_gold_candidates_requires_full_rationale_fields(self) -> None:
        payload = exam_ready_payload(
            [
                ("Q-CANDIDATE-GOOD", "open_license", "active", "current", 1, "candidate"),
                ("Q-CANDIDATE-BAD", "open_license", "active", "current", 2, "candidate"),
            ]
        )
        for question in payload["questions"]:
            if question["id"] == "Q-CANDIDATE-BAD":
                question["correct_rationale"] = ""
        path = Path(self.tmp.name) / "candidate_gold_bank.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        import_bank_file(self.conn, path)

        result = promote_gold_candidates(self.conn, "EXAM_READY_TEST", checked_at="2026-07-04")

        self.assertEqual(result["promoted"], 1)
        statuses = {
            row["id"]: row["gold_status"]
            for row in self.conn.execute("SELECT id, gold_status FROM questions WHERE exam_id = 'EXAM_READY_TEST'")
        }
        self.assertEqual(statuses["Q-CANDIDATE-GOOD"], "gold")
        self.assertEqual(statuses["Q-CANDIDATE-BAD"], "candidate")

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

    def test_info_processing_parser_handles_trailing_choice_markers(self) -> None:
        blocks = [
            "소프트웨어 공학에서 워크스루에 대한 설명으로 틀린\n1.\n(Walkthrough)\n것은?",
            "사용사례를 확장하여 명세하거나 설계 다이어그램에 적용할 수 있다.\n①",
            "테스트 케이스 등에 적용할 수 있다.\n복잡한 알고리즘을 이해하려고 할 때 유용하다.\n②",
            "인스펙션과 동일한 의미를 가진다.\n③",
            "단순한 테스트 케이스를 이용하여 수작업으로 수행해 보는 것이다.\n④",
            "애자일 방법론에 해당하지 않는 것은\n2.\n?\n기능 중심 개발\n①\n개발 및 검증\n②\n익스트림 프로그래밍\n③\n칸반\n④",
        ]

        questions = parse_info_processing_exam_blocks(
            blocks,
            answers={1: 3, 2: 2},
            year=2025,
            round_no=1,
            source_ref="2025_info_processing_written.zip/2025년1회.pdf",
        )

        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0]["id"], "IPE_PAST_2025_1_Q001")
        self.assertIn("워크스루", questions[0]["question_text"])
        self.assertEqual(questions[0]["choices"][0], "사용사례를 확장하여 명세하거나 설계 다이어그램에 적용할 수 있다. 테스트 케이스 등에 적용할 수 있다.")
        self.assertEqual(questions[0]["answer"], 3)
        self.assertEqual(questions[1]["choices"], ["기능 중심 개발", "개발 및 검증", "익스트림 프로그래밍", "칸반"])
        self.assertEqual(questions[1]["quality_status"], "needs_review")

    def test_kdata_text_converter_builds_sqld_private_bank(self) -> None:
        source = Path(self.tmp.name) / "sqld_raw.txt"
        source.write_text(
            """
1. NULL 비교에 대한 설명으로 옳은 것은?
1) NULL 여부는 IS NULL로 판단한다.
2) NULL = NULL은 항상 TRUE다.
3) NULL은 숫자 0과 같다.
4) NULL은 빈 문자열과 항상 같다.

2. HAVING 절의 역할로 가장 적절한 것은?
A. 그룹화 후 집계 결과에 조건을 적용한다.
B. 테이블을 물리적으로 삭제한다.
C. 사용자 권한을 부여한다.
D. 트랜잭션을 취소한다.

정답
1. 1
2. A
""",
            encoding="utf-8",
        )
        output = Path(self.tmp.name) / "sqld_import_ready.json"

        inspect_report = inspect_kdata_text_sources(source, exam_id="SQLD")
        convert_report = convert_kdata_text_sources(source, output, exam_id="SQLD")
        import_result = import_bank_file(self.conn, output, private=True)

        self.assertEqual(inspect_report["convertible_questions"], 2)
        self.assertEqual(convert_report["converted_questions"], 2)
        self.assertEqual(import_result["questions"], 2)
        row = self.conn.execute("SELECT * FROM questions WHERE id LIKE 'SQLD_SRC_%' ORDER BY id LIMIT 1").fetchone()
        self.assertEqual(row["source_type"], "licensed_private")
        self.assertEqual(row["quality_status"], "needs_review")

    def test_kdata_text_converter_builds_adsp_private_bank(self) -> None:
        source = Path(self.tmp.name) / "adsp_raw.md"
        source.write_text(
            """
1. 데이터와 정보의 관계로 옳은 것은?
① 데이터는 목적에 맞게 처리되면 의사결정에 쓸 수 있는 정보가 될 수 있다.
② 정보는 항상 원시 센서값만 의미한다.
③ 데이터와 정보는 어떤 맥락에서도 구분되지 않는다.
④ 정보는 분석 목적과 무관하다.

정답: 1
""",
            encoding="utf-8",
        )
        output = Path(self.tmp.name) / "adsp_import_ready.json"

        report = convert_kdata_text_sources(source, output, exam_id="ADSP")
        import_result = import_bank_file(self.conn, output, private=True)

        self.assertEqual(report["converted_questions"], 1)
        self.assertEqual(import_result["exam_id"], "ADSP")
        row = self.conn.execute("SELECT domain_id, concept_id FROM questions WHERE id LIKE 'ADSP_SRC_%'").fetchone()
        self.assertEqual(row["domain_id"], "ADSP-D1")
        self.assertEqual(row["concept_id"], "ADSP-SRC-C-D1")

    def test_kdata_text_converter_handles_tistory_question_and_answer_section(self) -> None:
        source = Path(self.tmp.name) / "sqld_tistory.html"
        source.write_text(
            """
<h3>SQLD 56회 1과목</h3>
<p>■ 문제 1. 스키마의 종류로 옳지 않은 것은? 정답확인 🌼</p>
<p>① 응용 스키마</p>
<p>② 외부 스키마</p>
<p>③ 개념 스키마</p>
<p>④ 내부 스키마</p>
<p>문제 2. 우선순위가 가장 높은 연산자는?</p>
<p>1) 비교</p>
<p>2) 괄호</p>
<p>3) AND</p>
<p>4) OR</p>
<p>1. 정답 : 1</p>
<p>2. 정답 : 2</p>
""",
            encoding="utf-8",
        )
        output = Path(self.tmp.name) / "sqld_tistory.json"

        report = convert_kdata_text_sources(source, output, exam_id="SQLD")
        import_result = import_bank_file(self.conn, output, private=True)

        self.assertEqual(report["converted_questions"], 2)
        self.assertEqual(import_result["questions"], 2)
        row = self.conn.execute(
            "SELECT answer, question_text FROM questions WHERE id LIKE 'SQLD_SRC_%' ORDER BY id LIMIT 1"
        ).fetchone()
        self.assertEqual(row["answer"], 1)
        self.assertNotIn("정답확인", row["question_text"])
        self.assertNotIn("🌼", row["question_text"])

    def test_kdata_text_converter_reads_tistory_highlighted_answer(self) -> None:
        source = Path(self.tmp.name) / "sqld_highlighted.html"
        source.write_text(
            """
<p>■ 문제 1. NULL에 대한 설명으로 옳은 것은?</p>
<p>① NULL은 0과 같은 의미다.</p>
<p><span style="color: #ee2323;"><b>② NULL은 집계함수에서 제외된다.</b></span></p>
<p>③ NULL = NULL은 TRUE이다.</p>
<p>④ NULL은 빈 문자열과 항상 같다.</p>
""",
            encoding="utf-8",
        )
        output = Path(self.tmp.name) / "sqld_highlighted.json"

        report = convert_kdata_text_sources(source, output, exam_id="SQLD")
        import_bank_file(self.conn, output, private=True)

        self.assertEqual(report["converted_questions"], 1)
        row = self.conn.execute("SELECT answer FROM questions WHERE id LIKE 'SQLD_SRC_%'").fetchone()
        self.assertEqual(row["answer"], 2)

    def test_kdata_text_converter_reads_tistory_javascript_exam_data(self) -> None:
        source = Path(self.tmp.name) / "sqld_exam_data.html"
        source.write_text(
            """
<script>
const examData = [
  { q: "1. 다음 중 키 엔터티에 해당하지 않는 것은?", o: ["① 사원", "② 프로젝트", "③ 회사", "④ 고객"], a: 2, h: "해설: 프로젝트는 보통 업무 과정에서 발생하는 중심 엔터티로 본다." },
  { q: "2. 다음 SQL 실행 결과로 옳은 것은?", o: ["① 0", "② 1", "③ 2", "④ 3"], c: "SELECT COUNT(*) FROM T WHERE C IS NOT NULL;", a: 2, h: "해설: COUNT(컬럼) 등 집계 함수는 NULL을 제외한다." }
];
</script>
""",
            encoding="utf-8",
        )
        output = Path(self.tmp.name) / "sqld_exam_data.json"

        report = convert_kdata_text_sources(source, output, exam_id="SQLD")
        import_result = import_bank_file(self.conn, output, private=True)

        self.assertEqual(report["converted_questions"], 2)
        self.assertEqual(import_result["questions"], 2)
        rows = self.conn.execute(
            "SELECT answer, question_text, choices_json, explanation FROM questions WHERE id LIKE 'SQLD_SRC_%' ORDER BY id"
        ).fetchall()
        self.assertEqual([row["answer"] for row in rows], [2, 2])
        self.assertIn("프로젝트", rows[0]["explanation"])
        self.assertEqual(json.loads(rows[0]["choices_json"])[3], "고객")
        self.assertNotIn("해설", json.loads(rows[0]["choices_json"])[3])
        self.assertIn("SELECT COUNT(*)", rows[1]["question_text"])

    def test_sqld_gold_enricher_adds_granular_concepts_and_rationales(self) -> None:
        payload = {
            "exam": {
                "id": "SQLD",
                "name": "SQLD",
                "official_question_count": 1,
                "official_duration_minutes": 90,
                "pass_score": 60,
                "domain_min_score": 40,
            },
            "domains": [{"id": "SQLD-D2", "name": "SQL 기본 및 활용", "official_weight": 100, "official_question_count": 1}],
            "concepts": [{"id": "SQLD-SRC-C-D2", "domain_id": "SQLD-D2", "name": "SQL 기본 및 활용 source-backed", "review_note": "임시 개념"}],
            "questions": [
                {
                    "id": "SQLD-SRC-TEST-Q001",
                    "domain_id": "SQLD-D2",
                    "concept_id": "SQLD-SRC-C-D2",
                    "question_type": "single_choice",
                    "question_text": "NULL 처리 설명으로 옳은 것은?",
                    "choices": ["NULL은 0이다", "NULL은 집계함수에서 제외된다", "NULL = NULL은 TRUE다", "NULL은 모든 값보다 크다"],
                    "answer": 2,
                    "answer_json": {"choices": [2]},
                    "explanation": "해설: COUNT(컬럼) 등 집계 함수는 NULL을 제외한다.",
                    "difficulty": "medium",
                    "source_type": "licensed_private",
                    "source_ref": "unit-test",
                    "source_license": "private-study-use",
                    "source_tier": "licensed_private",
                    "storage_policy": "private_only",
                    "validity_status": "current",
                    "quality_status": "active",
                    "scope_version": "2026",
                    "official_checked_at": "2026-07-04",
                    "quality_notes": "unit test",
                    "provenance": {"source_ref": "unit-test"},
                },
                {
                    "id": "SQLD-SRC-TEST-Q002",
                    "domain_id": "SQLD-D2",
                    "concept_id": "SQLD-SRC-C-D2",
                    "question_type": "single_choice",
                    "question_text": "다음 DCL 명령어 수행 후 SELECT 권한을 유지하는 유저를 모두 고르시오.",
                    "choices": ["DBA, U1", "DBA", "DBA, U1, U3", "DBA, U1, U2, U3"],
                    "answer": 4,
                    "answer_json": {"choices": [4]},
                    "explanation": "REVOKE DELETE는 DELETE 권한만 회수하므로 SELECT 권한은 유지된다.",
                    "difficulty": "medium",
                    "source_type": "licensed_private",
                    "source_ref": "unit-test",
                    "source_license": "private-study-use",
                    "source_tier": "licensed_private",
                    "storage_policy": "private_only",
                    "validity_status": "current",
                    "quality_status": "active",
                    "scope_version": "2026",
                    "official_checked_at": "2026-07-04",
                    "quality_notes": "unit test",
                    "provenance": {"source_ref": "unit-test"},
                },
                {
                    "id": "SQLD-SRC-TEST-Q003",
                    "domain_id": "SQLD-D2",
                    "concept_id": "SQLD-SRC-C-D2",
                    "question_type": "single_choice",
                    "question_text": "SELECT COUNT(*) 결과로 옳은 것은?",
                    "choices": ["0", "1", "2", "3"],
                    "answer": 2,
                    "answer_json": {"choices": [2]},
                    "explanation": "조건을 만족하는 행이 하나라서 COUNT 결과는 1이다.",
                    "difficulty": "medium",
                    "source_type": "licensed_private",
                    "source_ref": "unit-test",
                    "source_license": "private-study-use",
                    "source_tier": "licensed_private",
                    "storage_policy": "private_only",
                    "validity_status": "current",
                    "quality_status": "active",
                    "scope_version": "2026",
                    "official_checked_at": "2026-07-04",
                    "quality_notes": "unit test",
                    "provenance": {"source_ref": "unit-test"},
                },
            ],
        }

        enriched = enrich_sqld_gold_payload(payload, checked_at="2026-07-04")
        question = enriched["questions"][0]

        self.assertEqual(len(enriched["questions"]), 3)
        self.assertEqual(question["concept_id"], "SQLD-C-NULL")
        self.assertEqual(question["gold_status"], "gold")
        self.assertEqual(question["gold_checked_at"], "2026-07-04")
        self.assertIn("correct_rationale", question)
        self.assertEqual(set(question["distractor_rationales"]), {"1", "3", "4"})
        self.assertEqual(question["review_concepts"], ["NULL 처리"])
        self.assertEqual(question["official_scope_refs"], ["SQLD-D2-SQL기본-NULL"])

    def test_sqld_gold_enricher_preserves_official_domain_counts_when_limited(self) -> None:
        def row(question_id: str, domain_id: str, text: str) -> dict[str, object]:
            return {
                "id": question_id,
                "domain_id": domain_id,
                "concept_id": f"SQLD-SRC-C-{domain_id[-2:]}",
                "question_type": "single_choice",
                "question_text": text,
                "choices": ["0", "1", "2", "3"],
                "answer": 2,
                "answer_json": {"choices": [2]},
                "explanation": "조건을 만족하는 행이 하나라서 COUNT 결과는 1이다.",
                "difficulty": "medium",
                "source_type": "licensed_private",
                "source_ref": "unit-test",
                "source_license": "private-study-use",
                "source_tier": "licensed_private",
                "storage_policy": "private_only",
                "validity_status": "current",
                "quality_status": "active",
                "scope_version": "2026",
                "official_checked_at": "2026-07-04",
                "quality_notes": "unit test",
                "provenance": {"source_ref": "unit-test"},
            }

        payload = {
            "exam": {
                "id": "SQLD",
                "name": "SQLD",
                "official_question_count": 2,
                "official_duration_minutes": 90,
                "pass_score": 60,
                "domain_min_score": 40,
            },
            "domains": [
                {"id": "SQLD-D1", "name": "데이터 모델링의 이해", "official_weight": 50, "official_question_count": 1},
                {"id": "SQLD-D2", "name": "SQL 기본 및 활용", "official_weight": 50, "official_question_count": 1},
            ],
            "concepts": [],
            "questions": [
                row("SQLD-SRC-D1-Q001", "SQLD-D1", "엔터티 설명으로 옳은 것은?"),
                row("SQLD-SRC-D1-Q002", "SQLD-D1", "속성 설명으로 옳은 것은?"),
                row("SQLD-SRC-D2-Q001", "SQLD-D2", "SELECT COUNT(*) 결과로 옳은 것은?"),
            ],
        }

        enriched = enrich_sqld_gold_payload(payload, checked_at="2026-07-04", limit=2)

        self.assertEqual([question["domain_id"] for question in enriched["questions"]], ["SQLD-D1", "SQLD-D2"])

    def test_chathuranga_saa_markdown_converter_imports_single_choice_questions(self) -> None:
        source_dir = Path(self.tmp.name) / "chathuranga"
        source_dir.mkdir()
        source = source_dir / "PRACTICE-QUESTIONS.md"
        source.write_text(
            """
# Security - Practice Questions

### Question 1
A company wants full control over encryption keys for S3 data. Which option should be used?

A. SSE-S3
B. SSE-KMS with AWS managed keys
C. SSE-KMS with Customer Managed Keys
D. SSE-C

<details>
<summary>Show Answer</summary>

**Answer: C**

**Explanation:**
Customer managed KMS keys provide control over key policies and rotation.
</details>

---

### Question 2
Lambda needs to write CloudWatch Logs. Which permissions are required? (Choose 2)

A. logs:CreateLogStream
B. logs:PutLogEvents
C. logs:GetMetricData
D. logs:StartQuery

<details>
<summary>Show Answer</summary>

**Answer: A, B**
</details>
""",
            encoding="utf-8",
        )
        output = Path(self.tmp.name) / "saa_chathuranga.json"

        inspect_report = inspect_chathuranga_saa_markdown(source_dir)
        convert_report = convert_chathuranga_saa_markdown(source_dir, output, mark_active=True, checked_at="2026-07-04")
        import_result = import_bank_file(self.conn, output)

        self.assertEqual(inspect_report["convertible_questions"], 1)
        self.assertEqual(convert_report["converted_questions"], 1)
        self.assertEqual(import_result["exam_id"], "AWS_SOLUTIONS_ARCHITECT_ASSOCIATE")
        row = self.conn.execute(
            "SELECT answer, source_type, source_license, quality_status FROM questions WHERE id LIKE 'AWS_SAA_CHATH_%'"
        ).fetchone()
        self.assertEqual(row["answer"], 3)
        self.assertEqual(row["source_type"], "public_license")
        self.assertEqual(row["source_license"], "MIT")
        self.assertEqual(row["quality_status"], "active")

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
    question_rows: list[tuple[str, str, str, str, int] | tuple[str, str, str, str, int, str]],
    *,
    official_count: int = 2,
    concept_id: str = "ER-C1",
    explanation: str = "정답 선택지가 맞는 이유와 오답 선택지가 틀린 이유를 구분해 설명하는 검수 완료 문항입니다.",
) -> dict:
    def gold_status_for(row: tuple) -> str:
        if len(row) == 6:
            return str(row[5])
        source_tier = str(row[1])
        quality_status = str(row[2])
        validity_status = str(row[3])
        return "gold" if source_tier != "synthetic" and quality_status == "active" and validity_status == "current" else "none"

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
        "concepts": [{"id": concept_id, "domain_id": "ER-D1", "name": "세부 품질 개념", "review_note": "실전 출제 가능한 문제만 고른다."}],
        "questions": [
            {
                "id": question_id,
                "domain_id": "ER-D1",
                "concept_id": concept_id,
                "question_type": "single_choice",
                "question_text": f"{question_id} 문항",
                "choices": ["1", "2", "3", "4"],
                "answer_json": {"choices": [answer]},
                "explanation": explanation,
                "correct_rationale": f"{answer}번은 요구 조건을 직접 만족하므로 정답입니다.",
                "distractor_rationales": {
                    str(idx): f"{idx}번은 요구 조건을 만족하지 못하므로 오답입니다."
                    for idx in range(1, 5)
                    if idx != answer
                },
                "review_concepts": ["세부 품질 개념"],
                "official_scope_refs": ["EXAM_READY_TEST-D1-C1"],
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
                "gold_status": gold_status,
                "gold_checked_at": "2026-07-04" if gold_status == "gold" else "",
                "quality_notes": "unit test",
            }
            for row in question_rows
            for question_id, source_tier, quality_status, validity_status, answer in [row[:5]]
            for gold_status in [gold_status_for(row)]
        ],
    }


if __name__ == "__main__":
    unittest.main()
