from __future__ import annotations

from dataclasses import asdict
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from .coordination import AgentHandoff, CoordinationMemory
from .models import (
    Assessment,
    Attempt,
    CheckpointDecision,
    Difficulty,
    StudentProgress,
    ToolResult,
    TopicStatus,
)
from .memory_store import LearningMemoryStore
from .context import LearningContext
from .provider import LearningProvider
from .question_bank import QuestionBank
from .repository import ProgressRepository


def _unique(values: List[str]) -> List[str]:
    return list(dict.fromkeys(value for value in values if value))


class LearningTools:
    def __init__(
        self,
        repository: ProgressRepository,
        question_bank: QuestionBank,
        provider: LearningProvider,
        max_topic_depth: int = 5,
        max_extra_iterations: int = 1,
        memory_store: Optional[LearningMemoryStore] = None,
        learning_context: Optional[LearningContext] = None,
    ):
        self.repository = repository
        self.question_bank = question_bank
        self.provider = provider
        self.max_topic_depth = max_topic_depth
        self.max_extra_iterations = max_extra_iterations
        self.memory_store = memory_store
        self.learning_context = learning_context
        self.coordination_memory = CoordinationMemory(repository.progress_dir)

    def _persist_learning_memory(
        self,
        user_id: str,
        question,
        assessment: Assessment,
    ) -> None:
        """Store durable facts after the main progress write has succeeded.

        The historical progress JSON remains the current-session state during
        this transition; SQLite is the durable event and analytics store.
        A storage outage must not invalidate an answer that was already saved.
        """
        if self.memory_store is None:
            return
        try:
            self.memory_store.seed_question(
                course_id="ddia",
                course_title="Designing Data-Intensive Applications",
                topic_id=question.topic,
                topic_title=question.topic.replace("_", " ").title(),
                question_id=question.id,
                difficulty=question.difficulty.value,
                question_text=question.text,
                expected_answer="; ".join(question.expected_concepts),
            )
            attempt_id = self.memory_store.record_attempt(
                user_id=user_id,
                user_name=user_id,
                question_id=question.id,
                score=assessment.score,
            )
            if assessment.knowledge_gaps:
                gaps = ", ".join(assessment.knowledge_gaps)
                self.memory_store.remember(
                    user_id=user_id,
                    type="learning_fact",
                    content="Student needs practice with: %s." % gaps,
                    cue=[question.topic, *assessment.knowledge_gaps],
                    source={"question_id": question.id, "attempt_id": attempt_id},
                )
        except (OSError, sqlite3.Error, KeyError, ValueError) as exc:
            logging.getLogger(__name__).warning(
                "Learning memory was not persisted for %s: %s", user_id, exc
            )

    def assess_and_record_answer(
        self,
        user_id: str,
        question_id: str,
        student_answer: str,
    ) -> ToolResult:
        if not student_answer.strip():
            return ToolResult.error("EMPTY_ANSWER", "Student answer must not be empty")
        try:
            question = self.question_bank.get(question_id)
            progress = self.repository.load(user_id)
        except KeyError:
            return ToolResult.error(
                "QUESTION_NOT_FOUND",
                "Question %s does not exist" % question_id,
            )
        except ValueError as exc:
            return ToolResult.error("STATE_READ_FAILED", str(exc))

        if question_id in progress.answered_question_ids:
            return ToolResult.error(
                "QUESTION_ALREADY_ANSWERED",
                "Question %s was already recorded" % question_id,
            )
        if progress.topic_status == TopicStatus.MASTERY_CONFIRMATION_REQUIRED:
            return ToolResult.error(
                "CHECKPOINT_PENDING",
                "Resolve the topic checkpoint before another answer",
            )
        try:
            push_context = (
                self.learning_context.push(user_id, question)
                if self.learning_context else ""
            )
            # Executor proposes an assessment. It cannot write learner progress.
            proposal = AgentHandoff(
                status="assessment_proposed",
                result={
                    "assessment": self.provider.assess(
                        question,
                        student_answer,
                        push_context,
                    ).to_dict()
                },
            )
            self.coordination_memory.append("assessment_executor", proposal)
            if proposal.status != "assessment_proposed" or proposal.needs_approval:
                return ToolResult.error(
                    "ASSESSMENT_APPROVAL_REQUIRED",
                    "The assessment proposal requires review before saving.",
                )

            # The verifier receives only the structured proposal and independently
            # checks it against the question rubric. Persistence is gated on it.
            verification = self.provider.verify_assessment(
                question,
                student_answer,
                proposal,
                push_context,
            )
            self.coordination_memory.append("answer_verifier", verification)
            if verification.needs_approval:
                return ToolResult.error(
                    "VERIFICATION_APPROVAL_REQUIRED",
                    "The answer verifier requested human review.",
                )
            if verification.status != "verified":
                return ToolResult.error(
                    "ASSESSMENT_REJECTED",
                    str(verification.result.get("reason", "Verifier rejected assessment")),
                )
            assessment = Assessment.from_dict(verification.result["assessment"])
        except Exception as exc:
            return ToolResult.error("ASSESSMENT_FAILED", str(exc))

        if assessment.question_id != question.id:
            return ToolResult.error(
                "ASSESSMENT_QUESTION_MISMATCH",
                "Evaluator returned an assessment for another question",
            )

        progress.active_topic = question.topic
        progress.topic_depth += 1
        progress.knowledge_gaps = _unique(
            progress.knowledge_gaps + assessment.knowledge_gaps
        )
        progress.answered_question_ids.append(question.id)
        progress.attempts.append(
            Attempt(
                question_id=question.id,
                topic=question.topic,
                score=assessment.score,
                feedback=assessment.feedback,
                knowledge_gaps=assessment.knowledge_gaps,
                question_text=question.text,
                student_answer=student_answer,
            )
        )
        progress.recalculate_mastery()
        new_mastery = progress.mastery[question.topic]

        checkpoint_required = progress.topic_depth >= self.max_topic_depth
        if checkpoint_required:
            progress.topic_status = TopicStatus.MASTERY_CONFIRMATION_REQUIRED

        try:
            self.repository.save(progress)
            verified = self.repository.load(user_id)
        except (OSError, ValueError) as exc:
            return ToolResult.error("PROGRESS_WRITE_FAILED", str(exc))

        if (
            verified.topic_depth != progress.topic_depth
            or question.id not in verified.answered_question_ids
        ):
            return ToolResult.error(
                "PROGRESS_VERIFICATION_FAILED",
                "Saved progress does not contain the expected attempt",
            )

        self._persist_learning_memory(user_id, question, assessment)

        return ToolResult.ok(
            {
                "assessment": assessment.to_dict(),
                "saved_state": {
                    "topic": question.topic,
                    "topic_depth": verified.topic_depth,
                    "mastery": verified.mastery[question.topic],
                    "topic_status": verified.topic_status.value,
                },
                "checkpoint_required": checkpoint_required,
            }
        )

    def generate_next_question(
        self,
        user_id: str,
        topic: str,
        difficulty: Difficulty,
        knowledge_gaps: List[str],
    ) -> ToolResult:
        try:
            progress = self.repository.load(user_id)
        except ValueError as exc:
            return ToolResult.error("STATE_READ_FAILED", str(exc))

        if progress.topic_status == TopicStatus.MASTERY_CONFIRMATION_REQUIRED:
            return ToolResult.error(
                "CHECKPOINT_PENDING",
                "Student validation is required before another question",
            )
        if progress.topic_status in (TopicStatus.MASTERED, TopicStatus.NEEDS_REVIEW):
            return ToolResult.error(
                "TOPIC_SESSION_FINISHED",
                "The current topic session has already finished",
            )

        try:
            question = self.question_bank.find_unused(
                topic=topic,
                difficulty=difficulty,
                excluded_ids=progress.answered_question_ids,
            )
            generated = False
            if question is None:
                related = [
                    item
                    for item in self.question_bank.all()
                    if item.topic == topic
                ]
                source_context = "; ".join(
                    "%s — %s" % (item.source, item.explanation)
                    for item in related[:3]
                )
                if not source_context:
                    return ToolResult.error(
                        "NO_GROUNDED_SOURCE",
                        "No approved course source exists for topic %s" % topic,
                    )
                push_context = (
                    self.learning_context.push(user_id)
                    if self.learning_context else ""
                )
                pulled = self.retrieve_learning_memory(
                    user_id=user_id, topic=topic, limit=5
                )
                question = self.provider.generate_question(
                    topic=topic,
                    difficulty=difficulty,
                    knowledge_gaps=knowledge_gaps,
                    source_context=source_context,
                    context=push_context + "\nPULLED LEARNING MEMORY: " + str(pulled.data if pulled.success else []),
                )
                if not question.expected_concepts or not question.source.strip():
                    return ToolResult.error(
                        "UNGROUNDED_QUESTION",
                        "Generated question has no rubric or source",
                    )
                self.question_bank.add(question)
                generated = True
        except (KeyError, OSError, ValueError) as exc:
            return ToolResult.error("QUESTION_GENERATION_FAILED", str(exc))
        except Exception as exc:
            return ToolResult.error("PROVIDER_QUESTION_FAILED", str(exc))

        return ToolResult.ok(
            {
                "question": question.to_dict(),
                "generated": generated,
            }
        )

    def resolve_topic_checkpoint(
        self,
        user_id: str,
        decision: CheckpointDecision,
    ) -> ToolResult:
        try:
            progress = self.repository.load(user_id)
        except ValueError as exc:
            return ToolResult.error("STATE_READ_FAILED", str(exc))
        if progress.topic_status != TopicStatus.MASTERY_CONFIRMATION_REQUIRED:
            return ToolResult.error(
                "NO_CHECKPOINT_PENDING",
                "There is no mastery checkpoint awaiting a decision",
            )

        if decision == CheckpointDecision.MARK_MASTERED:
            progress.topic_status = TopicStatus.MASTERED
        elif decision == CheckpointDecision.NEEDS_REVIEW:
            progress.topic_status = TopicStatus.NEEDS_REVIEW
        elif decision == CheckpointDecision.ONE_MORE_QUESTION:
            if self.max_extra_iterations < 1 or progress.extra_iteration_used:
                return ToolResult.error(
                    "EXTRA_ITERATION_ALREADY_USED",
                    "Only one extra topic question is allowed",
                )
            progress.extra_iteration_used = True
            progress.topic_status = TopicStatus.IN_PROGRESS
        else:
            return ToolResult.error("INVALID_DECISION", str(decision))

        try:
            self.repository.save(progress)
            verified = self.repository.load(user_id)
        except (OSError, ValueError) as exc:
            return ToolResult.error("PROGRESS_WRITE_FAILED", str(exc))

        return ToolResult.ok(
            {
                "decision": decision.value,
                "progress": verified.to_dict(),
            }
        )

    def reset_learning_progress(
        self,
        user_id: str,
        explicit_confirmation: bool,
    ) -> ToolResult:
        if explicit_confirmation is not True:
            return ToolResult.error(
                "APPROVAL_REQUIRED",
                "Reset requires a separate explicit user confirmation",
            )
        try:
            progress = self.repository.reset(user_id)
        except (OSError, ValueError) as exc:
            return ToolResult.error("RESET_FAILED", str(exc))
        if self.memory_store:
            try:
                self.memory_store.reset_user(user_id)
            except (OSError, sqlite3.Error, ValueError):
                logging.getLogger(__name__).warning(
                    "Structured learning memory was not reset for %s", user_id
                )
        return ToolResult.ok({"progress": progress.to_dict()})

    def reset_topic_progress(
        self,
        user_id: str,
        topic: str,
        explicit_confirmation: bool,
    ) -> ToolResult:
        if explicit_confirmation is not True:
            return ToolResult.error(
                "APPROVAL_REQUIRED",
                "Topic reset requires a separate explicit user confirmation",
            )
        try:
            progress = self.repository.load(user_id)
            if topic != progress.active_topic:
                return ToolResult.error(
                    "TOPIC_MISMATCH",
                    "Only the current topic can be reset",
                )
            progress = self.repository.reset_topic(user_id, topic)
        except (OSError, ValueError) as exc:
            return ToolResult.error("RESET_FAILED", str(exc))
        if self.memory_store:
            try:
                self.memory_store.reset_topic(user_id, topic)
            except (OSError, sqlite3.Error, ValueError):
                logging.getLogger(__name__).warning(
                    "Topic learning memory was not reset for %s", user_id
                )
        return ToolResult.ok({"progress": progress.to_dict()})

    def select_learning_topic(
        self,
        user_id: str,
        topic: str,
    ) -> ToolResult:
        valid_topics = {question.topic for question in self.question_bank.all()}
        if topic not in valid_topics:
            return ToolResult.error(
                "TOPIC_NOT_FOUND",
                "Topic %s does not exist in the question bank" % topic,
            )
        try:
            progress = self.repository.load(user_id)
            progress.activate_topic(topic)
            self.repository.save(progress)
            verified = self.repository.load(user_id)
        except (OSError, ValueError) as exc:
            return ToolResult.error("TOPIC_SELECTION_FAILED", str(exc))
        return ToolResult.ok({"progress": verified.to_dict()})

    def retrieve_learning_memory(self, user_id: str, topic: str = "", limit: int = 5) -> ToolResult:
        if self.learning_context is None:
            return ToolResult.ok({"memories": []})
        return ToolResult.ok({"memories": self.learning_context.retrieve_learning_memory(user_id, topic or None, min(max(limit, 1), 10))})

    def get_topic_mastery(self, user_id: str, topic: str) -> ToolResult:
        if self.learning_context is None:
            return ToolResult.ok({"mastery_score": None})
        return ToolResult.ok({"mastery_score": self.learning_context.get_topic_mastery(user_id, topic)})

    def get_previous_attempts(self, user_id: str, topic: str = "", limit: int = 5) -> ToolResult:
        if self.learning_context is None:
            return ToolResult.ok({"attempts": []})
        return ToolResult.ok({"attempts": self.learning_context.get_previous_attempts(user_id, topic or None, min(max(limit, 1), 10))})

    def get_course_material(self, topic: str, limit: int = 3) -> ToolResult:
        if self.learning_context is None:
            return ToolResult.ok({"materials": []})
        return ToolResult.ok({"materials": self.learning_context.get_course_material(topic, min(max(limit, 1), 5))})


class ToolRegistry:
    """Small allowlist that exposes only named, validated learning tools."""

    SCHEMAS: Dict[str, Dict[str, Any]] = {
        "assess_and_record_answer": {
            "required": ["user_id", "question_id", "student_answer"],
        },
        "generate_next_question": {
            "required": ["user_id", "topic", "difficulty", "knowledge_gaps"],
        },
        "resolve_topic_checkpoint": {
            "required": ["user_id", "decision"],
        },
        "reset_learning_progress": {
            "required": ["user_id", "explicit_confirmation"],
        },
        "reset_topic_progress": {
            "required": ["user_id", "topic", "explicit_confirmation"],
        },
        "select_learning_topic": {
            "required": ["user_id", "topic"],
        },
        "retrieve_learning_memory": {"required": ["user_id"]},
        "get_topic_mastery": {"required": ["user_id", "topic"]},
        "get_previous_attempts": {"required": ["user_id"]},
        "get_course_material": {"required": ["topic"]},
    }

    def __init__(self, tools: LearningTools):
        self.tools = tools

    def execute(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        schema = self.SCHEMAS.get(name)
        if schema is None:
            return ToolResult.error("UNKNOWN_TOOL", "Tool %s is not allowed" % name)
        missing = [
            key for key in schema["required"] if key not in arguments
        ]
        if missing:
            return ToolResult.error(
                "INVALID_TOOL_ARGUMENTS",
                "Missing required arguments: %s" % ", ".join(missing),
            )
        try:
            if name == "assess_and_record_answer":
                return self.tools.assess_and_record_answer(
                    user_id=str(arguments["user_id"]),
                    question_id=str(arguments["question_id"]),
                    student_answer=str(arguments["student_answer"]),
                )
            if name == "generate_next_question":
                return self.tools.generate_next_question(
                    user_id=str(arguments["user_id"]),
                    topic=str(arguments["topic"]),
                    difficulty=Difficulty(str(arguments["difficulty"])),
                    knowledge_gaps=[
                        str(item) for item in arguments["knowledge_gaps"]
                    ],
                )
            if name == "resolve_topic_checkpoint":
                return self.tools.resolve_topic_checkpoint(
                    user_id=str(arguments["user_id"]),
                    decision=CheckpointDecision(str(arguments["decision"])),
                )
            if name == "reset_topic_progress":
                return self.tools.reset_topic_progress(
                    user_id=str(arguments["user_id"]),
                    topic=str(arguments["topic"]),
                    explicit_confirmation=arguments["explicit_confirmation"] is True,
                )
            if name == "select_learning_topic":
                return self.tools.select_learning_topic(
                    user_id=str(arguments["user_id"]),
                    topic=str(arguments["topic"]),
                )
            if name == "retrieve_learning_memory":
                return self.tools.retrieve_learning_memory(str(arguments["user_id"]), str(arguments.get("topic", "")), int(arguments.get("limit", 5)))
            if name == "get_topic_mastery":
                return self.tools.get_topic_mastery(str(arguments["user_id"]), str(arguments["topic"]))
            if name == "get_previous_attempts":
                return self.tools.get_previous_attempts(str(arguments["user_id"]), str(arguments.get("topic", "")), int(arguments.get("limit", 5)))
            if name == "get_course_material":
                return self.tools.get_course_material(str(arguments["topic"]), int(arguments.get("limit", 3)))
            return self.tools.reset_learning_progress(
                user_id=str(arguments["user_id"]),
                explicit_confirmation=arguments["explicit_confirmation"] is True,
            )
        except (TypeError, ValueError) as exc:
            return ToolResult.error("INVALID_TOOL_ARGUMENTS", str(exc))
