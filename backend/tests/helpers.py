import json
from pathlib import Path

from learnloop.agent import AgentLoop
from learnloop.models import Difficulty, Question
from learnloop.provider import HeuristicProvider
from learnloop.question_bank import QuestionBank
from learnloop.repository import ProgressRepository
from learnloop.tools import LearningTools, ToolRegistry


def question(
    number: int,
    difficulty: Difficulty = Difficulty.EASY,
    topic: str = "latency",
) -> Question:
    return Question(
        id="q-%s-%s" % (topic, number) if topic != "latency" else "q-%s" % number,
        topic=topic,
        difficulty=difficulty,
        text="%s question %s" % (topic.title(), number),
        expected_concepts=["tail latency"],
        explanation="Tail latency describes the slow end of the distribution.",
        source="DDIA Chapter 1",
    )


def build_components(
    root: Path,
    count: int = 7,
    max_depth: int = 5,
    max_steps: int = 12,
):
    progress_dir = root / "progress"
    bank_path = root / "questions.json"
    bank_path.write_text(
        json.dumps([question(index).to_dict() for index in range(1, count + 1)]),
        encoding="utf-8",
    )
    repository = ProgressRepository(progress_dir)
    bank = QuestionBank(bank_path)
    tools = LearningTools(
        repository=repository,
        question_bank=bank,
        provider=HeuristicProvider(),
        max_topic_depth=max_depth,
        max_extra_iterations=1,
    )
    registry = ToolRegistry(tools)
    agent = AgentLoop(
        registry=registry,
        repository=repository,
        max_steps=max_steps,
    )
    return repository, bank, tools, registry, agent
