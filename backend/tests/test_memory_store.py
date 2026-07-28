import tempfile
import unittest
from pathlib import Path

from learnloop.memory_store import LearningMemoryStore


class LearningMemoryStoreTests(unittest.TestCase):
    def test_attempt_updates_sqlite_and_observation_is_kept_in_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LearningMemoryStore(root / "learnloop.sqlite3", root / "memories.jsonl")
            store.seed_question(
                course_id="ddia", course_title="DDIA", topic_id="latency",
                topic_title="Latency", question_id="ddia-latency-01", difficulty="easy",
                question_text="What is P95?", expected_answer="95th percentile",
            )
            attempt_id = store.record_attempt(
                user_id="user-1", user_name="Natalia", question_id="ddia-latency-01", score=0.4,
            )
            memory = store.remember(
                user_id="user-1", type="learning_fact",
                content="Student confuses P95 and P99.", cue=["latency", "percentiles"],
                source={"question_id": "ddia-latency-01", "attempt_id": attempt_id},
            )

            self.assertEqual(store.mastery_for("user-1", "latency"), 0.4)
            self.assertEqual(store.memories_for("user-1"), [memory])

    def test_reset_removes_only_the_requested_students_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LearningMemoryStore(root / "db.sqlite3", root / "memories.jsonl")
            store.seed_question(course_id="ddia", course_title="DDIA", topic_id="latency", topic_title="Latency", question_id="q1", difficulty="easy", question_text="Q", expected_answer="A")
            store.record_attempt(user_id="one", user_name="One", question_id="q1", score=0.4)
            store.record_attempt(user_id="two", user_name="Two", question_id="q1", score=0.8)
            store.remember(user_id="one", type="learning_fact", content="Needs practice.", cue=["latency"], source={})
            store.remember(user_id="two", type="learning_fact", content="Understands it.", cue=["latency"], source={})

            store.reset_user("one")

            self.assertEqual(store.attempt_count_for("one"), 0)
            self.assertEqual(store.attempt_count_for("two"), 1)
            self.assertEqual(len(store.memories_for("one")), 0)
            self.assertEqual(len(store.memories_for("two")), 1)


if __name__ == "__main__":
    unittest.main()
