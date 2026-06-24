"""Skill I/O Schemas — Pydantic v2 contracts for all core skills.

Phase 2e: Every skill's input trigger and output structure is defined here.
This serves as:
  1. Documentation — what each skill must accept and produce
  2. Validation — when output parsing is added, these validate
  3. Golden Cases foundation — Golden Cases reference these schemas
  4. Anti-drift — changing a schema means intentionally changing the contract

Design rules:
  - All input fields are Optional[str] — skills are invoked by intent, not
    structured API calls. The LLM fills what it discovers.
  - All output fields are Optional — partial outputs are valid (agent may
    not have all data). Validation is lenient by design.
  - Timestamps use str (ISO 8601) for human readability in debug/trace.
"""

from cagent_os.schemas.skill_io import (
    # Macro
    MacroAnalysisInput,
    MacroAnalysisOutput,
    ShortTermMacro,
    MediumTermMacro,
    LongTermMacro,
    # US Stock
    UsStockAnalysisInput,
    UsStockAnalysisOutput,
    CyclicalTrapCheck,
    # Crypto
    CryptoAnalysisInput,
    CryptoAnalysisOutput,
    CryptoCyclePosition,
    # Content Triage
    ContentTriageInput,
    ContentTriageOutput,
    TriageScores,
    TriageEntry,
    # Crypto Stock
    CryptoStockAnalysisInput,
    CryptoStockAnalysisOutput,
    MnavAnalysis,
    StratusFlywheel,
    # Content Assetize
    AssetFact,
    AssetOpinion,
    AssetFramework,
    ArticleReference,
    ContentAssetizeInput,
    ContentAssetizeOutput,
)

from cagent_os.schemas.permissions import (
    SkillPermission,
    AgentRole,
    PERMISSION_MATRIX,
)

from cagent_os.schemas.state import (
    SessionStateSchema,
    AgentStateSchema,
    ToolContextSchema,
)

__all__ = [
    # Skill I/O
    "MacroAnalysisInput",
    "MacroAnalysisOutput",
    "ShortTermMacro",
    "MediumTermMacro",
    "LongTermMacro",
    "UsStockAnalysisInput",
    "UsStockAnalysisOutput",
    "CyclicalTrapCheck",
    "CryptoAnalysisInput",
    "CryptoAnalysisOutput",
    "CryptoCyclePosition",
    "ContentTriageInput",
    "ContentTriageOutput",
    "TriageScores",
    "TriageEntry",
    "CryptoStockAnalysisInput",
    "CryptoStockAnalysisOutput",
    "MnavAnalysis",
    "StratusFlywheel",
    # Content Assetize
    "AssetFact",
    "AssetOpinion",
    "AssetFramework",
    "ArticleReference",
    "ContentAssetizeInput",
    "ContentAssetizeOutput",
    # Permissions
    "SkillPermission",
    "AgentRole",
    "PERMISSION_MATRIX",
    # State
    "SessionStateSchema",
    "AgentStateSchema",
    "ToolContextSchema",
]
