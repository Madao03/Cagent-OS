"""HTTP streaming regressions. Use a fast producer to fill the former 256-event buffer."""
import asyncio
import inspect
import json
import threading
from unittest.mock import Mock, patch

import pytest
from fastapi import Request

from cagent_os.conversations.models import JournalEntry
from cagent_os.interfaces.http.routes_demo import build_demo_router
from cagent_os.interfaces.http.routes_runs import build_runs_router
from cagent_os.interfaces.http.schemas import PostMessageRequest


def test_chat_delivers_burst_and_releases_slot():
    tracker = Mock()
    engine = Mock()
    engine.run_stream.return_value = (
        JournalEntry(type="message.assistant_delta", role="assistant", content=str(i))
        for i in range(600)
    )
    router = build_runs_router(run_engine=engine, conversation_service=Mock(),
                               user_skill_service=Mock(), cost_tracker=tracker)
    send = inspect.unwrap(router.routes[0].endpoint)
    with patch("cagent_os.interfaces.http.routes_runs.require_principal_id", return_value="u"):
        response = send("conv", PostMessageRequest(content="test"), Request({"type": "http"}))

    async def consume():
        return [json.loads(frame.removeprefix("data: ")) async for frame in response.body_iterator]

    events = asyncio.run(asyncio.wait_for(consume(), timeout=5))
    assert [event["answer_chunk"] for event in events] == [str(i) for i in range(600)]
    tracker.release.assert_called_once_with("u")


def test_disconnect_leaves_worker_running_until_completion():
    resume = threading.Event()
    released = threading.Event()
    tracker = Mock()
    tracker.release.side_effect = lambda principal: released.set()

    def run_stream(**kwargs):
        yield JournalEntry(type="run.started")
        assert resume.wait(timeout=3)
        yield JournalEntry(type="run.completed")

    engine = Mock(run_stream=run_stream)
    router = build_runs_router(run_engine=engine, conversation_service=Mock(),
                               user_skill_service=Mock(), cost_tracker=tracker)
    send = inspect.unwrap(router.routes[0].endpoint)
    with patch("cagent_os.interfaces.http.routes_runs.require_principal_id", return_value="u"):
        response = send("conv", PostMessageRequest(content="test"), Request({"type": "http"}))

    async def disconnect():
        assert "run.started" in await anext(response.body_iterator)
        await response.body_iterator.aclose()

    try:
        asyncio.run(asyncio.wait_for(disconnect(), timeout=2))
        assert not released.is_set()
    finally:
        resume.set()
    assert released.wait(timeout=2)
    tracker.release.assert_called_once_with("u")


def test_chat_releases_slot_on_conversation_setup_failure():
    tracker = Mock()
    conversations = Mock()
    conversations.get_conversation.side_effect = RuntimeError("storage unavailable")
    router = build_runs_router(run_engine=Mock(), conversation_service=conversations,
                               user_skill_service=Mock(), cost_tracker=tracker)
    send = inspect.unwrap(router.routes[0].endpoint)
    with patch("cagent_os.interfaces.http.routes_runs.require_principal_id", return_value="u"):
        with pytest.raises(RuntimeError, match="storage unavailable"):
            send("conv", PostMessageRequest(content="test"), Request({"type": "http"}))
    tracker.release.assert_called_once_with("u")


def test_demo_setup_failure_does_not_start_agent():
    engine = Mock()
    conversations = Mock()
    conversations.create_conversation.side_effect = RuntimeError("storage unavailable")
    router = build_demo_router(engine, conversations, Mock())
    response = inspect.unwrap(router.routes[0].endpoint)({"query": "test"}, Request({"type": "http"}))
    assert response.status_code == 503
    engine.run_stream.assert_not_called()

def test_demo_persists_scoped_capabilities_and_separate_guests(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    from cagent_os.conversations.service import ConversationService
    from cagent_os.conversations.sqlite_store import SqliteConversationRepository
    from cagent_os.interfaces.http.rate_limiter import init_limiter
    from cagent_os.user_skills.models import UserSkillDocument, UserSkillSnapshot

    store = SqliteConversationRepository(str(tmp_path / "test.db"))
    service = ConversationService(store)
    skills = Mock()
    shared_skill = UserSkillDocument("shared:crypto", "crypto", "公共链上估值流程")
    skills.load_snapshot.side_effect = lambda uid: UserSkillSnapshot.from_documents(uid, [shared_skill])
    seen = []

    def run_stream(*, conversation_id, principal_id, user_content):
        record = service.get_conversation(principal_id, conversation_id)
        seen.append(record)
        yield JournalEntry(type="run.completed")

    limiter = Limiter(key_func=get_remote_address)
    monkeypatch.setattr("cagent_os.interfaces.http.routes_demo.limiter", limiter)
    monkeypatch.setattr("cagent_os.interfaces.http.rate_limiter.limiter", limiter)
    app = FastAPI()
    init_limiter(app)
    app.include_router(build_demo_router(Mock(run_stream=run_stream), service, skills))
    try:
        with TestClient(app, client=("test-guest-isolation", 123)) as client:
            for _ in range(2):
                response = client.post("/api/v1/demo", json={"query": "BTC估值"})
                assert "run.completed" in response.text
        assert seen[0].user_id != seen[1].user_id
        for record in seen:
            assert record.principal_id == record.user_id
            assert record.user_skill_snapshot.documents == (shared_skill,)
            allowed = set(record.policy_snapshot.allowed_capability_ids)
            assert {"Skill", "crypto.onchain.metrics", "crypto.sentiment.fng", "financial.websearch"} <= allowed
            assert not allowed.intersection({
                "docs.read", "write.file", "image.describe", "web.fetch", "publish_file", "bash",
                "financial.trace.query", "financial.rag.search", "financial.rag.status",
                "financial.memory.get_document", "memory.get_full_state", "memory.update_notes",
            })
        legacy = store._deserialize_record('{"principal_id":"legacy","user_id":"legacy","conversation_id":"legacy"}')
        assert legacy.policy_snapshot.allowed_capability_ids == []
    finally:
        store.close()
