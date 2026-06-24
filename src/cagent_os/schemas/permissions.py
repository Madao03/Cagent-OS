"""Skill permission labels — Phase 2e.

Each skill is tagged with:
  - domain: What asset class/data domain it accesses
  - mutability: Whether it writes data or is read-only
  - agent_roles: Which agent roles may invoke it (Phase 4 multi-agent)

Permissions are enforced at the ToolDispatcher / ToolGuard layer before
any skill code executes. A denied call returns a structured error — it
never reaches the plugin handler.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class AgentRole(str, Enum):
    """Agent roles for Phase 4 multi-agent orchestration."""

    RESEARCHER = "researcher"   # Full access — reads all data, invokes all skills
    RISK_AUDITOR = "risk_auditor"  # Read-only — audits analysis output, challenges assumptions
    EDITOR = "editor"           # Read-only on data — compresses Research + Audit into summary


class SkillPermission(BaseModel):
    """Permission tag attached to each skill manifest."""

    skill_name: str
    domain: str          # "macro", "equity", "crypto", "cross_asset", "methodology", "infra"
    mutability: str      # "read" | "write"
    agent_roles: list[AgentRole]  # which roles may invoke

    @property
    def is_write(self) -> bool:
        return self.mutability == "write"


# ── Permission Matrix ────────────────────────────────────────────────
# Maps every core skill to its permission tags.
# This is enforced at Phase 4; in Phase 2 only the Researcher role exists.

PERMISSION_MATRIX: dict[str, SkillPermission] = {
    # Research — Equity
    "us-stock-analysis": SkillPermission(
        skill_name="us-stock-analysis",
        domain="equity",
        mutability="read",
        agent_roles=[AgentRole.RESEARCHER, AgentRole.RISK_AUDITOR],
    ),
    # Research — Crypto
    "crypto-analysis": SkillPermission(
        skill_name="crypto-analysis",
        domain="crypto",
        mutability="read",
        agent_roles=[AgentRole.RESEARCHER, AgentRole.RISK_AUDITOR],
    ),
    "crypto-stock-analysis": SkillPermission(
        skill_name="crypto-stock-analysis",
        domain="crypto",
        mutability="read",
        agent_roles=[AgentRole.RESEARCHER, AgentRole.RISK_AUDITOR],
    ),
    "crypto-funds-flow-analysis": SkillPermission(
        skill_name="crypto-funds-flow-analysis",
        domain="crypto",
        mutability="read",
        agent_roles=[AgentRole.RESEARCHER, AgentRole.RISK_AUDITOR],
    ),
    # Research — Macro / Cross-asset
    "macro-analysis": SkillPermission(
        skill_name="macro-analysis",
        domain="macro",
        mutability="read",
        agent_roles=[AgentRole.RESEARCHER, AgentRole.RISK_AUDITOR],
    ),
    "tech-sector-bridge": SkillPermission(
        skill_name="tech-sector-bridge",
        domain="cross_asset",
        mutability="read",
        agent_roles=[AgentRole.RESEARCHER, AgentRole.RISK_AUDITOR],
    ),
    # Knowledge management
    "content-triage": SkillPermission(
        skill_name="content-triage",
        domain="methodology",
        mutability="write",  # appends to ledger
        agent_roles=[AgentRole.RESEARCHER],
    ),
    "read-later": SkillPermission(
        skill_name="read-later",
        domain="infra",
        mutability="write",  # saves articles to Obsidian
        agent_roles=[AgentRole.RESEARCHER],
    ),
    "content-assetize": SkillPermission(
        skill_name="content-assetize",
        domain="methodology",
        mutability="write",  # extracts + writes structured assets
        agent_roles=[AgentRole.RESEARCHER],
    ),
}
