"""FastAPI application factory for CagentOS — stage 0."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from cagent_os.agents.run_engine import AgentRuntime
from cagent_os.conversations.repository import InMemoryConversationRepository
from cagent_os.conversations.service import ConversationService
from cagent_os.config import get_settings
from cagent_os.data_layer import DataLayer
from cagent_os.data_layer.adapters.fred_adapter import FredAdapter
from cagent_os.data_layer.adapters.yfinance_adapter import YFinanceAdapter
from cagent_os.interfaces.http.routes_runs import build_runs_router
from cagent_os.llm.factory import create_backend
from cagent_os.mcp_client.session import MCPSessionManager
from cagent_os.plugins import ToolDispatcher, ToolRegistry
from cagent_os.plugins.financial.plugin import FinancialPlugin
from cagent_os.plugins.financial.toolkit import build_financial_toolkit
from cagent_os.plugins.read.plugin import ReadPlugin
from cagent_os.plugins.skills.plugin import SkillsPlugin
from cagent_os.plugins.web.plugin import WebPlugin
from cagent_os.shared.errors import ConversationOwnershipError
from cagent_os.shared.logging_utils import build_log_extra, configure_logging, format_log_context
from cagent_os.user_skills import FilesystemUserSkillStore, UserSkillService

import json as _json

logger = logging.getLogger(__name__)


def _load_mcp_config(settings) -> list[dict]:
    """Load MCP server configurations from the JSON config file."""
    config_path = Path(settings.mcp_servers_config)
    if not config_path.exists():
        logger.warning("%s not found — MCP disabled", config_path)
        return []
    with open(config_path) as f:
        data = _json.load(f)
    return data.get("servers", [])


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

    # MCP session manager (fin-skill + jin10)
    mcp_servers = _load_mcp_config(settings)
    mcp_manager = MCPSessionManager(mcp_servers) if mcp_servers else None

    # Data layer with cross-validation
    data_layer = DataLayer()
    data_layer.register_source(YFinanceAdapter())
    if mcp_manager is not None:
        from cagent_os.data_layer.adapters.fin_skill_adapter import FinSkillAdapter
        data_layer.register_source(FinSkillAdapter(mcp_manager))
    if settings.fred_api_key:
        data_layer.register_source(FredAdapter(api_key=settings.fred_api_key))

    # Toolkit with MCP bridge
    toolkit = build_financial_toolkit(settings=settings, mcp_session_manager=mcp_manager)

    # RAG service
    rag_service = None
    try:
        from cagent_os.rag.rag_service import RAGService
        rag_service = RAGService(knowledge_dir="knowledge", chroma_path="data/vectors",
                                  api_key=settings.siliconflow_api_key)
        logger.info("RAG service initialized: %d chunks", rag_service.chunk_count)
    except Exception as exc:
        logger.warning("RAG service not available: %s", exc)

    registry = ToolRegistry()
    registry.register_plugin(FinancialPlugin(settings=settings, toolkit=toolkit, data_layer=data_layer, rag_service=rag_service))
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

    # Phase 4c: Web UI — serve static files
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        @app.get("/")
        async def serve_index():
            return FileResponse(str(static_dir / "index.html"))

        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(
        build_runs_router(
            run_engine=run_engine,
            conversation_service=conversation_service,
            user_skill_service=user_skill_service,
        )
    )

    return app
