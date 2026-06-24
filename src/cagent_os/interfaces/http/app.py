"""FastAPI application factory for CagentOS — stage 0."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cagent_os.agents.run_engine import AgentRuntime
from cagent_os.conversations.repository import InMemoryConversationRepository
from cagent_os.conversations.service import ConversationService
from cagent_os.config import get_settings
from cagent_os.data_layer import DataLayer
from cagent_os.data_layer.adapters.fred_adapter import FredAdapter
from cagent_os.data_layer.adapters.yfinance_adapter import YFinanceAdapter
from cagent_os.interfaces.http.routes_runs import build_runs_router
from cagent_os.llm.factory import create_backend
from cagent_os.plugins import ToolDispatcher, ToolRegistry
from cagent_os.plugins.financial.plugin import FinancialPlugin
from cagent_os.plugins.read.plugin import ReadPlugin
from cagent_os.plugins.skills.plugin import SkillsPlugin
from cagent_os.plugins.web.plugin import WebPlugin
from cagent_os.shared.errors import ConversationOwnershipError
from cagent_os.shared.logging_utils import build_log_extra, configure_logging, format_log_context
from cagent_os.user_skills import FilesystemUserSkillStore, UserSkillService

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug=settings.debug)

    llm_backend = create_backend(settings)
    conversation_repository = InMemoryConversationRepository()
    conversation_service = ConversationService(repository=conversation_repository)

    _project_root = Path(__file__).resolve().parent.parent.parent.parent
    skills_data_dir = (_project_root / settings.skills_data_dir).resolve()
    shared_skills_dir = (_project_root / settings.shared_skills_dir).resolve() if settings.shared_skills_dir else None
    user_skill_service = UserSkillService(
        FilesystemUserSkillStore(skills_data_dir, shared_skills_dir=shared_skills_dir)
    )

    registry = ToolRegistry()
    data_layer = DataLayer()
    data_layer.register_source(YFinanceAdapter())
    if settings.fred_api_key:
        data_layer.register_source(FredAdapter(api_key=settings.fred_api_key))
    registry.register_plugin(FinancialPlugin(settings=settings, data_layer=data_layer))
    registry.register_plugin(WebPlugin(settings=settings))
    registry.register_plugin(ReadPlugin(settings=settings))
    registry.register_plugin(
        SkillsPlugin(
            user_skill_service=user_skill_service,
            skills_data_dir=skills_data_dir,
            shared_skills_dir=shared_skills_dir,
        )
    )
    executor = ToolDispatcher(registry=registry)

    run_engine = AgentRuntime(
        conversation_service=conversation_service,
        event_store=conversation_repository,
        llm_backend=llm_backend,
        capability_executor=executor,
        settings=settings,
    )

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="CagentOS — stage 0",
    )

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(KeyError)
    def handle_key_error(request: Request, exc: KeyError) -> JSONResponse:
        detail = exc.args[0] if exc.args else "resource not found"
        return JSONResponse(status_code=404, content={"detail": str(detail)})

    @app.exception_handler(ConversationOwnershipError)
    def handle_conversation_ownership_error(request: Request, exc: ConversationOwnershipError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.get("/health")
    def health_check() -> dict:
        return {"status": "healthy"}

    app.include_router(
        build_runs_router(
            run_engine=run_engine,
            conversation_service=conversation_service,
            user_skill_service=user_skill_service,
        )
    )

    return app
