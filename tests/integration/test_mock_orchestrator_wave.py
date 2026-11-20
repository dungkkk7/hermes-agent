"""
tests.integration.test_mock_orchestrator_wave
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Offline integration tests verifying multi-wave orchestrator execution,
iteration recovery loops, 2A decomposition, and succession transfer
using deterministic MockAgentRunner.

DO NOT decorate with @pytest.mark.integration so these run offline by default.
"""
from pathlib import Path
import pytest

from hermes_teamwork.core.orchestrator import (
    Milestone,
    MilestoneStatus,
    OrchestratorConfig,
    ProjectOrchestrator,
)
from hermes_teamwork.core.state import TeamworkRunState
from hermes_teamwork.runners.mock_runner import MockAgentRunner


def test_orchestrator_multi_wave_execution_happy_path(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 1: Full multi-wave orchestrator execution (Survey -> Wave 1 -> Wave 2 -> Wave 3 -> Gate PASS)."""
    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner)

    # Step 0 Survey Phase
    survey_handoffs = orch.run_survey_phase()
    assert len(survey_handoffs) == 3
    assert orch.spawn_count == 3

    # Wave execution for Milestone M1
    success = orch.execute_milestone("M1", "Core Architecture", ["src/core/"])
    assert success is True

    # 3 survey + 2 wave 1 explorers + 1 worker + 5 verifiers = 11 spawns
    assert orch.spawn_count == 11

    # Verify agent state directories and mandatory files on disk
    assert (run_state.run_dir / "explorer_m1_1" / "DISPATCH.md").exists()
    assert (run_state.run_dir / "explorer_m1_1" / "progress.md").exists()
    assert (run_state.run_dir / "explorer_m1_1" / "handoff.md").exists()

    worker_state_dir = run_state.run_dir / "worker_m1_iter1"
    assert (worker_state_dir / "DISPATCH.md").exists()
    assert (worker_state_dir / "progress.md").exists()
    worker_handoff = worker_state_dir / "handoff.md"
    assert worker_handoff.exists()
    assert "DONE" in worker_handoff.read_text(encoding="utf-8")

    assert (run_state.run_dir / "auditor_m1_iter1" / "handoff.md").exists()
    assert (run_state.run_dir / "reviewer_m1_iter1_full" / "handoff.md").exists()
    assert (run_state.run_dir / "challenger_m1_iter1_edge" / "handoff.md").exists()

    # Verify GATE_STATUS.md records PASS and contains evaluated verdicts table
    assert run_state.gate_status_file.exists()
    gate_content = run_state.gate_status_file.read_text(encoding="utf-8")
    assert "Gate Result: **PASS**" in gate_content
    assert "## Gate — Milestone M1 — Iteration 1" in gate_content
    assert "worker_m1_iter1" in gate_content
    assert "auditor_m1_iter1" in gate_content


def test_orchestrator_iteration_loop_reviewer_defect_retry_pass(run_state: TeamworkRunState):
    """Scenario 2: Reviewer defect in Iteration 1 -> Worker retry in Iteration 2 with defect feedback -> Gate pass."""
    def reviewer_defect_handler(agent_id, archetype, record):
        if archetype == "reviewer" and "iter1" in agent_id:
            state_dir = Path(record["state_dir"])
            state_dir.mkdir(parents=True, exist_ok=True)
            handoff = state_dir / "handoff.md"
            handoff.write_text(
                f"# Handoff Report: {agent_id}\n\n"
                f"**Agent**: `{agent_id}`  \n"
                f"**Role**: `reviewer`  \n"
                f"**Verdict**: **REQUEST_CHANGES**  \n"
                f"**Defect**: Missing boundary validation in API handler  \n\n"
                f"## 1. Observation\nMissing boundary validation in API handler.\n\n"
                f"## 2. Logic Chain\nInput causes unhandled exception.\n\n"
                f"## 3. Caveats\nNo caveats.\n\n"
                f"## 4. Conclusion\nFix required before approval.\n\n"
                f"## 5. Verification Method\npytest tests/\n",
                encoding="utf-8"
            )
            (state_dir / "progress.md").write_text("# Progress\nStatus: Complete\n", encoding="utf-8")
            return {
                "agent_id": agent_id,
                "archetype": archetype,
                "verdict": "REQUEST_CHANGES",
                "details": "Reviewer rejected: Missing boundary validation",
                "defect": "Missing boundary validation in API handler",
                "handoff_path": str(handoff),
            }
        return None  # Fall through to default mock runner for iter 2

    runner = MockAgentRunner(agent_handler=reviewer_defect_handler)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)

    success = orch.execute_milestone("M1", "API Endpoint", ["src/api.py"], max_iterations=3)
    assert success is True
    assert orch.total_iterations == 2

    # Verify iteration 1 failure logged to DEAD_ENDS.md
    assert run_state.dead_ends_file.exists()
    dead_ends = run_state.read_dead_ends()
    assert len(dead_ends) >= 1
    assert any("Missing boundary validation" in d.why_failed for d in dead_ends)

    # Verify iteration 2 worker received feedback in DISPATCH.md
    worker_iter2_dispatch = (run_state.run_dir / "worker_m1_iter2" / "DISPATCH.md").read_text(encoding="utf-8")
    assert "Address defects from prior iteration:" in worker_iter2_dispatch
    assert "Missing boundary validation in API handler" in worker_iter2_dispatch

    # Verify GATE_STATUS.md records both Iteration 1 (FAIL) and Iteration 2 (PASS)
    gate_content = run_state.gate_status_file.read_text(encoding="utf-8")
    assert "## Gate — Milestone M1 — Iteration 1" in gate_content
    assert "Gate Result: **FAIL**" in gate_content
    assert "## Gate — Milestone M1 — Iteration 2" in gate_content
    assert "Gate Result: **PASS**" in gate_content


def test_orchestrator_iteration_loop_challenger_falsification_retry_pass(run_state: TeamworkRunState):
    """Scenario 3: Challenger adversarial falsification in Iteration 1 -> remediation -> Gate pass in Iteration 2."""
    runner = MockAgentRunner(simulate_challenger_failure_rounds=1)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)

    success = orch.execute_milestone("M1", "Hardening", ["src/core.py"], max_iterations=3)
    assert success is True
    assert orch.total_iterations == 2

    # Iteration 1 falsification logged in DEAD_ENDS.md
    dead_ends = run_state.read_dead_ends()
    assert len(dead_ends) >= 1
    assert dead_ends[0].iteration == 1

    # GATE_STATUS records Iteration 1 FAIL and Iteration 2 PASS
    gate_content = run_state.gate_status_file.read_text(encoding="utf-8")
    assert "## Gate — Milestone M1 — Iteration 1" in gate_content
    assert "Gate Result: **FAIL**" in gate_content
    assert "## Gate — Milestone M1 — Iteration 2" in gate_content
    assert "Gate Result: **PASS**" in gate_content


def test_orchestrator_iteration_loop_auditor_integrity_veto_retry_pass(run_state: TeamworkRunState):
    """Scenario 4: Forensic Auditor binary veto in Iteration 1 -> clean audit in Iteration 2."""
    def auditor_veto_handler(agent_id, archetype, record):
        if archetype == "auditor" and "iter1" in agent_id:
            state_dir = Path(record["state_dir"])
            state_dir.mkdir(parents=True, exist_ok=True)
            handoff = state_dir / "handoff.md"
            handoff.write_text(
                f"# Handoff Report: {agent_id}\n\n"
                f"**Agent**: `{agent_id}`  \n"
                f"**Role**: `auditor`  \n"
                f"**Verdict**: **INTEGRITY_VIOLATION**  \n"
                f"**Defect**: Unauthorized touch to tests/test_security.py  \n\n"
                f"## 1. Observation\nUnauthorized test modification detected.\n\n"
                f"## 2. Logic Chain\nTest assertions weakened.\n\n"
                f"## 3. Caveats\nNo caveats.\n\n"
                f"## 4. Conclusion\nImmediate binary veto.\n\n"
                f"## 5. Verification Method\ngit diff tests/\n",
                encoding="utf-8"
            )
            (state_dir / "progress.md").write_text("# Progress\nStatus: Complete\n", encoding="utf-8")
            return {
                "agent_id": agent_id,
                "archetype": archetype,
                "verdict": "INTEGRITY_VIOLATION",
                "details": "Unauthorized touch to tests/test_security.py",
                "defect": "Unauthorized touch to tests/test_security.py",
                "handoff_path": str(handoff),
            }
        return None

    runner = MockAgentRunner(agent_handler=auditor_veto_handler)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)

    success = orch.execute_milestone("M1", "Security Boundary", ["src/sec.py"], max_iterations=3)
    assert success is True
    assert orch.total_iterations == 2

    gate_content = run_state.gate_status_file.read_text(encoding="utf-8")
    assert "FORENSIC INTEGRITY VIOLATION" in gate_content
    assert "## Gate — Milestone M1 — Iteration 2" in gate_content
    assert "Gate Result: **PASS**" in gate_content


def test_orchestrator_iteration_loop_exhaustion_and_dead_ends(run_state: TeamworkRunState):
    """Scenario 5: Repeated failures halt cleanly at max_iterations with DEAD_ENDS entries."""
    runner = MockAgentRunner(simulate_worker_failure=True)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)

    success = orch.execute_milestone("M1", "Failing Module", ["src/fail.py"], max_iterations=3)
    assert success is False
    assert orch.milestones["M1"].status == MilestoneStatus.FAILED
    assert orch.total_iterations == 3

    # DEAD_ENDS.md has 3 entries
    dead_ends = run_state.read_dead_ends()
    assert len(dead_ends) == 3

    # GATE_STATUS has 3 FAIL blocks
    gate_content = run_state.gate_status_file.read_text(encoding="utf-8")
    assert gate_content.count("Gate Result: **FAIL**") == 3


def test_orchestrator_2a_multi_milestone_decomposition(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 6: Path 2A multi-milestone decomposition runs sub-orchestrators and updates PROJECT.md."""
    run_state.project_file.write_text(
        "# Project\n"
        "- [ ] M1: Database Layer\n"
        "- [ ] M2: HTTP Service Layer\n",
        encoding="utf-8"
    )

    milestones = [
        Milestone(id="M1", title="Database Layer", scope_files=["src/db/"]),
        Milestone(id="M2", title="HTTP Service Layer", scope_files=["src/http/"]),
    ]

    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner)
    success = orch.execute_milestones_2a(milestones)
    assert success is True
    assert milestones[0].status == MilestoneStatus.DONE
    assert milestones[1].status == MilestoneStatus.DONE

    # Sub-orchestrator state folders exist
    assert (run_state.run_dir / "sub_orch_m1").exists()
    assert (run_state.run_dir / "sub_orch_m2").exists()

    # PROJECT.md checkboxes updated
    project_text = run_state.project_file.read_text(encoding="utf-8")
    assert "- [x] M1:" in project_text
    assert "- [x] M2:" in project_text


def test_orchestrator_succession_mid_wave_transfer(run_state: TeamworkRunState):
    """Scenario 7: Pre-wave succession triggers mid-milestone when spawn budget is exhausted."""
    # Succession threshold = 14
    config = OrchestratorConfig(succession_threshold=14)
    # Simulate challenger failing for 3 rounds; round 4 passes
    runner = MockAgentRunner(simulate_challenger_failure_rounds=3)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner, config=config)

    # 4 max iterations allowed
    success = orch.execute_milestone("M1", "Succession Milestone", ["src/mod.py"], max_iterations=4)
    assert success is True

    # Predecessor triggered succession before wave budget was exceeded
    assert orch.spawn_count <= 14
    assert orch.active_successor is not None
    assert orch.active_successor.generation == 2
    assert (orch.state.state_dir / "handoff.md").exists()
