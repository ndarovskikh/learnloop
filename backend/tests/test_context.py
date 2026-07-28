import tempfile
import unittest
from pathlib import Path

from learnloop.context import LearningContext
from learnloop.memory_store import LearningMemoryStore

from helpers import build_components


class LearningContextTests(unittest.TestCase):
    def test_push_is_bounded_and_pull_is_private_to_student(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, tools, _, _ = build_components(root)
            rules = root / "coach_rules.md"
            rules.write_text("# Rules\n- Ask a guiding question first.\n", encoding="utf-8")
            store = LearningMemoryStore(root / "memory.sqlite3", root / "memories.jsonl")
            context = LearningContext(repository, bank, rules, store)
            tools.learning_context = context
            tools.memory_store = store

            tools.assess_and_record_answer("student-1", "q-1", "unrelated")
            store.remember(user_id="student-2", type="learning_fact", content="Private fact.", cue=["latency"], source={})

            push = context.push("student-1")
            pulled = context.retrieve_learning_memory("student-1", "latency")

            self.assertIn("Ask a guiding question first", push)
            self.assertIn("user_id=student-1", push)
            self.assertIn("RECENT SESSION", push)
            self.assertEqual(len(pulled), 1)
            self.assertNotIn("Private fact.", str(pulled))

    def test_registry_exposes_scoped_pull_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, tools, registry, _ = build_components(root)
            context = LearningContext(repository, bank, root / "missing.md")
            tools.learning_context = context
            tools.assess_and_record_answer("student-1", "q-1", "unrelated")

            result = registry.execute(
                "get_previous_attempts", {"user_id": "student-1", "topic": "latency"}
            )
            materials = registry.execute("get_course_material", {"topic": "latency"})

            self.assertTrue(result.success)
            self.assertEqual(len(result.data["attempts"]), 1)
            self.assertTrue(materials.success)
            self.assertTrue(materials.data["materials"])


if __name__ == "__main__":
    unittest.main()
