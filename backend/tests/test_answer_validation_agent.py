import unittest

from learnloop.answer_validation_agent import AnswerValidationAgent
from learnloop.provider import HeuristicProvider

from helpers import question


class AnswerValidationAgentTests(unittest.TestCase):
    def test_delegates_scoring_to_its_own_provider(self):
        agent = AnswerValidationAgent(HeuristicProvider())
        item = question(1)

        correct = agent.validate(item, "Tail latency")
        wrong = agent.validate(item, "unrelated answer")

        self.assertEqual(correct.score, 1.0)
        self.assertEqual(wrong.score, 0.0)
        self.assertEqual(correct.question_id, item.id)

    def test_uses_the_provider_it_was_given_not_a_shared_default(self):
        class RecordingProvider(HeuristicProvider):
            def __init__(self):
                self.calls = 0

            def assess(self, question, student_answer, context=""):
                self.calls += 1
                return super().assess(question, student_answer, context)

        provider = RecordingProvider()
        agent = AnswerValidationAgent(provider)
        agent.validate(question(1), "Tail latency", context="ctx")

        self.assertEqual(provider.calls, 1)


if __name__ == "__main__":
    unittest.main()
