"""CLI entry point for CagentOS — interactive REPL and one-shot chat."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from cagent_os.agents import AgentRuntime
from cagent_os.config import get_settings
from cagent_os.conversations import (
    ConversationService,
    InMemoryConversationRepository,
)
from cagent_os.data_layer import DataLayer
from cagent_os.data_layer.adapters.fin_skill_adapter import FinSkillAdapter
from cagent_os.data_layer.adapters.yfinance_adapter import YFinanceAdapter
from cagent_os.llm.factory import create_backend
from cagent_os.mcp_client.session import MCPSessionManager
from cagent_os.memory.sqlite_store import SqliteMemoryStore
from cagent_os.observability.tracing import TraceWriter
from cagent_os.plugins import ToolDispatcher, ToolRegistry
from cagent_os.plugins.bash.plugin import BashPlugin
from cagent_os.plugins.financial.plugin import FinancialPlugin
from cagent_os.plugins.financial.toolkit import FinancialToolkit, build_financial_toolkit
from cagent_os.plugins.skills.plugin import SkillsPlugin
from cagent_os.plugins.web.plugin import WebPlugin
from cagent_os.plugins.read.plugin import ReadPlugin
from cagent_os.plugins.write.plugin import WritePlugin
from cagent_os.shared.async_bridge import AsyncBridge
from cagent_os.shared.logging_utils import configure_logging
from cagent_os.user_skills import FilesystemUserSkillStore, UserSkillService

logger = logging.getLogger(__name__)


def _load_mcp_config() -> list[dict]:
    settings = get_settings()
    config_path = Path(settings.mcp_servers_config)
    if not config_path.exists():
        logger.warning(f"{config_path} not found — MCP disabled")
        return []
    with open(config_path) as f:
        data = json.load(f)
    return data.get("servers", [])


def build_registry(
    mcp_manager: MCPSessionManager | None = None,
    skill_service: UserSkillService | None = None,
) -> tuple[ToolRegistry, FinancialToolkit | None]:
    """Build the tool registry. Returns (registry, toolkit) so callers
    can close the toolkit's MCP event-loop thread on shutdown."""
    settings = get_settings()
    registry = ToolRegistry()
    toolkit = build_financial_toolkit(settings=settings, mcp_session_manager=mcp_manager)
    # Phase 1b: DataLayer with cross-validation adapters
    data_layer = DataLayer()
    data_layer.register_source(YFinanceAdapter())
    if mcp_manager is not None:
        data_layer.register_source(FinSkillAdapter(mcp_manager))
    registry.register_plugin(FinancialPlugin(settings=settings, toolkit=toolkit, data_layer=data_layer))
    registry.register_plugin(WebPlugin(settings=settings))
    registry.register_plugin(ReadPlugin(settings=settings))
    registry.register_plugin(WritePlugin(settings=settings))
    # BashPlugin disabled — Windows has no /bin/bash, and its presence
    # causes the Agent to choose bash for file reading instead of Read.
    # registry.register_plugin(BashPlugin(settings=settings))
    if skill_service is not None:
        registry.register_plugin(
            SkillsPlugin(
                user_skill_service=skill_service,
                skills_data_dir=settings.skills_data_dir,
                shared_skills_dir=settings.shared_skills_dir,
            )
        )
    return registry, toolkit


def _safe_str(text: str) -> str:
    """Encode text safely for the current console encoding."""
    try:
        text.encode(sys.stdout.encoding or "utf-8")
        return text
    except UnicodeEncodeError:
        return text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        )


def _safe_print(*args, **kwargs) -> None:
    """Print safely, replacing unencodable characters."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        safe_args = tuple(
            _safe_str(a) if isinstance(a, str) else a for a in args
        )
        print(*safe_args, **kwargs)


def _print_event(event, *, verbose: bool = False) -> None:
    """Print a single run event to stdout."""
    if event.type == "message.assistant_delta":
        _safe_print(event.content, end="", flush=True)
    elif event.type == "message.assistant_added":
        if event.content:
            print(f"\n\nAgent:\n{_safe_str(event.content)}")
    elif event.type == "run.tool_requested":
        tool_name = event.data.get("name", "?")
        print(f"\n  [tool: {tool_name} ...]", end=" ", flush=True)
    elif event.type == "run.tool_completed":
        print("done]")
        if verbose:
            preview = event.data.get("result", "")
            if isinstance(preview, str) and len(preview) > 200:
                preview = preview[:200] + "..."
            print(f"  [result: {preview}]")
    elif event.type == "run.tool_failed":
        err = _safe_str(event.data.get("message", event.data.get("error_code", "?")))
        print(f"failed: {err}]")
    elif event.type == "run.failed":
        print(f"\n[ERROR] {_safe_str(event.data.get('message', 'unknown'))}")
    elif event.type == "run.completed":
        pass  # don't spam "completed" in REPL
    elif event.type == "message.assistant_tool_calls_added":
        tool_calls = event.data.get("tool_calls", [])
        names = [tc.get("name", "?") for tc in tool_calls]
        if verbose:
            print(f"\n  [planning tools: {', '.join(names)}]")


def _run_one_shot(
    engine: AgentRuntime,
    conversation_id: str,
    principal_id: str,
    user_message: str,
    *,
    verbose: bool = False,
) -> None:
    print(f"\nUser: {user_message}")
    for event in engine.run(
        conversation_id=conversation_id,
        principal_id=principal_id,
        user_content=user_message,
    ):
        _print_event(event, verbose=verbose)


def _run_repl(
    engine: AgentRuntime,
    conversation_id: str,
    principal_id: str,
    *,
    verbose: bool = False,
) -> None:
    """Interactive REPL loop with conversation context preserved across turns."""
    print()
    print("  CagentOS REPL")
    print("  Type your message, /help for commands, /exit to quit.")
    print()

    turn = 1
    while True:
        try:
            user_input = input(f"  [{turn}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            _handle_slash_command(user_input)
            if user_input in ("/exit", "/quit", "/q"):
                break
            continue

        print()
        for event in engine.run(
            conversation_id=conversation_id,
            principal_id=principal_id,
            user_content=user_input,
        ):
            _print_event(event, verbose=verbose)
        print()
        turn += 1


def _handle_slash_command(cmd: str) -> None:
    """Process /-prefixed REPL commands."""
    cmd = cmd.strip().lower()
    if cmd in ("/exit", "/quit", "/q"):
        print("Goodbye.")
    elif cmd in ("/help", "/h", "/?"):
        print()
        print("  Commands:")
        print("    /exit, /quit, /q    Exit REPL")
        print("    /help, /h, /?      Show this help")
        print("    /verbose           Toggle verbose tool output")
        print("    /clear             Start a new conversation")
        print()
    elif cmd == "/verbose":
        print("  Verbose mode not yet toggleable in REPL (use --verbose flag).")
    elif cmd == "/clear":
        print("  New conversation not yet supported in REPL (restart to clear).")
    else:
        print(f"  Unknown command: {cmd}")


def main() -> None:
    settings = get_settings()
    configure_logging(debug=settings.debug)

    parser = argparse.ArgumentParser(
        prog="cagent-os",
        description="CagentOS — multi-provider AI agent",
    )
    sub = parser.add_subparsers(dest="command")

    chat_parser = sub.add_parser("chat", help="One-shot message (non-interactive)")
    chat_parser.add_argument("message", nargs="+", help="Message to send")
    chat_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose tool output")

    args = parser.parse_args()

    # Wire up dependencies
    mcp_servers = _load_mcp_config()
    mcp_manager = MCPSessionManager(mcp_servers) if mcp_servers else None

    # Resolve relative paths against project root (derived from __file__)
    # so that skills/ and data/skills/ are found regardless of CWD.
    _project_root = Path(__file__).resolve().parent.parent.parent.parent
    skill_store = FilesystemUserSkillStore(
        data_dir=(_project_root / settings.skills_data_dir).resolve(),
        shared_skills_dir=(_project_root / settings.shared_skills_dir).resolve() if settings.shared_skills_dir else None,
    )
    skill_service = UserSkillService(store=skill_store)

    registry, toolkit = build_registry(mcp_manager=mcp_manager, skill_service=skill_service)
    executor = ToolDispatcher(registry=registry)

    repo = InMemoryConversationRepository()
    conversation_service = ConversationService(repository=repo)
    llm_backend = create_backend(settings)

    # Task 5: Memory + TraceWriter + AsyncBridge
    Path("data").mkdir(exist_ok=True)
    bridge = AsyncBridge()
    memory_store = SqliteMemoryStore(db_path="data/memory.db")
    trace_writer = TraceWriter(db_path="data/trace.db")
    # Open async resources on the bridge loop
    bridge.run(memory_store.open(), timeout=10)
    bridge.run(trace_writer.open(), timeout=10)

    principal_id = settings.default_principal_id
    user_id = settings.default_user_id

    snapshot = skill_service.load_snapshot(user_id)
    conversation = conversation_service.create_conversation(
        principal_id=principal_id,
        user_id=user_id,
        user_skill_snapshot=snapshot,
    )

    engine = AgentRuntime(
        conversation_service=conversation_service,
        event_store=repo,
        llm_backend=llm_backend,
        capability_executor=executor,
        settings=settings,
        memory_api=memory_store,
        trace_writer=trace_writer,
        async_bridge=bridge,
    )

    try:
        if args.command == "chat":
            user_message = " ".join(args.message)
            _run_one_shot(
                engine,
                conversation_id=conversation.conversation_id,
                principal_id=principal_id,
                user_message=user_message,
                verbose=getattr(args, "verbose", False),
            )
            print()
        else:
            # Default: interactive REPL
            _run_repl(
                engine,
                conversation_id=conversation.conversation_id,
                principal_id=principal_id,
                verbose=getattr(args, "verbose", False),
            )
    finally:
        # Close MCP toolkit (also closes MCP sessions on its own loop)
        if toolkit is not None:
            try:
                toolkit.close()
            except Exception:
                logger.debug("FinancialToolkit close failed", exc_info=True)
        # Close async stores and stop the bridge thread
        bridge.run(memory_store.close(), timeout=5)
        bridge.run(trace_writer.close(), timeout=5)
        bridge.shutdown()


if __name__ == "__main__":
    main()
