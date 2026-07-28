from __future__ import annotations

from .agent import AgentLoop
from .config import Settings
from .provider import build_provider
from .question_bank import QuestionBank
from .repository import ProgressRepository
from .tools import LearningTools, ToolRegistry


def build_agent(settings: Settings) -> AgentLoop:
    repository = ProgressRepository(settings.progress_dir)
    question_bank = QuestionBank(settings.question_bank_path)
    provider = build_provider(
        api_key=settings.api_key,
        model=settings.model,
        base_url=settings.base_url,
    )
    tools = LearningTools(
        repository=repository,
        question_bank=question_bank,
        provider=provider,
        max_topic_depth=settings.max_topic_depth,
        max_extra_iterations=settings.max_extra_topic_iterations,
    )
    return AgentLoop(
        registry=ToolRegistry(tools),
        repository=repository,
        max_steps=settings.max_agent_steps,
    )

