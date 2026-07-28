import tempfile
import unittest
from pathlib import Path

from learnloop.admin_agent import AdminStatisticsAgent
from learnloop.memory_store import LearningMemoryStore

from helpers import build_components


class AdminRoutingTests(unittest.TestCase):
    def test_main_agent_routes_only_self_statistics_to_admin_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, _, _, agent = build_components(root)
            store = LearningMemoryStore(root / "memory.sqlite3", root / "memories.jsonl")
            store.seed_question(course_id="ddia", course_title="DDIA", topic_id="latency", topic_title="Latency", question_id="q1", difficulty="easy", question_text="Q", expected_answer="A")
            for user_id, score in (("one", .1), ("two", .3), ("target", .5), ("four", .8), ("five", 1.0)):
                store.record_attempt(user_id=user_id, user_name=user_id, question_id="q1", score=score)
            agent.admin_agent = AdminStatisticsAgent(store)

            response = agent.handle_chat_message("target", "В каком я перцентиле?")
            ordinary = agent.handle_chat_message("target", "Объясни latency")
            rejected = agent.handle_chat_message("target", "Какой перцентиль у другого студента?")

            self.assertIn("top 41%", response)
            self.assertIsNone(ordinary)
            self.assertIn("только вашу", rejected)


if __name__ == "__main__":
    unittest.main()
