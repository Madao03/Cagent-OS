"""Multi-agent orchestration — Phase 4.

Supervisor coordinates 4 specialized agents:
  DataCollector → Researcher (parallel) → Red-Team → Editor (serial)

Agent-to-agent communication uses Pydantic schemas.
Phase 4a: infrastructure built. Phase 4b-4f: Cron, Web UI, Langfuse, CI/CD.
"""

from cagent_os.multi_agent.schemas import (
    AnalysisReport,
    CounterNarrative,
    DataCitation,
    DataSourceItem,
    DecisionSummary,
    RawDataDump,
    RiskAuditResult,
    SupervisorDecision,
    ValuationMetrics,
)
from cagent_os.multi_agent.cron_agent import (
    CronAgent,
    CronResult,
    DEFAULT_TEMPLATES,
    ReportTemplate,
)
from cagent_os.multi_agent.supervisor import (
    Supervisor,
    SupervisorConfig,
    SupervisorResult,
)

__all__ = [
    # Schemas
    "AnalysisReport",
    "CounterNarrative",
    "DataCitation",
    "DataSourceItem",
    "DecisionSummary",
    "RawDataDump",
    "RiskAuditResult",
    "SupervisorDecision",
    "ValuationMetrics",
    # Supervisor
    "Supervisor",
    "SupervisorConfig",
    "SupervisorResult",
    # Cron
    "CronAgent",
    "CronResult",
    "DEFAULT_TEMPLATES",
    "ReportTemplate",
]
