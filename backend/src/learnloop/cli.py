from __future__ import annotations

import argparse
from typing import Dict

from .app import build_agent
from .config import Settings
from .models import CheckpointDecision


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
    args = parser.parse_args()
    raise SystemExit(run(args.user))


if __name__ == "__main__":
    main()

