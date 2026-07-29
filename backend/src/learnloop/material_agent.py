"""Agent 5 — "Natali": reacts to teacher-uploaded course material.

This agent sits to the side of the main coach/student loop. A teacher
publishing a new longread for the course is the only thing that wakes it up.
When it runs, it:

1. stores the material so students can open it from the course library;
2. grounds a small batch of new questions in that material and adds them to
   the shared question bank;
3. refreshes every known student's saved progress so the new topic/questions
   show up immediately instead of waiting for their next answer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .memory_store import LearningMemoryStore
from .models import Difficulty, Question
from .provider import LearningProvider
from .question_bank import QuestionBank
from .repository import ProgressRepository


@dataclass(frozen=True)
class MaterialIngestionResult:
    material_id: str
    topic_id: str
    title: str
    generated_questions: List[Question] = field(default_factory=list)
    recalculated_students: int = 0


class CourseMaterialAgent:
    DEFAULT_QUESTION_COUNT = 5

    def __init__(
        self,
        materials_dir: Path,
        question_bank: QuestionBank,
        provider: LearningProvider,
        repository: ProgressRepository,
        memory_store: Optional[LearningMemoryStore] = None,
    ):
        self.materials_dir = materials_dir
        self.materials_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.materials_dir / "materials_index.json"
        self.question_bank = question_bank
        self.provider = provider
        self.repository = repository
        self.memory_store = memory_store

    def _load_index(self) -> List[Dict[str, Any]]:
        if not self.index_path.exists():
            return []
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def _save_index(self, entries: List[Dict[str, Any]]) -> None:
        self.index_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def list_materials(self) -> List[Dict[str, Any]]:
        return self._load_index()

    def read_material(self, material_id: str) -> Optional[str]:
        for entry in self._load_index():
            if entry["id"] == material_id:
                path = self.materials_dir / entry["filename"]
                return path.read_text(encoding="utf-8") if path.exists() else None
        return None

    def _known_user_ids(self) -> List[str]:
        users = set(self.memory_store.users_with_attempts()) if self.memory_store else set()
        if self.repository.progress_dir.exists():
            users.update(path.stem for path in self.repository.progress_dir.glob("*.json"))
        return sorted(users)

    def _recalculate_progress(self) -> int:
        """Reload and resave every known student's progress.

        Course completion and the topic list are derived on the fly from the
        question bank, so this mainly guarantees mastery is recomputed and
        each student's file is touched right after the bank changes, rather
        than silently waiting for their next answer.
        """
        touched = 0
        for user_id in self._known_user_ids():
            progress = self.repository.load(user_id)
            progress.recalculate_mastery()
            self.repository.save(progress)
            touched += 1
        return touched

    def ingest_material(
        self,
        topic_id: str,
        topic_title: str,
        title: str,
        content: str,
        question_count: int = DEFAULT_QUESTION_COUNT,
    ) -> MaterialIngestionResult:
        if not topic_id.strip():
            raise ValueError("topic_id must not be empty")
        if not content.strip():
            raise ValueError("MATERIAL_CONTENT_EMPTY")
        if question_count < 1:
            raise ValueError("question_count must be positive")

        material_id = "material-" + uuid4().hex[:12]
        filename = "%s.md" % material_id
        (self.materials_dir / filename).write_text(content, encoding="utf-8")

        entries = self._load_index()
        entries.append(
            {
                "id": material_id,
                "topic_id": topic_id,
                "topic_title": topic_title,
                "title": title,
                "filename": filename,
            }
        )
        self._save_index(entries)

        source_label = "%s (teacher upload)" % title
        excerpt = content.strip()[:4000]
        difficulties = (Difficulty.EASY, Difficulty.EASY, Difficulty.MEDIUM, Difficulty.MEDIUM, Difficulty.HARD)
        generated: List[Question] = []
        for index in range(question_count):
            drafted = self.provider.generate_question(
                topic=topic_id,
                difficulty=difficulties[index % len(difficulties)],
                knowledge_gaps=[topic_title],
                source_context=excerpt,
                context="NEW COURSE MATERIAL uploaded by the teacher:\n" + excerpt,
                variation=index + 1,
            )
            grounded = Question(
                id="%s-q%s" % (material_id, index + 1),
                topic=topic_id,
                difficulty=drafted.difficulty,
                text=drafted.text,
                expected_concepts=drafted.expected_concepts,
                explanation=drafted.explanation,
                source=source_label,
            )
            self.question_bank.add(grounded)
            generated.append(grounded)

        recalculated = self._recalculate_progress()
        if self.memory_store is not None:
            self.memory_store.record_material_ingestion(
                material_id=material_id,
                topic_id=topic_id,
                title=title,
                generated_count=len(generated),
                recalculated_students=recalculated,
            )

        return MaterialIngestionResult(
            material_id=material_id,
            topic_id=topic_id,
            title=title,
            generated_questions=generated,
            recalculated_students=recalculated,
        )
