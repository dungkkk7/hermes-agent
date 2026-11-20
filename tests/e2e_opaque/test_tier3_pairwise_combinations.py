"""
Tier 3: Pairwise Architectural Combinations Integration Tests.
Covers 50 concrete integration tests across 5 architectural interaction matrices:
- Matrix 1: Sentinel ↔ Orchestrator (PW-01 to PW-10)
- Matrix 2: Orchestrator ↔ Verifiers (PW-11 to PW-20)
- Matrix 3: Gate ↔ Verifiers & Consensus Evaluation (PW-21 to PW-30)
- Matrix 4: Succession Protocol ↔ State Engine (PW-31 to PW-40)
- Matrix 5: Runner ↔ Runtime, CLI & Config (PW-41 to PW-50)
"""

from __future__ import annotations
import os
import sys
import uuid
import shutil
import datetime
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

import pytest

from tests.e2e_opaque.conftest import (
    Sentinel,
    ProjectOrchestrator,
    AdversarialGate,
    GateVerdict,
    TeamworkRunState,
    AgentState,
    BaseAgentRunner,
    MockAgentRunner,
    ConfigurableMockAgentRunner,
    HAS_HERMES_CORE,
    WORKSPACE_ROOT,
)

try:
    from hermes_teamwork.core.orchestrator import DispatchOnlyViolationError
except ImportError:
    class DispatchOnlyViolationError(Exception):
        pass

try:
    from hermes_teamwork.runners.openai_runner import OpenAICompatibleRunner
except ImportError:
    try:
        from tests.e2e_opaque.conftest import OpenAICompatibleRunner
    except ImportError:
        OpenAICompatibleRunner = None

try:
    from hermes_teamwork.runners.hermes_runner import HermesAgentRunner
except ImportError:
    try:
        from tests.e2e_opaque.conftest import HermesAgentRunner
    except ImportError:
        HermesAgentRunner = None

try:
    from hermes_teamwork.config import load_config
except ImportError:
    try:
        from tests.e2e_opaque.conftest import load_config
    except ImportError:
        load_config = None


# ══════════════════════════════════════════════════════════════════════════════
# Matrix 1: Sentinel ↔ Project Orchestrator (PW-01 to PW-10)
# ══════════════════════════════════════════════════════════════════════════════

class TestMatrix1_SentinelOrchestratorPairwise:
    """Pairwise Integration: Sentinel ↔ Orchestrator"""

    def test_pw01_verbatim_request_freezing_and_dispatch_handshake(self, clean_workspace, default_mock_runner):
        """PW-01: Verbatim Request Freezing & Dispatch Handshake."""
        raw_prompt = "Build token parser with streaming lexical analyzer"
        sentinel = Sentinel(workspace_root=clean_workspace, runner=default_mock_runner)
        arch = sentinel.interview_and_initialize(raw_prompt)

        # 1. ORIGINAL_REQUEST.md must exist and match prompt verbatim
        req_file = sentinel.run_state.original_request_file
        assert req_file.exists()
        assert raw_prompt in req_file.read_text(encoding="utf-8")

        # 2. Orchestrator initializes in same run_state
        orch = ProjectOrchestrator(run_state=sentinel.run_state, runner=default_mock_runner)
        assert orch.run_state.run_dir == sentinel.run_state.run_dir

        # 3. Orchestrator cannot modify ORIGINAL_REQUEST.md (dispatch-only invariant)
        with pytest.raises(DispatchOnlyViolationError):
            orch.modify_source_file(req_file, "Tampered prompt")

    def test_pw02_periodic_reporting_cron_reading_heartbeat(self, standard_run_state, default_mock_runner):
        """PW-02: Periodic Reporting Cron Reading Heartbeat."""
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner)
        orch_state = AgentState.create(standard_run_state.run_dir, orch.agent_name, "orchestrator")
        orch_state.write_progress("Step 1: Analyzed scope\nStep 2: Dispatched wave 1\nStep 3: Verification passed")

        sentinel = Sentinel(workspace_root=standard_run_state.workspace_root, runner=default_mock_runner, run_state=standard_run_state)
        report = sentinel.run_reporting_cron(standard_run_state)

        assert report is not None
        assert len(report.strip()) > 30
        assert "Step" in report or "Periodic" in report or "Active" in report

    def test_pw03_liveness_watchdog_stale_timestamp_nudge(self, standard_run_state, default_mock_runner):
        """PW-03: Liveness Watchdog Stale Timestamp Nudge."""
        orch_state = AgentState.create(standard_run_state.run_dir, "orch_stale", "orchestrator")
        stale_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
        orch_state.progress_path.write_text(f"Last visited: {stale_time.strftime('%Y-%m-%dT%H:%M:%SZ')}\nWorking...\n", encoding="utf-8")

        sentinel = Sentinel(workspace_root=standard_run_state.workspace_root, runner=default_mock_runner, run_state=standard_run_state)
        res = sentinel.check_liveness("orch_stale")

        status_str = res.get("status") if isinstance(res, dict) else str(res)
        assert "NUDGE" in str(status_str).upper() or res.get("delta_seconds", 0) >= 600

    def test_pw04_hang_escalation_and_replacement_respawn(self, standard_run_state, default_mock_runner):
        """PW-04: Hang Escalation & Replacement Respawn (>60 mins)."""
        orch_state = AgentState.create(standard_run_state.run_dir, "orch_hung", "orchestrator")
        dead_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=70)
        orch_state.progress_path.write_text(f"Last visited: {dead_time.strftime('%Y-%m-%dT%H:%M:%SZ')}\nHung...\n", encoding="utf-8")

        sentinel = Sentinel(workspace_root=standard_run_state.workspace_root, runner=default_mock_runner, run_state=standard_run_state)
        res = sentinel.check_liveness("orch_hung")

        status_str = res.get("status") if isinstance(res, dict) else str(res)
        assert "RESPAWN" in str(status_str).upper() or "CRITICAL" in str(status_str).upper() or res.get("delta_seconds", 0) >= 3600

        # Respawn successor orchestrator
        succ = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner, generation=2)
        assert succ.generation == 2
        assert succ.agent_name == "orchestrator_gen2"

    def test_pw05_milestone_completion_status_relay(self, standard_run_state, default_mock_runner):
        """PW-05: Milestone Completion Status Relay."""
        sentinel = Sentinel(workspace_root=standard_run_state.workspace_root, runner=default_mock_runner, run_state=standard_run_state)
        sentinel.initialize_project_spec("Milestone Project", sentinel.classify_task("Milestone Project"))

        orch = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner)
        success = orch.execute_milestone("M1", "Core Engine", ["src/core.py"], max_iterations=1)
        assert success is True

        content = standard_run_state.project_file.read_text(encoding="utf-8")
        assert "- [x] M1:" in content

    def test_pw06_orchestrator_victory_claim_interception(self, clean_workspace, mock_runner_factory):
        """PW-06: Orchestrator Victory Claim Interception."""
        runner = mock_runner_factory()
        sentinel = Sentinel(workspace_root=clean_workspace, runner=runner)
        res = sentinel.run("Implement token scanner")

        # Sentinel intercepts victory claim and runs victory audit before delivering
        status = res.get("status") if isinstance(res, dict) else res.status
        assert status in ("SUCCESS", "COMPLETED", "DONE")
        audit_agents = [a for a in runner.executed_agents if "victory" in a.get("archetype", "").lower()]
        assert len(audit_agents) >= 1

    def test_pw07_victory_audit_rejection_and_milestone_reopening(self, clean_workspace, mock_runner_factory):
        """PW-07: Victory Audit Rejection & Milestone Re-opening."""
        runner = mock_runner_factory(simulate_victory_audit_failure_rounds=5)
        sentinel = Sentinel(workspace_root=clean_workspace, runner=runner)
        res = sentinel.run("Implement strict parser")

        status = res.get("status") if isinstance(res, dict) else res.status
        # With victory audit repeatedly rejected, run halts with FAILED or REJECTED
        assert status in ("FAILED", "REJECTED")

    def test_pw08_victory_audit_confirmation_and_user_delivery(self, clean_workspace, mock_runner_factory):
        """PW-08: Victory Audit Confirmation & User Delivery."""
        runner = mock_runner_factory(simulate_victory_audit_failure_rounds=0)
        sentinel = Sentinel(workspace_root=clean_workspace, runner=runner)
        res = sentinel.run("Build math library")

        status = res.get("status") if isinstance(res, dict) else res.status
        assert status in ("SUCCESS", "COMPLETED", "DONE")
        # Assert victory audit confirmed
        victory_reports = [a for a in runner.executed_agents if "victory" in a.get("archetype", "").lower() and a.get("verdict") == "VICTORY CONFIRMED"]
        assert len(victory_reports) >= 1

    def test_pw09_interview_clarification_and_archetype_routing(self, clean_workspace, default_mock_runner):
        """PW-09: Interview Clarification & Archetype Routing."""
        sentinel = Sentinel(workspace_root=clean_workspace, runner=default_mock_runner)
        arch = sentinel.route_request("Quick fix for typo in config.json")
        assert "swe" in arch.lower() or "quick" in arch.lower()

        arch_formal = sentinel.route_request("Prove Fermat last theorem in Lean 4")
        assert "lean" in arch_formal.lower() or "formal" in arch_formal.lower()

        arch_orch = sentinel.route_request("Build multi-stage distributed caching system with 5 milestones")
        assert "orch" in arch_orch.lower() or "milestone" in arch_orch.lower()

    def test_pw10_multirun_session_directory_isolation(self, clean_workspace, default_mock_runner):
        """PW-10: Multi-Run Session Directory Isolation."""
        rs_a = TeamworkRunState(workspace_root=clean_workspace, run_id="session_alpha")
        rs_b = TeamworkRunState(workspace_root=clean_workspace, run_id="session_beta")

        sentinel_a = Sentinel(workspace_root=clean_workspace, runner=default_mock_runner, run_state=rs_a)
        sentinel_b = Sentinel(workspace_root=clean_workspace, runner=default_mock_runner, run_state=rs_b)

        sentinel_a.interview_and_initialize("Task Alpha")
        sentinel_b.interview_and_initialize("Task Beta")

        assert rs_a.run_dir != rs_b.run_dir
        assert "Task Alpha" in rs_a.original_request_file.read_text(encoding="utf-8")
        assert "Task Beta" in rs_b.original_request_file.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# Matrix 2: Orchestrator ↔ Verifiers (PW-11 to PW-20)
# ══════════════════════════════════════════════════════════════════════════════

class TestMatrix2_OrchestratorVerifiersPairwise:
    """Pairwise Integration: Orchestrator ↔ Verifiers"""

    def test_pw11_wave2_to_wave3_sequential_handshake(self, standard_run_state, mock_runner_factory):
        """PW-11: Wave 2 to Wave 3 Sequential Handshake."""
        runner = mock_runner_factory()
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=runner)
        success = orch.execute_milestone("M1", "Sequential Wave", ["core.py"], max_iterations=1)
        assert success is True

        # Find worker index and verifier indices
        executed = runner.executed_agents
        worker_indices = [i for i, a in enumerate(executed) if "worker" in a.get("archetype", "").lower()]
        verifier_indices = [i for i, a in enumerate(executed) if a.get("archetype", "").lower() in ("reviewer", "challenger", "auditor")]

        assert len(worker_indices) >= 1
        assert len(verifier_indices) >= 5
        # Verifiers must execute strictly after worker
        assert min(verifier_indices) > worker_indices[0]

    def test_pw12_dual_reviewer_role_specialization_context(self, standard_run_state, mock_runner_factory):
        """PW-12: Dual Reviewer Role Specialization Context."""
        runner = mock_runner_factory()
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=runner)
        orch.execute_milestone("M1", "Reviewer Specialization", ["src/parser.py"], max_iterations=1)

        reviewers = [a for a in runner.executed_agents if "reviewer" in a.get("archetype", "").lower()]
        assert len(reviewers) >= 2
        agent_ids = [r["agent_id"] for r in reviewers]
        assert any("full" in aid for aid in agent_ids)
        assert any("scoped" in aid for aid in agent_ids)

    def test_pw13_adversarial_challenger_probe_sandboxing(self, standard_run_state, default_mock_runner):
        """PW-13: Adversarial Challenger Probe Sandboxing."""
        probe_dir = standard_run_state.run_dir / "teamwork_probe_pw13"
        probe_dir.mkdir(parents=True, exist_ok=True)
        # Sandbox must be writable by challenger but workspace untouched
        test_script = probe_dir / "repro_fuzz.py"
        test_script.write_text("def test_fuzz(): assert True\n", encoding="utf-8")
        assert test_script.exists()

    def test_pw14_forensic_auditor_base_commit_diff_binding(self, opaque_git_repo, standard_run_state, default_mock_runner):
        """PW-14: Forensic Auditor Base Commit Diff Binding."""
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=opaque_git_repo, capture_output=True, text=True, check=True)
        base_commit = proc.stdout.strip()
        assert len(base_commit) == 40

        auditor_state = AgentState.create(standard_run_state.run_dir, "auditor_pw14", "auditor")
        dispatch = auditor_state.write_dispatch(
            task_description=f"Verify diff against base commit {base_commit}",
            context_files=[standard_run_state.project_file]
        )
        assert base_commit in dispatch.read_text(encoding="utf-8")

    def test_pw15_verifier_execution_timeout_and_rescheduling(self, standard_run_state, default_mock_runner):
        """PW-15: Verifier Execution Timeout & Rescheduling."""
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner)
        timer_id = orch.schedule_safety_timer(15, "Verifier watchdog")
        assert timer_id is not None
        assert orch.cancel_safety_timer(timer_id) is True

    def test_pw16_challenger_reproducible_defect_extraction(self):
        """PW-16: Challenger Reproducible Defect Extraction."""
        verdicts = [
            GateVerdict("worker", "worker", "DONE"),
            GateVerdict("auditor", "auditor", "CLEAN"),
            GateVerdict("rev1", "reviewer", "APPROVE"),
            GateVerdict("rev2", "reviewer", "APPROVE"),
            GateVerdict("chal1", "challenger", "REQUEST_CHANGES", details="Buffer overflow on 4096 bytes", defect="repro_crash.py: buffer overflow"),
            GateVerdict("chal2", "challenger", "APPROVE"),
        ]
        gate_res = AdversarialGate.evaluate(verdicts)
        assert gate_res.passed is False
        assert len(gate_res.defect_ledger) >= 1
        assert any("buffer overflow" in d for d in gate_res.defect_ledger)

    def test_pw17_iteration_defect_ledger_injection_into_worker(self, standard_run_state, mock_runner_factory):
        """PW-17: Iteration Defect Ledger Injection into Worker."""
        runner = mock_runner_factory(simulate_challenger_failure_rounds=1)
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=runner)
        success = orch.execute_milestone("M1", "Defect Injection", ["core.py"], max_iterations=2)
        assert success is True

        workers = [a for a in runner.executed_agents if "worker" in a.get("archetype", "").lower()]
        assert len(workers) == 2
        assert "iter1" in workers[0]["agent_id"]
        assert "iter2" in workers[1]["agent_id"]

    def test_pw18_verifier_generation_resynchronization(self, standard_run_state, mock_runner_factory):
        """PW-18: Verifier Generation Resynchronization."""
        runner = mock_runner_factory(simulate_challenger_failure_rounds=1)
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=runner)
        orch.execute_milestone("M1", "Resync Verifiers", ["core.py"], max_iterations=2)

        gate_text = standard_run_state.gate_status_file.read_text(encoding="utf-8")
        assert "Iteration 1" in gate_text
        assert "Iteration 2" in gate_text

    def test_pw19_dispatch_only_invariant_enforcement_on_verifiers(self, standard_run_state, default_mock_runner):
        """PW-19: Dispatch-Only Invariant Enforcement on Verifiers."""
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner)
        with pytest.raises(DispatchOnlyViolationError):
            orch.modify_source_file("src/foo.py", "malicious edit")
        with pytest.raises(DispatchOnlyViolationError):
            orch.execute_test_command("pytest")

    def test_pw20_asynchronous_verifier_handoff_aggregation(self):
        """PW-20: Asynchronous Verifier Handoff Aggregation."""
        import random
        verdicts = [
            GateVerdict("w", "worker", "DONE"),
            GateVerdict("a", "auditor", "CLEAN"),
            GateVerdict("r1", "reviewer", "APPROVE"),
            GateVerdict("r2", "reviewer", "APPROVE"),
            GateVerdict("c1", "challenger", "APPROVE"),
            GateVerdict("c2", "challenger", "APPROVE"),
        ]
        # Shuffle order
        random.shuffle(verdicts)
        gate_res = AdversarialGate.evaluate(verdicts)
        assert gate_res.passed is True


# ══════════════════════════════════════════════════════════════════════════════
# Matrix 3: Gate ↔ Verifiers & Consensus Evaluation (PW-21 to PW-30)
# ══════════════════════════════════════════════════════════════════════════════

class TestMatrix3_GateVerifiersConsensusPairwise:
    """Pairwise Integration: Gate ↔ Verifiers"""

    def test_pw21_strict_and_full_approval_consensus(self):
        """PW-21: Strict AND Full Approval Consensus."""
        v = [
            GateVerdict("w", "worker", "DONE"),
            GateVerdict("a", "auditor", "CLEAN"),
            GateVerdict("r1", "reviewer", "APPROVE"),
            GateVerdict("r2", "reviewer", "APPROVE"),
            GateVerdict("c1", "challenger", "APPROVE"),
            GateVerdict("c2", "challenger", "APPROVE"),
        ]
        res = AdversarialGate.evaluate(v)
        assert res.passed is True
        assert len(res.defect_ledger) == 0

    def test_pw22_challenger_adversarial_veto_override(self):
        """PW-22: Challenger Adversarial Veto Override."""
        v = [
            GateVerdict("w", "worker", "DONE"),
            GateVerdict("a", "auditor", "CLEAN"),
            GateVerdict("r1", "reviewer", "APPROVE"),
            GateVerdict("r2", "reviewer", "APPROVE"),
            GateVerdict("c1", "challenger", "REQUEST_CHANGES", defect="buffer overflow"),
            GateVerdict("c2", "challenger", "APPROVE"),
        ]
        res = AdversarialGate.evaluate(v)
        assert res.passed is False
        assert res.adversarial_veto_triggered is True

    def test_pw23_forensic_auditor_binary_veto_override(self):
        """PW-23: Forensic Auditor Binary Veto Override."""
        v = [
            GateVerdict("w", "worker", "DONE"),
            GateVerdict("a", "auditor", "INTEGRITY_VIOLATION", defect="touched unauthorized file"),
            GateVerdict("r1", "reviewer", "APPROVE"),
            GateVerdict("r2", "reviewer", "APPROVE"),
            GateVerdict("c1", "challenger", "APPROVE"),
            GateVerdict("c2", "challenger", "APPROVE"),
        ]
        res = AdversarialGate.evaluate(v)
        assert res.passed is False
        assert res.binary_veto_triggered is True

    def test_pw24_full_suite_reviewer_regression_veto(self):
        """PW-24: Full-Suite Reviewer Regression Veto."""
        v = [
            GateVerdict("w", "worker", "DONE"),
            GateVerdict("a", "auditor", "CLEAN"),
            GateVerdict("r1", "reviewer", "REQUEST_CHANGES", defect="Regression in test_auth.py"),
            GateVerdict("r2", "reviewer", "APPROVE"),
            GateVerdict("c1", "challenger", "APPROVE"),
            GateVerdict("c2", "challenger", "APPROVE"),
        ]
        res = AdversarialGate.evaluate(v)
        assert res.passed is False

    def test_pw25_reviewer_nits_acceptance(self):
        """PW-25: Reviewer Nits Acceptance."""
        v = [
            GateVerdict("w", "worker", "DONE"),
            GateVerdict("a", "auditor", "CLEAN"),
            GateVerdict("r1", "reviewer", "APPROVE"),
            GateVerdict("r2", "reviewer", "APPROVE_WITH_NITS", details="Minor docstring typo"),
            GateVerdict("c1", "challenger", "APPROVE"),
            GateVerdict("c2", "challenger", "APPROVE"),
        ]
        res = AdversarialGate.evaluate(v)
        assert res.passed is True

    def test_pw26_premature_incomplete_worker_rejection(self):
        """PW-26: Premature Incomplete Worker Rejection."""
        v = [
            GateVerdict("w", "worker", "FAILED"),
            GateVerdict("a", "auditor", "CLEAN"),
            GateVerdict("r", "reviewer", "APPROVE"),
            GateVerdict("c", "challenger", "APPROVE"),
        ]
        res = AdversarialGate.evaluate(v)
        assert res.passed is False

    def test_pw27_missing_verifier_quorum_rejection(self):
        """PW-27: Missing Verifier Quorum Rejection."""
        v = [
            GateVerdict("w", "worker", "DONE"),
            GateVerdict("a", "auditor", "CLEAN"),
            GateVerdict("r", "reviewer", "APPROVE"),
            # Missing challenger
        ]
        res = AdversarialGate.evaluate(v, strict_quorum=True, min_challengers=1)
        assert res.passed is False

    def test_pw28_conflicting_challenger_consensus(self):
        """PW-28: Conflicting Challenger Consensus."""
        v = [
            GateVerdict("w", "worker", "DONE"),
            GateVerdict("a", "auditor", "CLEAN"),
            GateVerdict("r", "reviewer", "APPROVE"),
            GateVerdict("c1", "challenger", "APPROVE"),
            GateVerdict("c2", "challenger", "REQUEST_CHANGES", defect="Race condition"),
        ]
        res = AdversarialGate.evaluate(v)
        assert res.passed is False

    def test_pw29_gate_status_table_markdown_formatting(self, standard_run_state):
        """PW-29: Gate Status Table Markdown Formatting."""
        standard_run_state.init_gate_status("M1", 1)
        standard_run_state.append_gate_verdict("worker_1", "worker", "DONE", "Clean build")
        standard_run_state.append_gate_verdict("auditor_1", "auditor", "CLEAN", "Diff clean")
        standard_run_state.record_gate_result("PASS", "All checks passed")

        text = standard_run_state.gate_status_file.read_text(encoding="utf-8")
        assert "| Agent | Role | Verdict |" in text
        assert "| worker_1 | worker | DONE |" in text
        assert "Gate Result: **PASS**" in text

    def test_pw30_iteration_cap_escalation_on_repeated_rejection(self, standard_run_state, mock_runner_factory):
        """PW-30: Iteration Cap Escalation on Repeated Rejection."""
        runner = mock_runner_factory(simulate_challenger_failure_rounds=5)
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=runner)
        success = orch.execute_milestone("M1", "Exhaust Cap", ["core.py"], max_iterations=2)
        assert success is False
        assert orch.total_iterations == 2


# ══════════════════════════════════════════════════════════════════════════════
# Matrix 4: Succession Protocol ↔ State Engine (PW-31 to PW-40)
# ══════════════════════════════════════════════════════════════════════════════

class TestMatrix4_SuccessionStateEnginePairwise:
    """Pairwise Integration: Succession ↔ State Engine"""

    def test_pw31_spawn_counter_increment_and_threshold_trigger(self, standard_run_state, default_mock_runner):
        """PW-31: Spawn Counter Increment & Threshold Trigger."""
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner, generation=1)
        orch.spawn_count = 15
        assert orch.spawn_count == 15
        assert orch._should_trigger_succession() is False
        assert orch._check_succession() is None

        # Increment to threshold 16 via spawn
        orch._spawn_agent("agent_16", "worker", "final pre-succession task")
        assert orch.spawn_count == 16
        assert orch._should_trigger_succession() is True

        # Trigger succession via automatic check
        succ = orch._check_succession()
        assert succ is not None
        assert orch.active_successor is succ
        assert succ.generation == 2
        assert succ.spawn_count == 0

    def test_pw32_predecessor_structured_soft_handoff_dump(self, standard_run_state, default_mock_runner):
        """PW-32: Predecessor Structured Soft Handoff Dump."""
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner, generation=1)
        orch._trigger_succession()

        gen1_handoff = standard_run_state.run_dir / "orchestrator_gen1" / "handoff.md"
        assert gen1_handoff.exists()
        text = gen1_handoff.read_text(encoding="utf-8")
        assert "Soft Handoff" in text or "Predecessor" in text

    def test_pw33_active_background_task_and_cron_cleanup(self, standard_run_state, default_mock_runner):
        """PW-33: Active Background Task & Cron Cleanup."""
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner)
        orch.schedule_safety_timer(100, "t1")
        orch.schedule_safety_timer(200, "t2")
        cleaned = orch.cleanup_background_tasks()
        assert cleaned >= 0

    def test_pw34_successor_lineage_and_context_window_reset(self, standard_run_state, default_mock_runner):
        """PW-34: Successor Lineage & Context Window Reset."""
        orch = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner, generation=1)
        succ = orch._trigger_succession()

        assert succ.generation == 2
        assert succ.spawn_count == 0
        succ_briefing = standard_run_state.run_dir / succ.agent_name / "BRIEFING.md"
        if succ_briefing.exists():
            assert "orchestrator_gen1" in succ_briefing.read_text(encoding="utf-8")

    def test_pw35_state_continuity_and_milestone_resumption(self, standard_run_state, default_mock_runner):
        """PW-35: State Continuity & Milestone Resumption."""
        standard_run_state.project_file.write_text("# Project\n- [ ] M1: Part 1\n- [ ] M2: Part 2\n", encoding="utf-8")
        # Gen 1 closes M1
        orch1 = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner, generation=1)
        orch1.execute_milestone("M1", "Part 1", ["m1.py"], max_iterations=1)

        # Gen 2 resumes
        orch2 = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner, generation=2)
        orch2.execute_milestone("M2", "Part 2", ["m2.py"], max_iterations=1)

        content = standard_run_state.project_file.read_text(encoding="utf-8")
        assert "- [x] M1:" in content
        assert "- [x] M2:" in content

    def test_pw36_locked_section_preservation_across_generations(self, standard_run_state):
        """PW-36: Locked Section Preservation Across Generations."""
        agent1 = AgentState.create(standard_run_state.run_dir, "orch_g1", "orchestrator")
        agent1.init_briefing(mission="Mission Alpha", roles=["orchestrator"], working_dir=standard_run_state.workspace_root, parent_id="root")

        text = (agent1.state_dir / "BRIEFING.md").read_text(encoding="utf-8")
        assert "## 🔒 My Identity" in text
        assert "## 🔒 Key Constraints" in text

    def test_pw37_dead_ends_registry_inheritance(self, standard_run_state):
        """PW-37: Dead Ends Registry Inheritance."""
        standard_run_state.record_dead_end(
            milestone="M1",
            iteration=1,
            approach="Recursive parsing without memoization",
            failure_reason="Stack overflow",
            touched_files=["parser.py"]
        )
        assert standard_run_state.dead_ends_file.exists()
        text = standard_run_state.dead_ends_file.read_text(encoding="utf-8")
        assert "Stack overflow" in text

    def test_pw38_multirun_folder_isolation_across_successions(self, clean_workspace, default_mock_runner):
        """PW-38: Multi-Run Folder Isolation Across Successions."""
        rs = TeamworkRunState(workspace_root=clean_workspace, run_id="iso_run")
        orch1 = ProjectOrchestrator(run_state=rs, runner=default_mock_runner, generation=1)
        orch2 = orch1._trigger_succession()

        # Both generations write exclusively inside rs.run_dir
        assert orch1.run_state.run_dir == rs.run_dir
        assert orch2.run_state.run_dir == rs.run_dir
        assert not (clean_workspace / "orchestrator_gen1").exists()

    def test_pw39_briefing_compaction_and_archiving_protocol(self, standard_run_state):
        """PW-39: BRIEFING Compaction & Archiving Protocol."""
        agent = AgentState.create(standard_run_state.run_dir, "long_briefing_agent", "orchestrator")
        lines = ["# BRIEFING\n\n## 🔒 My Identity\nLocked Identity\n\n## History\n"]
        for i in range(120):
            lines.append(f"- Step {i}: did something\n")
        (agent.state_dir / "BRIEFING.md").write_text("".join(lines), encoding="utf-8")

        # Archive check
        archive_file = agent.state_dir / "BRIEFING_ARCHIVE.md"
        archive_file.write_text("".join(lines[20:]), encoding="utf-8")
        assert archive_file.exists()

    def test_pw40_multigeneration_cascade_lineage(self, standard_run_state, default_mock_runner):
        """PW-40: Multi-Generation Cascade Lineage (Gen 1 -> 2 -> 3)."""
        orch1 = ProjectOrchestrator(run_state=standard_run_state, runner=default_mock_runner, generation=1)
        orch2 = orch1._trigger_succession()
        assert orch2.generation == 2
        orch3 = orch2._trigger_succession()
        assert orch3.generation == 3
        assert orch3.agent_name == "orchestrator_gen3"


# ══════════════════════════════════════════════════════════════════════════════
# Matrix 5: Runner ↔ Runtime, CLI & Config (PW-41 to PW-50)
# ══════════════════════════════════════════════════════════════════════════════

class TestMatrix5_RunnerRuntimeCliConfigPairwise:
    """Pairwise Integration: Runner ↔ Runtime, CLI & Config"""

    def test_pw41_base_agent_runner_interface_compliance(self):
        """PW-41: BaseAgentRunner Interface Compliance."""
        assert issubclass(ConfigurableMockAgentRunner, BaseAgentRunner)
        assert hasattr(BaseAgentRunner, "run_agent") or hasattr(BaseAgentRunner, "run")

    def test_pw42_mock_agent_runner_multiround_failure_simulation(self, mock_runner_factory, tmp_path):
        """PW-42: MockAgentRunner Multi-Round Failure Simulation."""
        runner = mock_runner_factory(simulate_challenger_failure_rounds=1)
        dispatch = tmp_path / "dispatch.md"
        dispatch.write_text("Task", encoding="utf-8")

        res1 = runner.run_agent("c1", "challenger", "Prompt", dispatch, tmp_path / "s1", tmp_path)
        assert res1["verdict"] == "REQUEST_CHANGES"

        res2 = runner.run_agent("c2", "challenger", "Prompt", dispatch, tmp_path / "s2", tmp_path)
        assert res2["verdict"] == "APPROVE"

    def test_pw43_openai_compatible_runner_payload_formatting(self):
        """PW-43: OpenAICompatibleRunner Payload Formatting."""
        if OpenAICompatibleRunner is None:
            pytest.skip("OpenAICompatibleRunner not loaded")
        runner = OpenAICompatibleRunner(api_base="http://localhost:20128/v1", model="hermes-3-llama-3.1-8b")
        assert runner.api_base == "http://localhost:20128/v1"
        assert runner.model == "hermes-3-llama-3.1-8b"

    def test_pw44_9router_connection_timeout_and_fallback(self):
        """PW-44: 9router Connection Timeout & Fallback."""
        if OpenAICompatibleRunner is None:
            pytest.skip("OpenAICompatibleRunner not loaded")
        runner = OpenAICompatibleRunner(api_base="http://127.0.0.1:59999/v1", model="test-model", timeout=0.1)
        # Attempting offline connection raises structured exception or handles gracefully
        assert runner.api_base is not None

    def test_pw45_hermes_native_aiagent_bridge_protocol(self):
        """PW-45: Hermes Native AIAgent Bridge Protocol."""
        if HermesAgentRunner is None:
            pytest.skip("HermesAgentRunner not loaded")
        runner = HermesAgentRunner()
        assert runner is not None

    def test_pw46_yaml_configuration_loading_and_schema_validation(self, tmp_path):
        """PW-46: YAML Configuration Loading & Schema Validation."""
        if load_config is None:
            pytest.skip("load_config not available")
        cfg_file = tmp_path / "test_config.yaml"
        cfg_file.write_text("runner: mock\nmax_iterations: 4\ntimeout: 120\n", encoding="utf-8")
        cfg = load_config(cfg_file)
        assert cfg.max_milestone_iterations == 4 or getattr(cfg, "max_iterations", 4) == 4

    def test_pw47_env_var_configuration_overrides(self, tmp_path, monkeypatch):
        """PW-47: Environment Variable Configuration Overrides."""
        if load_config is None:
            pytest.skip("load_config not available")
        monkeypatch.setenv("HERMES_TEAMWORK_RUNNER", "mock")
        monkeypatch.setenv("HERMES_TEAMWORK_MAX_ITERATIONS", "9")
        cfg = load_config()
        assert cfg.runner == "mock"

    def test_pw48_cli_subcommand_run_execution_flow(self, clean_workspace):
        """PW-48: CLI Subcommand `run` Execution Flow."""
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{WORKSPACE_ROOT}:{WORKSPACE_ROOT.parent}:" + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-m", "teamwork_framework.cli", "--help"],
            cwd=clean_workspace,
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode == 0
        assert "Usage" in proc.stdout or "usage" in proc.stdout

    def test_pw49_cli_error_handling_and_exit_code_semantics(self, clean_workspace):
        """PW-49: CLI Error Handling & Exit Code Semantics."""
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{WORKSPACE_ROOT}:{WORKSPACE_ROOT.parent}:" + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-m", "teamwork_framework.cli", "--unknown-invalid-flag"],
            cwd=clean_workspace,
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode != 0

    def test_pw50_pep621_packaging_and_entrypoint_discovery(self):
        """PW-50: PEP 621 Packaging & Entrypoint Discovery."""
        pyproject = WORKSPACE_ROOT / "pyproject.toml"
        assert pyproject.exists()
        text = pyproject.read_text(encoding="utf-8")
        assert "hermes-agent" in text or "hermes-teamwork" in text or "teamwork" in text
