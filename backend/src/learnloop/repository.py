from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import StudentProgress, TopicStatus


class ProgressRepository:
    def __init__(self, progress_dir: Path):
        self.progress_dir = progress_dir
        self.progress_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, user_id: str) -> Path:
        safe = "".join(char for char in user_id if char.isalnum() or char in "-_")
        if not safe or safe != user_id:
            raise ValueError("user_id contains unsupported characters")
        return self.progress_dir / ("%s.json" % safe)

    def load(self, user_id: str) -> StudentProgress:
        path = self._path(user_id)
        if not path.exists():
            return StudentProgress(user_id=user_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            progress = StudentProgress.from_dict(payload)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("CORRUPTED_PROGRESS: %s" % exc) from exc
        if progress.user_id != user_id:
            raise ValueError("CORRUPTED_PROGRESS: user_id mismatch")
        return progress

    def save(self, progress: StudentProgress) -> None:
        path = self._path(progress.user_id)
        progress.sync_active_topic_state()
        serialized = json.dumps(
            progress.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=path.name + ".",
            suffix=".tmp",
            dir=str(self.progress_dir),
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        except Exception:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
            raise

    def reset(self, user_id: str) -> StudentProgress:
        path = self._path(user_id)
        if path.exists():
            path.unlink()
        progress = StudentProgress(user_id=user_id)
        self.save(progress)
        return progress

    def reset_topic(self, user_id: str, topic: str) -> StudentProgress:
        progress = self.load(user_id)
        removed_question_ids = {
            attempt.question_id
            for attempt in progress.attempts
            if attempt.topic == topic
        }
        progress.attempts = [
            attempt for attempt in progress.attempts if attempt.topic != topic
        ]
        progress.answered_question_ids = [
            question_id
            for question_id in progress.answered_question_ids
            if question_id not in removed_question_ids
        ]
        progress.mastery.pop(topic, None)
        progress.topic_states.pop(topic, None)
        progress.knowledge_gaps = list(
            dict.fromkeys(
                gap
                for attempt in progress.attempts
                for gap in attempt.knowledge_gaps
                if gap
            )
        )
        progress.active_topic = topic
        progress.topic_depth = 0
        progress.extra_iteration_used = False
        progress.topic_status = TopicStatus.IN_PROGRESS
        self.save(progress)
        return progress
