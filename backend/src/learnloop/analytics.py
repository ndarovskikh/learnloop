from __future__ import annotations

from typing import Any, Dict, List

from .models import StudentProgress, TopicStatus
from .question_bank import QuestionBank


TOPIC_TITLES = {
    "data_systems": "Thinking About Data Systems",
    "reliability": "Reliability",
    "scalability_load": "Scalability and Load",
    "latency": "Performance and Latency",
    "maintainability": "Maintainability",
    "relational_document_models": "Relational vs. Document Models",
    "relationships_normalization": "Relationships and Normalization",
    "query_languages": "Query Languages",
    "graph_models": "Graph Data Models",
    "schema_flexibility": "Schema Flexibility",
    "hash_indexes": "Hash Indexes",
    "lsm_trees": "SSTables and LSM-trees",
    "b_trees": "B-trees",
    "secondary_indexes": "Secondary Indexes",
    "oltp_olap": "OLTP and Analytics",
    "column_storage": "Column-oriented Storage",
    "encoding_formats": "Encoding Formats",
    "thrift_protobuf": "Thrift and Protocol Buffers",
    "avro": "Avro",
    "schema_evolution": "Schema Evolution and Dataflow",
}


def _topic_title(topic: str) -> str:
    return TOPIC_TITLES.get(topic, topic.replace("_", " ").title())


def _learning_streak(scores: List[float]) -> int:
    streak = 0
    for score in reversed(scores):
        if score < 0.75:
            break
        streak += 1
    return streak


def build_analytics(
    progress: StudentProgress,
    question_bank: QuestionBank,
    max_topic_depth: int,
) -> Dict[str, Any]:
    questions = question_bank.all()
    answered = len(progress.answered_question_ids)
    scores = [attempt.score for attempt in progress.attempts]
    average_score = sum(scores) / len(scores) if scores else 0.0
    topic_mastery = progress.mastery.get(progress.active_topic, 0.0)
    topic_ids = list(dict.fromkeys(question.topic for question in questions))
    attempts_by_topic = {
        topic: [attempt for attempt in progress.attempts if attempt.topic == topic]
        for topic in topic_ids
    }
    topics = []
    for topic in topic_ids:
        attempts = attempts_by_topic[topic]
        answered_count = len(attempts)
        state = progress.topic_states.get(topic)
        if state:
            status = str(state["status"])
            depth = int(state["depth"])
        elif answered_count:
            status = TopicStatus.IN_PROGRESS.value
            depth = answered_count
        else:
            status = "not_started"
            depth = 0
        topics.append(
            {
                "id": topic,
                "title": _topic_title(topic),
                "completion": round(
                    min(depth / max(max_topic_depth, 1), 1.0) * 100
                ),
                "mastery": round(progress.mastery.get(topic, 0.0) * 100),
                "questions_answered": answered_count,
                "questions_target": max_topic_depth,
                "status": status,
                "current": topic == progress.active_topic,
            }
        )
    required_answers = max(len(topic_ids) * max(max_topic_depth, 1), 1)

    return {
        "course_completion": round(min(answered / required_answers, 1.0) * 100),
        "current_topic_id": progress.active_topic,
        "current_topic": _topic_title(progress.active_topic),
        "topic_completion": round(
            min(progress.topic_depth / max(max_topic_depth, 1), 1.0) * 100
        ),
        "topic_questions_answered": len(
            attempts_by_topic.get(progress.active_topic, [])
        ),
        "topic_questions_target": max_topic_depth,
        "topic_mastery": round(topic_mastery * 100),
        "questions_answered": answered,
        "average_score": round(average_score * 100),
        "learning_streak": _learning_streak(scores),
        "knowledge_gaps": progress.knowledge_gaps[-3:],
        "topic_status": progress.topic_status.value,
        "topics": topics,
    }
