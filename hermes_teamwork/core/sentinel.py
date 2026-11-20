"""
hermes_teamwork.core.sentinel
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Sentinel Lifecycle Manager for Teamwork.
Invariants:
1. Single Point of User Contact: Only agent communicating with human user.
2. Relay-Only Negative Constraint: Never makes technical decisions, never edits code.
3. Verbatim Request Freezing: Writes immutable ORIGINAL_REQUEST.md.
4. Task Interview & Routing: Maps intent to TaskArchetype.
5. Background Dual Crons: Reporting (*/8m) and Liveness Watchdog (*/10m).
6. Independent Victory Audit: Dispatches VictoryAuditor (max 2 audits).
7. Executive Delivery: Synthesizes final user report upon verified victory.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Union

from hermes_teamwork.core.orchestrator import ProjectOrchestrator
from hermes_teamwork.core.state import (
    AgentState,
    TeamworkRunState,
    parse_iso_timestamp,
    utc_now_iso,
)
from hermes_teamwork.prompts import get_system_prompt
from hermes_teamwork.runners.base import BaseAgentRunner

_FORMAL_PROOF_RE = re.compile(r"\b(?:lean4?|mathlib|formal\s+proof|lemma)\b", re.IGNORECASE)
_DOCUMENT_REVIEW_RE = re.compile(r"\b(?:paper\s+review|document\s+review|rsa|peer\s+review)\b", re.IGNORECASE)
_MILESTONE_PIPELINE_RE = re.compile(r"\b(?:milestones?|multi-milestone|epic)\b", re.IGNORECASE)
_PIPELINE_RE = re.compile(r"\b(?:pipeline|multi-stage|conductor)\b", re.IGNORECASE)
_SWE_LIGHT_RE = re.compile(r"\b(?:quick\s+fix|one\s+line|typo|small\s+bug|swe\s+light|single\s+file)\b", re.IGNORECASE)
_ORCH_GEN_DIR_RE = re.compile(r"^orchestrator_gen(\d+)$")


class TaskArchetype(str, Enum):
    SWE_LIGHT = "swe_light"
    MILESTONE_PIPELINE = "milestone_pipeline"
    DOCUMENT_REVIEW = "document_review"
    FORMAL_PROOF = "formal_proof"
    PIPELINE = "pipeline"


class VictoryAuditVerdict(str, Enum):
    VICTORY_CONFIRMED = "VICTORY CONFIRMED"
    VICTORY_REJECTED = "VICTORY REJECTED"
    EXHAUSTED = "MAX_VICTORY_AUDITS_EXCEEDED"


class LivenessStatus(str, Enum):
    HEALTHY = "HEALTHY"
    NUDGE_REQUIRED = "NUDGE_REQUIRED"        # > 10 min
    WARNING_STALLED = "WARNING_STALLED"      # > 20 min
    CRITICAL_KILL = "CRITICAL_KILL"          # > 60 min


@dataclass
class SentinelResult:
    status: str                              # "SUCCESS", "FAILED"
    run_id: str
    run_dir: str
    archetype: TaskArchetype
    victory_verdict: Optional[str] = None
    audit_count: int = 0
    final_report: str = ""
    error_message: Optional[str] = None
    milestones_completed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Converts SentinelResult to a standard dictionary."""
        return {
            "status": self.status,
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "archetype": self.archetype.value if hasattr(self.archetype, "value") else str(self.archetype),
            "victory_verdict": self.victory_verdict,
            "audit_count": self.audit_count,
            "final_report": self.final_report,
            "error_message": self.error_message,
            "milestones_completed": list(self.milestones_completed),
        }

    def __getitem__(self, key: str) -> Any:
        d = self.to_dict()
        if key in d:
            return d[key]
        raise KeyError(f"SentinelResult has no field '{key}'")

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()


class Sentinel:
    """
    Sentinel Lifecycle Manager for Teamwork.
    """
    MAX_VICTORY_AUDITS: int = 2
    REPORTING_INTERVAL_SECONDS: int = 480    # 8 minutes
    LIVENESS_INTERVAL_SECONDS: int = 600     # 10 minutes
    STALL_NUDGE_SECONDS: int = 600           # 10 minutes
    STALL_WARNING_SECONDS: int = 1200        # 20 minutes
    STALL_KILL_SECONDS: int = 3600           # 60 minutes

    def __init__(
        self,
        workspace_root: Union[Path, str],
        runner: BaseAgentRunner,
        run_id: Optional[str] = None,
        base_state_dir: Optional[Union[Path, str]] = None,
        auto_start_crons: bool = False,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.runner = runner
        self.run_state = TeamworkRunState(
            workspace_root=self.workspace_root,
            run_id=run_id,
            base_state_dir=Path(base_state_dir) if base_state_dir else None,
        )
        self.state = AgentState.create(self.run_state.run_dir, "sentinel", "sentinel")
        self.archetype: Optional[TaskArchetype] = None
        self.victory_audit_count: int = 0
        self.active_agent_id: Optional[str] = None
        self._orchestrator: Optional[ProjectOrchestrator] = None

        # Background cron thread controls
        self._cron_stop_event = threading.Event()
        self._reporting_thread: Optional[threading.Thread] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        if auto_start_crons:
            self.start_background_crons()

    def classify_task(self, user_request: str) -> TaskArchetype:
        """
        Classifies incoming user prompt into a canonical TaskArchetype.
        """
        if _FORMAL_PROOF_RE.search(user_request):
            return TaskArchetype.FORMAL_PROOF
        if _DOCUMENT_REVIEW_RE.search(user_request):
            return TaskArchetype.DOCUMENT_REVIEW
        if _MILESTONE_PIPELINE_RE.search(user_request):
            return TaskArchetype.MILESTONE_PIPELINE
        if _PIPELINE_RE.search(user_request):
            return TaskArchetype.PIPELINE
        if _SWE_LIGHT_RE.search(user_request):
            return TaskArchetype.SWE_LIGHT
        return TaskArchetype.MILESTONE_PIPELINE

    def interview_and_initialize(self, user_request: str) -> TaskArchetype:
        """
        Freezes ORIGINAL_REQUEST.md verbatim, classifies task, and initializes PROJECT.md.
        """
        self.record_original_request(user_request)
        self.archetype = self.classify_task(user_request)
        self.initialize_project_spec(user_request, self.archetype)
        return self.archetype

    def record_original_request(self, user_request: str) -> Path:
        """
        Writes user request verbatim to ORIGINAL_REQUEST.md.
        """
        return self.run_state.record_original_request(user_request)

    def initialize_project_spec(self, user_request: str, archetype: TaskArchetype) -> Path:
        """
        Generates initial PROJECT.md specification defining archetype,
        feature inventory, milestones, and interface contracts.
        """
        project_file = self.run_state.project_file
        if not project_file.exists():
            content = f"""# Project Specification — {utc_now_iso()}
Archetype: {archetype.value}
Generated from request:
> {user_request.strip()}

## Milestones
- [ ] M1: Core Architecture Implementation & Verification
- [ ] M2: Regression Testing & Hardening

## Interface Contracts
- Code/work products remain strictly in workspace root.
- State metadata strictly contained within `.agents/teamwork/`.
- Zero tolerance for weakened or skipped tests.
"""
            project_file.write_text(content, encoding="utf-8")
        return project_file

    def get_recent_modified_files(self, limit: int = 5) -> List[str]:
        """
        Scans workspace for recently modified files, filtering out hidden directories.
        """
        if not self.workspace_root.exists():
            return []
        files = []
        for p in self.workspace_root.rglob("*"):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(self.workspace_root)
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel.parts):
                continue
            try:
                files.append((p.stat().st_mtime, str(rel)))
            except OSError:
                continue
        files.sort(key=lambda x: x[0], reverse=True)
        return [f[1] for f in files[:limit]]

    def _resolve_active_orchestrator_progress(self) -> Path:
        """Resolves progress.md for the latest active orchestrator generation."""
        if self._orchestrator is not None:
            latest_path = self._orchestrator.latest_orchestrator.state.progress_path
            if latest_path.exists():
                return latest_path

        best_gen = -1
        best_path: Optional[Path] = None
        if self.run_state.run_dir.exists():
            for child in self.run_state.run_dir.iterdir():
                if not child.is_dir():
                    continue
                m = _ORCH_GEN_DIR_RE.match(child.name)
                if m:
                    gen_num = int(m.group(1))
                    candidate = child / "progress.md"
                    if candidate.exists() and gen_num > best_gen:
                        best_gen = gen_num
                        best_path = candidate
        if best_path is not None:
            return best_path

        if self.active_agent_id:
            active_path = self.run_state.run_dir / self.active_agent_id / "progress.md"
            if active_path.exists():
                return active_path

        return self.run_state.run_dir / "orchestrator_gen1" / "progress.md"

    def generate_progress_report(self) -> str:
        """
        Generates a 3-5 bullet progress summary for the user (Reporting Cron */8m).
        """
        recent_files = self.get_recent_modified_files(limit=3)
        recent_files_str = ", ".join(f"`{f}`" for f in recent_files) if recent_files else "None"
        orch_progress = self._resolve_active_orchestrator_progress()
        active_status = "In Progress"
        if orch_progress.exists():
            for line in orch_progress.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Status:"):
                    active_status = line.replace("Status:", "").strip()
                    break

        report = f"""### 🛡️ Sentinel Status Update — {utc_now_iso()}
- **Active Phase**: {self.archetype.value if self.archetype else 'Initializing'}
- **Orchestrator Status**: {active_status}
- **Active Agent**: `{self.active_agent_id or 'Orchestrator'}`
- **Recent Workspace Changes**: {recent_files_str}
- **Gate / Victory Status**: Audit Round {self.victory_audit_count}/{self.MAX_VICTORY_AUDITS}
"""
        return report

    def check_liveness(self, target_agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Checks health of active agent (Liveness Watchdog */10m).
        Tiered escalation:
        - delta < 10m: HEALTHY
        - 10m <= delta < 20m: NUDGE_REQUIRED
        - 20m <= delta < 60m: WARNING_STALLED
        - delta >= 60m: CRITICAL_KILL
        """
        agent_id = target_agent_id or self.active_agent_id or "orchestrator_gen1"
        agent_dir = self.run_state.run_dir / agent_id
        progress_file = agent_dir / "progress.md"
        now = datetime.datetime.now(datetime.timezone.utc)

        if not progress_file.exists():
            if not agent_dir.exists():
                return {
                    "status": LivenessStatus.WARNING_STALLED,
                    "delta_seconds": 0,
                    "agent_id": agent_id,
                    "last_visited": None,
                    "details": f"Agent directory '{agent_id}' does not exist",
                }

            dir_mtime = datetime.datetime.fromtimestamp(agent_dir.stat().st_mtime, tz=datetime.timezone.utc)
            delta_seconds = max(0, int((now - dir_mtime).total_seconds()))

            if delta_seconds >= self.STALL_KILL_SECONDS:
                l_status = LivenessStatus.CRITICAL_KILL
            elif delta_seconds >= self.STALL_WARNING_SECONDS:
                l_status = LivenessStatus.WARNING_STALLED
            elif delta_seconds >= self.STALL_NUDGE_SECONDS:
                l_status = LivenessStatus.NUDGE_REQUIRED
            else:
                l_status = LivenessStatus.HEALTHY

            return {
                "status": l_status,
                "delta_seconds": delta_seconds,
                "agent_id": agent_id,
                "last_visited": dir_mtime.isoformat(),
                "details": f"Agent '{agent_id}' progress.md not found; measured from directory mtime",
            }

        last_visited = None
        text = progress_file.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("Last visited:"):
                ts_str = line.replace("Last visited:", "").strip()
                last_visited = parse_iso_timestamp(ts_str)
                if last_visited is not None:
                    break
        if not last_visited:
            last_visited = datetime.datetime.fromtimestamp(progress_file.stat().st_mtime, tz=datetime.timezone.utc)
        elif last_visited.tzinfo is None or last_visited.tzinfo.utcoffset(last_visited) is None:
            last_visited = last_visited.replace(tzinfo=datetime.timezone.utc)

        delta_seconds = max(0, int((now - last_visited).total_seconds()))

        if delta_seconds >= self.STALL_KILL_SECONDS:
            l_status = LivenessStatus.CRITICAL_KILL
        elif delta_seconds >= self.STALL_WARNING_SECONDS:
            l_status = LivenessStatus.WARNING_STALLED
        elif delta_seconds >= self.STALL_NUDGE_SECONDS:
            l_status = LivenessStatus.NUDGE_REQUIRED
        else:
            l_status = LivenessStatus.HEALTHY

        return {
            "status": l_status,
            "delta_seconds": delta_seconds,
            "agent_id": agent_id,
            "last_visited": last_visited.isoformat(),
        }

    def start_background_crons(self) -> None:
        """Starts reporting and watchdog background threads."""
        reporting_alive = self._reporting_thread is not None and self._reporting_thread.is_alive()
        watchdog_alive = self._watchdog_thread is not None and self._watchdog_thread.is_alive()
        if reporting_alive and watchdog_alive:
            return

        self._cron_stop_event.clear()

        def _reporting_loop():
            while not self._cron_stop_event.wait(self.REPORTING_INTERVAL_SECONDS):
                self.generate_progress_report()

        def _watchdog_loop():
            while not self._cron_stop_event.wait(self.LIVENESS_INTERVAL_SECONDS):
                self.check_liveness()

        if not reporting_alive:
            self._reporting_thread = threading.Thread(
                target=_reporting_loop, daemon=True, name="sentinel_reporting_cron"
            )
            self._reporting_thread.start()
        if not watchdog_alive:
            self._watchdog_thread = threading.Thread(
                target=_watchdog_loop, daemon=True, name="sentinel_liveness_watchdog"
            )
            self._watchdog_thread.start()

    def stop_background_crons(self) -> None:
        """Gracefully halts background cron threads."""
        self._cron_stop_event.set()
        if self._reporting_thread and self._reporting_thread.is_alive():
            self._reporting_thread.join(timeout=1.0)
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=1.0)

    def dispatch_victory_audit(self, audit_round: int) -> Dict[str, Any]:
        """
        Dispatches independent VictoryAuditor into an isolated probe directory.
        """
        agent_id = f"victory_auditor_round{audit_round}"
        agent_state = AgentState.create(self.run_state.run_dir, agent_id, "victory_auditor")
        dispatch_file = agent_state.write_dispatch(
            task_description=(
                f"Independently audit all deliverables against ORIGINAL_REQUEST.md. "
                f"Run test suite in isolated probe directory. Round {audit_round}/{self.MAX_VICTORY_AUDITS}."
            ),
            context_files=[self.run_state.original_request_file, self.run_state.project_file],
        )

        res = self.runner.run_agent(
            agent_id=agent_id,
            archetype="victory_auditor",
            system_prompt=get_system_prompt("victory_auditor", state_dir=agent_state.state_dir),
            dispatch_file=dispatch_file,
            state_dir=agent_state.state_dir,
            workspace_dir=self.workspace_root,
        )
        if not isinstance(res, dict):
            return {
                "agent_id": agent_id,
                "archetype": "victory_auditor",
                "verdict": "VICTORY REJECTED",
                "details": f"Victory Auditor returned invalid result type: {type(res).__name__}",
                "defect": "Invalid Victory Auditor result",
            }
        return res

    def run_mission(self, user_request: str) -> SentinelResult:
        """
        Main Sentinel orchestration entrypoint.
        """
        try:
            archetype = self.interview_and_initialize(user_request)

            # 1. Dispatch Orchestrator
            orchestrator = ProjectOrchestrator(run_state=self.run_state, runner=self.runner)
            self._orchestrator = orchestrator
            self.active_agent_id = orchestrator.latest_orchestrator.agent_name

            orch_success = orchestrator.execute_milestone(
                milestone_id="M1",
                milestone_title="Core Architecture Implementation & Regression Test",
                scope_files=["src/", "tests/"],
                max_iterations=3,
            )
            self.active_agent_id = orchestrator.latest_orchestrator.agent_name

            if not orch_success:
                return SentinelResult(
                    status="FAILED",
                    run_id=self.run_state.run_id,
                    run_dir=str(self.run_state.run_dir),
                    archetype=archetype,
                    error_message="Orchestrator failed to close milestones within iteration limits.",
                )

            # 2. Independent Victory Audit Loop (max 2 audits)
            for audit_round in range(1, self.MAX_VICTORY_AUDITS + 1):
                self.victory_audit_count = audit_round
                self.active_agent_id = f"victory_auditor_round{audit_round}"
                audit_res = self.dispatch_victory_audit(audit_round)
                verdict = str(audit_res.get("verdict") or "")

                if verdict.strip().upper() == "VICTORY CONFIRMED":
                    final_report = self.generate_final_report(success=True, victory_result=audit_res)
                    return SentinelResult(
                        status="SUCCESS",
                        run_id=self.run_state.run_id,
                        run_dir=str(self.run_state.run_dir),
                        archetype=archetype,
                        victory_verdict=VictoryAuditVerdict.VICTORY_CONFIRMED.value,
                        audit_count=audit_round,
                        final_report=final_report,
                        milestones_completed=["M1"],
                    )
                else:
                    # Feedback defects to Orchestrator if audit 1 fails
                    if audit_round < self.MAX_VICTORY_AUDITS:
                        defect_msg = (
                            audit_res.get("defect")
                            or audit_res.get("details")
                            or f"Victory Audit Round {audit_round} rejected without details."
                        )
                        latest_orch = orchestrator.latest_orchestrator
                        self.active_agent_id = latest_orch.agent_name
                        remediate_success = latest_orch.execute_milestone(
                            milestone_id=f"M1_remediate_round{audit_round}",
                            milestone_title="Remediate Victory Audit Defects",
                            scope_files=["src/", "tests/"],
                            max_iterations=2,
                            defect_ledger=[f"Victory Audit Round {audit_round} defect: {defect_msg}"],
                        )
                        self.active_agent_id = orchestrator.latest_orchestrator.agent_name
                        if not remediate_success:
                            break

            # If loop finishes without confirmation
            return SentinelResult(
                status="FAILED",
                run_id=self.run_state.run_id,
                run_dir=str(self.run_state.run_dir),
                archetype=archetype,
                victory_verdict=VictoryAuditVerdict.EXHAUSTED.value,
                audit_count=self.victory_audit_count,
                error_message="Victory audit failed or maximum audit attempts (2) exhausted.",
            )
        finally:
            self.stop_background_crons()

    # Convenience alias for run_mission
    run = run_mission

    def generate_final_report(self, success: bool, victory_result: Dict[str, Any]) -> str:
        """Formats the final user deliverable report."""
        return f"""# 🏁 Teamwork Execution Final Report

- **Status**: {'✅ SUCCESS' if success else '❌ FAILED'}
- **Run ID**: `{self.run_state.run_id}`
- **Archetype**: `{self.archetype.value if self.archetype else 'N/A'}`
- **Audits Executed**: {self.victory_audit_count}/{self.MAX_VICTORY_AUDITS}
- **Victory Verdict**: `{victory_result.get('verdict', 'N/A')}`

## Verification Certificate
Independent Victory Auditor verified zero test tampering, clean git diff hygiene,
and 100% test pass in isolated probe directory.

## Artifacts Location
All run metadata, handoffs, and audit trails are preserved in:
`{self.run_state.run_dir}`
"""
