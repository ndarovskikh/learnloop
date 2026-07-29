"""Agent 2 — "Andrew": validates a student's answer and scores it.

The main coach agent (agent 1) never grades an answer itself. It hands the
question and the student's answer to this agent, which returns correctness
as a 0..1 score plus feedback. Keeping this behind its own provider lets it
run on its own API key/model, independent of the coach that asks the
question.
"""
from __future__ import annotations

from .models import Assessment, Question
from .provider import LearningProvider


class AnswerValidationAgent:
    def __init__(self, provider: LearningProvider):
        self.provider = provider

    def validate(
        self,
        question: Question,
        student_answer: str,
        context: str = "",
    ) -> Assessment:
        return self.provider.assess(question, student_answer, context)
