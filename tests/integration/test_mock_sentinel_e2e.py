"""
tests.integration.test_mock_sentinel_e2e
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Offline integration tests verifying Sentinel lifecycle, task interview,
background crons & watchdog, independent Victory Audit loops (pass, remediation,
and exhaustion), and relay-only negative invariants.

DO NOT decorate with @pytest.mark.integration so these run offline by default.
"""
from pathlib import Path
import pytest

from hermes_teamwork.core.sentinel import (
    LivenessStatus,
    Sentinel,
    TaskArchetype,
    VictoryAuditVerdict,
)
from hermes_teamwork.runners.mock_runner import MockAgentRunner


def test_sentinel_e2e_happy_path_victory_audit_pass(tmp_workspace: Path):
    """Scenario 1: End-to-end happy path mission with Victory Audit Round 1 confirmation."""
    runner = MockAgentRunner(simulate_victory_audit_failure_rounds=0)
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=runner, run_id="sentinel_e2e_happy")

    prompt = "Please build high-assurance user authentication module with full test coverage"
    res = sentinel.run_mission(prompt)

    assert res.status == "SUCCESS"
    assert res.victory_verdict == VictoryAuditVerdict.VICTORY_CONFIRMED.value
    assert res.audit_count == 1
    assert res.archetype == TaskArchetype.MILESTONE_PIPELINE
    assert res.milestones_completed == ["M1"]
    assert "Verification Certificate" in res.final_report

    # Invariant: ORIGINAL_REQUEST.md frozen verbatim
    assert sentinel.run_state.original_request_file.exists()
    assert prompt in sentinel.run_state.original_request_file.read_text(encoding="utf-8")
    assert sentinel.run_state.project_file.exists()

    # Victory auditor handoff exists
    auditor_handoff = sentinel.run_state.run_dir / "victory_auditor_round1" / "handoff.md"
    assert auditor_handoff.exists()
    assert "VICTORY CONFIRMED" in auditor_handoff.read_text(encoding="utf-8")

    # Background crons terminated cleanly
    if sentinel._reporting_thread:
        assert not sentinel._reporting_thread.is_alive()
    if sentinel._watchdog_thread:
        assert not sentinel._watchdog_thread.is_alive()


def test_sentinel_e2e_victory_audit_defect_remediation_and_retry(tmp_workspace: Path):
    """Scenario 2: Victory Audit Round 1 fails -> Sentinel triggers remediation milestone -> Round 2 confirms victory."""
    runner = MockAgentRunner(simulate_victory_audit_failure_rounds=1)
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=runner, run_id="sentinel_e2e_remediate")

    prompt = "Build robust distributed cache"
    res = sentinel.run_mission(prompt)

    assert res.status == "SUCCESS"
    assert res.audit_count == 2
    assert res.victory_verdict == VictoryAuditVerdict.VICTORY_CONFIRMED.value

    # Round 1 auditor rejected
    round1_handoff = (sentinel.run_state.run_dir / "victory_auditor_round1" / "handoff.md").read_text(encoding="utf-8")
    assert "VICTORY REJECTED" in round1_handoff

    # Remediation worker was dispatched with Round 1 defect
    remediation_worker_dir = sentinel.run_state.run_dir / "worker_m1_remediate_round1_iter1"
    assert remediation_worker_dir.exists()
    dispatch_text = (remediation_worker_dir / "DISPATCH.md").read_text(encoding="utf-8")
    assert "Victory Audit Round 1 defect:" in dispatch_text

    # Round 2 auditor confirmed victory
    round2_handoff = (sentinel.run_state.run_dir / "victory_auditor_round2" / "handoff.md").read_text(encoding="utf-8")
    assert "VICTORY CONFIRMED" in round2_handoff


def test_sentinel_e2e_victory_audit_max_attempts_exhausted(tmp_workspace: Path):
    """Scenario 3: Victory Audit fails both rounds -> mission halts at MAX_VICTORY_AUDITS (2) without round 3."""
    runner = MockAgentRunner(simulate_victory_audit_failure_rounds=5)
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=runner, run_id="sentinel_e2e_exhaust")

    res = sentinel.run_mission("Build faulty banking service")

    assert res.status == "FAILED"
    assert res.audit_count == 2
    assert res.victory_verdict == VictoryAuditVerdict.EXHAUSTED.value
    assert "maximum audit attempts (2) exhausted" in (res.error_message or "")

    # Hard invariant: victory_auditor_round3 must NEVER be dispatched
    assert not (sentinel.run_state.run_dir / "victory_auditor_round3").exists()


def test_sentinel_e2e_orchestrator_failure_aborts_without_victory_audit(tmp_workspace: Path):
    """Scenario 4: Orchestrator milestone failure halts mission immediately without dispatching Victory Auditor."""
    runner = MockAgentRunner(simulate_worker_failure=True)
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=runner, run_id="sentinel_e2e_orch_fail")

    res = sentinel.run_mission("Mission destined to fail in implementation")

    assert res.status == "FAILED"
    assert res.audit_count == 0
    assert res.victory_verdict is None
    assert "Orchestrator failed to close milestones" in (res.error_message or "")

    # Victory auditor was never dispatched
    assert not (sentinel.run_state.run_dir / "victory_auditor_round1").exists()


def test_sentinel_e2e_background_crons_and_watchdog_monitoring(tmp_workspace: Path, mock_runner: MockAgentRunner):
    """Scenario 5: Background reporting and watchdog threads start, report health, and stop cleanly."""
    sentinel = Sentinel(
        workspace_root=tmp_workspace,
        runner=mock_runner,
        run_id="sentinel_e2e_crons",
        auto_start_crons=False,
    )
    sentinel.interview_and_initialize("Build data pipeline")

    sentinel.start_background_crons()
    assert sentinel._reporting_thread is not None and sentinel._reporting_thread.is_alive()
    assert sentinel._watchdog_thread is not None and sentinel._watchdog_thread.is_alive()

    # Progress report generation
    report = sentinel.generate_progress_report()
    assert "🛡️ Sentinel Status Update" in report
    assert "pipeline" in report
    assert "Audit Round 0/2" in report

    # Liveness check
    liveness = sentinel.check_liveness()
    assert liveness["status"] in (
        LivenessStatus.HEALTHY,
        LivenessStatus.WARNING_STALLED,
        LivenessStatus.NUDGE_REQUIRED,
    )

    sentinel.stop_background_crons()
    assert not sentinel._reporting_thread.is_alive()
    assert not sentinel._watchdog_thread.is_alive()


def test_sentinel_e2e_task_interview_and_archetype_routing(tmp_workspace: Path, mock_runner: MockAgentRunner):
    """Scenario 6: Prompt interview classifies and routes to correct TaskArchetypes."""
    test_cases = [
        ("Quick fix typo in tokenizer regex", TaskArchetype.SWE_LIGHT),
        ("Formal proof of theorem in lean4 mathlib", TaskArchetype.FORMAL_PROOF),
        ("Conduct paper review for journal submission", TaskArchetype.DOCUMENT_REVIEW),
        ("Run multi-stage data pipeline conductor", TaskArchetype.PIPELINE),
        ("Build billing epic across multiple milestones", TaskArchetype.MILESTONE_PIPELINE),
    ]

    for idx, (prompt, expected_archetype) in enumerate(test_cases):
        run_id = f"sentinel_route_{idx}"
        sentinel = Sentinel(workspace_root=tmp_workspace, runner=mock_runner, run_id=run_id, auto_start_crons=False)
        archetype = sentinel.interview_and_initialize(prompt)
        assert archetype == expected_archetype

        # Verify ORIGINAL_REQUEST.md contains prompt
        req_text = sentinel.run_state.original_request_file.read_text(encoding="utf-8")
        assert prompt in req_text

        # Verify PROJECT.md contains archetype
        proj_text = sentinel.run_state.project_file.read_text(encoding="utf-8")
        assert archetype.value in proj_text


def test_sentinel_e2e_relay_only_negative_invariant(tmp_workspace: Path, mock_runner: MockAgentRunner):
    """Scenario 7: Relay-only negative invariant: Sentinel liaises with user and never edits code directly."""
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=mock_runner, run_id="sentinel_relay_only", auto_start_crons=False)

    # Negative invariant: Sentinel has no source editing or direct test execution methods
    assert not hasattr(sentinel, "modify_source_file")
    assert not hasattr(sentinel, "execute_test_command")
    assert not hasattr(sentinel, "debug_code")

    # Run mission and assert non-metadata files are not created in root workspace
    sentinel.run_mission("Quick fix typo in test")
    root_entries = [p.name for p in tmp_workspace.iterdir()]
    # Only '.agents' directory should be created in the workspace root
    assert root_entries == [".agents"]
