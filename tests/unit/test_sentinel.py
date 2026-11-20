"""
tests.unit.test_sentinel
~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Sentinel lifecycle manager and role prompts.
"""
import datetime
from pathlib import Path
import pytest

from hermes_teamwork.core.sentinel import (
    LivenessStatus,
    Sentinel,
    SentinelResult,
    TaskArchetype,
    VictoryAuditVerdict,
)
from hermes_teamwork.core.state import TeamworkRunState
from hermes_teamwork.prompts import (
    AUDITOR_SYSTEM_PROMPT,
    CHALLENGER_SYSTEM_PROMPT,
    EXPLORER_SYSTEM_PROMPT,
    ORCHESTRATOR_SYSTEM_PROMPT,
    REVIEWER_SYSTEM_PROMPT,
    SENTINEL_SYSTEM_PROMPT,
    VICTORY_AUDITOR_SYSTEM_PROMPT,
    WORKER_SYSTEM_PROMPT,
)
from hermes_teamwork.runners.mock_runner import MockAgentRunner


def test_sentinel_initialization(tmp_workspace: Path, mock_runner: MockAgentRunner):
    """Scenario 1: Sentinel initializes state directories and locked BRIEFING.md."""
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=mock_runner, run_id="sentinel_init_run")
    assert sentinel.run_state.run_dir.exists()
    assert sentinel.state.state_dir.exists()
    assert sentinel.state.briefing_path.exists()

    briefing = sentinel.state.read_briefing()
    assert "## 🔒 My Identity" in briefing
    assert "## 🔒 Key Constraints" in briefing
    assert "sentinel" in briefing


def test_sentinel_record_original_request_immutable(tmp_workspace: Path, mock_runner: MockAgentRunner):
    """Scenario 2: Verbatim request recording."""
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=mock_runner, run_id="sentinel_req_run")
    req_file = sentinel.record_original_request("Build high assurance module")
    assert req_file.exists()
    assert "Build high assurance module" in req_file.read_text(encoding="utf-8")


def test_sentinel_classify_task_routing(tmp_workspace: Path, mock_runner: MockAgentRunner):
    """Scenario 3: Task interview & routing table."""
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=mock_runner)

    assert sentinel.classify_task("Quick fix typo in parser") == TaskArchetype.SWE_LIGHT
    assert sentinel.classify_task("Build distributed pipeline across 5 milestones") == TaskArchetype.MILESTONE_PIPELINE
    assert sentinel.classify_task("Conduct paper review for conference") == TaskArchetype.DOCUMENT_REVIEW
    assert sentinel.classify_task("Formal proof of lemma in lean4 mathlib") == TaskArchetype.FORMAL_PROOF
    assert sentinel.classify_task("Run multi-stage pipeline conductor") == TaskArchetype.PIPELINE


def test_sentinel_reporting_cron_generation(tmp_workspace: Path, mock_runner: MockAgentRunner):
    """Scenario 4: Periodic reporting cron (*/8m) generation."""
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=mock_runner, run_id="sentinel_report_run")
    sentinel.interview_and_initialize("Implement new feature")

    # Create dummy modified workspace file
    dummy_file = tmp_workspace / "dummy_feature.py"
    dummy_file.write_text("# new code", encoding="utf-8")

    # Create dummy orchestrator progress
    orch_dir = sentinel.run_state.run_dir / "orchestrator_gen1"
    orch_dir.mkdir(parents=True, exist_ok=True)
    (orch_dir / "progress.md").write_text("# Progress\nStatus: Wave 2 Workers Active\n", encoding="utf-8")

    report = sentinel.generate_progress_report()
    assert "🛡️ Sentinel Status Update" in report
    assert "Wave 2 Workers Active" in report
    assert "dummy_feature.py" in report
    assert "Audit Round 0/2" in report


def test_sentinel_liveness_watchdog_tiered_escalation(tmp_workspace: Path, mock_runner: MockAgentRunner):
    """Scenario 5: Tiered escalation based on heartbeat delta."""
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=mock_runner, run_id="sentinel_liveness_run")
    agent_id = "worker_watchdog_test"
    agent_dir = sentinel.run_state.run_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    prog_file = agent_dir / "progress.md"

    now = datetime.datetime.now(datetime.timezone.utc)

    # 1. Delta 5 minutes -> HEALTHY (<10m)
    t_5m = (now - datetime.timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    prog_file.write_text(f"Last visited: {t_5m}\nStatus: OK\n", encoding="utf-8")
    h1 = sentinel.check_liveness(target_agent_id=agent_id)
    assert h1["status"] == LivenessStatus.HEALTHY

    # 2. Delta 15 minutes -> NUDGE_REQUIRED (10m - 20m)
    t_15m = (now - datetime.timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    prog_file.write_text(f"Last visited: {t_15m}\nStatus: OK\n", encoding="utf-8")
    h2 = sentinel.check_liveness(target_agent_id=agent_id)
    assert h2["status"] == LivenessStatus.NUDGE_REQUIRED

    # 3. Delta 30 minutes -> WARNING_STALLED (20m - 60m)
    t_30m = (now - datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    prog_file.write_text(f"Last visited: {t_30m}\nStatus: OK\n", encoding="utf-8")
    h3 = sentinel.check_liveness(target_agent_id=agent_id)
    assert h3["status"] == LivenessStatus.WARNING_STALLED

    # 4. Delta 75 minutes -> CRITICAL_KILL (>=60m)
    t_75m = (now - datetime.timedelta(minutes=75)).strftime("%Y-%m-%dT%H:%M:%SZ")
    prog_file.write_text(f"Last visited: {t_75m}\nStatus: OK\n", encoding="utf-8")
    h4 = sentinel.check_liveness(target_agent_id=agent_id)
    assert h4["status"] == LivenessStatus.CRITICAL_KILL


def test_sentinel_victory_audit_pass_single_round(tmp_workspace: Path):
    """Scenario 6: Independent Victory Audit passes on round 1."""
    runner = MockAgentRunner(simulate_victory_audit_failure_rounds=0)
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=runner, run_id="sentinel_va_pass1")

    res = sentinel.run_mission("Build robust system")
    assert res.status == "SUCCESS"
    assert res.audit_count == 1
    assert res.victory_verdict == "VICTORY CONFIRMED"
    assert "Verification Certificate" in res.final_report


def test_sentinel_victory_audit_retry_and_pass(tmp_workspace: Path):
    """Scenario 7: Round 1 fails, orchestrator remediates, Round 2 passes."""
    runner = MockAgentRunner(simulate_victory_audit_failure_rounds=1)
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=runner, run_id="sentinel_va_retry")

    res = sentinel.run_mission("Build resilient service")
    assert res.status == "SUCCESS"
    assert res.audit_count == 2
    assert res.victory_verdict == "VICTORY CONFIRMED"


def test_sentinel_victory_audit_max_exhausted(tmp_workspace: Path):
    """Scenario 8: Round 1 & Round 2 both fail -> MAX_VICTORY_AUDITS_EXCEEDED (no 3rd audit)."""
    runner = MockAgentRunner(simulate_victory_audit_failure_rounds=5)
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=runner, run_id="sentinel_va_exhaust")

    res = sentinel.run_mission("Build buggy service")
    assert res.status == "FAILED"
    assert res.audit_count == 2
    assert res.victory_verdict == "MAX_VICTORY_AUDITS_EXCEEDED"


def test_sentinel_relay_only_negative_invariant():
    """Scenario 9: Sentinel exposes zero code-editing methods and prompt enforces RELAY-ONLY."""
    assert not hasattr(Sentinel, "modify_source_file")
    assert not hasattr(Sentinel, "write_code")
    assert not hasattr(Sentinel, "execute_test_command")

    assert "RELAY-ONLY" in SENTINEL_SYSTEM_PROMPT
    assert "NEVER make technical implementation decisions" in SENTINEL_SYSTEM_PROMPT
    assert "NEVER write, edit, or create source code files" in SENTINEL_SYSTEM_PROMPT


def test_prompts_integrity_and_anti_cheating():
    """Scenario 10: All 8 prompt modules uphold strict invariants."""
    # Worker anti-cheating
    assert "ANTI-CHEATING & TEST INTEGRITY WARNING" in WORKER_SYSTEM_PROMPT
    assert "Delete, comment out, disable, or soften" in WORKER_SYSTEM_PROMPT
    assert "@unittest.skip" in WORKER_SYSTEM_PROMPT or "@pytest.mark.skip" in WORKER_SYSTEM_PROMPT
    assert "BINARY VETO" in WORKER_SYSTEM_PROMPT

    # Auditor 4 forensic checks & binary veto
    assert "Scope Breach" in AUDITOR_SYSTEM_PROMPT
    assert "Test Weakening" in AUDITOR_SYSTEM_PROMPT
    assert "Dirty Secrets & Hardcoding" in AUDITOR_SYSTEM_PROMPT
    assert "Global State & Leaks" in AUDITOR_SYSTEM_PROMPT
    assert "INTEGRITY_VIOLATION" in AUDITOR_SYSTEM_PROMPT

    # Challenger attack vectors
    assert "PROVE THE IMPLEMENTATION WRONG" in CHALLENGER_SYSTEM_PROMPT
    assert "REQUEST_CHANGES" in CHALLENGER_SYSTEM_PROMPT

    # Victory auditor isolated probe
    assert "teamwork_probe" in VICTORY_AUDITOR_SYSTEM_PROMPT
    assert "VICTORY CONFIRMED" in VICTORY_AUDITOR_SYSTEM_PROMPT
    assert "VICTORY REJECTED" in VICTORY_AUDITOR_SYSTEM_PROMPT

    # Reviewer & Explorer & Orchestrator
    assert "APPROVE_WITH_NITS" in REVIEWER_SYSTEM_PROMPT
    assert "READ-ONLY investigation" in EXPLORER_SYSTEM_PROMPT
    assert "DISPATCH-ONLY" in ORCHESTRATOR_SYSTEM_PROMPT


def test_sentinel_result_item_access_and_to_dict():
    """Ergonomic Nit: SentinelResult supports dictionary item access and to_dict()."""
    res = SentinelResult(
        status="SUCCESS",
        run_id="run_test_123",
        run_dir="/tmp/test_dir",
        archetype=TaskArchetype.SWE_LIGHT,
        victory_verdict="VICTORY CONFIRMED",
        audit_count=1,
        final_report="Mission accomplished",
        milestones_completed=["M1"],
    )

    assert res["status"] == "SUCCESS"
    assert res["run_id"] == "run_test_123"
    assert res["archetype"] == "swe_light"
    assert res.get("victory_verdict") == "VICTORY CONFIRMED"
    assert "status" in res

    d = res.to_dict()
    assert isinstance(d, dict)
    assert d["status"] == "SUCCESS"
    assert d["run_id"] == "run_test_123"
    assert d["archetype"] == "swe_light"
    assert d["audit_count"] == 1


def test_sentinel_run_alias(tmp_workspace: Path, mock_runner: MockAgentRunner):
    """Ergonomic Nit: Sentinel has run = run_mission alias."""
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=mock_runner)
    assert hasattr(sentinel, "run")
    assert sentinel.run == sentinel.run_mission


def test_sentinel_watchdog_unstarted_agent_escalation(tmp_workspace: Path, mock_runner: MockAgentRunner):
    """Defect SE-1 Fix: Sentinel watchdog must not report unstarted/dead agents as HEALTHY with delta=0."""
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=mock_runner, run_id="test_unstarted_watchdog")
    # Nonexistent agent directory
    res_nonexistent = sentinel.check_liveness("dead_unstarted_agent")
    assert res_nonexistent["status"] != LivenessStatus.HEALTHY
    assert res_nonexistent["status"] in (LivenessStatus.WARNING_STALLED, LivenessStatus.NUDGE_REQUIRED)

    # Agent directory exists but progress.md was never created, directory is old (>10m)
    agent_dir = sentinel.run_state.run_dir / "agent_no_progress"
    agent_dir.mkdir(parents=True, exist_ok=True)
    import os, time
    old_mtime = time.time() - 900  # 15 minutes ago
    os.utime(agent_dir, (old_mtime, old_mtime))

    res_old = sentinel.check_liveness("agent_no_progress")
    assert res_old["status"] == LivenessStatus.NUDGE_REQUIRED
    assert res_old["delta_seconds"] >= 600


def test_sentinel_check_liveness_naive_iso_and_date_only(tmp_workspace: Path, mock_runner: MockAgentRunner):
    """Defect SE-1b Fix: Sentinel.check_liveness handles naive ISO & date-only timestamps without TypeError."""
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=mock_runner, run_id="sentinel_naive_ts")
    ag_dir = sentinel.run_state.run_dir / "ag_naive"
    ag_dir.mkdir(parents=True, exist_ok=True)

    recent_naive = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    (ag_dir / "progress.md").write_text(f"# Progress\nLast visited: {recent_naive}\n", encoding="utf-8")
    res_naive = sentinel.check_liveness("ag_naive")
    assert res_naive["status"] == LivenessStatus.HEALTHY

    (ag_dir / "progress.md").write_text("# Progress\nLast visited: 2020-01-01\n", encoding="utf-8")
    res_date = sentinel.check_liveness("ag_naive")
    assert res_date["status"] == LivenessStatus.CRITICAL_KILL


def test_sentinel_victory_audit_defect_forwarded_to_remediation_worker(tmp_workspace: Path):
    """Victory Audit rejection defect must be forwarded to remediation worker DISPATCH.md."""
    runner = MockAgentRunner(simulate_victory_audit_failure_rounds=1)
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=runner, run_id="sentinel_va_defect_fwd")
    res = sentinel.run_mission("Build service")
    assert res.status == "SUCCESS"
    rem_dispatch = sentinel.run_state.run_dir / "worker_m1_remediate_round1_iter1" / "DISPATCH.md"
    assert rem_dispatch.exists()
    dispatch_text = rem_dispatch.read_text(encoding="utf-8")
    assert "Victory audit round 1 rejected" in dispatch_text


def test_sentinel_run_mission_stops_crons_on_runner_exception(tmp_workspace: Path):
    """Sentinel.run_mission must stop background cron threads on both fail-closed runner errors and raised exceptions."""
    import threading
    from hermes_teamwork.runners.base import BaseAgentRunner

    class BoomRunner(BaseAgentRunner):
        def run_agent(self, *args, **kwargs):
            raise RuntimeError("LLM connection reset")

    # Case 1: Runner raises during orchestrator _spawn_agent -> fail-closed FAILED + crons stopped
    sentinel1 = Sentinel(
        workspace_root=tmp_workspace,
        runner=BoomRunner(),
        run_id="sentinel_boom_crons_1",
        auto_start_crons=True,
    )
    sentinel1.start_background_crons()
    res1 = sentinel1.run_mission("Crash test")
    assert res1.status == "FAILED"
    assert [t.name for t in threading.enumerate() if t.is_alive() and t.name.startswith("sentinel_")] == []

    # Case 2: Exception raised directly in Victory Audit -> propagates + crons stopped via finally
    runner2 = MockAgentRunner()
    orig_run = runner2.run_agent

    def boom_on_va(agent_id, archetype, *args, **kwargs):
        if archetype == "victory_auditor":
            raise RuntimeError("Victory audit transport failure")
        return orig_run(agent_id, archetype, *args, **kwargs)

    runner2.run_agent = boom_on_va  # type: ignore[method-assign]
    sentinel2 = Sentinel(
        workspace_root=tmp_workspace,
        runner=runner2,
        run_id="sentinel_boom_crons_2",
        auto_start_crons=True,
    )
    with pytest.raises(RuntimeError, match="Victory audit transport failure"):
        sentinel2.run_mission("Crash test 2")

    assert [t.name for t in threading.enumerate() if t.is_alive() and t.name.startswith("sentinel_")] == []


def test_sentinel_recent_files_under_dot_prefixed_parent_and_classify_word_boundaries(
    tmp_path: Path, mock_runner: MockAgentRunner
):
    """get_recent_modified_files ignores dot-ancestors outside workspace; classify_task uses word boundaries."""
    hidden_ws = tmp_path / ".hidden_parent" / "ws"
    hidden_ws.mkdir(parents=True)
    (hidden_ws / "visible.py").write_text("x = 1\n", encoding="utf-8")
    (hidden_ws / ".git").mkdir()
    (hidden_ws / ".git" / "config").write_text("secret\n", encoding="utf-8")

    sentinel = Sentinel(workspace_root=hidden_ws, runner=mock_runner, run_id="sentinel_dot_parent")
    recent = sentinel.get_recent_modified_files()
    assert "visible.py" in recent
    assert not any(".git" in f for f in recent)

    assert sentinel.classify_task("Build adversarial universal cleaner") == TaskArchetype.MILESTONE_PIPELINE


def test_sentinel_generate_progress_report_tracks_latest_orchestrator_gen(
    tmp_workspace: Path, mock_runner: MockAgentRunner
):
    """generate_progress_report reads latest orchestrator generation and tolerates corrupt UTF-8."""
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=mock_runner, run_id="sentinel_gen2_report")
    g1 = sentinel.run_state.run_dir / "orchestrator_gen1"
    g2 = sentinel.run_state.run_dir / "orchestrator_gen2"
    g1.mkdir(parents=True, exist_ok=True)
    g2.mkdir(parents=True, exist_ok=True)
    (g1 / "progress.md").write_text("Status: Gen1 Retired\n", encoding="utf-8")
    (g2 / "progress.md").write_bytes(b"Status: Gen2 Active \xff\xfe\n")

    report = sentinel.generate_progress_report()
    assert "Gen2 Active" in report


def test_all_handoff_prompts_parseable_5_components_and_wired(tmp_workspace: Path):
    """All 6 handoff prompts align with 5-component schema and VictoryAuditor uses VICTORY_AUDITOR_SYSTEM_PROMPT."""
    from hermes_teamwork.core.gate import AdversarialGate
    from hermes_teamwork.core.state import parse_handoff_text
    from hermes_teamwork.prompts import get_system_prompt

    for role, verdict in [
        ("explorer", "DONE"),
        ("worker", "DONE"),
        ("reviewer", "APPROVE"),
        ("challenger", "REQUEST_CHANGES"),
        ("auditor", "CLEAN"),
        ("victory_auditor", "VICTORY CONFIRMED"),
    ]:
        rendered = get_system_prompt(role, state_dir=tmp_workspace / role)
        for section in [
            "## 1. Observation",
            "## 2. Logic Chain",
            "## 3. Caveats",
            "## 4. Conclusion",
            "## 5. Verification Method",
        ]:
            assert section in rendered, f"{role} prompt missing {section}"

        sample_handoff = f"""# Handoff Report: test_{role}
**Agent**: `test_{role}`
**Role**: `{role}`
**Verdict**: **{verdict}**

## 1. Observation
Observed output.
## 2. Logic Chain
Verified logic.
## 3. Caveats
No caveats.
## 4. Conclusion
Done with {verdict}.
## 5. Verification Method
pytest -v
"""
        parsed = parse_handoff_text(sample_handoff)
        assert parsed.verdict == verdict
        gv = AdversarialGate.parse_verdict_from_handoff(f"test_{role}", role, sample_handoff)
        assert gv.verdict == verdict

    captured_prompts = {}
    runner = MockAgentRunner()
    orig_run = runner.run_agent

    def spy_run(agent_id, archetype, system_prompt, dispatch_file, state_dir, workspace_dir):
        captured_prompts[archetype] = system_prompt
        return orig_run(agent_id, archetype, system_prompt, dispatch_file, state_dir, workspace_dir)

    runner.run_agent = spy_run  # type: ignore[method-assign]
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=runner, run_id="sentinel_prompt_wire")
    sentinel.dispatch_victory_audit(1)
    assert "teamwork_probe" in captured_prompts["victory_auditor"]
    assert "{state_dir}" not in captured_prompts["victory_auditor"]


def test_sentinel_rejects_not_victory_confirmed_substring(tmp_workspace: Path):
    """Reviewer 2 Nit #3: Substring 'NOT VICTORY CONFIRMED' must never satisfy victory audit."""
    runner = MockAgentRunner()
    orig_run = runner.run_agent

    def neg_victory_handler(agent_id, archetype, system_prompt, dispatch_file, state_dir, workspace_dir):
        if archetype == "victory_auditor":
            return {
                "agent_id": agent_id,
                "archetype": "victory_auditor",
                "verdict": "NOT VICTORY CONFIRMED",
                "details": "Residual defect detected.",
                "defect": "Audit rejected",
            }
        return orig_run(agent_id, archetype, system_prompt, dispatch_file, state_dir, workspace_dir)

    runner.run_agent = neg_victory_handler  # type: ignore[method-assign]
    sentinel = Sentinel(workspace_root=tmp_workspace, runner=runner, run_id="sentinel_not_vc")
    res = sentinel.run_mission("Build reliable service")
    assert res.status == "FAILED"
    assert res.audit_count == 2
    assert res.victory_verdict == VictoryAuditVerdict.EXHAUSTED.value




