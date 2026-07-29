import tempfile
import unittest
from pathlib import Path

from learnloop.material_agent import CourseMaterialAgent
from learnloop.memory_store import LearningMemoryStore
from learnloop.provider import HeuristicProvider
from learnloop.repository import ProgressRepository

from helpers import build_components


class CourseMaterialAgentTests(unittest.TestCase):
    def test_ingesting_material_adds_grounded_questions_to_the_bank(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, tools, _, coach = build_components(root)
            agent = CourseMaterialAgent(
                materials_dir=root / "materials",
                question_bank=bank,
                provider=HeuristicProvider(),
                repository=repository,
            )

            result = agent.ingest_material(
                topic_id="replication",
                topic_title="Replication",
                title="Chapter 5: Replication",
                content="Leader-based replication forwards writes to replicas.",
                question_count=3,
            )

            self.assertEqual(len(result.generated_questions), 3)
            bank_topics = {item.topic for item in bank.all()}
            self.assertIn("replication", bank_topics)
            stored = [item for item in bank.all() if item.topic == "replication"]
            self.assertEqual(len(stored), 3)
            self.assertTrue(all("teacher upload" in item.source for item in stored))

            listed = agent.list_materials()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["topic_id"], "replication")
            self.assertEqual(
                agent.read_material(result.material_id),
                "Leader-based replication forwards writes to replicas.",
            )

    def test_ingesting_material_recalculates_known_students_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, tools, _, coach = build_components(root)
            tools.assess_and_record_answer("student-1", "q-1", "Tail latency")
            tools.assess_and_record_answer("student-2", "q-1", "unrelated")

            store = LearningMemoryStore(root / "db.sqlite3", root / "memories.jsonl")
            agent = CourseMaterialAgent(
                materials_dir=root / "materials",
                question_bank=bank,
                provider=HeuristicProvider(),
                repository=repository,
                memory_store=store,
            )

            result = agent.ingest_material(
                topic_id="replication",
                topic_title="Replication",
                title="Chapter 5",
                content="Some grounded course text about replication.",
            )

            self.assertEqual(result.recalculated_students, 2)
            log = store.material_ingestion_logs()[-1]
            self.assertEqual(log["topic_id"], "replication")
            self.assertEqual(log["generated_count"], 5)
            self.assertEqual(log["recalculated_students"], 2)

    def test_rejects_empty_material(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, _, _, _ = build_components(root)
            agent = CourseMaterialAgent(
                materials_dir=root / "materials",
                question_bank=bank,
                provider=HeuristicProvider(),
                repository=repository,
            )

            with self.assertRaisesRegex(ValueError, "MATERIAL_CONTENT_EMPTY"):
                agent.ingest_material(
                    topic_id="replication",
                    topic_title="Replication",
                    title="Empty",
                    content="   ",
                )


if __name__ == "__main__":
    unittest.main()
