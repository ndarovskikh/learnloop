from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from typing import Dict

from .app import build_agent
from .config import Settings
from .models import CheckpointDecision
from .memory_store import LearningMemoryStore


DECISIONS: Dict[str, CheckpointDecision] = {
    "mastered": CheckpointDecision.MARK_MASTERED,
    "extra": CheckpointDecision.ONE_MORE_QUESTION,
    "review": CheckpointDecision.NEEDS_REVIEW,
}


def _ask_checkpoint(allowed_actions):
    visible = []
    if CheckpointDecision.MARK_MASTERED.value in allowed_actions:
        visible.append("mastered")
    if CheckpointDecision.ONE_MORE_QUESTION.value in allowed_actions:
        visible.append("extra")
    if CheckpointDecision.NEEDS_REVIEW.value in allowed_actions:
        visible.append("review")
    while True:
        value = input("Choose [%s]: " % "/".join(visible)).strip().lower()
        if value in visible:
            return DECISIONS[value]
        print("Please choose one of: %s" % ", ".join(visible))


def run(user_id: str) -> int:
    settings = Settings.load()
    agent = build_agent(settings)
    mode = "OpenAI-compatible API" if settings.has_real_api_key else "local demo"
    print("LearnLoop started for %s (%s)." % (user_id, mode))

    result = agent.start(user_id)
    while True:
        if result.status == "question_ready" and result.question:
            question = result.question
            print("\nTopic: %s | Difficulty: %s" % (
                question.topic,
                question.difficulty.value,
            ))
            print("Question: %s" % question.text)
            answer = input("Your answer: ")
            result = agent.submit_answer(user_id, question.id, answer)
            if result.assessment:
                print("\nScore: %.2f" % result.assessment.score)
                print("Feedback: %s" % result.assessment.feedback)
            continue

        if result.status == "mastery_confirmation_required":
            print("\n%s" % result.message)
            decision = _ask_checkpoint(result.allowed_actions)
            result = agent.resolve_checkpoint(user_id, decision)
            continue

        if result.status == "topic_finished":
            print("\n%s" % result.message)
            return 0

        print("\nStopped: %s" % result.message)
        if result.error_code:
            print("Error code: %s" % result.error_code)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="LearnLoop adaptive coach")
    parser.add_argument("--user", default="demo-student")
    parser.add_argument("--memory-demo", action="store_true", help="run the SQLite/JSON memory example")
    parser.add_argument("--memory-status", action="store_true", help="show saved memory statistics for the user")
    parser.add_argument(
        "--generate-nightly-questions",
        action="store_true",
        help="generate private practice questions from SQLite progress",
    )
    args = parser.parse_args()
    if args.generate_nightly_questions:
        settings = Settings.load()
        agent = build_agent(settings)
        generator = agent.registry.tools.question_generation_agent
        if generator is None:
            parser.error("SQLite learning memory is required")
        results = generator.run_nightly()
        generated = [result for result in results if result.status == "generated"]
        if generated:
            print(
                "Generated %d private questions for %d student(s)."
                % (
                    sum(len(result.questions) for result in generated),
                    len(generated),
                )
            )
        return
    if args.memory_demo:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = LearningMemoryStore(root / "learnloop.sqlite3", root / "memories.jsonl")
            store.seed_question(course_id="ddia", course_title="DDIA", topic_id="latency", topic_title="Latency", question_id="ddia-latency-01", difficulty="easy", question_text="Explain P95 latency.", expected_answer="95th percentile")
            attempt_id = store.record_attempt(user_id="user-1", user_name="Natalia", question_id="ddia-latency-01", score=0.4)
            store.remember(user_id="user-1", type="learning_fact", content="Student confuses P95 and P99.", cue=["latency", "percentiles"], source={"question_id": "ddia-latency-01", "attempt_id": attempt_id})
            print("mastery(latency)=%.2f" % store.mastery_for("user-1", "latency"))
            print("memories=%d" % len(store.memories_for("user-1")))
        return
    if args.memory_status:
        settings = Settings.load()
        if not settings.memory_db_path or not settings.memory_jsonl_path:
            parser.error("persistent memory paths are not configured")
        store = LearningMemoryStore(
            settings.memory_db_path, settings.memory_jsonl_path
        )
        print("database=%s" % settings.memory_db_path)
        print("attempts=%d" % store.attempt_count_for(args.user))
        print("observations=%d" % len(store.memories_for(args.user)))
        return
    raise SystemExit(run(args.user))


if __name__ == "__main__":
    main()
