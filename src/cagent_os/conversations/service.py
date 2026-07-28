from __future__ import annotations

from cagent_os.conversations.models import SessionSnapshot
from cagent_os.conversations.repository import ConversationRepository
from cagent_os.domain.models import (
    MemorySnapshot,
    PolicyView,
    SessionOverrides,
    UserPersona,
)
from cagent_os.shared.errors import ConversationOwnershipError
from cagent_os.shared.ids import new_conversation_id
from cagent_os.user_skills.models import UserSkillSnapshot


class ConversationService:
    def __init__(self, repository: ConversationRepository) -> None:
        self._repository = repository

    def create_conversation(
        self,
        *,
        principal_id: str,
        user_id: str,
        user_skill_snapshot: UserSkillSnapshot,
        policy_snapshot: PolicyView | None = None,
        user_prompt_preferences: UserPersona | None = None,
        session_prompt_overrides: SessionOverrides | None = None,
        memory_context: MemorySnapshot | None = None,
        conversation_id: str | None = None,
    ) -> SessionSnapshot:
        """Create a new conversation record.

        Args:
            conversation_id: optional explicit ID. When omitted, a new
                UUID is generated. Used by the HTTP layer to register
                client-generated IDs (e.g. "web-<uuid>") so the same ID
                sent in POST /messages can be found in the repository.
        """
        record = SessionSnapshot(
            conversation_id=conversation_id or new_conversation_id(),
            principal_id=principal_id,
            user_id=user_id,
            user_skill_snapshot=user_skill_snapshot,
            policy_snapshot=policy_snapshot or PolicyView(),
            user_prompt_preferences_snapshot=user_prompt_preferences or UserPersona(),
            session_prompt_overrides=session_prompt_overrides or SessionOverrides(),
            memory_context=memory_context or MemorySnapshot(),
        )
        return self._repository.create(record)

    def get_conversation(self, principal_id: str, conversation_id: str) -> SessionSnapshot:
        record = self._repository.get(conversation_id)
        if record.principal_id != principal_id:
            raise ConversationOwnershipError("Conversation belongs to another principal.")
        return record
