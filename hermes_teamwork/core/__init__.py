"""
hermes_teamwork.core
~~~~~~~~~~~~~~~~~~~~
Core multi-agent Teamwork architecture engine.
"""
from hermes_teamwork.core.state import (
    StateError,
    LockedSectionTamperError,
    ImmutableStateViolationError,
    HandoffValidationError,
    HandoffReport,
    DeadEndRecord,
    ProgressState,
    AgentState,
    TeamworkRunState,
    utc_now_iso,
    parse_iso_timestamp,
    parse_handoff_text,
    LOCKED_SECTION_HEADERS,
    MANDATORY_HANDOFF_SECTIONS,
    MAX_BRIEFING_LINES,
    DEFAULT_LIVENESS_TIMEOUT_SECONDS,
)
from hermes_teamwork.core.gate import (
    Verdict,
    GateVerdict,
    GateResult,
    AdversarialGate,
)
from hermes_teamwork.core.orchestrator import (
    DispatchOnlyViolationError,
    MilestoneStatus,
    Milestone,
    OrchestratorConfig,
    LineageInfo,
    ProjectOrchestrator,
)
from hermes_teamwork.core.sentinel import (
    TaskArchetype,
    VictoryAuditVerdict,
    LivenessStatus,
    SentinelResult,
    Sentinel,
)

__all__ = [
    # State
    "StateError",
    "LockedSectionTamperError",
    "ImmutableStateViolationError",
    "HandoffValidationError",
    "HandoffReport",
    "DeadEndRecord",
    "ProgressState",
    "AgentState",
    "TeamworkRunState",
    "utc_now_iso",
    "parse_iso_timestamp",
    "parse_handoff_text",
    "LOCKED_SECTION_HEADERS",
    "MANDATORY_HANDOFF_SECTIONS",
    "MAX_BRIEFING_LINES",
    "DEFAULT_LIVENESS_TIMEOUT_SECONDS",
    # Gate
    "Verdict",
    "GateVerdict",
    "GateResult",
    "AdversarialGate",
    # Orchestrator
    "DispatchOnlyViolationError",
    "MilestoneStatus",
    "Milestone",
    "OrchestratorConfig",
    "LineageInfo",
    "ProjectOrchestrator",
    # Sentinel
    "TaskArchetype",
    "VictoryAuditVerdict",
    "LivenessStatus",
    "SentinelResult",
    "Sentinel",
]
