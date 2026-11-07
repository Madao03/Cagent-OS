import json

from cagent_os.conversations.models import SessionSnapshot
from cagent_os.conversations.sqlite_store import SqliteConversationRepository
from cagent_os.domain.models import MemorySnapshot, PolicyView, SessionOverrides, UserPersona
from cagent_os.user_skills.models import UserSkillDocument, UserSkillSnapshot


def test_session_snapshot_survives_reopen(tmp_path):
    path = str(tmp_path / "conv.db")
    snapshot = SessionSnapshot(
        conversation_id="c",
        principal_id="principal",
        user_id="user",
        user_skill_snapshot=UserSkillSnapshot.from_documents("user", [
            UserSkillDocument("shared:crypto", "crypto", "技能正文", "描述"),
            UserSkillDocument("user:custom", "custom", "第二个技能"),
        ]),
        policy_snapshot=PolicyView(["Skill", "crypto.onchain.metrics"]),
        user_prompt_preferences_snapshot=UserPersona("用中文回答。"),
        session_prompt_overrides=SessionOverrides("使用本次会话指定的口径。"),
        memory_context=MemorySnapshot("测试摘要", ["第一条", "第二条"]),
    )
    store = SqliteConversationRepository(path)
    try:
        store.create(snapshot)
    finally:
        store.close()
    reopened = SqliteConversationRepository(path)
    try:
        assert reopened.get("c") == snapshot
    finally:
        reopened.close()

    legacy = {"conversation_id": "c", "principal_id": "p", "user_id": "u", "allowed_capability_ids": ["Skill"]}
    restored = SqliteConversationRepository._deserialize_record(json.dumps(legacy))
    assert restored.policy_snapshot == PolicyView(["Skill"])
    assert restored.user_skill_snapshot == UserSkillSnapshot("u")
    assert restored.memory_context == MemorySnapshot()
