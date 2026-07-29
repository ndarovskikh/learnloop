"""Small persistence layer for the three LearnLoop memory types.

SQLite keeps facts and relations.
JSON Lines keeps coach observations, and
``coach_rules.md`` is deliberately read-only from the application's point of
view: a course author owns those operating rules.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from uuid import uuid4

from .models import Difficulty, Question


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class LearningMemory:
    memory_id: str
    user_id: str
    type: str
    content: str
    cue: List[str]
    source: dict
    created_at: str


class LearningMemoryStore:
    """A minimal, dependency-free implementation of the proposed split."""

    def __init__(self, database_path: Path, memories_path: Path):
        self.database_path = database_path
        self.memories_path = memories_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.memories_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS courses (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS topics (
                    id TEXT PRIMARY KEY,
                    course_id TEXT NOT NULL REFERENCES courses(id),
                    title TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY,
                    topic_id TEXT NOT NULL REFERENCES topics(id),
                    difficulty TEXT NOT NULL,
                    question_text TEXT NOT NULL,
                    expected_answer TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    question_id TEXT NOT NULL REFERENCES questions(id),
                    score REAL NOT NULL CHECK(score >= 0 AND score <= 1),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mastery (
                    user_id TEXT NOT NULL REFERENCES users(id),
                    topic_id TEXT NOT NULL REFERENCES topics(id),
                    mastery_score REAL NOT NULL CHECK(mastery_score >= 0 AND mastery_score <= 1),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, topic_id)
                );
                CREATE TABLE IF NOT EXISTS personal_questions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    topic_id TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    question_text TEXT NOT NULL,
                    expected_concepts TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    source TEXT NOT NULL,
                    generation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_personal_questions_owner_topic
                    ON personal_questions(user_id, topic_id, created_at);
                CREATE TABLE IF NOT EXISTS question_generation_logs (
                    id TEXT PRIMARY KEY,
                    trigger TEXT NOT NULL,
                    user_id TEXT,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    course_completion REAL NOT NULL,
                    topic_id TEXT,
                    generated_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_question_generation_logs_user
                    ON question_generation_logs(user_id, created_at);
                """
            )

    def seed_question(
        self,
        *,
        course_id: str,
        course_title: str,
        topic_id: str,
        topic_title: str,
        question_id: str,
        difficulty: str,
        question_text: str,
        expected_answer: str,
    ) -> None:
        with self._connection() as connection:
            connection.execute("INSERT OR IGNORE INTO courses VALUES (?, ?)", (course_id, course_title))
            connection.execute("INSERT OR IGNORE INTO topics VALUES (?, ?, ?)", (topic_id, course_id, topic_title))
            connection.execute("INSERT OR IGNORE INTO questions VALUES (?, ?, ?, ?, ?)", (question_id, topic_id, difficulty, question_text, expected_answer))

    def record_attempt(self, *, user_id: str, user_name: str, question_id: str, score: float) -> str:
        if not 0 <= score <= 1:
            raise ValueError("score must be between 0 and 1")
        attempt_id, timestamp = "attempt-" + uuid4().hex, _now()
        with self._connection() as connection:
            connection.execute("INSERT OR IGNORE INTO users VALUES (?, ?)", (user_id, user_name))
            topic = connection.execute(
                "SELECT topic_id FROM questions WHERE id = ?", (question_id,)
            ).fetchone()
            if topic is None:
                raise KeyError("unknown question: %s" % question_id)
            connection.execute(
                "INSERT INTO attempts VALUES (?, ?, ?, ?, ?)",
                (attempt_id, user_id, question_id, score, timestamp),
            )
            mastery_score = connection.execute(
                "SELECT AVG(score) FROM attempts a JOIN questions q ON q.id = a.question_id "
                "WHERE a.user_id = ? AND q.topic_id = ?", (user_id, topic["topic_id"])
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO mastery VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, topic_id) DO UPDATE SET mastery_score = excluded.mastery_score, updated_at = excluded.updated_at",
                (user_id, topic["topic_id"], mastery_score, timestamp),
            )
        return attempt_id

    def mastery_for(self, user_id: str, topic_id: str) -> float:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT mastery_score FROM mastery WHERE user_id = ? AND topic_id = ?",
                (user_id, topic_id),
            ).fetchone()
        if row is None:
            raise KeyError("no mastery for user/topic")
        return float(row["mastery_score"])

    def remember(self, *, user_id: str, type: str, content: str, cue: Iterable[str], source: dict) -> LearningMemory:
        if not content.strip():
            raise ValueError("memory content must not be empty")
        memory = LearningMemory(
            memory_id="mem-" + uuid4().hex,
            user_id=user_id,
            type=type,
            content=content.strip(),
            cue=list(cue),
            source=source,
            created_at=_now(),
        )
        with self.memories_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(asdict(memory), ensure_ascii=False) + "\n")
        return memory

    def memories_for(self, user_id: str) -> List[LearningMemory]:
        if not self.memories_path.exists():
            return []
        result = []
        for line in self.memories_path.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            if payload["user_id"] == user_id:
                result.append(LearningMemory(**payload))
        return result

    def attempt_count_for(self, user_id: str) -> int:
        with self._connection() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM attempts WHERE user_id = ?", (user_id,)
            ).fetchone()[0])

    def users_with_attempts(self) -> List[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT DISTINCT user_id FROM attempts ORDER BY user_id"
            ).fetchall()
        return [str(row["user_id"]) for row in rows]

    def question_generation_progress(
        self,
        user_id: str,
        total_required_questions: int,
        topic_id: Optional[str] = None,
    ) -> Dict[str, object]:
        """Read completion and knowledge gaps only from durable SQLite data."""
        if total_required_questions < 1:
            raise ValueError("total_required_questions must be positive")
        with self._connection() as connection:
            attempt_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM attempts WHERE user_id = ?",
                    (user_id,),
                ).fetchone()[0]
            )
            if topic_id:
                topic = connection.execute(
                    "SELECT q.topic_id, COUNT(*) AS attempt_count, AVG(a.score) AS mastery "
                    "FROM attempts a JOIN questions q ON q.id = a.question_id "
                    "WHERE a.user_id = ? AND q.topic_id = ? GROUP BY q.topic_id",
                    (user_id, topic_id),
                ).fetchone()
            else:
                topic = connection.execute(
                    "SELECT q.topic_id, COUNT(*) AS attempt_count, AVG(a.score) AS mastery "
                    "FROM attempts a JOIN questions q ON q.id = a.question_id "
                    "WHERE a.user_id = ? GROUP BY q.topic_id "
                    "ORDER BY mastery ASC, attempt_count DESC, q.topic_id ASC LIMIT 1",
                    (user_id,),
                ).fetchone()

            selected_topic = str(topic["topic_id"]) if topic is not None else topic_id
            gap_rows = []
            if selected_topic:
                gap_rows = connection.execute(
                    "SELECT q.expected_answer FROM attempts a "
                    "JOIN questions q ON q.id = a.question_id "
                    "WHERE a.user_id = ? AND q.topic_id = ? "
                    "ORDER BY a.score ASC, a.created_at DESC LIMIT 5",
                    (user_id, selected_topic),
                ).fetchall()

        gaps: List[str] = []
        for row in gap_rows:
            for concept in str(row["expected_answer"]).split(";"):
                normalized = concept.strip()
                if normalized and normalized not in gaps:
                    gaps.append(normalized)
        return {
            "user_id": user_id,
            "attempt_count": attempt_count,
            "course_completion": min(
                attempt_count / total_required_questions * 100.0,
                100.0,
            ),
            "topic": selected_topic,
            "topic_attempt_count": int(topic["attempt_count"]) if topic else 0,
            "mastery": float(topic["mastery"]) if topic else 0.0,
            "knowledge_gaps": gaps,
        }

    def add_personal_question(
        self,
        user_id: str,
        question: Question,
        generation_id: str,
    ) -> None:
        self.add_personal_questions(user_id, [question], generation_id)

    def add_personal_questions(
        self,
        user_id: str,
        questions: Iterable[Question],
        generation_id: str,
    ) -> None:
        timestamp = _now()
        rows = [
            (
                question.id,
                user_id,
                question.topic,
                question.difficulty.value,
                question.text,
                json.dumps(question.expected_concepts, ensure_ascii=False),
                question.explanation,
                question.source,
                generation_id,
                timestamp,
            )
            for question in questions
        ]
        with self._connection() as connection:
            connection.executemany(
                "INSERT INTO personal_questions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    @staticmethod
    def _personal_question_from_row(row: sqlite3.Row) -> Question:
        return Question(
            id=str(row["id"]),
            topic=str(row["topic_id"]),
            difficulty=Difficulty(str(row["difficulty"])),
            text=str(row["question_text"]),
            expected_concepts=[
                str(item) for item in json.loads(row["expected_concepts"])
            ],
            explanation=str(row["explanation"]),
            source=str(row["source"]),
        )

    def personal_question_for(self, user_id: str, question_id: str) -> Question:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM personal_questions WHERE user_id = ? AND id = ?",
                (user_id, question_id),
            ).fetchone()
        if row is None:
            raise KeyError(question_id)
        return self._personal_question_from_row(row)

    def find_unused_personal_question(
        self,
        user_id: str,
        topic_id: str,
        excluded_ids: Iterable[str],
    ) -> Optional[Question]:
        excluded = set(excluded_ids)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM personal_questions "
                "WHERE user_id = ? AND topic_id = ? ORDER BY created_at ASC, id ASC",
                (user_id, topic_id),
            ).fetchall()
        for row in rows:
            if str(row["id"]) not in excluded:
                return self._personal_question_from_row(row)
        return None

    def record_question_generation_decision(
        self,
        *,
        trigger: str,
        user_id: Optional[str],
        status: str,
        reason: str,
        course_completion: float,
        topic_id: Optional[str],
        generated_count: int,
    ) -> str:
        decision_id = "generation-log-" + uuid4().hex
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO question_generation_logs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_id,
                    trigger,
                    user_id,
                    status,
                    reason,
                    course_completion,
                    topic_id,
                    generated_count,
                    _now(),
                ),
            )
        return decision_id

    def question_generation_logs(
        self,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        with self._connection() as connection:
            if user_id is None:
                rows = connection.execute(
                    "SELECT * FROM question_generation_logs ORDER BY created_at, id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM question_generation_logs "
                    "WHERE user_id = ? ORDER BY created_at, id",
                    (user_id,),
                ).fetchall()
        return [dict(row) for row in rows]

    def reset_user(self, user_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM attempts WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM mastery WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
            connection.execute(
                "DELETE FROM personal_questions WHERE user_id = ?", (user_id,)
            )
        self._rewrite_memories(
            memory for memory in self.memories_for_all() if memory.user_id != user_id
        )

    def reset_topic(self, user_id: str, topic_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM attempts WHERE user_id = ? AND question_id IN "
                "(SELECT id FROM questions WHERE topic_id = ?)",
                (user_id, topic_id),
            )
            connection.execute(
                "DELETE FROM mastery WHERE user_id = ? AND topic_id = ?",
                (user_id, topic_id),
            )
            connection.execute(
                "DELETE FROM personal_questions WHERE user_id = ? AND topic_id = ?",
                (user_id, topic_id),
            )
        self._rewrite_memories(
            memory for memory in self.memories_for_all()
            if not (
                memory.user_id == user_id
                and topic_id in memory.cue
            )
        )

    def memories_for_all(self) -> List[LearningMemory]:
        if not self.memories_path.exists():
            return []
        return [
            LearningMemory(**json.loads(line))
            for line in self.memories_path.read_text(encoding="utf-8").splitlines()
        ]

    def _rewrite_memories(self, memories: Iterable[LearningMemory]) -> None:
        payload = "".join(
            json.dumps(asdict(memory), ensure_ascii=False) + "\n"
            for memory in memories
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=self.memories_path.name + ".",
            suffix=".tmp",
            dir=str(self.memories_path.parent),
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, self.memories_path)
        except Exception:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
            raise
