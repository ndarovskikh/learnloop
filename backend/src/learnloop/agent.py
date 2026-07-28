from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set

from .models import (
    AgentResult,
    Assessment,
    CheckpointDecision,
    Difficulty,
    Question,
    TopicStatus,
)
from .repository import ProgressRepository
from .tools import ToolRegistry
from .admin_agent import AdminStatisticsAgent


def _question_from_result(data: Dict[str, Any]) -> Question:
    return Question.from_dict(data["question"])


def _assessment_from_result(data: Dict[str, Any]) -> Assessment:
    return Assessment.from_dict(data["assessment"])


class AgentLoop:
    """Direct observe → reason → act → verify state machine."""

    def __init__(
        self,
        registry: ToolRegistry,
        repository: ProgressRepository,
        max_steps: int = 12,
        admin_agent: Optional[AdminStatisticsAgent] = None,
    ):
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.registry = registry
        self.repository = repository
        self.max_steps = max_steps
        self.admin_agent = admin_agent

    def handle_chat_message(self, user_id: str, message: str) -> Optional[str]:
        """Route only self-service ranking questions to the privileged helper.

        The ordinary agent never receives cohort data. It can request the
        admin helper to calculate the current user's own aggregate position.
        """
        normalized = message.lower()
        statistics_words = ("перцентил", "процентиль", "топ", "рейтинг", "место среди", "percentile", "top ", "ranking")
        if not any(word in normalized for word in statistics_words):
            return None
        if any(word in normalized for word in ("другого студента", "другого пользователя", "other student", "another user")):
            return "Я могу показать только вашу собственную обезличенную позицию в группе."
        if self.admin_agent is None:
            return "Сравнительная статистика сейчас недоступна."
        try:
            result = self.admin_agent.benchmark(user_id)
        except ValueError as exc:
            if str(exc) == "INSUFFICIENT_COHORT":
                return "Пока недостаточно участников для безопасного сравнения."
            return "Пока нет достаточно ваших результатов для расчёта позиции."
        return result["message"]

    @staticmethod
    def _signature(name: str, arguments: Dict[str, Any]) -> str:
        return "%s:%s" % (
            name,
            json.dumps(arguments, sort_keys=True, ensure_ascii=False),
        )

    @staticmethod
    def _difficulty(progress_mastery: float) -> Difficulty:
        if progress_mastery < 0.45:
            return Difficulty.EASY
        if progress_mastery < 0.75:
            return Difficulty.MEDIUM
        return Difficulty.HARD

    def _execute_once(
        self,
        name: str,
        arguments: Dict[str, Any],
        signatures: Set[str],
    ):
        signature = self._signature(name, arguments)
        if signature in signatures:
            return None, AgentResult(
                status="stalled",
                message="The agent repeated an identical tool call and stopped.",
                error_code="REPEATED_TOOL_CALL",
            )
        signatures.add(signature)
        return self.registry.execute(name, arguments), None

    def start(self, user_id: str) -> AgentResult:
        try:
            progress = self.repository.load(user_id)
        except ValueError as exc:
            return AgentResult(
                status="failed",
                message=str(exc),
                error_code="STATE_READ_FAILED",
            )
        if progress.topic_status == TopicStatus.MASTERY_CONFIRMATION_REQUIRED:
            return self._checkpoint_result(progress)
        if progress.topic_status in (TopicStatus.MASTERED, TopicStatus.NEEDS_REVIEW):
            return AgentResult(
                status="topic_finished",
                message="The current topic session is already finished.",
                progress=progress,
            )

        difficulty = self._difficulty(
            progress.mastery.get(progress.active_topic, 0.0)
        )
        result = self.registry.execute(
            "generate_next_question",
            {
                "user_id": user_id,
                "topic": progress.active_topic,
                "difficulty": difficulty.value,
                "knowledge_gaps": progress.knowledge_gaps,
            },
        )
        if not result.success or result.data is None:
            return AgentResult(
                status="failed",
                message=result.error_message or "Could not create a question",
                progress=progress,
                error_code=result.error_code,
            )
        return AgentResult(
            status="question_ready",
            message="Answer the next question.",
            question=_question_from_result(result.data),
            progress=progress,
        )

    def submit_answer(
        self,
        user_id: str,
        question_id: str,
        student_answer: str,
    ) -> AgentResult:
        signatures: Set[str] = set()
        assessment: Optional[Assessment] = None
        next_question: Optional[Question] = None
        step = 0

        while step < self.max_steps:
            step += 1
            if assessment is None:
                arguments = {
                    "user_id": user_id,
                    "question_id": question_id,
                    "student_answer": student_answer,
                }
                tool_result, stopped = self._execute_once(
                    "assess_and_record_answer",
                    arguments,
                    signatures,
                )
                if stopped:
                    return stopped
                if tool_result is None or not tool_result.success:
                    return AgentResult(
                        status="failed",
                        message=(
                            tool_result.error_message
                            if tool_result
                            else "Assessment tool failed"
                        ),
                        error_code=(
                            tool_result.error_code if tool_result else "TOOL_FAILED"
                        ),
                    )
                if tool_result.data is None:
                    return AgentResult(
                        status="failed",
                        message="Assessment tool returned no data.",
                        error_code="EMPTY_TOOL_RESULT",
                    )
                assessment = _assessment_from_result(tool_result.data)

                try:
                    progress = self.repository.load(user_id)
                except ValueError as exc:
                    return AgentResult(
                        status="failed",
                        message=str(exc),
                        assessment=assessment,
                        error_code="STATE_VERIFY_FAILED",
                    )
                if question_id not in progress.answered_question_ids:
                    return AgentResult(
                        status="failed",
                        message="The assessment was not found in saved progress.",
                        assessment=assessment,
                        progress=progress,
                        error_code="ASSESSMENT_NOT_PERSISTED",
                    )
                if progress.topic_status == TopicStatus.MASTERY_CONFIRMATION_REQUIRED:
                    return self._checkpoint_result(progress, assessment)
                continue

            try:
                progress = self.repository.load(user_id)
            except ValueError as exc:
                return AgentResult(
                    status="failed",
                    message=str(exc),
                    assessment=assessment,
                    error_code="STATE_READ_FAILED",
                )
            difficulty = assessment.recommended_difficulty
            arguments = {
                "user_id": user_id,
                "topic": progress.active_topic,
                "difficulty": difficulty.value,
                "knowledge_gaps": assessment.knowledge_gaps,
            }
            tool_result, stopped = self._execute_once(
                "generate_next_question",
                arguments,
                signatures,
            )
            if stopped:
                return stopped
            if tool_result is None or not tool_result.success:
                return AgentResult(
                    status="failed",
                    message=(
                        tool_result.error_message
                        if tool_result
                        else "Question tool failed"
                    ),
                    assessment=assessment,
                    progress=progress,
                    error_code=(
                        tool_result.error_code if tool_result else "TOOL_FAILED"
                    ),
                )
            if tool_result.data is None:
                return AgentResult(
                    status="failed",
                    message="Question tool returned no data.",
                    assessment=assessment,
                    progress=progress,
                    error_code="EMPTY_TOOL_RESULT",
                )
            next_question = _question_from_result(tool_result.data)
            return AgentResult(
                status="question_ready",
                message=assessment.feedback,
                assessment=assessment,
                question=next_question,
                progress=progress,
            )

        return AgentResult(
            status="max_steps_reached",
            message="The agent reached its step limit and stopped safely.",
            assessment=assessment,
            question=next_question,
            error_code="MAX_STEPS_REACHED",
        )

    def resolve_checkpoint(
        self,
        user_id: str,
        decision: CheckpointDecision,
    ) -> AgentResult:
        result = self.registry.execute(
            "resolve_topic_checkpoint",
            {
                "user_id": user_id,
                "decision": decision.value,
            },
        )
        if not result.success:
            return AgentResult(
                status="failed",
                message=result.error_message or "Checkpoint update failed",
                error_code=result.error_code,
            )
        progress = self.repository.load(user_id)
        if decision == CheckpointDecision.ONE_MORE_QUESTION:
            return self.start(user_id)
        return AgentResult(
            status="topic_finished",
            message=(
                "Topic marked as mastered."
                if decision == CheckpointDecision.MARK_MASTERED
                else "Topic marked as needing review."
            ),
            progress=progress,
        )

    @staticmethod
    def _checkpoint_result(
        progress,
        assessment: Optional[Assessment] = None,
    ) -> AgentResult:
        actions: List[str] = [
            CheckpointDecision.MARK_MASTERED.value,
            CheckpointDecision.NEEDS_REVIEW.value,
        ]
        if not progress.extra_iteration_used:
            actions.insert(1, CheckpointDecision.ONE_MORE_QUESTION.value)
        return AgentResult(
            status=TopicStatus.MASTERY_CONFIRMATION_REQUIRED.value,
            message=(
                "You reached the planned depth for %s. "
                "Do you consider the material understood?" % progress.active_topic
            ),
            assessment=assessment,
            progress=progress,
            allowed_actions=actions,
        )
