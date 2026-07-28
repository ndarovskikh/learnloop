from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .agent import AgentLoop
from .analytics import build_analytics
from .app import build_agent
from .config import Settings
from .models import CheckpointDecision, Question, TopicStatus
from .question_bank import QuestionBank
from .repository import ProgressRepository
from .admin_agent import AdminStatisticsAgent
from .memory_store import LearningMemoryStore


COURSE_ID = "ddia"
COURSE = {
    "id": COURSE_ID,
    "title": "Designing Data-Intensive Applications",
    "short_title": "DDIA",
    "description": "Build strong foundations in reliable, scalable data systems.",
    "accent": "violet",
    "level": "Intermediate",
    "estimated_hours": 18,
}
MATERIALS = [
    {
        "id": "ddia-book",
        "title": "Designing Data-Intensive Applications",
        "filename": "ddia.pdf",
        "type": "PDF",
        "status": "Stored locally",
    }
]
DEMO_ACCOUNTS = {
    "natali": "1234",
    "liza": "1234",
    "danya": "1234",
    "andrew": "1234",
}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=120)


class ChatRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    question_id: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=10000)


class CheckpointRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    decision: CheckpointDecision


class ResetRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    confirmed: bool = False


class TopicResetRequest(ResetRequest):
    topic: str = Field(min_length=1, max_length=120)


class TopicSelectionRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=120)


class AdminBenchmarkRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    topic: Optional[str] = Field(default=None, min_length=1, max_length=120)


def _question_payload(question: Optional[Question]) -> Optional[Dict[str, Any]]:
    return question.to_dict() if question else None


def create_app(
    settings: Optional[Settings] = None,
    agent: Optional[AgentLoop] = None,
    repository: Optional[ProgressRepository] = None,
    question_bank: Optional[QuestionBank] = None,
) -> FastAPI:
    settings = settings or Settings.load()
    repository = repository or ProgressRepository(settings.progress_dir)
    question_bank = question_bank or QuestionBank(settings.question_bank_path)
    agent = agent or build_agent(settings)
    admin_agent = None
    if settings.memory_db_path and settings.memory_jsonl_path:
        admin_agent = AdminStatisticsAgent(
            LearningMemoryStore(settings.memory_db_path, settings.memory_jsonl_path)
        )
    agent.admin_agent = admin_agent

    app = FastAPI(
        title="LearnLoop API",
        version="0.1.0",
        description="Adaptive course coaching API",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_course(course_id: str) -> None:
        if course_id != COURSE_ID:
            raise HTTPException(status_code=404, detail="Course not found")

    def course_workspace(user_id: str) -> Dict[str, Any]:
        progress = repository.load(user_id)
        current_question: Optional[Question] = None
        checkpoint: Optional[Dict[str, Any]] = None

        if progress.topic_status == TopicStatus.IN_PROGRESS:
            start_result = agent.start(user_id)
            if start_result.status == "question_ready":
                current_question = start_result.question
            elif start_result.status == "failed":
                raise HTTPException(
                    status_code=500,
                    detail={
                        "code": start_result.error_code,
                        "message": start_result.message,
                    },
                )
        elif progress.topic_status == TopicStatus.MASTERY_CONFIRMATION_REQUIRED:
            allowed = [
                CheckpointDecision.MARK_MASTERED.value,
                CheckpointDecision.NEEDS_REVIEW.value,
            ]
            if not progress.extra_iteration_used:
                allowed.insert(1, CheckpointDecision.ONE_MORE_QUESTION.value)
            checkpoint = {
                "message": (
                    "You reached the planned depth for this topic. "
                    "Do you consider the material understood?"
                ),
                "allowed_actions": allowed,
            }

        history: List[Dict[str, Any]] = [
            {
                "id": "welcome",
                "role": "assistant",
                "content": (
                    "Welcome back. I will adapt each question to your answers "
                    "and keep track of the concepts that need more practice."
                ),
            }
        ]
        for index, attempt in enumerate(progress.attempts):
            history.extend(
                [
                    {
                        "id": "question-%s" % index,
                        "role": "assistant",
                        "content": attempt.question_text
                        or "Question %s" % attempt.question_id,
                    },
                    {
                        "id": "answer-%s" % index,
                        "role": "user",
                        "content": attempt.student_answer or "Answer submitted",
                    },
                    {
                        "id": "feedback-%s" % index,
                        "role": "assistant",
                        "content": attempt.feedback,
                        "score": round(attempt.score * 100),
                    },
                ]
            )
        if current_question:
            history.append(
                {
                    "id": "current-question",
                    "role": "assistant",
                    "content": current_question.text,
                    "question": True,
                }
            )
        if checkpoint:
            history.append(
                {
                    "id": "checkpoint",
                    "role": "assistant",
                    "content": checkpoint["message"],
                    "checkpoint": True,
                }
            )

        return {
            "course": COURSE,
            "materials": MATERIALS,
            "analytics": build_analytics(
                progress,
                question_bank,
                settings.max_topic_depth,
            ),
            "history": history,
            "current_question": _question_payload(current_question),
            "checkpoint": checkpoint,
        }

    @app.get("/api/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/admin/benchmark")
    def admin_benchmark(
        request: AdminBenchmarkRequest,
        x_admin_token: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        if not settings.admin_token:
            raise HTTPException(status_code=503, detail="Admin statistics are disabled")
        if x_admin_token != settings.admin_token:
            raise HTTPException(status_code=403, detail="Admin access required")
        if admin_agent is None:
            raise HTTPException(status_code=503, detail="Admin statistics are unavailable")
        try:
            return admin_agent.benchmark(request.user_id, request.topic)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/auth/login")
    def login(request: LoginRequest) -> Dict[str, str]:
        username = request.username.strip().lower()
        if DEMO_ACCOUNTS.get(username) != request.password:
            raise HTTPException(
                status_code=401,
                detail="Incorrect username or password",
            )
        return {
            "user_id": username,
            "display_name": username.capitalize(),
        }

    @app.get("/api/courses")
    def courses(user_id: str = "nataliia") -> List[Dict[str, Any]]:
        progress = repository.load(user_id)
        return [
            {
                **COURSE,
                "analytics": build_analytics(
                    progress,
                    question_bank,
                    settings.max_topic_depth,
                ),
                "materials_count": len(MATERIALS),
            }
        ]

    @app.get("/api/courses/{course_id}")
    def course(course_id: str, user_id: str = "nataliia") -> Dict[str, Any]:
        require_course(course_id)
        return course_workspace(user_id)

    @app.post("/api/courses/{course_id}/messages")
    def send_message(
        course_id: str,
        request: ChatRequest,
    ) -> Dict[str, Any]:
        require_course(course_id)
        admin_reply = agent.handle_chat_message(request.user_id, request.message)
        if admin_reply is not None:
            workspace = course_workspace(request.user_id)
            workspace["history"].extend(
                [
                    {"id": "admin-question", "role": "user", "content": request.message},
                    {"id": "admin-reply", "role": "assistant", "content": admin_reply},
                ]
            )
            return workspace
        result = agent.submit_answer(
            user_id=request.user_id,
            question_id=request.question_id,
            student_answer=request.message,
        )
        if result.status == "failed":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": result.error_code,
                    "message": result.message,
                },
            )
        return course_workspace(request.user_id)

    @app.post("/api/courses/{course_id}/checkpoint")
    def checkpoint(
        course_id: str,
        request: CheckpointRequest,
    ) -> Dict[str, Any]:
        require_course(course_id)
        result = agent.resolve_checkpoint(request.user_id, request.decision)
        if result.status == "failed":
            raise HTTPException(
                status_code=422,
                detail={
                    "code": result.error_code,
                    "message": result.message,
                },
            )
        return course_workspace(request.user_id)

    @app.post("/api/courses/{course_id}/reset")
    def reset(course_id: str, request: ResetRequest) -> Dict[str, Any]:
        require_course(course_id)
        result = agent.registry.execute(
            "reset_learning_progress",
            {
                "user_id": request.user_id,
                "explicit_confirmation": request.confirmed,
            },
        )
        if not result.success:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": result.error_code,
                    "message": result.error_message,
                },
            )
        return course_workspace(request.user_id)

    @app.post("/api/courses/{course_id}/reset-topic")
    def reset_topic(
        course_id: str,
        request: TopicResetRequest,
    ) -> Dict[str, Any]:
        require_course(course_id)
        result = agent.registry.execute(
            "reset_topic_progress",
            {
                "user_id": request.user_id,
                "topic": request.topic,
                "explicit_confirmation": request.confirmed,
            },
        )
        if not result.success:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": result.error_code,
                    "message": result.error_message,
                },
            )
        return course_workspace(request.user_id)

    @app.post("/api/courses/{course_id}/select-topic")
    def select_topic(
        course_id: str,
        request: TopicSelectionRequest,
    ) -> Dict[str, Any]:
        require_course(course_id)
        result = agent.registry.execute(
            "select_learning_topic",
            {
                "user_id": request.user_id,
                "topic": request.topic,
            },
        )
        if not result.success:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": result.error_code,
                    "message": result.error_message,
                },
            )
        return course_workspace(request.user_id)

    @app.get("/api/courses/{course_id}/materials/{material_id}")
    def material(course_id: str, material_id: str):
        require_course(course_id)
        if material_id != "ddia-book":
            raise HTTPException(status_code=404, detail="Material not found")
        path = settings.progress_dir.parent / "materials" / "ddia.pdf"
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="Put ddia.pdf into backend/data/materials/",
            )
        return FileResponse(
            path=Path(path),
            media_type="application/pdf",
            filename="ddia.pdf",
        )

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "learnloop.api:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
