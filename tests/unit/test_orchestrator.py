"""
tests.unit.test_orchestrator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Project Orchestrator (hermes_teamwork.core.orchestrator).
"""
import pytest
from pathlib import Path

from hermes_teamwork.core.orchestrator import (
    DispatchOnlyViolationError,
    Milestone,
    MilestoneStatus,
    OrchestratorConfig,
    ProjectOrchestrator,
)
from hermes_teamwork.core.state import TeamworkRunState
from hermes_teamwork.runners.mock_runner import MockAgentRunner


def test_dispatch_only_negative_invariant(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 1: DISPATCH-ONLY invariant prevents direct edits or tests."""
    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner)

    with pytest.raises(DispatchOnlyViolationError):
        orch.modify_source_file("src/main.py", "print('hello')")

    with pytest.raises(DispatchOnlyViolationError):
        orch.execute_test_command("pytest tests/")

    # Orchestrator's state files are written only in its state folder
    assert orch.state.state_dir.exists()
    assert orch.state.briefing_path.exists()


def test_step_0_survey_phase(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 2: Dispatches 3 specialized parallel explorers before decomposition."""
    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner)
    run_state.record_original_request("Implement system")

    results = orch.run_survey_phase()
    assert orch.spawn_count == 3
    assert "explorer_survey_codebase" in results
    assert "spec_miner_survey" in results
    assert "explorer_survey_tests" in results
    for r in results.values():
        assert r["verdict"] == "DONE"


def test_2a_decomposition_routing(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 3: 2A Decomposition routes multi-milestone tasks to sub-orchestrators."""
    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner)
    assert orch.should_decompose(milestone_count=3) is True

    # Initialize PROJECT.md with checkboxes
    run_state.project_file.write_text(
        "# Project\n- [ ] M1: Core Engine\n- [ ] M2: Extensions\n",
        encoding="utf-8"
    )

    milestones = [
        Milestone(id="M1", title="Core Engine", scope_files=["src/core/"]),
        Milestone(id="M2", title="Extensions", scope_files=["src/ext/"]),
    ]
    success = orch.execute_milestones_2a(milestones)
    assert success is True
    assert milestones[0].status == MilestoneStatus.DONE
    assert milestones[1].status == MilestoneStatus.DONE

    project_text = run_state.project_file.read_text(encoding="utf-8")
    assert "- [x] M1:" in project_text
    assert "- [x] M2:" in project_text


def test_2b_direct_wave_routing(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 4: 2B Direct Wave routing for single milestone."""
    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner)
    assert orch.should_decompose(milestone_count=1) is False
    assert orch.should_decompose(milestone_count=1, has_dual_tracks=True) is True


def test_3_wave_execution_model_pass(run_state: TeamworkRunState):
    """Scenario 5: 3-Wave execution model passes on iteration 1 with full consensus."""
    runner = MockAgentRunner(simulate_challenger_failure_rounds=0)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)

    success = orch.execute_milestone(
        milestone_id="M1",
        milestone_title="State & Gate",
        scope_files=["core/state.py", "core/gate.py"],
        max_iterations=3,
    )
    assert success is True

    # Check spawn counts: 2 explorers (Wave 1) + 1 worker (Wave 2) + 5 verifiers (Wave 3) = 8
    assert orch.spawn_count == 8

    # Check GATE_STATUS.md
    assert run_state.gate_status_file.exists()
    status_text = run_state.gate_status_file.read_text(encoding="utf-8")
    assert "Gate Result: **PASS**" in status_text
    assert "worker_m1_iter1" in status_text
    assert "auditor_m1_iter1" in status_text
    assert "reviewer_m1_iter1_full" in status_text
    assert "challenger_m1_iter1_edge" in status_text


def test_adversarial_rejection_and_dead_ends(run_state: TeamworkRunState):
    """Scenario 6: Challenger rejection logs to DEAD_ENDS.md, retries, and passes."""
    runner = MockAgentRunner(simulate_challenger_failure_rounds=1)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)

    success = orch.execute_milestone(
        milestone_id="M1",
        milestone_title="Adversarial Hardening",
        scope_files=["core/state.py"],
        max_iterations=3,
    )
    assert success is True

    # Round 1 failed and was recorded in DEAD_ENDS.md
    assert run_state.dead_ends_file.exists()
    dead_ends = run_state.read_dead_ends()
    assert len(dead_ends) >= 1
    assert dead_ends[0].iteration == 1
    assert "Adversarial falsification breached" in dead_ends[0].why_failed

    # Check GATE_STATUS.md has both FAIL and PASS entries
    status_text = run_state.gate_status_file.read_text(encoding="utf-8")
    assert "Gate Result: **FAIL**" in status_text
    assert "Gate Result: **PASS**" in status_text


def test_forensic_auditor_binary_veto(run_state: TeamworkRunState):
    """Scenario 7: Auditor INTEGRITY_VIOLATION halts gate immediately."""
    runner = MockAgentRunner(simulate_auditor_integrity_violation=True)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)

    success = orch.execute_milestone(
        milestone_id="M1",
        milestone_title="Tamper Test",
        scope_files=["core/gate.py"],
        max_iterations=1,
    )
    assert success is False
    status_text = run_state.gate_status_file.read_text(encoding="utf-8")
    assert "Gate Result: **FAIL**" in status_text
    assert "FORENSIC INTEGRITY VIOLATION" in status_text


def test_max_iterations_ceiling(run_state: TeamworkRunState):
    """Scenario 8: Iteration halts at max iterations and global safety ceiling."""
    runner = MockAgentRunner(simulate_worker_failure=True)
    config = OrchestratorConfig(max_milestone_iterations=3, max_overall_iterations=5)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner, config=config)

    success = orch.execute_milestone(
        milestone_id="M1",
        milestone_title="Failing Task",
        scope_files=["core/fail.py"],
    )
    assert success is False
    assert orch.total_iterations == 3


def test_crashing_subagent_fail_closed(run_state: TeamworkRunState):
    """Defect 1 Fix: Subagent runner missing verdict key must fail-closed, not pass."""
    from hermes_teamwork.runners.base import BaseAgentRunner

    class CrashingRunner(BaseAgentRunner):
        def run_agent(self, *args, **kwargs):
            return {"agent_id": kwargs.get("agent_id", "test"), "status": "crashed"}

    orch = ProjectOrchestrator(run_state=run_state, runner=CrashingRunner())
    success = orch.execute_milestone("M1", "Test Crash", ["a.py"], max_iterations=1)
    assert success is False

    # Check that verdicts in GATE_STATUS.md reflect fail-closed defaults
    gate_status_text = run_state.gate_status_file.read_text(encoding="utf-8")
    assert "| FAIL |" in gate_status_text
    assert "| REQUEST_CHANGES |" in gate_status_text
    assert "Gate Result: **FAIL**" in gate_status_text


def test_succession_binding_prevents_gen1_budget_overflow(run_state: TeamworkRunState):
    """Defect 4 Fix: Succession in execute_milestone transfers execution to successor."""
    runner = MockAgentRunner(simulate_challenger_failure_rounds=3)
    config = OrchestratorConfig(succession_threshold=14)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner, config=config)

    success = orch.execute_milestone("M1", "Succession Test", ["a.py"], max_iterations=4)
    assert success is True
    # Gen 1 must NOT exceed succession threshold of 14
    assert orch.spawn_count <= 14
    assert orch.generation == 1
    # Successor must be bound and have executed
    assert orch.active_successor is not None
    assert orch.active_successor.generation == 2
    assert orch.active_successor.spawn_count > 0
    assert orch.latest_orchestrator.generation == 2


def test_orchestrator_execute_milestone_delegates_to_active_successor(run_state: TeamworkRunState):
    """Defect SE-2 Fix: Calling execute_milestone on an orchestrator with active_successor delegates directly."""
    runner = MockAgentRunner(simulate_challenger_failure_rounds=2)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)
    orch.execute_milestone("M1", "M1 Title", ["src/"], max_iterations=3)

    assert orch.active_successor is not None
    gen1_spawns = orch.spawn_count
    assert 0 < gen1_spawns <= orch.config.succession_threshold

    # Call execute_milestone on Gen 1 again (simulating victory audit defect remediation)
    orch.execute_milestone("M1_remediate", "Remediate defects", ["src/"], max_iterations=2)

    # Gen 1 spawn count must remain unchanged; successor must have handled the milestone
    assert orch.spawn_count == gen1_spawns
    assert orch.active_successor.spawn_count > 0


def test_succession_preserves_global_iteration_defect_ledger_and_dead_ends(run_state: TeamworkRunState):
    """Gen 2 preserves global start_iteration, defect_ledger, and DEAD_ENDS.md without Iter-1 collision."""
    runner = MockAgentRunner(simulate_challenger_failure_rounds=3)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)

    ok = orch.execute_milestone("M1", "Succession Continuity", ["a.py"], max_iterations=5)
    assert ok is True
    assert orch.spawn_count == 14
    assert orch.spawn_count <= orch.config.succession_threshold
    assert orch.active_successor is not None
    assert orch.active_successor.generation == 2

    gate_text = run_state.gate_status_file.read_text(encoding="utf-8")
    assert gate_text.count("## Gate — Milestone M1 — Iteration 1") == 1
    assert "## Gate — Milestone M1 — Iteration 3" in gate_text
    assert "## Gate — Milestone M1 — Iteration 4" in gate_text

    iter3_dispatch = run_state.run_dir / "worker_m1_iter3" / "DISPATCH.md"
    assert iter3_dispatch.exists()
    dispatch_text = iter3_dispatch.read_text(encoding="utf-8")
    assert "Address defects from prior iteration:" in dispatch_text
    assert "DEAD_ENDS.md" in dispatch_text


def test_2a_sub_orchestrator_succession_isolated_and_aggregated(run_state: TeamworkRunState):
    """Path 2A sub-orchestrator succession scopes IDs to sub_orch_m1_gen2 and aggregates full chain spawns."""
    runner = MockAgentRunner(simulate_challenger_failure_rounds=3)
    config = OrchestratorConfig(succession_threshold=14)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner, config=config)

    m1 = Milestone(id="M1", title="First", scope_files=["a.py"], max_iterations=4)
    m2 = Milestone(id="M2", title="Second", scope_files=["b.py"], max_iterations=2)
    ok = orch.execute_milestones_2a([m1, m2])
    assert ok is True

    assert (run_state.run_dir / "sub_orch_m1" / "handoff.md").exists()
    assert (run_state.run_dir / "sub_orch_m1_gen2" / "BRIEFING.md").exists()
    assert m1.iteration == 4
    assert orch.spawn_count > 14


def test_orchestrator_runner_exception_and_none_fail_closed_with_timer_cleanup(run_state: TeamworkRunState):
    """Runner exceptions and None returns fail closed, record FAIL, and never leak safety timers."""
    from hermes_teamwork.runners.base import BaseAgentRunner

    class RaisingRunner(BaseAgentRunner):
        def run_agent(self, *args, **kwargs):
            raise RuntimeError("LLM connection reset")

    orch1 = ProjectOrchestrator(run_state=run_state, runner=RaisingRunner())
    assert orch1.execute_milestone("M_EXC", "Exc", ["a.py"], max_iterations=1) is False
    assert orch1.active_timers == []
    assert "Gate Result: **FAIL**" in run_state.gate_status_file.read_text(encoding="utf-8")

    class NoneRunner(BaseAgentRunner):
        def run_agent(self, *args, **kwargs):
            return None  # type: ignore[return-value]

    orch2 = ProjectOrchestrator(run_state=run_state, runner=NoneRunner())
    assert orch2.execute_milestone("M_NONE", "None", ["a.py"], max_iterations=1) is False
    assert orch2.active_timers == []

    # max_iterations=0 must return False immediately without executing waves
    orch3 = ProjectOrchestrator(run_state=run_state, runner=MockAgentRunner())
    assert orch3.execute_milestone("M_ZERO", "Zero", ["a.py"], max_iterations=0) is False
    assert orch3.spawn_count == 0


def test_orchestrator_spawn_wires_real_system_prompts(run_state: TeamworkRunState):
    """ProjectOrchestrator._spawn_agent injects real prompts from hermes_teamwork.prompts."""
    seen_prompts = {}
    runner = MockAgentRunner()
    orig_run = runner.run_agent

    def spy_run(agent_id, archetype, system_prompt, dispatch_file, state_dir, workspace_dir):
        seen_prompts[archetype] = system_prompt
        return orig_run(agent_id, archetype, system_prompt, dispatch_file, state_dir, workspace_dir)

    runner.run_agent = spy_run  # type: ignore[method-assign]
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)
    assert orch.execute_milestone("M1", "Prompt Wiring", ["a.py"], max_iterations=1) is True

    assert "READ-ONLY investigation" in seen_prompts["explorer"]
    assert "ANTI-CHEATING & TEST INTEGRITY WARNING" in seen_prompts["worker"]
    assert "APPROVE_WITH_NITS" in seen_prompts["reviewer"]
    assert "PROVE THE IMPLEMENTATION WRONG" in seen_prompts["challenger"]
    assert "INTEGRITY_VIOLATION" in seen_prompts["auditor"]
    for p in seen_prompts.values():
        assert "{state_dir}" not in p


def test_2a_enforces_max_overall_iterations_across_milestones_and_succession(run_state: TeamworkRunState):
    """Path 2A forwards _prior_iterations and enforces max_overall_iterations across milestones and succession."""
    from hermes_teamwork.runners.base import BaseAgentRunner

    class Iter1FailRunner(BaseAgentRunner):
        def run_agent(self, agent_id, archetype, system_prompt, dispatch_file, state_dir, workspace_dir):
            verdict = "DONE"
            if archetype == "auditor":
                verdict = "CLEAN"
            elif archetype == "reviewer":
                verdict = "APPROVE"
            elif archetype == "challenger":
                verdict = "REQUEST_CHANGES" if "_iter1_" in agent_id else "APPROVE"
            return {
                "agent_id": agent_id,
                "archetype": archetype,
                "verdict": verdict,
                "details": f"{agent_id} -> {verdict}",
                "defect": "Iter 1 defect" if verdict == "REQUEST_CHANGES" else None,
            }

    # Case 1: M1 consumes 2 iters, M2 consumes 1 iter then halts at max_overall_iterations=3
    config = OrchestratorConfig(max_overall_iterations=3, succession_threshold=16)
    orch = ProjectOrchestrator(run_state=run_state, runner=Iter1FailRunner(), config=config)
    m1 = Milestone(id="M1", title="First", scope_files=["a.py"], max_iterations=3)
    m2 = Milestone(id="M2", title="Second", scope_files=["b.py"], max_iterations=3)

    ok = orch.execute_milestones_2a([m1, m2])
    assert ok is False
    assert m1.status == MilestoneStatus.DONE
    assert m1.iteration == 2
    assert m2.status == MilestoneStatus.FAILED
    assert m2.iteration == 1
    assert orch.total_iterations == 3

    # Case 2: Succession between M1 and M2 still preserves global max_overall_iterations=3
    run_state2 = TeamworkRunState(workspace_root=run_state.workspace_root, run_id="run_2a_succ_cap")
    config2 = OrchestratorConfig(max_overall_iterations=3, succession_threshold=14)
    orch2 = ProjectOrchestrator(run_state=run_state2, runner=Iter1FailRunner(), config=config2)
    m1_s = Milestone(id="M1", title="First", scope_files=["a.py"], max_iterations=3)
    m2_s = Milestone(id="M2", title="Second", scope_files=["b.py"], max_iterations=3)

    ok2 = orch2.execute_milestones_2a([m1_s, m2_s])
    assert ok2 is False
    assert orch2.active_successor is not None
    assert orch2.total_iterations == 3
    assert m2_s.status == MilestoneStatus.FAILED




