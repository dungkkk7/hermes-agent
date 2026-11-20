"""
tests.unit.test_succession_protocol
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for the Succession Protocol (spawn counter, soft handoff, timer cleanup, lineage).
"""
import pytest
from pathlib import Path

from hermes_teamwork.core.orchestrator import (
    Milestone,
    MilestoneStatus,
    OrchestratorConfig,
    ProjectOrchestrator,
)
from hermes_teamwork.core.state import TeamworkRunState
from hermes_teamwork.runners.mock_runner import MockAgentRunner


def test_spawn_counter_tracking(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 1: spawn_count increments strictly by 1 for each dispatched agent."""
    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner)
    assert orch.spawn_count == 0

    orch._spawn_agent("agent_1", "explorer", "Task 1")
    assert orch.spawn_count == 1

    orch._spawn_agent("agent_2", "worker", "Task 2")
    assert orch.spawn_count == 2

    orch._spawn_agent("agent_3", "reviewer", "Task 3")
    assert orch.spawn_count == 3


def test_succession_hard_trigger_at_16(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 2: Succession trigger fires when spawn_count reaches threshold (16)."""
    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner)
    orch.spawn_count = 15
    assert orch._should_trigger_succession() is False

    orch._spawn_agent("agent_16", "worker", "Task 16")
    assert orch.spawn_count == 16
    assert orch._should_trigger_succession() is True


def test_soft_handoff_generation(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 3: Succession writes comprehensive soft handoff.md in predecessor folder."""
    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner)
    orch.milestones["M1"] = Milestone(id="M1", title="State & Gate", scope_files=["core/"], status=MilestoneStatus.DONE)
    orch.spawn_count = 16

    successor = orch._trigger_succession()
    handoff_path = orch.state.state_dir / "handoff.md"
    assert handoff_path.exists()

    content = handoff_path.read_text(encoding="utf-8")
    assert "Soft Handoff Report" in content
    assert "orchestrator_gen1" in content
    assert "gen2" in content
    assert "16 / 16 (Threshold Reached)" in content
    assert "## 1. Milestone State" in content
    assert "## 2. Active Subagents" in content
    assert "## 3. Pending Decisions & Hard Constraints" in content
    assert "## 4. Key Artifacts" in content
    assert "## 5. Concrete Next Steps for Successor" in content

    # Defect 5 Fix: Verify soft handoff parses cleanly without HandoffValidationError
    report = orch.state.parse_handoff()
    assert report.agent_name == "orchestrator_gen1"
    assert report.role == "orchestrator"
    assert report.verdict == "DONE"
    assert report.observation != ""
    assert report.logic_chain != ""
    assert report.caveats != ""
    assert report.conclusion != ""
    assert report.verification_method != ""
    assert report.remaining_work is not None


def test_active_timer_and_cron_cancellation(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 4: Succession clears all active safety timers and crons."""
    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner)
    orch.register_timer("safety_timer_worker_1")
    orch.register_timer("safety_timer_reviewer_1")
    orch.register_timer("sentinel_reporting_cron")
    assert len(orch.active_timers) == 3

    orch._trigger_succession()
    assert len(orch.active_timers) == 0


def test_successor_spawning_and_fresh_context(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 5: Successor initializes with gen N+1, clean 0/16 budget, and predecessor link."""
    orch_gen1 = ProjectOrchestrator(run_state=run_state, runner=mock_runner, generation=1)
    orch_gen1.spawn_count = 16

    orch_gen2 = orch_gen1._trigger_succession()
    assert orch_gen2.generation == 2
    assert orch_gen2.agent_name == "orchestrator_gen2"
    assert orch_gen2.spawn_count == 0  # Fresh budget
    assert orch_gen2.predecessor_handoff == orch_gen1.state.state_dir / "handoff.md"

    # Verify successor's BRIEFING.md contains lineage block
    briefing = orch_gen2.state.read_briefing()
    assert "Generation: gen2" in briefing
    assert "Predecessor:" in briefing
    assert "orchestrator_gen1" in briefing


def test_multi_generation_cascade(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """Scenario 6: Cascade across generations (Gen 1 -> Gen 2 -> Gen 3)."""
    current_orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner, generation=1)

    generations = [current_orch]
    total_spawns = 35

    for i in range(total_spawns):
        current_orch._spawn_agent(f"agent_{i+1}", "worker", f"Subtask {i+1}")
        if current_orch._should_trigger_succession():
            current_orch = current_orch._trigger_succession()
            generations.append(current_orch)

    # 35 spawns with threshold 16:
    # Gen 1: 16 spawns -> triggers succession -> Gen 2
    # Gen 2: 16 spawns -> triggers succession -> Gen 3
    # Gen 3: 3 spawns
    assert len(generations) == 3
    assert generations[0].generation == 1
    assert generations[0].spawn_count == 16
    assert generations[1].generation == 2
    assert generations[1].spawn_count == 16
    assert generations[2].generation == 3
    assert generations[2].spawn_count == 3


def test_pre_wave_succession_budget_check(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """F37: Pre-wave succession check triggers before Wave 2+3 if adding 6 spawns exceeds threshold."""
    config = OrchestratorConfig(succession_threshold=14)
    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner, config=config, generation=1)
    orch.spawn_count = 10  # 10 + 6 (wave 2 + 3) = 16 > 14

    # Execute milestone with pre-supplied empty explorer handoffs to reach pre-wave check
    success = orch.execute_milestone(
        milestone_id="M1",
        milestone_title="Pre-wave check",
        scope_files=["src/core.py"],
        max_iterations=1,
        explorer_handoffs=[],
    )
    assert success is True
    # Gen 1 halted at 10 spawns and triggered succession
    assert orch.spawn_count == 10
    assert orch.active_successor is not None
    assert orch.active_successor.generation == 2
    # Gen 2 executed Wave 2 (1 worker) + Wave 3 (5 verifiers) = 6 spawns
    assert orch.active_successor.spawn_count == 6


def test_active_subagent_safety_timer_lifecycle(run_state: TeamworkRunState):
    """F37: Safety timers are registered during subagent execution and cleared in finally block."""
    observed_timer_during_run = []

    def check_timer_handler(agent_id, archetype, record):
        timer_id = f"safety_timer_{agent_id}"
        if timer_id in orch.active_timers:
            observed_timer_during_run.append(timer_id)
        return None

    runner = MockAgentRunner(agent_handler=check_timer_handler)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)

    orch._spawn_agent("worker_timer_test", "worker", "Test timer lifecycle")

    # The timer existed during execution
    assert "safety_timer_worker_timer_test" in observed_timer_during_run
    # The timer is strictly removed afterwards
    assert "safety_timer_worker_timer_test" not in orch.active_timers
    assert len(orch.active_timers) == 0


def test_sub_orchestrator_succession_and_parent_updating(run_state: TeamworkRunState):
    """F37: Sub-orchestrator in Path 2A handles succession with scoped naming and aggregates chain spawns."""
    sub_orch = ProjectOrchestrator(
        run_state=run_state,
        runner=MockAgentRunner(),
        generation=1,
        config=OrchestratorConfig(succession_threshold=4),
        is_sub_orchestrator=True,
        sub_orchestrator_id="sub_orch_m1",
    )
    assert sub_orch.agent_name == "sub_orch_m1"
    sub_orch.spawn_count = 4

    successor = sub_orch._trigger_succession()
    assert successor.agent_name == "sub_orch_m1_gen2"
    assert successor.generation == 2
    assert successor.is_sub_orchestrator is True

    # Simulate successor performing 3 spawns
    successor.spawn_count = 3
    # Chain spawn count should sum across both generations: 4 + 3 = 7
    assert sub_orch._chain_spawn_count() == 7


def test_background_task_cleanup_simulation_on_exception(run_state: TeamworkRunState, monkeypatch: pytest.MonkeyPatch):
    """F37: Exception during milestone execution triggers active timer cleanup in catch block."""
    orch = ProjectOrchestrator(run_state=run_state, runner=MockAgentRunner())
    orch.register_timer("cron_heartbeat_test")
    orch.register_timer("safety_timer_active_01")
    assert len(orch.active_timers) == 2

    def mock_fail(*args, **kwargs):
        raise RuntimeError("Simulated runner fatal crash")

    monkeypatch.setattr(orch, "_run_wave1_explorers", mock_fail)

    # Expect exception to propagate and active_timers to be cleared
    with pytest.raises(RuntimeError, match="Simulated runner fatal crash"):
        orch.execute_milestone("M1", "Crash test", ["src/"])

    assert len(orch.active_timers) == 0


def test_lineage_continuity_and_chain_spawn_count(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """F37: Lineage traversal resolves latest_orchestrator and sums cumulative chain spawns."""
    gen1 = ProjectOrchestrator(run_state=run_state, runner=mock_runner, generation=1)
    gen1.spawn_count = 16

    gen2 = gen1._trigger_succession()
    gen2.spawn_count = 16

    gen3 = gen2._trigger_succession()
    gen3.spawn_count = 4

    # Latest orchestrator resolution
    assert gen1.latest_orchestrator == gen3
    assert gen2.latest_orchestrator == gen3
    assert gen3.latest_orchestrator == gen3

    # Cumulative chain spawns
    assert gen1._chain_spawn_count() == 36
    assert gen2._chain_spawn_count() == 20
    assert gen3._chain_spawn_count() == 4

    # Linked list predecessor handoffs
    assert gen3.predecessor_handoff == gen2.state.state_dir / "handoff.md"
    assert gen2.predecessor_handoff == gen1.state.state_dir / "handoff.md"


def test_soft_handoff_5_component_validation(run_state: TeamworkRunState, mock_runner: MockAgentRunner):
    """F37: Soft handoff markdown conforms strictly to 5-component protocol with non-empty sections."""
    orch = ProjectOrchestrator(run_state=run_state, runner=mock_runner)
    orch.milestones["M1"] = Milestone(id="M1", title="State & Gate", scope_files=["core/"], status=MilestoneStatus.DONE)
    orch.spawn_count = 16
    orch._trigger_succession()

    report = orch.state.parse_handoff()
    errors = report.validate()
    assert errors == []
    assert report.agent_name == "orchestrator_gen1"
    assert report.role == "orchestrator"
    assert report.verdict == "DONE"
    assert len(report.observation) > 0
    assert len(report.logic_chain) > 0
    assert len(report.caveats) > 0
    assert len(report.conclusion) > 0
    assert len(report.verification_method) > 0

