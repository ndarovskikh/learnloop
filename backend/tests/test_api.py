import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from learnloop.api import create_app
from learnloop.config import Settings

from helpers import build_components, question


class ApiTests(unittest.TestCase):
    def test_demo_team_accounts_can_log_in(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, _, _, agent = build_components(root)
            settings = Settings(
                api_key="insert api key here",
                model="mimo-v2.5-free",
                base_url="https://opencode.ai/zen/v1",
                max_agent_steps=12,
                max_topic_depth=5,
                max_extra_topic_iterations=1,
                question_bank_path=bank.path,
                progress_dir=repository.progress_dir,
            )
            client = TestClient(
                create_app(settings, agent, repository, bank)
            )

            for username in ("natali", "liza", "danya", "andrew"):
                response = client.post(
                    "/api/auth/login",
                    json={"username": username, "password": "1234"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["user_id"], username)

            rejected = client.post(
                "/api/auth/login",
                json={"username": "natali", "password": "wrong"},
            )
            self.assertEqual(rejected.status_code, 401)

    def test_course_workspace_contains_material_chat_and_analytics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, _, _, agent = build_components(root)
            settings = Settings(
                api_key="insert api key here",
                model="mimo-v2.5-free",
                base_url="https://opencode.ai/zen/v1",
                max_agent_steps=12,
                max_topic_depth=5,
                max_extra_topic_iterations=1,
                question_bank_path=bank.path,
                progress_dir=repository.progress_dir,
            )
            client = TestClient(
                create_app(settings, agent, repository, bank)
            )

            response = client.get("/api/courses/ddia?user_id=student-1")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["course"]["id"], "ddia")
            self.assertEqual(payload["materials"][0]["type"], "PDF")
            self.assertIsNotNone(payload["current_question"])
            self.assertIn("course_completion", payload["analytics"])
            self.assertIn("topics", payload["analytics"])
            self.assertEqual(payload["analytics"]["topics"][0]["id"], "latency")
            self.assertGreaterEqual(len(payload["history"]), 2)

    def test_answer_updates_chat_and_analytics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, _, _, agent = build_components(root)
            settings = Settings(
                api_key="insert api key here",
                model="mimo-v2.5-free",
                base_url="https://opencode.ai/zen/v1",
                max_agent_steps=12,
                max_topic_depth=5,
                max_extra_topic_iterations=1,
                question_bank_path=bank.path,
                progress_dir=repository.progress_dir,
            )
            client = TestClient(
                create_app(settings, agent, repository, bank)
            )
            workspace = client.get(
                "/api/courses/ddia?user_id=student-1"
            ).json()

            response = client.post(
                "/api/courses/ddia/messages",
                json={
                    "user_id": "student-1",
                    "question_id": workspace["current_question"]["id"],
                    "message": "Tail latency is the slow end.",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["analytics"]["questions_answered"], 1)
            self.assertTrue(
                any(item["role"] == "user" for item in payload["history"])
            )
            self.assertIsNotNone(payload["current_question"])

    def test_missing_local_pdf_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, _, _, agent = build_components(root)
            settings = Settings(
                api_key="insert api key here",
                model="mimo-v2.5-free",
                base_url="https://opencode.ai/zen/v1",
                max_agent_steps=12,
                max_topic_depth=5,
                max_extra_topic_iterations=1,
                question_bank_path=bank.path,
                progress_dir=repository.progress_dir,
            )
            client = TestClient(
                create_app(settings, agent, repository, bank)
            )

            response = client.get(
                "/api/courses/ddia/materials/ddia-book"
            )

            self.assertEqual(response.status_code, 404)

    def test_current_topic_and_full_progress_can_be_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, tools, _, agent = build_components(root)
            settings = Settings(
                api_key="insert api key here",
                model="mimo-v2.5-free",
                base_url="https://opencode.ai/zen/v1",
                max_agent_steps=12,
                max_topic_depth=5,
                max_extra_topic_iterations=1,
                question_bank_path=bank.path,
                progress_dir=repository.progress_dir,
            )
            client = TestClient(
                create_app(settings, agent, repository, bank)
            )
            tools.assess_and_record_answer(
                "student-1", "q-1", "Tail latency"
            )

            topic_response = client.post(
                "/api/courses/ddia/reset-topic",
                json={
                    "user_id": "student-1",
                    "topic": "latency",
                    "confirmed": True,
                },
            )
            self.assertEqual(topic_response.status_code, 200)
            self.assertEqual(
                topic_response.json()["analytics"]["questions_answered"], 0
            )

            tools.assess_and_record_answer(
                "student-1", "q-2", "Tail latency"
            )
            full_response = client.post(
                "/api/courses/ddia/reset",
                json={"user_id": "student-1", "confirmed": True},
            )
            self.assertEqual(full_response.status_code, 200)
            self.assertEqual(
                full_response.json()["analytics"]["questions_answered"], 0
            )

    def test_student_can_select_a_topic_from_the_question_bank(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, _, _, agent = build_components(root)
            bank.add(question(1, topic="reliability"))
            settings = Settings(
                api_key="insert api key here",
                model="mimo-v2.5-free",
                base_url="https://opencode.ai/zen/v1",
                max_agent_steps=12,
                max_topic_depth=5,
                max_extra_topic_iterations=1,
                question_bank_path=bank.path,
                progress_dir=repository.progress_dir,
            )
            client = TestClient(
                create_app(settings, agent, repository, bank)
            )

            response = client.post(
                "/api/courses/ddia/select-topic",
                json={"user_id": "student-1", "topic": "reliability"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(
                payload["analytics"]["current_topic_id"], "reliability"
            )
            self.assertEqual(
                payload["current_question"]["topic"], "reliability"
            )


if __name__ == "__main__":
    unittest.main()
