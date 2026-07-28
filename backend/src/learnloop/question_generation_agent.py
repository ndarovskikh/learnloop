from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
from uuid import uuid4

from .memory_store import LearningMemoryStore
from .models import Difficulty, Question
from .provider import LearningProvider
from .question_bank import QuestionBank


class QuestionGenerationTrigger(str, Enum):
    NIGHTLY = "nightly_cron"
    USER_REQUEST = "user_request"


@dataclass(frozen=True)
class QuestionGenerationResult:
    status: str
    reason: str
    user_id: Optional[str]
    course_completion: float
    topic: Optional[str] = None
    questions: List[Question] = field(default_factory=list)
    decision_id: str = ""


class AdaptiveQuestionBankAgent:
    """Build a private practice bank from durable student progress.

    Progress, mastery, and gap signals are read from SQLite. The shared JSON
    question bank is used only as approved grounding material; generated
    questions are stored in SQLite and are scoped to one user.
    """

    MINIMUM_COURSE_COMPLETION = 5.0
    DEFAULT_BATCH_SIZE = 5

    def __init__(
        self,
        memory_store: LearningMemoryStore,
        question_bank: QuestionBank,
        provider: LearningProvider,
        max_topic_depth: int = 5,
    ):
        if max_topic_depth < 1:
            raise ValueError("max_topic_depth must be positive")
        self.memory_store = memory_store
        self.question_bank = question_bank
        self.provider = provider
        self.max_topic_depth = max_topic_depth

    @property
    def total_required_questions(self) -> int:
        topics = {question.topic for question in self.question_bank.all()}
        return max(len(topics) * self.max_topic_depth, 1)

    @staticmethod
    def _difficulty(mastery: float) -> Difficulty:
        if mastery < 0.45:
            return Difficulty.EASY
        if mastery < 0.75:
            return Difficulty.MEDIUM
        return Difficulty.HARD

    def _source_context(self, topic: str) -> str:
        related = [
            question for question in self.question_bank.all()
            if question.topic == topic
        ]
        return "; ".join(
            "%s — %s" % (question.source, question.explanation)
            for question in related[:5]
        )

    def _record(
        self,
        *,
        trigger: QuestionGenerationTrigger,
        user_id: Optional[str],
        status: str,
        reason: str,
        course_completion: float,
        topic: Optional[str],
        generated_count: int,
    ) -> str:
        return self.memory_store.record_question_generation_decision(
            trigger=trigger.value,
            user_id=user_id,
            status=status,
            reason=reason,
            course_completion=course_completion,
            topic_id=topic,
            generated_count=generated_count,
        )

    def generate_for_user(
        self,
        user_id: str,
        trigger: QuestionGenerationTrigger,
        topic: Optional[str] = None,
        count: int = DEFAULT_BATCH_SIZE,
    ) -> QuestionGenerationResult:
        if count < 1:
            raise ValueError("count must be positive")
        progress = self.memory_store.question_generation_progress(
            user_id,
            self.total_required_questions,
            topic,
        )
        completion = float(progress["course_completion"])
        selected_topic = progress["topic"]
        selected_topic = str(selected_topic) if selected_topic else None

        if completion < self.MINIMUM_COURSE_COMPLETION:
            reason = "course_completion_below_5_percent"
            decision_id = self._record(
                trigger=trigger,
                user_id=user_id,
                status="silent" if trigger == QuestionGenerationTrigger.NIGHTLY else "rejected",
                reason=reason,
                course_completion=completion,
                topic=selected_topic,
                generated_count=0,
            )
            return QuestionGenerationResult(
                status="silent" if trigger == QuestionGenerationTrigger.NIGHTLY else "rejected",
                reason=reason,
                user_id=user_id,
                course_completion=completion,
                topic=selected_topic,
                decision_id=decision_id,
            )

        if (
            trigger == QuestionGenerationTrigger.USER_REQUEST
            and int(progress["topic_attempt_count"]) < self.max_topic_depth
        ):
            reason = "topic_depth_below_%s" % self.max_topic_depth
            decision_id = self._record(
                trigger=trigger,
                user_id=user_id,
                status="rejected",
                reason=reason,
                course_completion=completion,
                topic=selected_topic,
                generated_count=0,
            )
            return QuestionGenerationResult(
                status="rejected",
                reason=reason,
                user_id=user_id,
                course_completion=completion,
                topic=selected_topic,
                decision_id=decision_id,
            )

        source_context = self._source_context(selected_topic or "")
        if not selected_topic or not source_context:
            reason = "no_grounded_topic_for_generation"
            status = "silent" if trigger == QuestionGenerationTrigger.NIGHTLY else "rejected"
            decision_id = self._record(
                trigger=trigger,
                user_id=user_id,
                status=status,
                reason=reason,
                course_completion=completion,
                topic=selected_topic,
                generated_count=0,
            )
            return QuestionGenerationResult(
                status=status,
                reason=reason,
                user_id=user_id,
                course_completion=completion,
                topic=selected_topic,
                decision_id=decision_id,
            )

        gaps = [str(item) for item in progress["knowledge_gaps"]]
        if not gaps:
            gaps = [selected_topic]
        generation_id = "question-generation-" + uuid4().hex
        generated: List[Question] = []
        try:
            for index in range(count):
                question = self.provider.generate_question(
                    topic=selected_topic,
                    difficulty=self._difficulty(float(progress["mastery"])),
                    knowledge_gaps=gaps,
                    source_context=source_context,
                    variation=index + 1,
                )
                identifier = "personal-%s" % hashlib.sha256(
                    ("%s:%s:%s" % (user_id, generation_id, index)).encode("utf-8")
                ).hexdigest()[:24]
                generated.append(
                    Question(
                        id=identifier,
                        topic=selected_topic,
                        difficulty=question.difficulty,
                        text=question.text,
                        expected_concepts=question.expected_concepts,
                        explanation=question.explanation,
                        source=question.source,
                    )
                )
            self.memory_store.add_personal_questions(
                user_id,
                generated,
                generation_id,
            )
        except Exception:
            self._record(
                trigger=trigger,
                user_id=user_id,
                status="failed",
                reason="question_generation_failed",
                course_completion=completion,
                topic=selected_topic,
                generated_count=0,
            )
            raise

        decision_id = self._record(
            trigger=trigger,
            user_id=user_id,
            status="generated",
            reason="generated_from_sqlite_learning_gaps",
            course_completion=completion,
            topic=selected_topic,
            generated_count=len(generated),
        )
        return QuestionGenerationResult(
            status="generated",
            reason="generated_from_sqlite_learning_gaps",
            user_id=user_id,
            course_completion=completion,
            topic=selected_topic,
            questions=generated,
            decision_id=decision_id,
        )

    def run_nightly(self) -> List[QuestionGenerationResult]:
        users = self.memory_store.users_with_attempts()
        if not users:
            decision_id = self._record(
                trigger=QuestionGenerationTrigger.NIGHTLY,
                user_id=None,
                status="silent",
                reason="no_student_progress",
                course_completion=0.0,
                topic=None,
                generated_count=0,
            )
            return [
                QuestionGenerationResult(
                    status="silent",
                    reason="no_student_progress",
                    user_id=None,
                    course_completion=0.0,
                    decision_id=decision_id,
                )
            ]
        return [
            self.generate_for_user(user_id, QuestionGenerationTrigger.NIGHTLY)
            for user_id in users
        ]

    def personal_question_for(self, user_id: str, question_id: str) -> Question:
        return self.memory_store.personal_question_for(user_id, question_id)

    def find_unused_question(
        self,
        user_id: str,
        topic: str,
        excluded_ids: List[str],
    ) -> Optional[Question]:
        return self.memory_store.find_unused_personal_question(
            user_id,
            topic,
            excluded_ids,
        )
