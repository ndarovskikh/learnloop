import tempfile
import unittest
from pathlib import Path

from learnloop.models import CheckpointDecision

from helpers import build_components


class AgentLoopTests(unittest.TestCase):
    def test_normal_turn_records_answer_and_returns_next_question(self):
        with tempfile.TemporaryDirectory() as directory:
            repository, _, _, _, agent = build_components(Path(directory))
            start = agent.start("student-1")

            result = agent.submit_answer(
                "student-1",
                start.question.id,
                "Tail latency describes slow requests.",
            )

            self.assertEqual(result.status, "question_ready")
            self.assertIsNotNone(result.assessment)
            self.assertIsNotNone(result.question)
            self.assertNotEqual(result.question.id, start.question.id)
            self.assertEqual(repository.load("student-1").topic_depth, 1)

    def test_fifth_answer_stops_before_generating_another_question(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, _, agent = build_components(Path(directory))
            current = agent.start("student-1")

            for _ in range(4):
                current = agent.submit_answer(
                    "student-1",
                    current.question.id,
                    "Tail latency",
                )
                self.assertEqual(current.status, "question_ready")

            checkpoint = agent.submit_answer(
                "student-1",
                current.question.id,
                "Tail latency",
            )

            self.assertEqual(
                checkpoint.status,
                "mastery_confirmation_required",
            )
            self.assertIn("one_more_question", checkpoint.allowed_actions)
            self.assertIsNone(checkpoint.question)

    def test_one_extra_question_then_no_second_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, _, agent = build_components(Path(directory))
            current = agent.start("student-1")
            for _ in range(5):
                current = agent.submit_answer(
                    "student-1",
                    current.question.id,
                    "Tail latency",
                )

            extra = agent.resolve_checkpoint(
                "student-1",
                CheckpointDecision.ONE_MORE_QUESTION,
            )
            self.assertEqual(extra.status, "question_ready")
            checkpoint = agent.submit_answer(
                "student-1",
                extra.question.id,
                "Tail latency",
            )
            self.assertEqual(
                checkpoint.status,
                "mastery_confirmation_required",
            )
            self.assertNotIn("one_more_question", checkpoint.allowed_actions)

    def test_max_steps_stops_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, _, agent = build_components(
                Path(directory),
                max_steps=1,
            )
            start = agent.start("student-1")

            result = agent.submit_answer(
                "student-1",
                start.question.id,
                "Tail latency",
            )

            self.assertEqual(result.status, "max_steps_reached")
            self.assertEqual(result.error_code, "MAX_STEPS_REACHED")


if __name__ == "__main__":
    unittest.main()

