from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Optional

from .models import Difficulty, Question


class QuestionBank:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def all(self) -> List[Question]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError("QUESTION_BANK_NOT_FOUND") from exc
        except json.JSONDecodeError as exc:
            raise ValueError("CORRUPTED_QUESTION_BANK: %s" % exc) from exc
        if not isinstance(payload, list):
            raise ValueError("CORRUPTED_QUESTION_BANK: root must be a list")
        questions = [Question.from_dict(item) for item in payload]
        ids = [question.id for question in questions]
        if len(ids) != len(set(ids)):
            raise ValueError("CORRUPTED_QUESTION_BANK: duplicate IDs")
        return questions

    def get(self, question_id: str) -> Question:
        for question in self.all():
            if question.id == question_id:
                return question
        raise KeyError(question_id)

    def find_unused(
        self,
        topic: str,
        difficulty: Difficulty,
        excluded_ids: Iterable[str],
    ) -> Optional[Question]:
        excluded = set(excluded_ids)
        exact = [
            question
            for question in self.all()
            if question.topic == topic
            and question.difficulty == difficulty
            and question.id not in excluded
        ]
        if exact:
            return exact[0]
        fallback = [
            question
            for question in self.all()
            if question.topic == topic and question.id not in excluded
        ]
        return fallback[0] if fallback else None

    def add(self, question: Question) -> None:
        questions = self.all()
        if any(existing.id == question.id for existing in questions):
            raise ValueError("DUPLICATE_QUESTION_ID")
        normalized = question.text.strip().lower()
        if any(existing.text.strip().lower() == normalized for existing in questions):
            raise ValueError("DUPLICATE_QUESTION_TEXT")
        questions.append(question)
        self.path.write_text(
            json.dumps(
                [item.to_dict() for item in questions],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

