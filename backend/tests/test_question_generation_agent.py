import json
import tempfile
import unittest
from pathlib import Path

from learnloop.memory_store import LearningMemoryStore
from learnloop.models import TopicStatus
from learnloop.provider import HeuristicProvider
from learnloop.question_bank import QuestionBank
from learnloop.question_generation_agent import (
    AdaptiveQuestionBankAgent,
    QuestionGenerationTrigger,
)

from helpers import build_components, question


def build_large_bank(root: Path) -> QuestionBank:
    questions = []
    for topic_index in range(20):
        topic = "topic-%s" % topic_index
        for question_index in range(1, 6):
            questions.append(
                question(question_index, topic=topic).to_dict()
            )
    path = root / "questions.json"
    path.write_text(json.dumps(questions), encoding="utf-8")
    return QuestionBank(path)


class AdaptiveQuestionBankAgentTests(unittest.TestCase):
    def test_user_request_generates_five_private_questions_from_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = build_large_bank(root)
            store = LearningMemoryStore(root / "db.sqlite3", root / "memory.jsonl")
            for item in bank.all()[:5]:
                store.seed_question(
                    course_id="ddia",
                    course_title="DDIA",
                    topic_id=item.topic,
                    topic_title=item.topic,
                    question_id=item.id,
                    difficulty=item.difficulty.value,
                    question_text=item.text,
                    expected_answer="; ".join(item.expected_concepts),
                )
                store.record_attempt(
                    user_id="student-1",
                    user_name="Student 1",
                    question_id=item.id,
                    score=0.2,
                )
            agent = AdaptiveQuestionBankAgent(
                store,
                bank,
                HeuristicProvider(),
            )

            result = agent.generate_for_user(
                "student-1",
                QuestionGenerationTrigger.USER_REQUEST,
                topic="topic-0",
            )

            self.assertEqual(result.status, "generated")
            self.assertEqual(result.course_completion, 5.0)
            self.assertEqual(len(result.questions), 5)
            self.assertEqual(len({item.text for item in result.questions}), 5)
            first = result.questions[0]
            self.assertEqual(
                agent.personal_question_for("student-1", first.id),
                first,
            )
            with self.assertRaises(KeyError):
                agent.personal_question_for("student-2", first.id)
            log = store.question_generation_logs("student-1")[-1]
            self.assertEqual(log["status"], "generated")
            self.assertEqual(log["generated_count"], 5)

    def test_nightly_run_is_silent_and_logged_when_there_is_no_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LearningMemoryStore(root / "db.sqlite3", root / "memory.jsonl")
            agent = AdaptiveQuestionBankAgent(
                store,
                build_large_bank(root),
                HeuristicProvider(),
            )

            results = agent.run_nightly()

            self.assertEqual(results[0].status, "silent")
            self.assertEqual(results[0].reason, "no_student_progress")
            log = store.question_generation_logs()[-1]
            self.assertEqual(log["status"], "silent")
            self.assertEqual(log["reason"], "no_student_progress")
            self.assertEqual(log["generated_count"], 0)

    def test_nightly_run_is_silent_below_five_percent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bank = build_large_bank(root)
            store = LearningMemoryStore(root / "db.sqlite3", root / "memory.jsonl")
            item = bank.all()[0]
            store.seed_question(
                course_id="ddia",
                course_title="DDIA",
                topic_id=item.topic,
                topic_title=item.topic,
                question_id=item.id,
                difficulty=item.difficulty.value,
                question_text=item.text,
                expected_answer="; ".join(item.expected_concepts),
            )
            store.record_attempt(
                user_id="student-1",
                user_name="Student 1",
                question_id=item.id,
                score=0.0,
            )
            agent = AdaptiveQuestionBankAgent(
                store,
                bank,
                HeuristicProvider(),
            )

            result = agent.run_nightly()[0]

            self.assertEqual(result.status, "silent")
            self.assertEqual(
                result.reason,
                "course_completion_below_5_percent",
            )
            self.assertEqual(result.questions, [])
            log = store.question_generation_logs("student-1")[-1]
            self.assertEqual(log["course_completion"], 1.0)

    def test_manual_tool_serves_the_entire_five_question_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, bank, tools, registry, coach = build_components(
                root,
                count=5,
            )
            store = LearningMemoryStore(root / "db.sqlite3", root / "memory.jsonl")
            tools.memory_store = store
            tools.question_generation_agent = AdaptiveQuestionBankAgent(
                store,
                bank,
                HeuristicProvider(),
            )
            current = coach.start("student-1")
            for _ in range(5):
                current = coach.submit_answer(
                    "student-1",
                    current.question.id,
                    "Tail latency",
                )
            self.assertEqual(
                current.status,
                TopicStatus.MASTERY_CONFIRMATION_REQUIRED.value,
            )

            generated = registry.execute(
                "generate_personal_practice_questions",
                {"user_id": "student-1"},
            )

            self.assertTrue(generated.success)
            self.assertEqual(generated.data["generated_count"], 5)
            current = coach.start("student-1")
            personal_ids = []
            for index in range(5):
                personal_ids.append(current.question.id)
                current = coach.submit_answer(
                    "student-1",
                    current.question.id,
                    "Tail latency",
                )
                if index < 4:
                    self.assertEqual(current.status, "question_ready")
            self.assertTrue(all(item.startswith("personal-") for item in personal_ids))
            self.assertEqual(len(set(personal_ids)), 5)
            self.assertEqual(
                current.status,
                TopicStatus.MASTERY_CONFIRMATION_REQUIRED.value,
            )
            self.assertEqual(repository.load("student-1").topic_depth, 10)


if __name__ == "__main__":
    unittest.main()
