"""FastAPI application factory for CagentOS — stage 0."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

# Load .env file at import time so all `os.environ.get(...)` calls in
# settings/jwt/auth see the values. python-dotenv is already a dependency.
try:
    from dotenv import load_dotenv
    # Search for .env in the current working dir and up to 3 parent dirs
    _env_path = Path.cwd() / ".env"
    if not _env_path.exists():
        for parent in Path.cwd().parents[:3]:
            candidate = parent / ".env"
            if candidate.exists():
                _env_path = candidate
                break
    if _env_path.exists():
        load_dotenv(_env_path)
        logger_env = logging.getLogger(__name__)
        logger_env.info("Loaded .env from %s", _env_path)
except ImportError:
    # python-dotenv not installed — env vars must be set manually
    pass

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from cagent_os.agents.run_engine import AgentRuntime
from cagent_os.conversations.repository import InMemoryConversationRepository
from cagent_os.conversations.service import ConversationService
from cagent_os.conversations.sqlite_store import SqliteConversationRepository
from cagent_os.config import get_settings
from cagent_os.config.cost_tracker import CostTracker
from cagent_os.data_layer import DataLayer
from cagent_os.auth import InvitationCodeStore, UserStore
from cagent_os.data_layer.adapters.fred_adapter import FredAdapter
from cagent_os.data_layer.adapters.yfinance_adapter import YFinanceAdapter
from cagent_os.interfaces.http.routes_auth import build_auth_router
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
import asyncio as _asyncio
import threading as _threading
from datetime import datetime as _datetime, timezone as _timezone

logger = logging.getLogger(__name__)

# ── Cron scheduler state ──────────────────────────────────────────────
_cron_task: _asyncio.Task | None = None
_cron_stop_event = _threading.Event()


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

    # Project root resolution — walk up from this file until we hit
    # pyproject.toml. Robust against accidental parent-count mistakes
    # (this file lives at <root>/src/cagent_os/interfaces/http/app.py,
    # so 4 .parent calls happen to yield <root>/src — wrong!).
    def _resolve_project_root() -> Path:
        here = Path(__file__).resolve()
        for ancestor in [here.parent, *here.parents]:
            if (ancestor / "pyproject.toml").exists():
                return ancestor
        # Fallback: assume 5 .parent calls reach the root
        return here.parents[4]

    _project_root = _resolve_project_root()
    logger.info("Project root resolved: %s", _project_root)

    # Phase 4c+: Persistent conversation storage.
    # Previously: InMemoryConversationRepository (lost on restart).
    # Now: SQLite at data/conversations.db with WAL mode for concurrent reads.
    # This is a prerequisite for multi-user isolation and for conversation
    # history surviving restarts.
    _conv_db_path = _project_root / "data" / "conversations.db"
    _conv_db_path.parent.mkdir(parents=True, exist_ok=True)
    conversation_repository = SqliteConversationRepository(str(_conv_db_path))
    conversation_service = ConversationService(repository=conversation_repository)
    logger.info("Conversation storage: SQLite at %s", _conv_db_path)

    # Phase 4c+ multi-user: user accounts (separate SQLite DB for clean
    # separation and easier future migration to PostgreSQL).
    _users_db_path = _project_root / "data" / "users.db"
    user_store = UserStore(str(_users_db_path))
    logger.info("User accounts storage: SQLite at %s", _users_db_path)

    # Invitation codes (内测 mode) — stored alongside users.db
    _invitations_db_path = _project_root / "data" / "invitation_codes.db"
    invitation_store = InvitationCodeStore(str(_invitations_db_path))
    logger.info("Invitation codes storage: SQLite at %s", _invitations_db_path)

    # Phase A: Memory store (Hermes-style agent_notes + user_profile, plus
    # legacy user_facts/investment_theses). Injected into AgentRuntime so
    # the LLM gets memory injected into its system prompt every turn.
    _memory_db_path = _project_root / "data" / "memory.db"
    from cagent_os.memory.sqlite_store import SqliteMemoryStore
    memory_store = SqliteMemoryStore(str(_memory_db_path))
    logger.info("Memory storage: SQLite at %s", _memory_db_path)

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
    # ── Financial data (free, no API key) ──
    data_layer.register_source(YFinanceAdapter())
    from cagent_os.data_layer.adapters.edgar_adapter import EdgardAdapter
    data_layer.register_source(EdgardAdapter())
    # ── MCP-based (requires MCP session) ──
    if mcp_manager is not None:
        from cagent_os.data_layer.adapters.fin_skill_adapter import FinSkillAdapter
        data_layer.register_source(FinSkillAdapter(mcp_manager))
    # ── Macro (requires API key) ──
    if settings.fred_api_key:
        data_layer.register_source(FredAdapter(api_key=settings.fred_api_key))
    # ── Crypto (all free, no API key) ──
    from cagent_os.data_layer.adapters.coinmetrics_adapter import CoinMetricsAdapter
    data_layer.register_source(CoinMetricsAdapter())
    from cagent_os.data_layer.adapters.binance_derivatives_adapter import BinanceDerivativesAdapter
    data_layer.register_source(BinanceDerivativesAdapter())
    from cagent_os.data_layer.adapters.defillama_adapter import DefiLlamaAdapter
    data_layer.register_source(DefiLlamaAdapter())
    from cagent_os.data_layer.adapters.fear_greed_adapter import FearGreedAdapter
    data_layer.register_source(FearGreedAdapter())
    # ── A-share (akshare → Sina, free, no API key) ──
    try:
        from cagent_os.data_layer.adapters.akshare_financials_adapter import AkshareFinancialsAdapter
        data_layer.register_source(AkshareFinancialsAdapter())
    except Exception as exc:
        logger.warning("A-share financials adapter not available: %s", exc)
    try:
        from cagent_os.data_layer.adapters.akshare_stock_adapter import AkshareStockAdapter
        data_layer.register_source(AkshareStockAdapter())
    except Exception as exc:
        logger.warning("A-share stock adapter not available: %s", exc)
    try:
        from cagent_os.data_layer.adapters.akshare_futures_adapter import AkshareFuturesAdapter
        data_layer.register_source(AkshareFuturesAdapter())
    except Exception as exc:
        logger.warning("A-share futures adapter not available: %s", exc)

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
    # Phase A: memory tools — let LLM read/write user's markdown memory
    from cagent_os.plugins.memory.plugin import MemoryPlugin
    registry.register_plugin(MemoryPlugin(memory_store))
    registry.register_plugin(
        SkillsPlugin(
            user_skill_service=user_skill_service,
            skills_data_dir=skills_data_dir,
            shared_skills_dir=shared_skills_dir,
        )
    )
    from cagent_os.plugins.crypto.plugin import CryptoPlugin
    registry.register_plugin(CryptoPlugin())
    executor = ToolDispatcher(registry=registry)

    run_engine = AgentRuntime(
        conversation_service=conversation_service,
        event_store=conversation_repository,
        llm_backend=llm_backend,
        capability_executor=executor,
        settings=settings,
        memory_api=memory_store,
        cost_tracker=CostTracker(db_path=str(_project_root / "data" / "cost_tracker.db")),
    )

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="CagentOS — stage 0",
    )

    # Initialize rate limiter (PIN brute-force protection on auth endpoints)
    from cagent_os.interfaces.http.rate_limiter import init_limiter
    init_limiter(app)

    @app.on_event("startup")
    async def _open_memory_store():
        """Open the async SQLite connection for memory_store."""
        await memory_store.open()

    @app.on_event("shutdown")
    async def _close_memory_store():
        await memory_store.close()

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

    # ── Data source status (cached, async background refresh) ───
    _ds_cache: dict | None = None
    _ds_cache_ts: float = 0.0
    _ds_cache_ttl: float = 30.0  # refresh every 30s
    import time as _time_module

    async def _refresh_ds_cache() -> dict:
        nonlocal _ds_cache, _ds_cache_ts
        if _ds_cache is not None and (_time_module.time() - _ds_cache_ts) < _ds_cache_ttl:
            return _ds_cache
        results = await data_layer.health_check_all()
        sources = []
        for name, h in results.items():
            sources.append({
                "name": name,
                "available": h.available,
                "latency_ms": round(h.latency_ms, 1) if h.latency_ms else None,
                "error": h.error_message,
            })
        _ds_cache = {"sources": sources, "total": len(sources),
                      "available": sum(1 for s in sources if s["available"])}
        _ds_cache_ts = _time_module.time()
        return _ds_cache

    @app.get("/api/v1/data-sources")
    async def list_data_sources() -> dict:
        """Return health status for all registered data adapters (cached)."""
        return await _refresh_ds_cache()

    # ── Phase 4b: Cron scheduler ──────────────────────────────────────
    @app.on_event("startup")
    async def _startup_cron() -> None:
        """Start the daily cron scheduler on HTTP server startup."""
        global _cron_task
        _cron_stop_event.clear()
        _cron_task = _asyncio.create_task(_cron_loop())
        logger.info("Cron scheduler started (daily 8:00 AM)")

    @app.on_event("shutdown")
    async def _shutdown_cron() -> None:
        """Stop the cron scheduler on HTTP server shutdown."""
        global _cron_task
        _cron_stop_event.set()
        if _cron_task is not None:
            _cron_task.cancel()
            try:
                await _cron_task
            except _asyncio.CancelledError:
                pass
        logger.info("Cron scheduler stopped")

    async def _cron_loop() -> None:
        """Background loop: check every 60s if it's 8:00 AM local time, then run daily reports."""
        last_run_date: str = ""
        while not _cron_stop_event.is_set():
            try:
                now = _datetime.now()
                today_str = now.strftime("%Y-%m-%d")
                # Run at 8:00 AM local time, once per day
                if now.hour == 8 and today_str != last_run_date:
                    logger.info("Cron: triggering daily reports at %s", now.isoformat())
                    try:
                        from cagent_os.multi_agent.cron_agent import CronAgent
                        agent = CronAgent()
                        results = await agent.run_all_daily()
                        for r in results:
                            if r.error:
                                logger.error("Cron daily failed: %s — %s", r.name, r.error)
                            else:
                                logger.info("Cron daily OK: %s → %s", r.name, r.output_path)
                        last_run_date = today_str
                    except Exception as exc:
                        logger.error("Cron daily run failed: %s", exc)
                # Sleep in 30-second increments so shutdown is responsive
                for _ in range(2):
                    if _cron_stop_event.is_set():
                        break
                    await _asyncio.sleep(30)
            except _asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Cron loop error — will retry in 60s")
                await _asyncio.sleep(60)

    # Phase 4c: Web UI — serve static files.
    # Layout (see cagentos-frontend/ source):
    #   static/
    #     pages/chat.html    ← chat page (referenced as ../assets/...)
    #     pages/brief.html   ← daily brief page
    #     pages/knowledge.html ← knowledge base search page
    #     assets/icons/...   ← SVG icons
    #     legacy.html        ← pre-Phase-4c single-file UI (kept for comparison)
    #
    # URL strategy:
    #   GET /          → redirect to /static/pages/chat.html (so HTML's
    #                    relative ../assets/ paths resolve to /static/assets/)
    #   GET /brief     → redirect to /static/pages/brief.html
    #   GET /knowledge → redirect to /static/pages/knowledge.html
    #   GET /legacy    → serve old single-file UI
    #   GET /static/*  → serve everything under static/
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        @app.get("/")
        async def serve_root():
            if (static_dir / "pages" / "chat.html").exists():
                return RedirectResponse(url="/static/pages/chat.html")
            if (static_dir / "legacy.html").exists():
                return FileResponse(str(static_dir / "legacy.html"))
            return JSONResponse({"detail": "no UI installed"}, status_code=404)

        @app.get("/brief")
        async def serve_brief():
            if (static_dir / "pages" / "brief.html").exists():
                return RedirectResponse(url="/static/pages/brief.html")
            return RedirectResponse(url="/")

        @app.get("/knowledge")
        async def serve_knowledge():
            if (static_dir / "pages" / "knowledge.html").exists():
                return RedirectResponse(url="/static/pages/knowledge.html")
            return RedirectResponse(url="/")

        @app.get("/welcome")
        async def serve_welcome():
            p = static_dir / "pages" / "welcome.html"
            if p.exists():
                return FileResponse(str(p))
            return RedirectResponse(url="/")

        @app.get("/onboard")
        async def serve_onboard():
            p = static_dir / "pages" / "onboard.html"
            if p.exists():
                return FileResponse(str(p))
            return RedirectResponse(url="/")

        @app.get("/login")
        async def serve_login():
            login_page = static_dir / "pages" / "login.html"
            if login_page.exists():
                return FileResponse(str(login_page))
            return RedirectResponse(url="/")

        @app.get("/about")
        async def serve_about():
            p = static_dir / "pages" / "about.html"
            if p.exists():
                return FileResponse(str(p))
            return RedirectResponse(url="/")

        @app.get("/legacy")
        async def serve_legacy():
            p = static_dir / "legacy.html"
            if p.exists():
                return FileResponse(str(p))
            return JSONResponse({"detail": "legacy UI not found"}, status_code=404)

        # Serve the entire static/ tree at /static/* so HTML can reference
        # icons via absolute paths like /static/assets/icons/agent.svg,
        # or via relative ../assets/... from /static/pages/*.html.
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(
        build_runs_router(
            run_engine=run_engine,
            conversation_service=conversation_service,
            user_skill_service=user_skill_service,
            cost_tracker=run_engine._cost_tracker if hasattr(run_engine, '_cost_tracker') else None,
        )
    )

    # Phase 4c: RAG (knowledge base) HTTP endpoints
    from cagent_os.interfaces.http.routes_rag import build_rag_router
    app.include_router(build_rag_router(rag_service))

    # Phase 4c: Knowledge triage + article browsing
    from cagent_os.interfaces.http.routes_knowledge import build_knowledge_router
    _knowledge_dir = _project_root / "knowledge"
    app.include_router(build_knowledge_router(_knowledge_dir))

    # Serve knowledge/ images so article markdown can reference them.
    # Custom endpoint under /knowledge-static/ (NOT /static/ because
    # /static/ is mounted by StaticFiles above which intercepts all sub-paths).
    # URL pattern: /knowledge-static/00_Inbox/<article>/images/img_0.png
    if _knowledge_dir.exists():
        from fastapi.responses import FileResponse

        @app.get("/knowledge-static/{file_path:path}")
        async def serve_knowledge_file(file_path: str):
            """Serve any file under knowledge/ (images, articles, etc)."""
            full = _knowledge_dir / file_path
            # Security: prevent path traversal
            try:
                full.resolve().relative_to(_knowledge_dir.resolve())
            except ValueError:
                from fastapi import HTTPException
                raise HTTPException(status_code=400, detail="Invalid path")
            if not full.exists() or not full.is_file():
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail=f"Not found: {file_path}")
            return FileResponse(str(full))

    # Phase 4c+: Conversation listing + event replay
    from cagent_os.interfaces.http.routes_conversations import build_conversations_router
    app.include_router(build_conversations_router(conversation_repository))

    # Phase 4c+: Auth (register / login / me / invitations)
    app.include_router(build_auth_router(user_store, invitation_store))

    # Phase A: Memory management (agent_notes + user_profile)
    from cagent_os.interfaces.http.routes_memory import build_memory_router
    app.include_router(build_memory_router(memory_store))

    # Phase 4c+: User profile (investment focus, free text)
    from cagent_os.interfaces.http.routes_profile import build_profile_router
    profiles_dir = _project_root / "data" / "profiles"
    app.include_router(build_profile_router(profiles_dir))

    # Phase 4c+: cost tracking status
    from cagent_os.interfaces.http.routes_cost import build_cost_router
    _cost_tracker = run_engine._cost_tracker if hasattr(run_engine, '_cost_tracker') else None
    if _cost_tracker is not None:
        app.include_router(build_cost_router(_cost_tracker))

    return app
