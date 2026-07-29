from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Protocol, Optional

from .coordination import AgentHandoff
from .models import Assessment, Difficulty, Question


class LearningProvider(Protocol):
    def assess(self, question: Question, student_answer: str, context: str = "") -> Assessment:
        ...

    def verify_assessment(
        self,
        question: Question,
        student_answer: str,
        proposal: AgentHandoff,
        context: str = "",
    ) -> AgentHandoff:
        ...

    def generate_question(
        self,
        topic: str,
        difficulty: Difficulty,
        knowledge_gaps: List[str],
        source_context: str, context: str = "",
    ) -> Question:
        ...


def _difficulty_for_score(score: float) -> Difficulty:
    if score < 0.45:
        return Difficulty.EASY
    if score < 0.75:
        return Difficulty.MEDIUM
    return Difficulty.HARD


class HeuristicProvider:
    """Deterministic local provider for tests and keyless demos."""

    def assess(self, question: Question, student_answer: str, context: str = "") -> Assessment:
        normalized = student_answer.lower()
        matched = [
            concept
            for concept in question.expected_concepts
            if all(word.lower() in normalized for word in concept.split())
        ]
        score = len(matched) / max(len(question.expected_concepts), 1)
        gaps = [
            concept
            for concept in question.expected_concepts
            if concept not in matched
        ]
        if score >= 0.75:
            feedback = "Good answer. You covered the key ideas."
        elif score > 0:
            feedback = "Partially correct. Review: %s." % ", ".join(gaps)
        else:
            feedback = "The answer misses the rubric concepts. Review: %s." % (
                ", ".join(gaps)
            )
        return Assessment(
            question_id=question.id,
            score=round(score, 2),
            feedback=feedback,
            knowledge_gaps=gaps,
            recommended_difficulty=_difficulty_for_score(score),
        )

    def verify_assessment(
        self,
        question: Question,
        student_answer: str,
        proposal: AgentHandoff,
        context: str = "",
    ) -> AgentHandoff:
        if proposal.status != "assessment_proposed" or proposal.needs_approval:
            return AgentHandoff("rejected", {"reason": "Invalid assessment proposal"})
        # This role recalculates from the rubric instead of trusting the
        # executor's score, so it remains an independent deterministic check.
        verified = self.assess(question, student_answer, context)
        return AgentHandoff("verified", {"assessment": verified.to_dict()})

    def generate_question(
        self,
        topic: str,
        difficulty: Difficulty,
        knowledge_gaps: List[str],
        source_context: str, context: str = "",
    ) -> Question:
        gap = knowledge_gaps[0] if knowledge_gaps else topic
        digest = hashlib.sha256(
            ("%s:%s:%s" % (topic, difficulty.value, gap)).encode("utf-8")
        ).hexdigest()[:10]
        return Question(
            id="generated-%s" % digest,
            topic=topic,
            difficulty=difficulty,
            text="Explain %s in your own words and give one practical consequence." % gap,
            expected_concepts=[gap],
            explanation="A correct answer should explain %s using the course material."
            % gap,
            source=source_context or "Grounded in the configured course question bank",
        )


class OpenAIProvider:
    """OpenAI-compatible provider using JSON structured responses."""

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The openai package is not installed. Run: python -m pip install -e ."
            ) from exc
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model

    def _json_call(self, system: str, user: str) -> Dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("PROVIDER_EMPTY_RESPONSE")
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("PROVIDER_INVALID_JSON")
        return parsed

    def assess(self, question: Question, student_answer: str, context: str = "") -> Assessment:
        payload = self._json_call(
            system=(
                "You are a strict learning evaluator. Use only the supplied "
                "rubric. Return JSON with question_id, score (0..1), feedback, "
                "knowledge_gaps (array), and recommended_difficulty "
                "(easy|medium|hard).\n\n" + context
            ),
            user=json.dumps(
                {
                    "question": question.to_dict(),
                    "student_answer": student_answer,
                },
                ensure_ascii=False,
            ),
        )
        payload["question_id"] = question.id
        assessment = Assessment.from_dict(payload)
        # Keep the adaptive policy deterministic even when a lightweight model
        # returns a difficulty inconsistent with its own score.
        return Assessment(
            question_id=assessment.question_id,
            score=assessment.score,
            feedback=assessment.feedback,
            knowledge_gaps=assessment.knowledge_gaps,
            recommended_difficulty=_difficulty_for_score(assessment.score),
        )

    def verify_assessment(
        self,
        question: Question,
        student_answer: str,
        proposal: AgentHandoff,
        context: str = "",
    ) -> AgentHandoff:
        if proposal.status != "assessment_proposed" or proposal.needs_approval:
            return AgentHandoff("rejected", {"reason": "Invalid assessment proposal"})
        payload = self._json_call(
            system=(
                "You are the independent answer-verification agent. Check the "
                "executor proposal against only the supplied rubric. Correct it "
                "where needed. Return JSON with question_id, score (0..1), "
                "feedback, knowledge_gaps (array), and recommended_difficulty "
                "(easy|medium|hard). Feedback must be constructive and address "
                "the learner directly.\n\n" + context
            ),
            user=json.dumps(
                {
                    "question": question.to_dict(),
                    "student_answer": student_answer,
                    "executor_proposal": proposal.to_dict(),
                },
                ensure_ascii=False,
            ),
        )
        payload["question_id"] = question.id
        assessment = Assessment.from_dict(payload)
        final = Assessment(
            question_id=assessment.question_id,
            score=assessment.score,
            feedback=assessment.feedback,
            knowledge_gaps=assessment.knowledge_gaps,
            recommended_difficulty=_difficulty_for_score(assessment.score),
        )
        return AgentHandoff("verified", {"assessment": final.to_dict()})

    def generate_question(
        self,
        topic: str,
        difficulty: Difficulty,
        knowledge_gaps: List[str],
        source_context: str, context: str = "",
    ) -> Question:
        payload = self._json_call(
            system=(
                "Generate exactly one question using only the supplied source "
                "context. Return JSON with id, topic, difficulty, text, "
                "expected_concepts, explanation, and source. Never invent a "
                "source. The ID must start with generated-.\n\n" + context
            ),
            user=json.dumps(
                {
                    "topic": topic,
                    "difficulty": difficulty.value,
                    "knowledge_gaps": knowledge_gaps,
                    "source_context": source_context,
                },
                ensure_ascii=False,
            ),
        )
        payload["topic"] = topic
        payload["difficulty"] = difficulty.value
        return Question.from_dict(payload)


def build_provider(api_key: str, model: str, base_url: str) -> LearningProvider:
    normalized = api_key.strip().lower()
    if normalized and normalized != "insert api key here":
        return OpenAIProvider(api_key=api_key, model=model, base_url=base_url)
    return HeuristicProvider()
