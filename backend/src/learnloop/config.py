from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_env(path: Path) -> Dict[str, str]:
    """Read a small .env file without adding a runtime dependency."""
    values: Dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _value(name: str, env_file: Dict[str, str], default: str) -> str:
    return os.environ.get(name, env_file.get(name, default))


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    base_url: str
    max_agent_steps: int
    max_topic_depth: int
    max_extra_topic_iterations: int
    question_bank_path: Path
    progress_dir: Path

    @property
    def has_real_api_key(self) -> bool:
        normalized = self.api_key.strip().lower()
        return bool(normalized) and normalized != "insert api key here"

    @classmethod
    def load(cls, root: Path = PROJECT_ROOT) -> "Settings":
        env_file = _read_env(root / ".env")
        return cls(
            api_key=_value("OPENAI_API_KEY", env_file, "insert api key here"),
            model=_value("OPENAI_MODEL", env_file, "gpt-4.1-mini"),
            base_url=_value("OPENAI_BASE_URL", env_file, ""),
            max_agent_steps=int(_value("MAX_AGENT_STEPS", env_file, "12")),
            max_topic_depth=int(_value("MAX_TOPIC_DEPTH", env_file, "5")),
            max_extra_topic_iterations=int(
                _value("MAX_EXTRA_TOPIC_ITERATIONS", env_file, "1")
            ),
            question_bank_path=root / "data" / "questions" / "ddia_questions.json",
            progress_dir=root / "data" / "progress",
        )

