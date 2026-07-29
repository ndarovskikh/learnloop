from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


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
    # Agent 1 — main coach agent (asks questions, records answers).
    api_key: str
    model: str
    base_url: str
    max_agent_steps: int
    max_topic_depth: int
    max_extra_topic_iterations: int
    question_bank_path: Path
    progress_dir: Path
    memory_db_path: Optional[Path] = None
    memory_jsonl_path: Optional[Path] = None
    coach_rules_path: Optional[Path] = None
    materials_dir: Optional[Path] = None
    admin_token: str = ""
    teacher_token: str = ""
    # Agent 2 — "Andrew", validates a student's answer and scores it.
    validator_api_key: str = ""
    validator_model: str = ""
    validator_base_url: str = ""
    # Agent 3 — "Liza", grows the personal question bank from progress gaps.
    question_bank_agent_api_key: str = ""
    question_bank_agent_model: str = ""
    question_bank_agent_base_url: str = ""
    # Agent 4 — "Danya", the superior/statistics agent (percentile lookups).
    superior_agent_api_key: str = ""
    superior_agent_model: str = ""
    superior_agent_base_url: str = ""
    # Agent 5 — "Natali", reacts to teacher-uploaded course material.
    material_agent_api_key: str = ""
    material_agent_model: str = ""
    material_agent_base_url: str = ""

    @property
    def has_real_api_key(self) -> bool:
        normalized = self.api_key.strip().lower()
        return bool(normalized) and normalized != "insert api key here"

    def agent_credentials(self, prefix: str) -> "AgentCredentials":
        """Resolve one agent's key/model/base_url, falling back to agent 1's."""
        api_key = getattr(self, "%s_api_key" % prefix, "") or self.api_key
        model = getattr(self, "%s_model" % prefix, "") or self.model
        base_url = getattr(self, "%s_base_url" % prefix, "") or self.base_url
        return AgentCredentials(api_key=api_key, model=model, base_url=base_url)

    @classmethod
    def load(cls, root: Path = PROJECT_ROOT) -> "Settings":
        env_file = _read_env(root / ".env")
        main_api_key = _value("OPENAI_API_KEY", env_file, "insert api key here")
        main_model = _value("OPENAI_MODEL", env_file, "gpt-4.1-mini")
        main_base_url = _value("OPENAI_BASE_URL", env_file, "")
        return cls(
            api_key=main_api_key,
            model=main_model,
            base_url=main_base_url,
            max_agent_steps=int(_value("MAX_AGENT_STEPS", env_file, "12")),
            max_topic_depth=int(_value("MAX_TOPIC_DEPTH", env_file, "5")),
            max_extra_topic_iterations=int(
                _value("MAX_EXTRA_TOPIC_ITERATIONS", env_file, "1")
            ),
            question_bank_path=root / "data" / "questions" / "ddia_questions.json",
            progress_dir=root / "data" / "progress",
            memory_db_path=root / "data" / "learnloop.sqlite3",
            memory_jsonl_path=root / "data" / "learning_memories.jsonl",
            coach_rules_path=root / "coach_rules.md",
            materials_dir=root / "data" / "materials",
            admin_token=_value("LEARNLOOP_ADMIN_TOKEN", env_file, ""),
            teacher_token=_value("LEARNLOOP_TEACHER_TOKEN", env_file, ""),
            validator_api_key=_value("LEARNLOOP_VALIDATOR_API_KEY", env_file, main_api_key),
            validator_model=_value("LEARNLOOP_VALIDATOR_MODEL", env_file, main_model),
            validator_base_url=_value("LEARNLOOP_VALIDATOR_BASE_URL", env_file, main_base_url),
            question_bank_agent_api_key=_value(
                "LEARNLOOP_QUESTION_BANK_API_KEY", env_file, main_api_key
            ),
            question_bank_agent_model=_value(
                "LEARNLOOP_QUESTION_BANK_MODEL", env_file, main_model
            ),
            question_bank_agent_base_url=_value(
                "LEARNLOOP_QUESTION_BANK_BASE_URL", env_file, main_base_url
            ),
            superior_agent_api_key=_value(
                "LEARNLOOP_SUPERIOR_API_KEY", env_file, main_api_key
            ),
            superior_agent_model=_value("LEARNLOOP_SUPERIOR_MODEL", env_file, main_model),
            superior_agent_base_url=_value(
                "LEARNLOOP_SUPERIOR_BASE_URL", env_file, main_base_url
            ),
            material_agent_api_key=_value(
                "LEARNLOOP_MATERIAL_API_KEY", env_file, main_api_key
            ),
            material_agent_model=_value("LEARNLOOP_MATERIAL_MODEL", env_file, main_model),
            material_agent_base_url=_value(
                "LEARNLOOP_MATERIAL_BASE_URL", env_file, main_base_url
            ),
        )


@dataclass(frozen=True)
class AgentCredentials:
    api_key: str
    model: str
    base_url: str
