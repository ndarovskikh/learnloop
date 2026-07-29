"""Accumulates a student's multi-message answer before it reaches agent 2.

A student may send several chat messages before their answer to a single
question is complete ("wait, also..."). Each message is a *chunk*. Chunks
are combined into one answer and graded exactly once, when the student (or
an idle timeout on the frontend) finalizes.

This module is the concurrency boundary for that flow and exists to make
three race conditions impossible rather than merely unlikely:

1. Out-of-order delivery — two chunk requests from the same browser tab can
   race on the network and arrive reordered. Each chunk carries a client-
   assigned ``seq``; chunks are combined in ``seq`` order, not arrival order.
2. Duplicate delivery — a retried request (double-click, client retry after
   a timeout) must not append the same text twice. Each chunk carries a
   client-generated ``chunk_id``; a repeated id is a no-op.
3. Double grading — an explicit "submit" click and an idle-timeout submit
   can land at nearly the same time. ``begin_finalize`` is the only way to
   take the accumulated draft for grading, and it hands it out exactly once
   per question: a second, concurrent caller gets ``None`` back and must
   treat it as "already being graded" rather than grading it again.

All of this is process-local (an in-memory dict guarded by per-user locks),
which matches the rest of this demo app — the progress store, question bank,
etc. are also single-process, file-based state with no external broker.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class _Draft:
    question_id: str
    chunks: List[Tuple[int, str]] = field(default_factory=list)
    seen_chunk_ids: Set[str] = field(default_factory=set)
    finalizing: bool = False


def _combined_text(draft: _Draft) -> str:
    ordered = sorted(draft.chunks, key=lambda pair: pair[0])
    return "\n".join(text for _, text in ordered if text.strip())


class AnswerDraftQueue:
    def __init__(self) -> None:
        self._registry_lock = threading.Lock()
        self._user_locks: Dict[str, threading.Lock] = {}
        self._drafts: Dict[str, _Draft] = {}

    def _lock_for(self, user_id: str) -> threading.Lock:
        with self._registry_lock:
            lock = self._user_locks.get(user_id)
            if lock is None:
                lock = threading.Lock()
                self._user_locks[user_id] = lock
            return lock

    def append(
        self,
        user_id: str,
        question_id: str,
        chunk_id: str,
        seq: int,
        text: str,
    ) -> str:
        """Add one chunk to the draft and return the combined text so far.

        A blank chunk or a repeated ``chunk_id`` is a no-op. Switching to a
        different ``question_id`` (the previous question was already graded
        or abandoned) starts a fresh draft.
        """
        if not text.strip():
            return self.peek(user_id, question_id)
        lock = self._lock_for(user_id)
        with lock:
            draft = self._drafts.get(user_id)
            if draft is None or draft.question_id != question_id:
                draft = _Draft(question_id=question_id)
                self._drafts[user_id] = draft
            if chunk_id in draft.seen_chunk_ids:
                return _combined_text(draft)
            draft.seen_chunk_ids.add(chunk_id)
            draft.chunks.append((seq, text))
            return _combined_text(draft)

    def peek(self, user_id: str, question_id: str) -> str:
        lock = self._lock_for(user_id)
        with lock:
            draft = self._drafts.get(user_id)
            if draft is None or draft.question_id != question_id:
                return ""
            return _combined_text(draft)

    def begin_finalize(self, user_id: str, question_id: str) -> Optional[str]:
        """Atomically claim the draft for grading.

        Returns the combined answer text exactly once per question. Returns
        ``None`` when there is nothing to grade, or when another finalize
        for the same question is already in flight — callers must treat
        ``None`` as "someone else is already handling this", not an error.
        """
        lock = self._lock_for(user_id)
        with lock:
            draft = self._drafts.get(user_id)
            if draft is None or draft.question_id != question_id:
                return None
            if draft.finalizing:
                return None
            combined = _combined_text(draft)
            if not combined:
                return None
            draft.finalizing = True
            return combined

    def clear(self, user_id: str, question_id: str) -> None:
        """Drop the draft after it was graded successfully."""
        lock = self._lock_for(user_id)
        with lock:
            draft = self._drafts.get(user_id)
            if draft is not None and draft.question_id == question_id:
                del self._drafts[user_id]

    def cancel_finalize(self, user_id: str, question_id: str) -> None:
        """Release the finalize claim after a failed grading attempt.

        The drafted text is kept so the student doesn't lose it; a later
        finalize call can retry.
        """
        lock = self._lock_for(user_id)
        with lock:
            draft = self._drafts.get(user_id)
            if draft is not None and draft.question_id == question_id:
                draft.finalizing = False
