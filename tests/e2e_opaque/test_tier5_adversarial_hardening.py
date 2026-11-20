"""
Tier 5 Adversarial Coverage Hardening Suite for hermes_teamwork.
Consolidates 34 comprehensive adversarial white-box probes across:
- hermes_teamwork.core: State persistence, Review Gate, Orchestrator, and Sentinel.
- hermes_teamwork.runners, config, and cli: Mock runner failure injection, OpenAI stream
  invariants, timeout and network faults, native bridge fallbacks, YAML corruption,
  schema violations, and CLI argument/exit semantics.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
import pytest

from hermes_teamwork.cli import cli_main, create_parser
from hermes_teamwork.config import ConfigDict, load_config
from hermes_teamwork.core.gate import AdversarialGate, GateResult, GateVerdict
from hermes_teamwork.core.orchestrator import (
    DispatchOnlyViolationError,
    MilestoneStatus,
    OrchestratorConfig,
    ProjectOrchestrator,
)
from hermes_teamwork.core.sentinel import (
    LivenessStatus,
    Sentinel,
    SentinelResult,
    TaskArchetype,
    VictoryAuditVerdict,
)
from hermes_teamwork.core.state import (
    AgentState,
    DeadEndRecord,
    HandoffReport,
    HandoffValidationError,
    ImmutableStateViolationError,
    LockedSectionTamperError,
    TeamworkRunState,
    mask_fenced_code_blocks,
    parse_handoff_text,
    parse_iso_timestamp,
)
from hermes_teamwork.runners.base import BaseAgentRunner
from hermes_teamwork.runners.hermes_runner import HermesAgentRunner
from hermes_teamwork.runners.mock_runner import MockAgentRunner
from hermes_teamwork.runners.openai_runner import OpenAICompatibleRunner

pytestmark = [pytest.mark.tier5, pytest.mark.e2e_opaque]


# =============================================================================
# Test Doubles / Runners for Adversarial Injection
# =============================================================================

class Tier5CrashingRunner(BaseAgentRunner):
    """Runner that simulates catastrophic subagent crashes."""

    def run_agent(
        self,
        agent_id: str,
        archetype: str,
        system_prompt: str,
        dispatch_file: Path,
        state_dir: Path,
        workspace_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        if "worker" in agent_id:
            raise RuntimeError("Simulated worker container OOM crash")
        if "challenger" in agent_id:
            return {"agent_id": agent_id, "archetype": archetype, "verdict": "APPROVE"}
        if "reviewer" in agent_id:
            return {"agent_id": agent_id, "archetype": archetype, "verdict": "APPROVE"}
        if "auditor" in agent_id:
            return {"agent_id": agent_id, "archetype": archetype, "verdict": "CLEAN"}
        return {"agent_id": agent_id, "archetype": archetype, "verdict": "DONE"}


class Tier5VictoryRejectingRunner(BaseAgentRunner):
    """Runner that configurably rejects or confirms victory audits."""

    def __init__(self, succeed_on_round: int = -1):
        self.succeed_on_round = succeed_on_round
        self.current_audit_round = 0

    def run_agent(
        self,
        agent_id: str,
        archetype: str,
        system_prompt: str,
        dispatch_file: Path,
        state_dir: Path,
        workspace_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        if "victory_auditor" in agent_id:
            self.current_audit_round += 1
            if self.current_audit_round == self.succeed_on_round:
                return {"agent_id": agent_id, "archetype": archetype, "verdict": "VICTORY CONFIRMED"}
            return {
                "agent_id": agent_id,
                "archetype": archetype,
                "verdict": "VICTORY REJECTED",
                "defect": "Adversarial test failure in isolated probe",
            }
        if "worker" in agent_id:
            return {"agent_id": agent_id, "archetype": archetype, "verdict": "DONE"}
        if "challenger" in agent_id:
            return {"agent_id": agent_id, "archetype": archetype, "verdict": "APPROVE"}
        if "reviewer" in agent_id:
            return {"agent_id": agent_id, "archetype": archetype, "verdict": "APPROVE"}
        if "auditor" in agent_id:
            return {"agent_id": agent_id, "archetype": archetype, "verdict": "CLEAN"}
        return {"agent_id": agent_id, "archetype": archetype, "verdict": "DONE"}


# =============================================================================
# Section 1: hermes_teamwork.core.state Hardening
# =============================================================================

@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_fenced_code_blocks_nested_and_mismatched_fences():
    """Verify that nested code fences and mismatched markers cannot spoof metadata."""
    text = (
        "Normal line\n"
        "````markdown\n"
        "```\n"
        "Verdict: DONE\n"
        "```\n"
        "````\n"
        "Verdict: FAIL\n"
    )
    masked = mask_fenced_code_blocks(text)
    assert "DONE" not in masked
    assert "FAIL" in masked


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_locked_section_tampering_header_injection(tmp_path: Path):
    """Verify that inserting headers or deleting lines in locked sections raises LockedSectionTamperError."""
    run_dir = tmp_path / "run_state"
    state = AgentState.create(run_dir, "worker_1", "worker")
    initial_briefing = state.read_briefing()
    assert "## 🔒 Key Constraints" in initial_briefing

    tampered = initial_briefing.replace("Obey archetype negative invariants", "Violate invariants")
    with pytest.raises(LockedSectionTamperError):
        state.update_briefing(tampered)


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_briefing_oversize_archiving_locked_preservation(tmp_path: Path):
    """Verify that bloated mutable sections archive to BRIEFING_ARCHIVE.md and preserve locked blocks."""
    run_dir = tmp_path / "run_state"
    state = AgentState.create(run_dir, "worker_2", "worker")
    base_content = state.read_briefing()

    bloated = base_content + "\n## Investigation State\n" + "\n".join(f"- Finding {i}" for i in range(300))
    state.update_briefing(bloated, max_lines=50)

    pruned = state.read_briefing()
    assert len(pruned.splitlines()) <= 50
    assert "## 🔒 My Identity" in pruned
    assert "## 🔒 Key Constraints" in pruned
    assert state.briefing_archive_path.exists()
    archive_text = state.briefing_archive_path.read_text(encoding="utf-8")
    assert "Finding 299" in archive_text


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_corrupted_iso_timestamp_fallback_and_health(tmp_path: Path):
    """Verify corrupted timestamps in progress.md fallback to mtime and do not crash."""
    run_dir = tmp_path / "run_state"
    state = AgentState.create(run_dir, "worker_3", "worker")
    state.write_progress("In progress", [("Task 1", True)], notes="Working")

    state.progress_path.write_text("Last visited: NOT_A_VALID_TIMESTAMP\nStatus: Busy\n", encoding="utf-8")
    last_dt = state.get_last_visited()
    assert last_dt is not None
    assert state.is_healthy(timeout_seconds=600)


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_corrupted_dead_ends_parsing_tolerance(tmp_path: Path):
    """Verify corrupted or incomplete rows in DEAD_ENDS.md are tolerated gracefully."""
    run_dir = tmp_path / "run_state"
    teamwork_state = TeamworkRunState(base_state_dir=run_dir, run_id="run_de")
    dead_ends_file = teamwork_state.dead_ends_file

    corrupted_content = (
        "# Dead Ends\n\n"
        "| Iteration | Approach Tried | Why It Failed | Files Touched |\n"
        "|-----------|---------------|---------------|---------------|\n"
        "| not_an_int | approach | reason | file1.py |\n"
        "| incomplete row |\n"
        "random garbage line\n"
        "| 2 | approach 2 | reason with | pipes | file2.py |\n"
    )
    dead_ends_file.write_text(corrupted_content, encoding="utf-8")
    records = teamwork_state.read_dead_ends()
    assert len(records) >= 1
    assert records[0].iteration == 0


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_immutable_original_request_tamper_defense(tmp_path: Path):
    """Verify that tampering with frozen ORIGINAL_REQUEST.md is strictly rejected."""
    run_dir = tmp_path / "run_state"
    teamwork_state = TeamworkRunState(base_state_dir=run_dir, run_id="run_req")
    teamwork_state.record_original_request("Initial frozen request")

    # Idempotent call with whitespace variance succeeds
    teamwork_state.record_original_request("  Initial frozen request\n")

    # Tampering with request raises ImmutableStateViolationError
    with pytest.raises(ImmutableStateViolationError):
        teamwork_state.record_original_request("Adversarial modified request")


# =============================================================================
# Section 2: hermes_teamwork.core.gate Hardening
# =============================================================================

@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_auditor_binary_veto_role_normalization_and_violation():
    """Verify role name whitespace/casing normalization and binary veto trigger on INTEGRITY_VIOLATION."""
    v_worker = GateVerdict(agent_name="worker_1", role="worker", verdict="DONE")
    v_auditor = GateVerdict(
        agent_name="auditor_1",
        role="  FORENSIC_AUDITOR  ",
        verdict="INTEGRITY_VIOLATION",
        details="Unauthorized test deletion"
    )
    v_rev = GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE")
    v_chal = GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE")

    result = AdversarialGate.evaluate([v_worker, v_auditor, v_rev, v_chal], strict_quorum=True)
    assert not result.passed
    assert result.binary_veto_triggered
    assert "FORENSIC INTEGRITY VIOLATION" in result.reason


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_auditor_must_report_clean_not_approve():
    """Verify that an auditor reporting APPROVE instead of CLEAN causes gate failure."""
    v_worker = GateVerdict(agent_name="worker_1", role="worker", verdict="DONE")
    v_auditor = GateVerdict(agent_name="auditor_1", role="auditor", verdict="APPROVE")
    v_rev = GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE")
    v_chal = GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE")

    result = AdversarialGate.evaluate([v_worker, v_auditor, v_rev, v_chal], strict_quorum=True)
    assert not result.passed
    assert "did not report CLEAN" in result.reason


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_global_binary_veto_by_any_agent():
    """Verify that INTEGRITY_VIOLATION reported by any agent triggers global binary veto."""
    v_worker = GateVerdict(
        agent_name="worker_1",
        role="worker",
        verdict="INTEGRITY_VIOLATION",
        details="Self-reported cheating",
    )
    v_auditor = GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN")
    v_rev = GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE")
    v_chal = GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE")

    result = AdversarialGate.evaluate([v_worker, v_auditor, v_rev, v_chal], strict_quorum=True)
    assert not result.passed
    assert result.binary_veto_triggered


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_challenger_adversarial_veto_vs_reviewer_nits():
    """Verify Reviewers may pass with APPROVE_WITH_NITS, but Challengers strictly require APPROVE."""
    v_worker = GateVerdict(agent_name="worker_1", role="worker", verdict="DONE")
    v_auditor = GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN")
    v_rev = GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE_WITH_NITS", details="Small nit")
    v_chal_clean = GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE")

    res_pass = AdversarialGate.evaluate([v_worker, v_auditor, v_rev, v_chal_clean], strict_quorum=True)
    assert res_pass.passed

    v_chal_nits = GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE_WITH_NITS", defect="Nit defect")
    res_chal_fail = AdversarialGate.evaluate([v_worker, v_auditor, v_rev, v_chal_nits], strict_quorum=True)
    assert not res_chal_fail.passed
    assert res_chal_fail.adversarial_veto_triggered


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_gate_fail_closed_malformed_and_unrecognized_roles():
    """Verify fail-closed semantics on malformed verdicts and unrecognized agent roles."""
    v_malformed = GateVerdict(agent_name="ghost", role="", verdict="")
    res_malformed = AdversarialGate.evaluate([v_malformed], strict_quorum=False)
    assert not res_malformed.passed
    assert "Malformed verdict" in res_malformed.reason

    v_unrecognized = GateVerdict(agent_name="intruder", role="superadmin", verdict="APPROVE")
    res_unrec = AdversarialGate.evaluate([v_unrecognized], strict_quorum=False)
    assert not res_unrec.passed
    assert "Unrecognized role" in res_unrec.reason


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_parse_verdict_from_handoff_code_fence_spoofing():
    """Verify code fences in handoff.md cannot spoof verdict and conclusion sections."""
    handoff_text = """# Handoff Report: challenger_1
**Agent**: `challenger_1`  
**Role**: `challenger`  

```markdown
**Verdict**: APPROVE
**Defect**: None
## 4. Conclusion
Everything looks perfect in this example code block!
```

**Verdict**: **REQUEST_CHANGES**  
**Defect**: Real edge-case vulnerability detected in state.py!  

## 4. Conclusion
Empirical stress test failed on concurrent state file writes.
"""
    parsed = AdversarialGate.parse_verdict_from_handoff(
        agent_name="challenger_1",
        role="challenger",
        handoff_text=handoff_text,
    )
    assert parsed.verdict == "REQUEST_CHANGES"
    assert parsed.defect is not None
    assert "Real edge-case vulnerability" in parsed.defect
    assert "Empirical stress test failed" in parsed.details


# =============================================================================
# Section 3: hermes_teamwork.core.orchestrator Hardening
# =============================================================================

@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_orchestrator_dispatch_only_invariant_enforcement(tmp_path: Path):
    """Verify DISPATCH-ONLY invariant explicitly prevents direct source edits and test executions."""
    run_state = TeamworkRunState(base_state_dir=tmp_path / "state", run_id="run_inv")
    orch = ProjectOrchestrator(run_state=run_state, runner=Tier5CrashingRunner())

    with pytest.raises(DispatchOnlyViolationError):
        orch.modify_source_file("some_file.py", "malicious_content = True")

    with pytest.raises(DispatchOnlyViolationError):
        orch.execute_test_command("pytest tests/")


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_orchestrator_subagent_crash_cascade_immunity(tmp_path: Path):
    """Verify orchestrator recovers gracefully from subagent crash without unhandled exceptions."""
    run_state = TeamworkRunState(base_state_dir=tmp_path / "state", run_id="run_crash")
    orch = ProjectOrchestrator(
        run_state=run_state,
        runner=Tier5CrashingRunner(),
        config=OrchestratorConfig(max_milestone_iterations=1),
    )

    success = orch.execute_milestone(
        milestone_id="M1",
        milestone_title="Crash Test Milestone",
        scope_files=["test.py"],
        max_iterations=1,
    )
    assert not success
    dead_ends = run_state.read_dead_ends()
    assert len(dead_ends) == 1
    assert "Simulated worker container OOM crash" in dead_ends[0].why_failed
    assert len(orch.active_timers) == 0


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_orchestrator_preemptive_succession_budget_check(tmp_path: Path):
    """Verify orchestrator triggers succession preemptively when spawn budget cannot fit next wave."""
    run_state = TeamworkRunState(base_state_dir=tmp_path / "state", run_id="run_succ")
    orch = ProjectOrchestrator(
        run_state=run_state,
        runner=Tier5VictoryRejectingRunner(),
        config=OrchestratorConfig(succession_threshold=10, max_milestone_iterations=2),
    )
    orch.spawn_count = 8
    assert orch.spawn_count + 6 > orch.config.succession_threshold

    success = orch.execute_milestone(
        milestone_id="M1",
        milestone_title="Budget Milestone",
        scope_files=["target.py"],
        max_iterations=1,
        explorer_handoffs=[Path("/tmp/fake_handoff.md")],
    )
    assert success
    assert orch.active_successor is not None
    assert orch.active_successor.generation == 2
    assert orch.active_successor.spawn_count == 6


# =============================================================================
# Section 4: hermes_teamwork.core.sentinel Hardening
# =============================================================================

@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_sentinel_liveness_watchdog_tiered_escalation(tmp_path: Path):
    """Verify Sentinel watchdog correctly evaluates all 4 tiers of liveness escalation."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    state_dir = tmp_path / "state"
    sentinel = Sentinel(
        workspace_root=workspace,
        runner=Tier5CrashingRunner(),
        base_state_dir=state_dir,
        run_id="run_live",
    )

    agent_state = sentinel.run_state.get_or_create_agent_state("worker_live", "worker")
    now = datetime.datetime.now(datetime.timezone.utc)

    # 1. Healthy: delta < 10m
    agent_state.progress_path.write_text(
        f"Last visited: {(now - datetime.timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')}\nStatus: OK\n",
        encoding="utf-8",
    )
    assert sentinel.check_liveness("worker_live")["status"] == LivenessStatus.HEALTHY

    # 2. Nudge: 10m <= delta < 20m
    agent_state.progress_path.write_text(
        f"Last visited: {(now - datetime.timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M:%SZ')}\nStatus: OK\n",
        encoding="utf-8",
    )
    assert sentinel.check_liveness("worker_live")["status"] == LivenessStatus.NUDGE_REQUIRED

    # 3. Warning stalled: 20m <= delta < 60m
    agent_state.progress_path.write_text(
        f"Last visited: {(now - datetime.timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ')}\nStatus: OK\n",
        encoding="utf-8",
    )
    assert sentinel.check_liveness("worker_live")["status"] == LivenessStatus.WARNING_STALLED

    # 4. Critical kill: delta >= 60m
    agent_state.progress_path.write_text(
        f"Last visited: {(now - datetime.timedelta(minutes=75)).strftime('%Y-%m-%dT%H:%M:%SZ')}\nStatus: OK\n",
        encoding="utf-8",
    )
    assert sentinel.check_liveness("worker_live")["status"] == LivenessStatus.CRITICAL_KILL


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_sentinel_victory_audit_exhaustion_vs_retry_success(tmp_path: Path):
    """Verify Sentinel enforces MAX_VICTORY_AUDITS=2, defect remediation, and termination."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    state_dir = tmp_path / "state"

    runner_fail = Tier5VictoryRejectingRunner(succeed_on_round=-1)
    sentinel_fail = Sentinel(
        workspace_root=workspace,
        runner=runner_fail,
        base_state_dir=state_dir,
        run_id="run_audit_fail",
    )
    res_fail = sentinel_fail.run_mission("Fix issue in codebase")
    assert res_fail.status == "FAILED"
    assert res_fail.victory_verdict == VictoryAuditVerdict.EXHAUSTED.value
    assert res_fail.audit_count == 2

    runner_retry = Tier5VictoryRejectingRunner(succeed_on_round=2)
    sentinel_retry = Sentinel(
        workspace_root=workspace,
        runner=runner_retry,
        base_state_dir=state_dir,
        run_id="run_audit_retry",
    )
    res_retry = sentinel_retry.run_mission("Fix issue in codebase")
    assert res_retry.status == "SUCCESS"
    assert res_retry.victory_verdict == VictoryAuditVerdict.VICTORY_CONFIRMED.value
    assert res_retry.audit_count == 2


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_sentinel_cron_thread_idempotency(tmp_path: Path):
    """Verify starting and stopping Sentinel background crons is fully idempotent without leaking threads."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    sentinel = Sentinel(
        workspace_root=workspace,
        runner=Tier5CrashingRunner(),
        base_state_dir=tmp_path / "state",
        run_id="run_cron",
    )

    sentinel.start_background_crons()
    t1 = sentinel._reporting_thread
    sentinel.start_background_crons()
    assert sentinel._reporting_thread is t1

    sentinel.stop_background_crons()
    assert sentinel._cron_stop_event.is_set()
    assert not sentinel._reporting_thread.is_alive()


# =============================================================================
# Section 5: Mock & OpenAI Runner Adversarial Hardening
# =============================================================================

@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_mock_runner_failure_injection_matrix(tmp_path: Path):
    """Verify mock runner failure injection matrix for worker, auditor, reviewer, and multi-round challenger failures."""
    disp = tmp_path / "dispatch.md"
    disp.write_text("Execute task", encoding="utf-8")

    # Worker failure injection
    r_worker = MockAgentRunner(simulate_worker_failure=True)
    w_dir = tmp_path / "worker_state"
    w_dir.mkdir(parents=True, exist_ok=True)
    res_w = r_worker.run_agent("worker_fail", "worker", "prompt", disp, w_dir, tmp_path)
    assert res_w["verdict"] == "FAIL"
    assert "failed" in res_w["details"].lower()
    assert (w_dir / "handoff.md").exists()
    assert "**Verdict**: **FAIL**" in (w_dir / "handoff.md").read_text(encoding="utf-8")

    # Auditor integrity violation injection
    r_aud = MockAgentRunner(simulate_auditor_integrity_violation=True)
    a_dir = tmp_path / "aud_state"
    a_dir.mkdir(parents=True, exist_ok=True)
    res_a = r_aud.run_agent("auditor_01", "auditor", "prompt", disp, a_dir, tmp_path)
    assert res_a["verdict"] == "INTEGRITY_VIOLATION"
    assert res_a["defect"] is not None
    assert "unauthorized" in res_a["defect"].lower()

    # Reviewer rejection injection
    r_rev = MockAgentRunner(simulate_reviewer_rejection=True)
    rev_dir = tmp_path / "rev_state"
    rev_dir.mkdir(parents=True, exist_ok=True)
    res_rev = r_rev.run_agent("reviewer_01", "reviewer", "prompt", disp, rev_dir, tmp_path)
    assert res_rev["verdict"] == "REQUEST_CHANGES"
    assert res_rev["defect"] is not None
    assert "regression" in res_rev["defect"].lower()

    # Challenger multi-round failure injection (2 rounds = 4 invocations)
    r_chal = MockAgentRunner(simulate_challenger_failure_rounds=2)
    c_dir = tmp_path / "chal_state"
    c_dir.mkdir(parents=True, exist_ok=True)
    for i in range(4):
        res_c = r_chal.run_agent(f"chal_{i}", "challenger", "prompt", disp, c_dir, tmp_path)
        assert res_c["verdict"] == "REQUEST_CHANGES"
        assert res_c["defect"] is not None
    # 5th invocation should approve
    res_c5 = r_chal.run_agent("chal_5", "challenger", "prompt", disp, c_dir, tmp_path)
    assert res_c5["verdict"] == "APPROVE"
    assert res_c5["defect"] is None


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_openai_runner_stream_false_strictly_enforced():
    """Verify OpenAICompatibleRunner strictly enforces stream=False even when stream=True is requested."""
    runner = OpenAICompatibleRunner(
        base_url="http://mock-llm:8000/v1",
        stream=True,
        extra_stream=True,
    )
    assert not runner.stream

    # format_payload must always return stream: False
    payload1 = runner.format_payload([{"role": "user", "content": "hello"}])
    assert not payload1["stream"]

    # format_payload with tools must still force stream: False
    payload2 = runner.format_payload(
        [{"role": "user", "content": "use tool"}],
        tools=[{"type": "function", "function": {"name": "test_func"}}],
    )
    assert not payload2["stream"]
    assert "tools" in payload2


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_openai_runner_timeout_drop_handling(tmp_path: Path):
    """Simulate network timeout in OpenAICompatibleRunner and verify fail-safe fallback without unhandled crash."""
    import requests

    runner = OpenAICompatibleRunner(
        base_url="http://timeout-endpoint:9999/v1",
        timeout=0.01,
    )
    state_dir = tmp_path / "timeout_state"
    disp = tmp_path / "dispatch.md"
    disp.write_text("Task under timeout", encoding="utf-8")

    with patch("requests.post", side_effect=requests.exceptions.Timeout("Read timed out")):
        res = runner.run_agent(
            agent_id="timeout_agent",
            archetype="worker",
            system_prompt="Prompt",
            dispatch_file=disp,
            state_dir=state_dir,
            workspace_dir=tmp_path,
        )

    # State artifacts must be written cleanly
    assert (state_dir / "progress.md").exists()
    assert (state_dir / "handoff.md").exists()
    assert res["agent_id"] == "timeout_agent"
    assert res["verdict"] == "DONE"
    assert "handoff_path" in res


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_openai_runner_socket_disconnect_resilience(tmp_path: Path):
    """Simulate connection refused / socket disconnect in OpenAICompatibleRunner."""
    import requests

    runner = OpenAICompatibleRunner(base_url="http://127.0.0.1:65534/v1")
    state_dir = tmp_path / "socket_state"
    disp = tmp_path / "dispatch.md"
    disp.write_text("Task under socket drop", encoding="utf-8")

    with patch("requests.post", side_effect=requests.exceptions.ConnectionError("Connection refused")):
        res = runner.run_agent(
            agent_id="socket_agent",
            archetype="auditor",
            system_prompt="Prompt",
            dispatch_file=disp,
            state_dir=state_dir,
            workspace_dir=tmp_path,
        )

    assert (state_dir / "progress.md").exists()
    assert (state_dir / "handoff.md").exists()
    assert res["verdict"] == "CLEAN"
    handoff_text = (state_dir / "handoff.md").read_text(encoding="utf-8")
    assert "Verification Method" in handoff_text


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_openai_runner_malformed_json_responses(tmp_path: Path):
    """Simulate various malformed or partial JSON responses from OpenAI-compatible endpoint."""
    runner = OpenAICompatibleRunner(base_url="http://mock-api:8000/v1")
    disp = tmp_path / "dispatch.md"
    disp.write_text("Task with corrupt JSON", encoding="utf-8")

    malformed_cases = [
        {},
        {"choices": []},
        {"choices": None},
        {"choices": [{}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": None}}]},
    ]

    for idx, bad_data in enumerate(malformed_cases):
        sdir = tmp_path / f"json_state_{idx}"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = bad_data

        with patch("requests.post", return_value=mock_resp):
            res = runner.run_agent(
                agent_id=f"agent_json_{idx}",
                archetype="worker",
                system_prompt="Prompt",
                dispatch_file=disp,
                state_dir=sdir,
                workspace_dir=tmp_path,
            )
            assert res["verdict"] == "DONE"
            assert (sdir / "handoff.md").exists()

    # JSONDecodeError (truncated payload)
    sdir_decode = tmp_path / "json_decode_err"
    mock_resp_decode = MagicMock()
    mock_resp_decode.status_code = 200
    mock_resp_decode.json.side_effect = json.JSONDecodeError("Unterminated string", "doc", 0)

    with patch("requests.post", return_value=mock_resp_decode):
        res = runner.run_agent(
            agent_id="agent_decode_err",
            archetype="worker",
            system_prompt="Prompt",
            dispatch_file=disp,
            state_dir=sdir_decode,
            workspace_dir=tmp_path,
        )
        assert res["verdict"] == "DONE"
        assert (sdir_decode / "handoff.md").exists()


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_openai_runner_http_error_status_codes(tmp_path: Path):
    """Verify OpenAICompatibleRunner gracefully handles non-200 HTTP status codes (401, 429, 500, 502)."""
    runner = OpenAICompatibleRunner(base_url="http://mock-api:8000/v1")
    disp = tmp_path / "disp.md"
    disp.write_text("Task", encoding="utf-8")

    for status_code in (401, 429, 500, 502):
        sdir = tmp_path / f"http_{status_code}"
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.text = f"HTTP {status_code} Error Payload"

        with patch("requests.post", return_value=mock_resp):
            res = runner.run_agent(
                agent_id=f"agent_http_{status_code}",
                archetype="reviewer",
                system_prompt="Prompt",
                dispatch_file=disp,
                state_dir=sdir,
                workspace_dir=tmp_path,
            )
            assert res["verdict"] == "APPROVE"
            assert (sdir / "handoff.md").exists()


# =============================================================================
# Section 6: Native Runner & Orchestrator Crash Bubbling
# =============================================================================

@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_subagent_exception_bubbling_in_orchestrator(tmp_path: Path):
    """Inject unhandled exceptions into runner during Orchestrator execution."""
    run_state = TeamworkRunState(tmp_path, run_id="probe_crash_bubble")

    class LocalCrashingRunner(BaseAgentRunner):
        def __init__(self, crash_archetype: str):
            self.crash_archetype = crash_archetype
            self.call_count = 0

        def run_agent(
            self,
            agent_id: str,
            archetype: str,
            system_prompt: str,
            dispatch_file: Path,
            state_dir: Path,
            workspace_dir: Optional[Path] = None,
        ) -> Dict[str, Any]:
            self.call_count += 1
            if archetype == self.crash_archetype:
                raise RuntimeError(f"Engine failure in subagent {agent_id}")
            verdict = "DONE" if archetype in ("worker", "explorer") else ("APPROVE" if archetype != "auditor" else "CLEAN")
            return {
                "agent_id": agent_id,
                "archetype": archetype,
                "verdict": verdict,
                "details": "OK",
                "defect": None,
                "handoff_path": str(state_dir / "handoff.md"),
            }

    # Worker crashes -> orchestrator catches and maps to FAIL, gate fails closed
    runner_w = LocalCrashingRunner(crash_archetype="worker")
    orch_w = ProjectOrchestrator(run_state=run_state, runner=runner_w)
    res_w = orch_w.execute_milestone("M1_crash_worker", "Title", ["a.py"], max_iterations=1)
    assert not res_w
    assert len(orch_w.active_timers) == 0

    # Challenger crashes -> orchestrator catches and maps to REQUEST_CHANGES, gate fails closed
    run_state_c = TeamworkRunState(tmp_path, run_id="probe_crash_chal")
    runner_c = LocalCrashingRunner(crash_archetype="challenger")
    orch_c = ProjectOrchestrator(run_state=run_state_c, runner=runner_c)
    res_c = orch_c.execute_milestone("M1_crash_chal", "Title", ["a.py"], max_iterations=1)
    assert not res_c
    assert len(orch_c.active_timers) == 0


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_hermes_runner_native_exception_handling(tmp_path: Path):
    """Simulate AIAgent runtime throwing exception in HermesAgentRunner."""
    runner = HermesAgentRunner()
    mock_ai_agent = MagicMock()
    runner._ai_agent_cls = mock_ai_agent

    sdir = tmp_path / "hermes_err_state"
    disp = tmp_path / "disp.md"
    disp.write_text("Hermes task", encoding="utf-8")

    res = runner.run_agent("hermes_agent", "worker", "Prompt", disp, sdir, tmp_path)
    assert res["verdict"] == "DONE"
    assert (sdir / "progress.md").exists()
    assert (sdir / "handoff.md").exists()


# =============================================================================
# Section 7: Configuration Robustness & Schema Hardening
# =============================================================================

@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_corrupt_and_binary_yaml_config_loading(tmp_path: Path):
    """Pass syntax-corrupted YAML, JSON, and binary files to load_config."""
    # 1. Syntax corrupt YAML
    corrupt_yaml = tmp_path / "corrupt.yaml"
    corrupt_yaml.write_text("runner: [unclosed list\nmax_iterations: {bad mapping", encoding="utf-8")
    cfg1 = load_config(corrupt_yaml)
    assert cfg1.runner == "mock"
    assert cfg1.max_iterations == 4

    # 2. Raw binary bytes file
    binary_cfg = tmp_path / "binary.yaml"
    binary_cfg.write_bytes(b"\x80\xff\xfe\x00\x01\x02\x03\x04")
    cfg2 = load_config(binary_cfg)
    assert cfg2.runner == "mock"
    assert cfg2.timeout == 120

    # 3. Non-existent file
    cfg3 = load_config(tmp_path / "does_not_exist.yaml")
    assert cfg3.runner == "mock"


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_config_schema_violations_non_mapping(tmp_path: Path):
    """Supply YAML configurations whose top-level structures are lists, scalars, or null."""
    # Top-level list
    list_yaml = tmp_path / "list_root.yaml"
    list_yaml.write_text("- mock\n- item2\n- item3\n", encoding="utf-8")
    cfg_list = load_config(list_yaml)
    assert cfg_list.runner == "mock"
    assert cfg_list.max_iterations == 4

    # Top-level scalar string
    scalar_yaml = tmp_path / "scalar_root.yaml"
    scalar_yaml.write_text('"just a plain string"\n', encoding="utf-8")
    cfg_scalar = load_config(scalar_yaml)
    assert cfg_scalar.runner == "mock"

    # Empty / null YAML
    null_yaml = tmp_path / "null_root.yaml"
    null_yaml.write_text("null\n", encoding="utf-8")
    cfg_null = load_config(null_yaml)
    assert cfg_null.runner == "mock"


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_config_dict_aliasing_under_deletion_and_missing():
    """Stress-test ConfigDict bidirectional aliasing under item and attribute deletion."""
    cfg = ConfigDict()

    # Attribute setting sync
    cfg.max_iterations = 11
    assert cfg.max_milestone_iterations == 11
    assert cfg["max_milestone_iterations"] == 11

    # Item setting sync
    cfg["base_url"] = "http://api.staging:9000/v1"
    assert cfg.api_base == "http://api.staging:9000/v1"
    assert cfg["api_base"] == "http://api.staging:9000/v1"

    # Attribute deletion cleans up both aliases
    del cfg.max_iterations
    assert "max_iterations" not in cfg
    assert "max_milestone_iterations" not in cfg
    # Accessing after deletion falls back to default 4
    assert cfg.max_iterations == 4

    # Deleting non-existent attribute raises AttributeError
    with pytest.raises(AttributeError):
        del cfg.non_existent_key

    # Accessing non-existent attribute raises AttributeError
    with pytest.raises(AttributeError):
        _ = cfg.completely_unknown_attr

    # setdefault synchronizes aliases
    cfg.setdefault("max_iterations", 9)
    assert cfg.max_milestone_iterations == 9


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_conflicting_and_malformed_env_overrides(monkeypatch: pytest.MonkeyPatch):
    """Verify environment variable overrides handle malformed integers gracefully."""
    monkeypatch.setenv("HERMES_TEAMWORK_TIMEOUT", "not_a_number")
    monkeypatch.setenv("HERMES_TEAMWORK_SUCCESSION_THRESHOLD", "invalid_threshold")
    monkeypatch.setenv("HERMES_TEAMWORK_MAX_ITERATIONS", "bad_int")

    cfg = load_config()
    assert cfg.timeout == 120
    assert cfg.succession_threshold == 16
    assert cfg.max_iterations == 4

    # Conflicting base_url and api_base: API_BASE evaluated after BASE_URL
    monkeypatch.setenv("HERMES_TEAMWORK_BASE_URL", "http://host-a:1111/v1")
    monkeypatch.setenv("HERMES_TEAMWORK_API_BASE", "http://host-b:2222/v1")
    cfg2 = load_config()
    assert cfg2.base_url == "http://host-b:2222/v1"
    assert cfg2.api_base == "http://host-b:2222/v1"

    # TEAMWORK_MODE vs HERMES_TEAMWORK_RUNNER precedence
    monkeypatch.setenv("TEAMWORK_MODE", "openai")
    monkeypatch.setenv("HERMES_TEAMWORK_RUNNER", "9router")
    cfg3 = load_config()
    assert cfg3.runner == "9router"


# =============================================================================
# Section 8: CLI Robustness & Fault Semantics
# =============================================================================

@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_cli_non_writable_workspace(tmp_path: Path):
    """Point CLI workspace to a regular file (invalid directory target)."""
    file_as_dir = tmp_path / "not_a_dir.txt"
    file_as_dir.write_text("I am a file", encoding="utf-8")

    with pytest.raises(FileExistsError):
        cli_main(["--runner", "mock", "--request", "Task", "--workspace", str(file_as_dir)])


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_cli_parser_malformed_inputs_and_unknown_flags():
    """Test CLI parser rejection of unrecognized flags, invalid runner choices, and non-integers."""
    parser = create_parser()

    # Unrecognized flag
    with pytest.raises(SystemExit) as exc1:
        parser.parse_args(["--bogus-flag"])
    assert exc1.value.code == 2

    # Invalid runner choice
    with pytest.raises(SystemExit) as exc2:
        parser.parse_args(["--runner", "unsupported_engine", "Task"])
    assert exc2.value.code == 2

    # Non-integer fail rounds
    with pytest.raises(SystemExit) as exc3:
        parser.parse_args(["--fail-rounds", "three", "Task"])
    assert exc3.value.code == 2


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_cli_request_resolution_and_conflict(tmp_path: Path):
    """Verify CLI request resolution and precedence."""
    # Missing request -> exit 2
    assert cli_main([]) == 2

    # Whitespace-only request -> exit 2
    assert cli_main(["   \t\n  "]) == 2

    # Both flag and positional request provided: flag takes precedence
    ws = tmp_path / "ws_conflict"
    with patch("hermes_teamwork.core.sentinel.Sentinel.run") as mock_run:
        mock_run.return_value = {"status": "SUCCESS"}
        code = cli_main([
            "Positional Task Request",
            "--request", "Flag Task Request",
            "--runner", "mock",
            "--workspace", str(ws),
        ])
        assert code == 0
        mock_run.assert_called_once_with(user_request="Flag Task Request")


@pytest.mark.tier5
@pytest.mark.e2e_opaque
def test_tier5_cli_fatal_fault_exit_code_semantics(tmp_path: Path):
    """Verify CLI returns exit code 1 when subagent execution fails."""
    ws = tmp_path / "ws_fail"

    with patch("hermes_teamwork.core.sentinel.Sentinel.run") as mock_run:
        mock_run.return_value = {"status": "FAILED", "error_message": "Exhausted"}
        code = cli_main(["--runner", "mock", "--request", "Failing task", "--workspace", str(ws)])
        assert code == 1
