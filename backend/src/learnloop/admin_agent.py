"""Privileged, privacy-preserving aggregate statistics helper.

This module is intentionally not registered in ``ToolRegistry``.  The regular
coach only sees one student's records; this helper can read cohort scores but
its public API can return only a student's own relative position.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from .memory_store import LearningMemoryStore


class AdminStatisticsAgent:
    MINIMUM_COHORT_SIZE = 2

    def __init__(self, memory_store: LearningMemoryStore):
        self.memory_store = memory_store

    def benchmark(self, user_id: str, topic: Optional[str] = None) -> Dict[str, Any]:
        """Return only anonymized relative standing, never peer records."""
        with self.memory_store._connection() as connection:
            if topic:
                rows = connection.execute(
                    "SELECT user_id, mastery_score AS score FROM mastery WHERE topic_id = ?",
                    (topic,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT a.user_id, AVG(a.score) AS score FROM attempts a "
                    "GROUP BY a.user_id"
                ).fetchall()

        scores = {str(row["user_id"]): float(row["score"]) for row in rows}
        if user_id not in scores:
            raise ValueError("NO_STATISTICS_FOR_USER")
        if len(scores) < self.MINIMUM_COHORT_SIZE:
            raise ValueError("INSUFFICIENT_COHORT")

        own_score = scores[user_id]
        # Higher score is better. Equal scores receive the same percentile.
        percentile = round(100 * sum(score <= own_score for score in scores.values()) / len(scores))
        return {
            "scope": "topic" if topic else "course",
            "topic": topic,
            "percentile": percentile,
            "top_percent": max(1, 100 - percentile + 1),
            "message": "Your result is in the top %d%% of the eligible cohort." % max(1, 100 - percentile + 1),
        }
