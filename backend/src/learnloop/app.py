from __future__ import annotations

from .agent import AgentLoop
from .config import Settings
from .memory_store import LearningMemoryStore
from .context import LearningContext
from .provider import build_provider
from .question_bank import QuestionBank
from .question_generation_agent import AdaptiveQuestionBankAgent
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
    memory_store = None
    if settings.memory_db_path and settings.memory_jsonl_path:
        memory_store = LearningMemoryStore(
            settings.memory_db_path, settings.memory_jsonl_path
        )
    question_generation_agent = None
    if memory_store is not None:
        question_generation_agent = AdaptiveQuestionBankAgent(
            memory_store=memory_store,
            question_bank=question_bank,
            provider=provider,
            max_topic_depth=settings.max_topic_depth,
        )
    learning_context = LearningContext(
        repository=repository,
        question_bank=question_bank,
        rules_path=settings.coach_rules_path or settings.progress_dir.parent / "coach_rules.md",
        memory_store=memory_store,
    )
    tools = LearningTools(
        repository=repository,
        question_bank=question_bank,
        provider=provider,
        max_topic_depth=settings.max_topic_depth,
        max_extra_iterations=settings.max_extra_topic_iterations,
        memory_store=memory_store,
        learning_context=learning_context,
        question_generation_agent=question_generation_agent,
    )
    return AgentLoop(
        registry=ToolRegistry(tools),
        repository=repository,
        max_steps=settings.max_agent_steps,
    )
