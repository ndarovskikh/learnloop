import tempfile
import unittest
from pathlib import Path

from learnloop.admin_agent import AdminStatisticsAgent
from learnloop.memory_store import LearningMemoryStore

from helpers import build_components


class AdminStatisticsAgentTests(unittest.TestCase):
    def _store_with_cohort(self, root, size=5):
        store = LearningMemoryStore(root / "memory.sqlite3", root / "memories.jsonl")
        store.seed_question(
            course_id="ddia", course_title="DDIA", topic_id="latency",
            topic_title="Latency", question_id="q1", difficulty="easy",
            question_text="What is latency?", expected_answer="A delay",
        )
        cohort = (("target", .5), ("peer-alpha", .1), ("peer-beta", .3), ("peer-delta", .8), ("peer-epsilon", 1.0))[:size]
        for user_id, score in cohort:
            store.record_attempt(user_id=user_id, user_name="private-" + user_id, question_id="q1", score=score)
        return store

    def test_returns_only_requesters_aggregate_position(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store_with_cohort(Path(directory))
            result = AdminStatisticsAgent(store).benchmark("target", "latency")

            self.assertEqual(result["percentile"], 60)
            self.assertEqual(result["top_percent"], 41)
            self.assertNotIn("private-target", str(result))
            self.assertNotIn("peer-alpha", str(result))
            self.assertNotIn("score", result)

    def test_blocks_small_cohorts_and_regular_tool_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store_with_cohort(root, size=1)
            with self.assertRaisesRegex(ValueError, "INSUFFICIENT_COHORT"):
                AdminStatisticsAgent(store).benchmark("target", "latency")

            _, _, _, registry, _ = build_components(root)
            ordinary = registry.execute("admin_benchmark", {"user_id": "target"})
            self.assertEqual(ordinary.error_code, "UNKNOWN_TOOL")


if __name__ == "__main__":
    unittest.main()
