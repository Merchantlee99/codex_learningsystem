from __future__ import annotations

import os
import tempfile
import unittest
import json
from pathlib import Path

from cert_study.db import connect, initialize
from cert_study.engine import create_session, finish_session, get_next_unanswered, submit_answer
from cert_study.mcp_server import call_tool, handle_message
from cert_study.notion_sync import prepare_notion_sync_plan
from cert_study.reporting import write_session_report
from cert_study.seed_sqld import seed as seed_sqld


class StudySystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_home = os.environ.get("CERT_STUDY_HOME")
        os.environ["CERT_STUDY_HOME"] = self.tmp.name
        self.conn = connect()
        initialize(self.conn)
        seed_sqld(self.conn)

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

    def test_perfect_session_scores_100_and_passes(self) -> None:
        first = create_session(self.conn, exam_id="SQLD", count=10, mode="custom-cbt", seed=1)
        answer_all_with_correct_answers(self.conn, first.session_id)
        result = finish_session(self.conn, first.session_id)
        self.assertEqual(result["correct"], 10)
        self.assertEqual(result["score"], 100.0)
        self.assertIn("합격권", result["judgement"])

    def test_wrong_note_report_contains_answers_explanation_and_export(self) -> None:
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
        self.assertTrue((Path(self.tmp.name) / "notion_exports" / f"{first.session_id}.md").exists())

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

    def test_mcp_tools_list_and_start_session(self) -> None:
        tools_response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tool_names = {tool["name"] for tool in tools_response["result"]["tools"]}
        self.assertIn("start_session", tool_names)
        self.assertIn("prepare_notion_sync", tool_names)

        call_tool("init_study_db", {})
        result = call_tool("start_session", {"exam": "SQLD", "count": 5, "seed": 4})
        text = result["content"][0]["text"]
        self.assertIn("session_id:", text)
        self.assertIn("[1/5]", text)


def correct_answer_for(conn, question_id: str) -> int:
    return conn.execute("SELECT answer FROM questions WHERE id = ?", (question_id,)).fetchone()["answer"]


def answer_all_with_correct_answers(conn, session_id: str) -> None:
    while True:
        current = get_next_unanswered(conn, session_id)
        if current is None:
            return
        submit_answer(conn, session_id, correct_answer_for(conn, current.question_id))


if __name__ == "__main__":
    unittest.main()
