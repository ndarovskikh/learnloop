"""Traceable hand-off between the answer assessor and answer verifier."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class AgentHandoff:
    """The only payload agents may use to communicate with each other."""

    status: str
    result: Dict[str, Any]
    needs_approval: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "result": self.result,
            "needs_approval": self.needs_approval,
        }


class CoordinationMemory:
    """Append-only shared memory, deliberately small enough to inspect easily."""

    def __init__(self, progress_dir: Path):
        self.path = progress_dir / "agent_coordination.jsonl"

    def append(self, role: str, handoff: AgentHandoff) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "at": datetime.now(timezone.utc).isoformat(),
            "role": role,
            "handoff": handoff.to_dict(),
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
