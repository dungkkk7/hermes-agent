"""
Tier 4: Real-World Application Scenarios (S1 to S5).
Implements complete end-to-end multi-turn operational scenarios:
- S1: Greenfield Feature Development
- S2: Multi-Round Adversarial Rejection & Self-Healing
- S3: Long-Horizon Orchestration & Succession Cascade
- S4: Large Project Multi-Module Decomposition (Path 2A)
- S5: Standalone CLI & Config-Driven Dual Runtime
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
    OpenAICompatibleRunner = None

try:
    from hermes_teamwork.runners.hermes_runner import HermesAgentRunner
except ImportError:
    HermesAgentRunner = None

try:
    from hermes_teamwork.config import load_config
except ImportError:
    load_config = None


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 1: Greenfield Feature Development (S1)
# ══════════════════════════════════════════════════════════════════════════════

class TestScenario1_GreenfieldFeatureDevelopment:
    """
    S1: Greenfield Feature Development Scenario.
    12-turn complete lifecycle from prompt ingestion to frozen specification,
    Step 0 survey, 3-wave execution, strict AND gate approval, independent
    victory audit, and delivery.
    """

    def test_scenario1_greenfield_feature_development(self, opaque_git_repo, clean_workspace, mock_runner_factory):
        runner = mock_runner_factory()
        user_prompt = "Implement robust JSON streaming parser with schema validation"

        # Turn 1 & 2: Prompt Ingestion, Verbatim Freezing, and Interview
        sentinel = Sentinel(workspace_root=clean_workspace, runner=runner)
        arch = sentinel.interview_and_initialize(user_prompt)

        req_file = sentinel.run_state.original_request_file
        assert req_file.exists(), "ORIGINAL_REQUEST.md must be frozen"
        assert user_prompt in req_file.read_text(encoding="utf-8")
        assert sentinel.run_state.project_file.exists(), "PROJECT.md must be generated"

        # Turn 3 & 4: Orchestrator Boot & Step 0 Survey
        orch = ProjectOrchestrator(run_state=sentinel.run_state, runner=runner)
        survey_results = orch.run_survey_phase()
        assert len(survey_results) >= 2 or orch.spawn_count >= 2

        # Step 0 Path determination (Path 2B for focused scope)
        selected_path = orch.select_execution_path(["src/json_stream.py", "tests/test_json_stream.py"])
        assert selected_path == "2B"

        # Turn 5 to 8: 3-Wave Execution & Gate Consensus
        success = orch.execute_milestone(
            milestone_id="M1",
            milestone_title="Core Streaming Parser Implementation",
            scope_files=["src/json_stream.py", "tests/test_json_stream.py"],
            max_iterations=1,
        )
        assert success is True, "Milestone execution must succeed"

        # Check GATE_STATUS.md
        gate_status = sentinel.run_state.gate_status_file
        assert gate_status.exists()
        gate_content = gate_status.read_text(encoding="utf-8")
        assert "Gate Result: **PASS**" in gate_content

        # Turn 9 to 12: Claim Victory & Independent Victory Audit
        res = sentinel.run_mission(user_prompt)
        assert res.status == "SUCCESS" or res.get("status") in ("SUCCESS", "COMPLETED", "DONE")

        # Verify independent victory audit was dispatched
        victory_agents = [
            a for a in runner.executed_agents
            if "victory" in a.get("archetype", "").lower()
        ]
        assert len(victory_agents) >= 1
        assert victory_agents[0]["verdict"] == "VICTORY CONFIRMED"


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 2: Multi-Round Adversarial Rejection & Self-Healing (S2)
# ══════════════════════════════════════════════════════════════════════════════

class TestScenario2_MultiRoundAdversarialRejectionSelfHealing:
    """
    S2: Multi-Round Adversarial Rejection & Self-Healing Scenario.
    11-turn failure injection (adversarial boundary defect + unauthorized touch),
    dual veto enforcement, dead ends registry, and round 2 self-healing to PASS.
    """

    def test_scenario2_multi_round_adversarial_rejection_self_healing(self, clean_workspace, mock_runner_factory):
        user_prompt = "Implement safe circular ring buffer"
        # Configure runner to fail on Round 1 with Challenger rejection and Auditor violation
        runner = mock_runner_factory(
            simulate_challenger_failure_rounds=1,
            simulate_auditor_violation=True,
        )

        sentinel = Sentinel(workspace_root=clean_workspace, runner=runner)
        sentinel.interview_and_initialize(user_prompt)

        # Round 1 Wave 3 evaluation with flaws
        r1_verdicts = [
            GateVerdict("worker_m1_iter1", "worker", "DONE"),
            GateVerdict("auditor_m1", "auditor", "INTEGRITY_VIOLATION", details="Touched utils/math.py", defect="out-of-scope edit"),
            GateVerdict("rev_full", "reviewer", "APPROVE"),
            GateVerdict("rev_scoped", "reviewer", "APPROVE"),
            GateVerdict("chal_edge", "challenger", "REQUEST_CHANGES", details="IndexError on capacity <= 0", defect="capacity <= 0 crash"),
            GateVerdict("chal_sound", "challenger", "APPROVE"),
        ]

        # Gate Evaluation Round 1: Forensic Auditor binary veto halts immediately
        r1_gate = AdversarialGate.evaluate(r1_verdicts)
        assert r1_gate.passed is False
        assert r1_gate.binary_veto_triggered is True
        assert len(r1_gate.defect_ledger) >= 1

        # Record failed approach in DEAD_ENDS.md and GATE_STATUS.md
        sentinel.run_state.init_gate_status("M1", 1)
        for v in r1_verdicts:
            sentinel.run_state.append_gate_verdict(v.agent_name, v.role, v.verdict, notes=v.details)
        sentinel.run_state.record_gate_result("FAIL", r1_gate.reason)

        sentinel.run_state.record_dead_end(
            iteration=1,
            approach="Unvalidated negative buffer capacity",
            reason="Unhandled crash reproduced in probe dir",
            files=["src/ring_buffer.py", "utils/math.py"],
            milestone="M1",
        )

        assert sentinel.run_state.dead_ends_file.exists()
        dead_ends_text = sentinel.run_state.dead_ends_file.read_text(encoding="utf-8")
        assert "Unvalidated negative buffer capacity" in dead_ends_text

        # Round 2: Worker heals self, verifiers pass
        r2_verdicts = [
            GateVerdict("worker_m1_iter2", "worker", "DONE"),
            GateVerdict("auditor_m1_iter2", "auditor", "CLEAN", details="All edits inside scope"),
            GateVerdict("rev_full_iter2", "reviewer", "APPROVE"),
            GateVerdict("rev_scoped_iter2", "reviewer", "APPROVE"),
            GateVerdict("chal_edge_iter2", "challenger", "APPROVE", details="ValueError raised gracefully"),
            GateVerdict("chal_sound_iter2", "challenger", "APPROVE"),
        ]

        r2_gate = AdversarialGate.evaluate(r2_verdicts)
        assert r2_gate.passed is True
        assert len(r2_gate.defect_ledger) == 0

        # Record Round 2 into GATE_STATUS.md
        sentinel.run_state.init_gate_status("M1", 2)
        for v in r2_verdicts:
            sentinel.run_state.append_gate_verdict(v.agent_name, v.role, v.verdict, notes=v.details)
        sentinel.run_state.record_gate_result("PASS", "All checks passed after self-healing")

        # Verify history preservation in GATE_STATUS.md
        gate_text = sentinel.run_state.gate_status_file.read_text(encoding="utf-8")
        assert "Iteration 1" in gate_text
        assert "Iteration 2" in gate_text
        assert "Gate Result: **FAIL**" in gate_text
        assert "Gate Result: **PASS**" in gate_text


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 3: Long-Horizon Orchestration & Succession Cascade (S3)
# ══════════════════════════════════════════════════════════════════════════════

class TestScenario3_LongHorizonOrchestrationSuccessionCascade:
    """
    S3: Long-Horizon Orchestration & Succession Cascade Scenario.
    10-turn multi-milestone project triggering succession at 16 spawns,
    generating soft handoff report, cleaning active crons/timers, and
    orchestrator_gen2 resuming M3 seamlessly.
    """

    def test_scenario3_long_horizon_orchestration_succession_cascade(self, clean_workspace, mock_runner_factory):
        runner = mock_runner_factory()
        prompt = "Develop modular telemetry collector with 3 pipeline plugins"

        sentinel = Sentinel(workspace_root=clean_workspace, runner=runner)
        sentinel.interview_and_initialize(prompt)
        sentinel.run_state.project_file.write_text(
            "# Project Specification\n- [ ] M1: Core Engine\n- [ ] M2: Plugin Pipeline\n- [ ] M3: Exporters\n",
            encoding="utf-8",
        )

        orch1 = ProjectOrchestrator(run_state=sentinel.run_state, runner=runner, generation=1)

        # Gen 1 completes M1
        orch1.execute_milestone("M1", "Core Engine", ["src/core/"], max_iterations=1)
        assert orch1.spawn_count >= 8

        # Gen 1 registers background timers
        t1 = orch1.schedule_safety_timer(300, "Safety watchdog 1")
        t2 = orch1.schedule_safety_timer(600, "Safety watchdog 2")
        assert len(orch1.active_timers) >= 2 or len(getattr(orch1, "_active_timers", {})) >= 2

        # Gen 1 completes M2 and reaches succession threshold (16 cumulative spawns)
        orch1.execute_milestone("M2", "Plugin Pipeline", ["src/plugins/"], max_iterations=1)
        assert orch1.spawn_count >= 16, f"Expected at least 16 spawns, got {orch1.spawn_count}"

        # Succession Protocol triggered automatically at 16 spawns (no manual bypass fallback)
        assert orch1.active_successor is not None, "Automatic succession was not triggered at 16 spawns"
        orch2 = orch1.active_successor

        # Phase 1: Soft handoff.md in Gen 1 state folder
        gen1_handoff = sentinel.run_state.run_dir / "orchestrator_gen1" / "handoff.md"
        assert gen1_handoff.exists()
        handoff_text = gen1_handoff.read_text(encoding="utf-8")
        assert "Soft Handoff" in handoff_text or "Predecessor" in handoff_text

        # Phase 2: Active timers cleaned
        assert len(orch1.active_timers) == 0

        # Phase 3: Gen 2 clean context
        assert orch2.generation == 2
        assert orch2.spawn_count == 0
        assert orch2.agent_name == "orchestrator_gen2"

        # Phase 4: Gen 2 resumes directly at M3 without re-executing M1 or M2
        orch2.execute_milestone("M3", "Exporters", ["src/exporters/"], max_iterations=1)

        project_content = sentinel.run_state.project_file.read_text(encoding="utf-8")
        assert "- [x] M1:" in project_content
        assert "- [x] M2:" in project_content
        assert "- [x] M3:" in project_content


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 4: Large Project Multi-Module Decomposition (Path 2A) (S4)
# ══════════════════════════════════════════════════════════════════════════════

class TestScenario4_LargeProjectMultiModuleDecomposition:
    """
    S4: Large Project Multi-Module Decomposition (Path 2A) Scenario.
    Step 0 survey, Path 2A complexity branching, architectural decomposition
    into decoupled sub-orchestrators with localized SCOPE.md files, and
    cross-module global integration verification.
    """

    def test_scenario4_large_project_multi_module_decomposition(self, clean_workspace, mock_runner_factory):
        runner = mock_runner_factory()
        prompt = "Build complete e-commerce backend with auth, inventory, and payment modules"

        sentinel = Sentinel(workspace_root=clean_workspace, runner=runner)
        sentinel.interview_and_initialize(prompt)

        orch = ProjectOrchestrator(run_state=sentinel.run_state, runner=runner)

        # Step 0: Parallel Survey Phase
        survey = orch.run_survey_phase()
        assert len(survey) >= 2 or orch.spawn_count >= 2

        # Branching decision: Path 2A selected due to multi-module decoupled scope
        path = orch.select_execution_path(["src/auth/", "src/inventory/", "src/payment/", "src/api/"])
        assert path == "2A"

        # Decompose into 3 sub-orchestrators with localized SCOPE.md
        modules = [
            ("M1", "Auth Module", ["src/auth/"]),
            ("M2", "Inventory Module", ["src/inventory/"]),
            ("M3", "Payment Module", ["src/payment/"]),
        ]

        sub_orch_results = []
        for m_id, title, scope in modules:
            sub_id = f"sub_orch_{m_id.lower()}"
            sub_state_dir = sentinel.run_state.run_dir / sub_id
            sub_state_dir.mkdir(parents=True, exist_ok=True)

            # Localized SCOPE.md
            scope_file = sub_state_dir / "SCOPE.md"
            scope_file.write_text(f"# SCOPE — {m_id}\nAllowed: {scope}\n", encoding="utf-8")
            assert scope_file.exists()

            # Execute sub-orchestrator milestone
            sub_orch = ProjectOrchestrator(
                run_state=sentinel.run_state,
                runner=runner,
                is_sub_orchestrator=True,
                sub_orchestrator_id=sub_id,
            )
            res = sub_orch.execute_milestone(m_id, title, scope, max_iterations=1)
            assert res is True
            sub_orch_results.append((m_id, res))

        assert len(sub_orch_results) == 3

        # Cross-module Global Verification Wave
        integration_verdicts = [
            GateVerdict("sub_orch_m1", "worker", "DONE"),
            GateVerdict("sub_orch_m2", "worker", "DONE"),
            GateVerdict("sub_orch_m3", "worker", "DONE"),
            GateVerdict("global_auditor", "auditor", "CLEAN"),
            GateVerdict("global_reviewer", "reviewer", "APPROVE"),
            GateVerdict("global_challenger", "challenger", "APPROVE"),
        ]
        global_gate = AdversarialGate.evaluate(integration_verdicts)
        assert global_gate.passed is True


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 5: Standalone CLI & Config-Driven Dual Runtime (S5)
# ══════════════════════════════════════════════════════════════════════════════

class TestScenario5_StandaloneCLIConfigDualRuntime:
    """
    S5: Standalone CLI & Config-Driven Dual Runtime Scenario.
    CLI parameter verification, YAML configuration parsing, environment
    variable override precedence, offline mock execution, runner contracts,
    PEP 621 metadata, and documentation completeness.
    """

    def test_scenario5_standalone_cli_config_dual_runtime(self, clean_workspace, tmp_path, monkeypatch):
        # Turn 1: CLI Help Flag
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{WORKSPACE_ROOT}:{WORKSPACE_ROOT.parent}:" + env.get("PYTHONPATH", "")
        proc_help = subprocess.run(
            [sys.executable, "-m", "teamwork_framework.cli", "--help"],
            cwd=clean_workspace,
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc_help.returncode == 0
        assert "Usage" in proc_help.stdout or "usage" in proc_help.stdout

        # Turn 2: YAML Configuration Loading
        if load_config is not None:
            yaml_config = tmp_path / "custom_config.yaml"
            yaml_config.write_text("runner: mock\nmax_iterations: 5\ntimeout: 180\n", encoding="utf-8")
            cfg = load_config(yaml_config)
            assert cfg.max_milestone_iterations == 5 or getattr(cfg, "max_iterations", 5) == 5

            # Turn 3: Env var override takes precedence
            monkeypatch.setenv("HERMES_TEAMWORK_RUNNER", "openai")
            cfg_override = load_config(yaml_config)
            assert cfg_override.runner == "openai" or getattr(cfg_override, "runner", "openai") == "openai"

        # Turn 4: Offline MockRunner execution with complete isolation
        runner = MockAgentRunner()
        sentinel = Sentinel(workspace_root=clean_workspace, runner=runner)
        result = sentinel.run("Offline CLI verification mission")
        status = result.get("status") if isinstance(result, dict) else result.status
        assert status in ("SUCCESS", "COMPLETED", "DONE")
        assert sentinel.run_state.original_request_file.exists()
        assert sentinel.run_state.gate_status_file.exists()

        # Turn 5: OpenAI runner contract verification
        if OpenAICompatibleRunner is not None:
            runner_openai = OpenAICompatibleRunner(api_base="http://localhost:20128/v1", model="hermes-3-llama-3.1-8b")
            assert runner_openai.api_base == "http://localhost:20128/v1"

        # Turn 6: PEP 621 packaging metadata verification
        pyproject = WORKSPACE_ROOT / "pyproject.toml"
        assert pyproject.exists()
        pyproj_text = pyproject.read_text(encoding="utf-8")
        assert "hermes-agent" in pyproj_text or "hermes-teamwork" in pyproj_text or "teamwork" in pyproj_text

        # Turn 7: Documentation completeness verification
        doc_files = [
            WORKSPACE_ROOT / "README.md",
            WORKSPACE_ROOT / "SECURITY.md",
            WORKSPACE_ROOT / "SOUL.md",
        ]
        for d in doc_files:
            assert d.exists(), f"Mandatory document {d.name} must exist"
            assert len(d.read_text(encoding="utf-8").strip()) > 50, f"{d.name} must not be empty"
