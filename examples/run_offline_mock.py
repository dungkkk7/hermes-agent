#!/usr/bin/env python3
"""
examples/run_offline_mock.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runnable standalone example demonstrating the complete Hermes Teamwork multi-agent
workflow using MockAgentRunner (offline deterministic simulation, zero network).

Demonstrates:
  1. Sentinel E2E mission: request ingestion, immutable prompt freezing, 3-wave execution,
     and independent Victory Audit confirmation.
  2. Adversarial Review Gate self-healing: Challenger falsification rejection in Iteration 1
     logged to DEAD_ENDS.md and resolved in Iteration 2.
  3. Succession Protocol: spawn count budget exhaustion (threshold = 14) triggering
     clean resource cleanup, structured soft handoff, and Generation 2 spawning.

Usage:
    python3 examples/run_offline_mock.py
    python3 examples/run_offline_mock.py --workspace /tmp/my_mock_run
    python3 examples/run_offline_mock.py --simulate-defect
    python3 examples/run_offline_mock.py --simulate-succession
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
from typing import Optional

# Ensure package root is in sys.path when executed directly
_pkg_root = Path(__file__).resolve().parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from hermes_teamwork.core.gate import AdversarialGate
from hermes_teamwork.core.orchestrator import OrchestratorConfig, ProjectOrchestrator
from hermes_teamwork.core.sentinel import Sentinel, VictoryAuditVerdict
from hermes_teamwork.core.state import TeamworkRunState
from hermes_teamwork.runners.mock_runner import MockAgentRunner


def print_banner(title: str) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {title}")
    print(f"{'=' * 72}")


def run_happy_path_mission(workspace_dir: Path) -> bool:
    """Demonstrates full Sentinel E2E mission with Victory Audit confirmation."""
    print_banner("Phase 1: Sentinel E2E Happy Path Mission")
    print(f"Target Workspace: {workspace_dir}")

    user_request = "Implement robust rate-limiting middleware with Redis token bucket"
    runner = MockAgentRunner()
    sentinel = Sentinel(workspace_root=workspace_dir, runner=runner, run_id="mock_happy_path")

    print(f"\n[1/4] Ingesting request and freezing prompt...")
    print(f'Prompt: "{user_request}"')
    result = sentinel.run_mission(user_request)

    print(f"\n[2/4] Verifying state artifacts...")
    req_file = sentinel.run_state.original_request_file
    proj_file = sentinel.run_state.project_file
    gate_file = sentinel.run_state.gate_status_file
    print(f"  - ORIGINAL_REQUEST.md: {'EXISTS' if req_file.exists() else 'MISSING'}")
    print(f"  - PROJECT.md:          {'EXISTS' if proj_file.exists() else 'MISSING'}")
    print(f"  - GATE_STATUS.md:      {'EXISTS' if gate_file.exists() else 'MISSING'}")

    print(f"\n[3/4] Checking Gate Result...")
    if gate_file.exists():
        for line in gate_file.read_text(encoding="utf-8").splitlines():
            if "Gate Result:" in line:
                print(f"  {line.strip()}")

    print(f"\n[4/4] Mission Outcome:")
    print(f"  - Status:          {result.status}")
    print(f"  - Victory Verdict: {result.victory_verdict}")
    print(f"  - Audits Run:      {result.audit_count}")
    print(f"  - Run Directory:   {result.run_dir}")

    return result.status == "SUCCESS"


def run_defect_remediation_demo(workspace_dir: Path) -> bool:
    """Demonstrates adversarial falsification rejection in Iter 1 and self-healing in Iter 2."""
    print_banner("Phase 2: Adversarial Review Gate Defect Self-Healing")
    run_state = TeamworkRunState(workspace_root=workspace_dir, run_id="mock_defect_healing")
    run_state.record_original_request("Build safe database interface with boundary checks")

    # Simulate challenger rejecting round 1 with a boundary case defect
    runner = MockAgentRunner(simulate_challenger_failure_rounds=1)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner)

    print("\nExecuting Milestone M1 with simulated challenger boundary defect...")
    success = orch.execute_milestone(
        milestone_id="M1",
        milestone_title="Database Layer",
        scope_files=["src/db.py"],
        max_iterations=3,
    )

    print(f"\nIteration Outcome:")
    print(f"  - Total Iterations: {orch.total_iterations} (Expected: 2)")
    print(f"  - Milestone Status: {'PASSED' if success else 'FAILED'}")

    # Inspect DEAD_ENDS.md
    if run_state.dead_ends_file.exists():
        dead_ends = run_state.read_dead_ends()
        print(f"  - DEAD_ENDS.md logged {len(dead_ends)} failure(s) during exploration.")
        if dead_ends:
            print(f'    Defect logged: "{dead_ends[0].why_failed[:70]}..."')

    return success and orch.total_iterations == 2


def run_succession_demo(workspace_dir: Path) -> bool:
    """Demonstrates Succession Protocol triggered mid-milestone at spawn threshold."""
    print_banner("Phase 3: Succession Protocol & Soft Handoff Transfer")
    run_state = TeamworkRunState(workspace_root=workspace_dir, run_id="mock_succession")
    run_state.record_original_request("Develop modular microservice architecture")

    # Succession threshold set to 14 spawns; challenger retries 3 rounds
    config = OrchestratorConfig(succession_threshold=14)
    runner = MockAgentRunner(simulate_challenger_failure_rounds=3)
    orch = ProjectOrchestrator(run_state=run_state, runner=runner, config=config)

    print("\nExecuting Milestone M1 with spawn threshold = 14...")
    success = orch.execute_milestone(
        milestone_id="M1",
        milestone_title="Microservice Mesh",
        scope_files=["src/mesh.py"],
        max_iterations=4,
    )

    print(f"\nSuccession Outcome:")
    print(f"  - Predecessor Spawns: {orch.spawn_count} (Capped <= 14)")
    print(f"  - Successor Created:  {orch.active_successor is not None}")
    if orch.active_successor:
        print(f"  - Successor Agent:    {orch.active_successor.agent_name} (Gen {orch.active_successor.generation})")

    handoff_file = orch.state.state_dir / "handoff.md"
    print(f"  - Predecessor Soft Handoff: {'EXISTS' if handoff_file.exists() else 'MISSING'}")

    return success and orch.active_successor is not None


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_offline_mock",
        description="Execute Hermes Teamwork offline deterministic mock demonstration.",
    )
    parser.add_argument(
        "--workspace",
        "-w",
        type=str,
        default=None,
        help="Workspace directory (default: isolated temporary directory)",
    )
    parser.add_argument(
        "--simulate-defect",
        action="store_true",
        help="Run only the Adversarial Gate defect self-healing demo",
    )
    parser.add_argument(
        "--simulate-succession",
        action="store_true",
        help="Run only the Succession Protocol soft handoff demo",
    )
    args = parser.parse_args()

    temp_ctx = None
    if args.workspace:
        ws_path = Path(args.workspace).resolve()
        ws_path.mkdir(parents=True, exist_ok=True)
    else:
        temp_ctx = tempfile.TemporaryDirectory(prefix="teamwork_offline_mock_")
        ws_path = Path(temp_ctx.name)

    try:
        if args.simulate_defect:
            ok = run_defect_remediation_demo(ws_path)
        elif args.simulate_succession:
            ok = run_succession_demo(ws_path)
        else:
            # Run complete demonstration suite
            ok1 = run_happy_path_mission(ws_path)
            ok2 = run_defect_remediation_demo(ws_path)
            ok3 = run_succession_demo(ws_path)
            ok = ok1 and ok2 and ok3

        if ok:
            print_banner("✅ Offline Mock Demonstration Completed Successfully (Exit: 0)")
            return 0
        else:
            print_banner("❌ Offline Mock Demonstration Failed (Exit: 1)")
            return 1
    finally:
        if temp_ctx:
            temp_ctx.cleanup()


if __name__ == "__main__":
    sys.exit(main())
