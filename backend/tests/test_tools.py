import tempfile
import unittest
from pathlib import Path

from learnloop.models import CheckpointDecision, Difficulty, TopicStatus
from learnloop.memory_store import LearningMemoryStore

from helpers import build_components, question


class LearningToolsTests(unittest.TestCase):
    def test_mastery_is_the_average_score_for_the_topic(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, _, tools, _, _ = build_components(Path(directory))

            tools.assess_and_record_answer(
                "student-1", "q-1", "Tail latency"
            )
            tools.assess_and_record_answer(
                "student-1", "q-2", "unrelated answer"
            )

            progress = repository.load("student-1")
            self.assertEqual(progress.mastery["latency"], 0.5)

    def test_assessment_is_analyzed_saved_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, _, tools, _, _ = build_components(Path(directory))

            result = tools.assess_and_record_answer(
                user_id="student-1",
                question_id="q-1",
                student_answer="Tail latency is the slow end.",
            )

            self.assertTrue(result.success)
            progress = repository.load("student-1")
            self.assertEqual(progress.topic_depth, 1)
            self.assertIn("q-1", progress.answered_question_ids)
            self.assertEqual(len(progress.attempts), 1)

    def test_assessment_is_also_written_to_structured_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, tools, _, _ = build_components(root)
            store = LearningMemoryStore(root / "learnloop.sqlite3", root / "memories.jsonl")
            tools.memory_store = store

            result = tools.assess_and_record_answer(
                "student-1", "q-1", "unrelated answer"
            )

            self.assertTrue(result.success)
            self.assertEqual(store.attempt_count_for("student-1"), 1)
            self.assertEqual(store.mastery_for("student-1", "latency"), 0.0)
            self.assertEqual(len(store.memories_for("student-1")), 1)

    def test_unknown_question_reaches_error_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, tools, _, _ = build_components(Path(directory))

            result = tools.assess_and_record_answer(
                user_id="student-1",
                question_id="missing",
                student_answer="answer",
            )

            self.assertFalse(result.success)
            self.assertEqual(result.error_code, "QUESTION_NOT_FOUND")

    def test_depth_five_requires_student_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, _, tools, _, _ = build_components(Path(directory))

            for index in range(1, 6):
                result = tools.assess_and_record_answer(
                    user_id="student-1",
                    question_id="q-%s" % index,
                    student_answer="Tail latency",
                )
                self.assertTrue(result.success)

            progress = repository.load("student-1")
            self.assertEqual(progress.topic_depth, 5)
            self.assertEqual(
                progress.topic_status,
                TopicStatus.MASTERY_CONFIRMATION_REQUIRED,
            )
            blocked = tools.generate_next_question(
                user_id="student-1",
                topic="latency",
                difficulty=Difficulty.EASY,
                knowledge_gaps=[],
            )
            self.assertEqual(blocked.error_code, "CHECKPOINT_PENDING")

    def test_only_one_extra_iteration_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, _, tools, _, _ = build_components(Path(directory))
            for index in range(1, 6):
                tools.assess_and_record_answer(
                    "student-1", "q-%s" % index, "Tail latency"
                )

            first = tools.resolve_topic_checkpoint(
                "student-1",
                CheckpointDecision.ONE_MORE_QUESTION,
            )
            self.assertTrue(first.success)
            tools.assess_and_record_answer("student-1", "q-6", "Tail latency")
            second = tools.resolve_topic_checkpoint(
                "student-1",
                CheckpointDecision.ONE_MORE_QUESTION,
            )

            self.assertFalse(second.success)
            self.assertEqual(
                second.error_code,
                "EXTRA_ITERATION_ALREADY_USED",
            )
            self.assertEqual(repository.load("student-1").topic_depth, 6)

    def test_reset_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, _, tools, _, _ = build_components(Path(directory))
            tools.assess_and_record_answer("student-1", "q-1", "Tail latency")

            rejected = tools.reset_learning_progress(
                "student-1",
                explicit_confirmation=False,
            )
            self.assertEqual(rejected.error_code, "APPROVAL_REQUIRED")
            self.assertEqual(repository.load("student-1").topic_depth, 1)

            accepted = tools.reset_learning_progress(
                "student-1",
                explicit_confirmation=True,
            )
            self.assertTrue(accepted.success)
            self.assertEqual(repository.load("student-1").topic_depth, 0)

    def test_current_topic_reset_removes_only_topic_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, _, tools, _, _ = build_components(Path(directory))
            tools.assess_and_record_answer("student-1", "q-1", "Tail latency")

            rejected = tools.reset_topic_progress(
                "student-1",
                topic="latency",
                explicit_confirmation=False,
            )
            self.assertEqual(rejected.error_code, "APPROVAL_REQUIRED")

            accepted = tools.reset_topic_progress(
                "student-1",
                topic="latency",
                explicit_confirmation=True,
            )
            self.assertTrue(accepted.success)
            progress = repository.load("student-1")
            self.assertEqual(progress.topic_depth, 0)
            self.assertEqual(progress.attempts, [])
            self.assertEqual(progress.answered_question_ids, [])
            self.assertNotIn("latency", progress.mastery)

    def test_topic_selection_preserves_each_topics_session(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, bank, tools, _, _ = build_components(Path(directory))
            bank.add(question(1, topic="reliability"))
            tools.assess_and_record_answer("student-1", "q-1", "Tail latency")

            selected = tools.select_learning_topic(
                "student-1", "reliability"
            )
            self.assertTrue(selected.success)
            reliability = repository.load("student-1")
            self.assertEqual(reliability.active_topic, "reliability")
            self.assertEqual(reliability.topic_depth, 0)

            tools.assess_and_record_answer(
                "student-1", "q-reliability-1", "Fault tolerance"
            )
            tools.select_learning_topic("student-1", "latency")
            latency = repository.load("student-1")
            self.assertEqual(latency.topic_depth, 1)

            tools.select_learning_topic("student-1", "reliability")
            reliability_again = repository.load("student-1")
            self.assertEqual(reliability_again.topic_depth, 1)


if __name__ == "__main__":
    unittest.main()
