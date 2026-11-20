"""
hermes_teamwork.runners.mock_runner
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Deterministic MockAgentRunner for fast, offline testing of multi-agent workflows.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from hermes_teamwork.core.state import HandoffReport, utc_now_iso
from hermes_teamwork.runners.base import BaseAgentRunner


class MockAgentRunner(BaseAgentRunner):
    """
    Simulates subagent execution deterministically offline.
    """

    def __init__(
        self,
        simulate_challenger_failure_rounds: int = 0,
        simulate_auditor_integrity_violation: bool = False,
        simulate_auditor_fail: bool = False,
        simulate_worker_failure: bool = False,
        simulate_reviewer_rejection: bool = False,
        simulate_reviewer_nits: bool = False,
        simulate_victory_audit_failure_rounds: int = 0,
        agent_handler: Optional[Callable[[str, str, Dict[str, Any]], Dict[str, Any]]] = None,
    ):
        self.simulate_challenger_failure_rounds = simulate_challenger_failure_rounds
        self.simulate_auditor_integrity_violation = simulate_auditor_integrity_violation
        self.simulate_auditor_fail = simulate_auditor_fail
        self.simulate_worker_failure = simulate_worker_failure
        self.simulate_reviewer_rejection = simulate_reviewer_rejection
        self.simulate_reviewer_nits = simulate_reviewer_nits
        self.simulate_victory_audit_failure_rounds = simulate_victory_audit_failure_rounds
        self.agent_handler = agent_handler

        self.dispatched_agents: List[Dict[str, Any]] = []
        self._challenger_invocations: int = 0
        self._victory_audit_invocations: int = 0

    def run_agent(
        self,
        agent_id: str,
        archetype: str,
        system_prompt: str,
        dispatch_file: Path,
        state_dir: Path,
        workspace_dir: Path,
    ) -> Dict[str, Any]:
        """Simulates agent run, writing progress and handoff to state_dir."""
        record = {
            "agent_id": agent_id,
            "archetype": archetype,
            "dispatch_file": str(dispatch_file),
            "state_dir": str(state_dir),
            "workspace_dir": str(workspace_dir),
            "timestamp": utc_now_iso(),
        }
        self.dispatched_agents.append(record)

        # Allow custom handler override
        if self.agent_handler:
            custom_res = self.agent_handler(agent_id, archetype, record)
            if custom_res:
                return custom_res

        # Determine verdict and defect based on archetype and simulation flags
        verdict = "DONE"
        details = f"Task completed successfully by {agent_id}."
        defect: Optional[str] = None

        norm_archetype = archetype.lower()

        if norm_archetype == "worker":
            if self.simulate_worker_failure:
                verdict = "FAIL"
                details = "Worker tests failed with compilation error."
            else:
                verdict = "DONE"
                details = "Worker implemented changes and verified tests."

        elif norm_archetype == "auditor":
            if self.simulate_auditor_integrity_violation:
                verdict = "INTEGRITY_VIOLATION"
                defect = "Unauthorized test modification detected: relaxed assertion in tests."
                details = defect
            elif self.simulate_auditor_fail:
                verdict = "FAIL"
                details = "Forensic git diff check failed."
            else:
                verdict = "CLEAN"
                details = "Forensic audit passed. Clean git diff, zero scope breaches, zero test tampering."

        elif norm_archetype == "reviewer":
            if self.simulate_reviewer_rejection:
                verdict = "REQUEST_CHANGES"
                defect = "Code quality regression: Missing bounds checking in method."
                details = defect
            elif self.simulate_reviewer_nits:
                verdict = "APPROVE_WITH_NITS"
                details = "Minor docstring suggestions only. Non-blocking."
            else:
                verdict = "APPROVE"
                details = "Code review approved without objections."

        elif norm_archetype == "challenger":
            self._challenger_invocations += 1
            # In each round there are 2 challengers. So check if invocation count exceeds 2 * rounds
            threshold = self.simulate_challenger_failure_rounds * 2
            if self._challenger_invocations <= threshold:
                verdict = "REQUEST_CHANGES"
                defect = f"Adversarial falsification breached: boundary case overflow in {agent_id}."
                details = defect
            else:
                verdict = "APPROVE"
                details = "Adversarial attacks withstood. No defects found."

        elif norm_archetype == "victory_auditor":
            self._victory_audit_invocations += 1
            if self._victory_audit_invocations <= self.simulate_victory_audit_failure_rounds:
                verdict = "VICTORY REJECTED"
                defect = f"Victory audit round {self._victory_audit_invocations} rejected: residual regression found."
                details = defect
            else:
                verdict = "VICTORY CONFIRMED"
                details = "Independent victory audit verified all deliverables against ORIGINAL_REQUEST.md."

        elif norm_archetype == "explorer":
            verdict = "DONE"
            details = f"Exploration completed with evidence chains by {agent_id}."

        # Write progress.md
        progress_path = state_dir / "progress.md"
        progress_content = f"""# Progress: {agent_id}

Last visited: {utc_now_iso()}
Status: Complete
## Steps
- [x] Initialized
- [x] Executed task
- [x] Wrote handoff
"""
        progress_path.write_text(progress_content, encoding="utf-8")

        # Write handoff.md
        handoff_report = HandoffReport(
            agent_name=agent_id,
            role=archetype,
            verdict=verdict,
            observation=f"Observed task parameters and execution environment for {agent_id}.",
            logic_chain=f"Step-by-step reasoning completed for {agent_id}: verdict {verdict}.",
            caveats="No caveats.",
            conclusion=details,
            verification_method=f"Run pytest or inspection command for {agent_id}.",
            defect=defect,
        )
        handoff_path = state_dir / "handoff.md"
        handoff_path.write_text(handoff_report.render_markdown(), encoding="utf-8")

        return {
            "agent_id": agent_id,
            "archetype": archetype,
            "verdict": verdict,
            "details": details,
            "defect": defect,
            "handoff_path": str(handoff_path),
        }
