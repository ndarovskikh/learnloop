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
from typing import Iterable, List
from uuid import uuid4


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

    def reset_user(self, user_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM attempts WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM mastery WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
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
