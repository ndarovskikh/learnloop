from __future__ import annotations

from .agent import AgentLoop
from .answer_validation_agent import AnswerValidationAgent
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
    # Agent 1 — main coach: picks/asks questions with its own key/model.
    provider = build_provider(
        api_key=settings.api_key,
        model=settings.model,
        base_url=settings.base_url,
    )
    # Agent 2 — Andrew: validates and scores each answer independently.
    validator_credentials = settings.agent_credentials("validator")
    validator_provider = build_provider(
        api_key=validator_credentials.api_key,
        model=validator_credentials.model,
        base_url=validator_credentials.base_url,
    )
    answer_validation_agent = AnswerValidationAgent(validator_provider)
    memory_store = None
    if settings.memory_db_path and settings.memory_jsonl_path:
        memory_store = LearningMemoryStore(
            settings.memory_db_path, settings.memory_jsonl_path
        )
    question_generation_agent = None
    if memory_store is not None:
        # Agent 3 — Liza: grows the personal question bank from progress gaps.
        question_bank_credentials = settings.agent_credentials("question_bank_agent")
        question_bank_provider = build_provider(
            api_key=question_bank_credentials.api_key,
            model=question_bank_credentials.model,
            base_url=question_bank_credentials.base_url,
        )
        question_generation_agent = AdaptiveQuestionBankAgent(
            memory_store=memory_store,
            question_bank=question_bank,
            provider=question_bank_provider,
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
        answer_validation_agent=answer_validation_agent,
    )
    return AgentLoop(
        registry=ToolRegistry(tools),
        repository=repository,
        max_steps=settings.max_agent_steps,
    )
