from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class TopicStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    MASTERY_CONFIRMATION_REQUIRED = "mastery_confirmation_required"
    MASTERED = "mastered"
    NEEDS_REVIEW = "needs_review"


class CheckpointDecision(str, Enum):
    MARK_MASTERED = "mark_mastered"
    ONE_MORE_QUESTION = "one_more_question"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class Question:
    id: str
    topic: str
    difficulty: Difficulty
    text: str
    expected_concepts: List[str]
    explanation: str
    source: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Question":
        required = {
            "id",
            "topic",
            "difficulty",
            "text",
            "expected_concepts",
            "explanation",
            "source",
        }
        missing = required.difference(data)
        if missing:
            raise ValueError("Question is missing fields: %s" % sorted(missing))
        concepts = data["expected_concepts"]
        if not isinstance(concepts, list) or not concepts:
            raise ValueError("expected_concepts must be a non-empty list")
        return cls(
            id=str(data["id"]),
            topic=str(data["topic"]),
            difficulty=Difficulty(str(data["difficulty"])),
            text=str(data["text"]),
            expected_concepts=[str(item) for item in concepts],
            explanation=str(data["explanation"]),
            source=str(data["source"]),
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["difficulty"] = self.difficulty.value
        return data


@dataclass(frozen=True)
class Assessment:
    question_id: str
    score: float
    feedback: str
    knowledge_gaps: List[str]
    recommended_difficulty: Difficulty

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0 and 1")
        if not self.feedback.strip():
            raise ValueError("feedback must not be empty")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Assessment":
        return cls(
            question_id=str(data["question_id"]),
            score=float(data["score"]),
            feedback=str(data["feedback"]),
            knowledge_gaps=[str(item) for item in data.get("knowledge_gaps", [])],
            recommended_difficulty=Difficulty(
                str(data["recommended_difficulty"])
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["recommended_difficulty"] = self.recommended_difficulty.value
        return data


@dataclass
class Attempt:
    question_id: str
    topic: str
    score: float
    feedback: str
    knowledge_gaps: List[str]
    question_text: str = ""
    student_answer: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Attempt":
        return cls(
            question_id=str(data["question_id"]),
            topic=str(data["topic"]),
            score=float(data["score"]),
            feedback=str(data["feedback"]),
            knowledge_gaps=[str(item) for item in data.get("knowledge_gaps", [])],
            question_text=str(data.get("question_text", "")),
            student_answer=str(data.get("student_answer", "")),
        )


@dataclass
class StudentProgress:
    user_id: str
    active_topic: str = "latency"
    topic_depth: int = 0
    extra_iteration_used: bool = False
    mastery: Dict[str, float] = field(default_factory=dict)
    knowledge_gaps: List[str] = field(default_factory=list)
    answered_question_ids: List[str] = field(default_factory=list)
    topic_status: TopicStatus = TopicStatus.IN_PROGRESS
    attempts: List[Attempt] = field(default_factory=list)
    topic_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StudentProgress":
        progress = cls(
            user_id=str(data["user_id"]),
            active_topic=str(data.get("active_topic", "latency")),
            topic_depth=int(data.get("topic_depth", 0)),
            extra_iteration_used=bool(data.get("extra_iteration_used", False)),
            mastery={
                str(key): float(value)
                for key, value in data.get("mastery", {}).items()
            },
            knowledge_gaps=[
                str(item) for item in data.get("knowledge_gaps", [])
            ],
            answered_question_ids=[
                str(item) for item in data.get("answered_question_ids", [])
            ],
            topic_status=TopicStatus(
                data.get("topic_status", TopicStatus.IN_PROGRESS.value)
            ),
            attempts=[
                Attempt.from_dict(item) for item in data.get("attempts", [])
            ],
            topic_states={
                str(topic): {
                    "depth": int(state.get("depth", 0)),
                    "extra_iteration_used": bool(
                        state.get("extra_iteration_used", False)
                    ),
                    "status": TopicStatus(
                        state.get("status", TopicStatus.IN_PROGRESS.value)
                    ).value,
                }
                for topic, state in data.get("topic_states", {}).items()
                if isinstance(state, dict)
            },
        )
        progress.recalculate_mastery()
        if progress.active_topic not in progress.topic_states:
            progress.sync_active_topic_state()
        return progress

    def recalculate_mastery(self) -> None:
        scores_by_topic: Dict[str, List[float]] = {}
        for attempt in self.attempts:
            scores_by_topic.setdefault(attempt.topic, []).append(attempt.score)
        for topic, scores in scores_by_topic.items():
            self.mastery[topic] = round(sum(scores) / len(scores), 3)

    def sync_active_topic_state(self) -> None:
        self.topic_states[self.active_topic] = {
            "depth": self.topic_depth,
            "extra_iteration_used": self.extra_iteration_used,
            "status": self.topic_status.value,
        }

    def activate_topic(self, topic: str) -> None:
        self.sync_active_topic_state()
        state = self.topic_states.get(
            topic,
            {
                "depth": 0,
                "extra_iteration_used": False,
                "status": TopicStatus.IN_PROGRESS.value,
            },
        )
        self.active_topic = topic
        self.topic_depth = int(state["depth"])
        self.extra_iteration_used = bool(state["extra_iteration_used"])
        self.topic_status = TopicStatus(str(state["status"]))
        self.sync_active_topic_state()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "active_topic": self.active_topic,
            "topic_depth": self.topic_depth,
            "extra_iteration_used": self.extra_iteration_used,
            "mastery": self.mastery,
            "knowledge_gaps": self.knowledge_gaps,
            "answered_question_ids": self.answered_question_ids,
            "topic_status": self.topic_status.value,
            "attempts": [asdict(attempt) for attempt in self.attempts],
            "topic_states": self.topic_states,
        }


@dataclass(frozen=True)
class ToolResult:
    success: bool
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    @classmethod
    def ok(cls, data: Dict[str, Any]) -> "ToolResult":
        return cls(success=True, data=data)

    @classmethod
    def error(cls, code: str, message: str) -> "ToolResult":
        return cls(
            success=False,
            error_code=code,
            error_message=message,
        )


@dataclass(frozen=True)
class AgentResult:
    status: str
    message: str
    assessment: Optional[Assessment] = None
    question: Optional[Question] = None
    progress: Optional[StudentProgress] = None
    allowed_actions: List[str] = field(default_factory=list)
    error_code: Optional[str] = None
