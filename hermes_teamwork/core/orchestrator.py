"""
hermes_teamwork.core.orchestrator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Production-grade Project Orchestrator implementing:
- DISPATCH-ONLY negative invariant
- Step 0 Survey Phase (3 parallel explorers)
- 2A Decomposition vs 2B Direct Wave execution model
- 3-Wave Execution Model (Wave 1: Explorers, Wave 2: Worker, Wave 3: Parallel Verifiers)
- Gate evaluation & iteration loop with DEAD_ENDS.md registry
- Succession Protocol (hard trigger at 16 spawns, soft handoff, active timer cancellation, lineage tracking)
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from hermes_teamwork.core.gate import AdversarialGate, GateResult, GateVerdict
from hermes_teamwork.core.state import AgentState, TeamworkRunState, utc_now_iso
from hermes_teamwork.prompts import get_system_prompt
from hermes_teamwork.runners.base import BaseAgentRunner


class DispatchOnlyViolationError(RuntimeError):
    """Raised when an orchestrator violates the DISPATCH-ONLY invariant."""
    pass


class MilestoneStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass
class Milestone:
    id: str
    title: str
    scope_files: List[str]
    dependencies: List[str] = field(default_factory=list)
    status: MilestoneStatus = MilestoneStatus.PLANNED
    iteration: int = 0
    max_iterations: int = 4


@dataclass
class OrchestratorConfig:
    succession_threshold: int = 16
    max_milestone_iterations: int = 4
    max_overall_iterations: int = 32
    default_explorers_count: int = 3
    probe_isolation: bool = True
    hang_nudge_timeout_seconds: int = 600   # 10 minutes
    hang_kill_timeout_seconds: int = 3600   # 60 minutes


@dataclass
class LineageInfo:
    predecessor_id: Optional[str]
    predecessor_handoff: Optional[Path]
    generation: int
    spawn_count: int = 0
    created_at: str = field(default_factory=utc_now_iso)


class ProjectOrchestrator:
    """
    Project Orchestrator for the Antigravity Teamwork Architecture.

    Hard Rules / Negative Invariants:
    - NEVER write, modify, or create source code files directly.
    - NEVER explore or debug the codebase directly in order to solve tasks.
    - MUST delegate all technical discovery, implementation, and verification to subagents.
    - MAY only write metadata and state files (.md) in its state folder.
    """

    def __init__(
        self,
        run_state: TeamworkRunState,
        runner: BaseAgentRunner,
        generation: int = 1,
        predecessor_handoff: Optional[Path] = None,
        config: Optional[OrchestratorConfig] = None,
        is_sub_orchestrator: bool = False,
        sub_orchestrator_id: Optional[str] = None,
    ):
        self.run_state = run_state
        self.runner = runner
        self.generation = generation
        self.predecessor_handoff = predecessor_handoff
        self.config = config or OrchestratorConfig()
        self.is_sub_orchestrator = is_sub_orchestrator

        if sub_orchestrator_id:
            self._sub_orchestrator_base_id: Optional[str] = re.sub(r"_gen\d+$", "", sub_orchestrator_id)
        elif is_sub_orchestrator:
            self._sub_orchestrator_base_id = "sub_orchestrator"
        else:
            self._sub_orchestrator_base_id = None

        if sub_orchestrator_id:
            self.agent_name = sub_orchestrator_id
        elif self._sub_orchestrator_base_id:
            self.agent_name = f"{self._sub_orchestrator_base_id}_gen{generation}"
        else:
            self.agent_name = f"orchestrator_gen{generation}"

        self.spawn_count = 0
        self._own_iterations = 0
        self._prior_iterations = 0
        self.active_timers: List[str] = []
        self.milestones: Dict[str, Milestone] = {}
        self.active_successor: Optional[ProjectOrchestrator] = None

        # Initialize AgentState working memory
        self.state = AgentState.create(self.run_state.run_dir, self.agent_name, "orchestrator")
        self._init_briefing_lineage()

    @property
    def total_iterations(self) -> int:
        succ_iters = self.active_successor.total_iterations if self.active_successor is not None else 0
        return self._own_iterations + succ_iters

    @total_iterations.setter
    def total_iterations(self, value: int) -> None:
        self._own_iterations = value

    def _chain_spawn_count(self) -> int:
        total = self.spawn_count
        curr = self.active_successor
        while curr is not None:
            total += curr.spawn_count
            curr = curr.active_successor
        return total

    def _next_successor_id(self) -> str:
        next_gen = self.generation + 1
        if self._sub_orchestrator_base_id:
            return f"{self._sub_orchestrator_base_id}_gen{next_gen}"
        return f"orchestrator_gen{next_gen}"

    @property
    def latest_orchestrator(self) -> "ProjectOrchestrator":
        curr = self
        while curr.active_successor is not None:
            curr = curr.active_successor
        return curr

    # -------------------------------------------------------------------------
    # Negative Invariant Guard (DISPATCH-ONLY)
    # -------------------------------------------------------------------------
    def modify_source_file(self, file_path: Union[str, Path], content: str) -> None:
        """Explicitly guarded: raises DispatchOnlyViolationError if invoked."""
        raise DispatchOnlyViolationError(
            f"DISPATCH-ONLY violation: {self.agent_name} attempted direct modification of {file_path}."
        )

    def execute_test_command(self, command: str) -> None:
        """Explicitly guarded: raises DispatchOnlyViolationError if invoked."""
        raise DispatchOnlyViolationError(
            f"DISPATCH-ONLY violation: {self.agent_name} attempted direct execution of '{command}'."
        )

    # -------------------------------------------------------------------------
    # Step 0 Survey Phase
    # -------------------------------------------------------------------------
    def run_survey_phase(self) -> Dict[str, Any]:
        """
        Dispatches 3 specialized parallel explorers before milestone decomposition:
        1. Codebase architecture explorer (`explorer_survey_codebase`)
        2. Formal specification miner (`spec_miner_survey`)
        3. Test suite & baseline explorer (`explorer_survey_tests`)
        Returns dictionary containing findings and outputs.
        """
        survey_dispatches = [
            (
                "explorer_survey_codebase",
                "explorer",
                "Perform in-depth survey of codebase architecture, component boundaries, entry points, and dependencies."
            ),
            (
                "spec_miner_survey",
                "explorer",
                "Mine authoritative specifications, RFCs, ABI invariants, and formal contract requirements."
            ),
            (
                "explorer_survey_tests",
                "explorer",
                "Survey existing test suites, fixtures, regression baselines, and test infrastructure."
            )
        ]

        results = {}
        for agent_id, archetype, task in survey_dispatches:
            full_agent_id = f"{agent_id}_gen{self.generation}"
            res = self._spawn_agent(
                agent_id=full_agent_id,
                archetype=archetype,
                task=task,
                context_files=[self.run_state.original_request_file],
            )
            results[agent_id] = res

        return results

    # -------------------------------------------------------------------------
    # Branch: 2A Decomposition vs 2B Direct Wave
    # -------------------------------------------------------------------------
    def should_decompose(self, milestone_count: int, has_dual_tracks: bool = False) -> bool:
        """
        Determines whether to trigger Path 2A (Decomposition) or Path 2B (Direct Wave).
        Path 2A is selected when multiple decoupled milestones or dual tracks exist.
        """
        return milestone_count > 1 or has_dual_tracks

    def execute_milestones_2a(self, milestones: List[Milestone]) -> bool:
        """
        Path 2A: Decompose and delegate each milestone to dedicated sub-orchestrators.
        """
        if self.active_successor is not None:
            return self.active_successor.execute_milestones_2a(milestones)

        for m in milestones:
            self.milestones[m.id] = m

        for idx, m in enumerate(milestones):
            if m.status == MilestoneStatus.DONE:
                continue

            if (self._prior_iterations + self._own_iterations) >= self.config.max_overall_iterations:
                m.status = MilestoneStatus.FAILED
                self._update_project_md_milestone(m.id, "[ ]")
                return False

            m.status = MilestoneStatus.IN_PROGRESS
            sub_orch = ProjectOrchestrator(
                run_state=self.run_state,
                runner=self.runner,
                generation=1,
                config=self.config,
                is_sub_orchestrator=True,
                sub_orchestrator_id=f"sub_orch_{m.id.lower()}",
            )
            sub_orch._prior_iterations = self._prior_iterations + self._own_iterations

            # Sub-orchestrator executes 2B direct wave
            success = sub_orch.execute_milestone(
                milestone_id=m.id,
                milestone_title=m.title,
                scope_files=m.scope_files,
                max_iterations=m.max_iterations,
            )

            # Incorporate full sub-orchestrator successor chain spawns & iterations
            self.spawn_count += sub_orch._chain_spawn_count()
            m.iteration = sub_orch.total_iterations
            self._own_iterations += sub_orch.total_iterations

            if success:
                m.status = MilestoneStatus.DONE
                self._update_project_md_milestone(m.id, "[x]")
            else:
                m.status = MilestoneStatus.FAILED
                self._update_project_md_milestone(m.id, "[ ]")
                return False

            successor = self._check_succession()
            if successor is not None:
                self.active_successor = successor
                remaining_milestones = milestones[idx + 1:]
                if remaining_milestones:
                    return successor.execute_milestones_2a(remaining_milestones)
                return True

        return True

    # -------------------------------------------------------------------------
    # 3-Wave Execution Model (Path 2B)
    # -------------------------------------------------------------------------
    def execute_milestone(
        self,
        milestone_id: str,
        milestone_title: str,
        scope_files: List[str],
        max_iterations: Optional[int] = None,
        explorer_handoffs: Optional[List[Path]] = None,
        defect_ledger: Optional[List[str]] = None,
        start_iteration: int = 1,
    ) -> bool:
        """
        Executes a single milestone using the 3-wave execution model and adversarial gate.
        Wave 1: Explorers (2-3)
        Wave 2: Worker (1)
        Wave 3: Parallel Verifiers (2 Reviewers, 2 Challengers, 1 Forensic Auditor)
        """
        if self.active_successor is not None:
            return self.active_successor.execute_milestone(
                milestone_id=milestone_id,
                milestone_title=milestone_title,
                scope_files=scope_files,
                max_iterations=max_iterations,
                explorer_handoffs=explorer_handoffs,
                defect_ledger=defect_ledger,
                start_iteration=start_iteration,
            )

        max_iter = max_iterations if max_iterations is not None else self.config.max_milestone_iterations
        if max_iter <= 0:
            return False

        milestone_obj = self.milestones.get(milestone_id)
        if milestone_obj is None:
            milestone_obj = Milestone(
                id=milestone_id,
                title=milestone_title,
                scope_files=list(scope_files),
                status=MilestoneStatus.IN_PROGRESS,
                max_iterations=max_iter,
            )
            self.milestones[milestone_id] = milestone_obj
        else:
            milestone_obj.status = MilestoneStatus.IN_PROGRESS

        defect_ledger = list(defect_ledger) if defect_ledger else []
        end_iteration = start_iteration + max_iter

        try:
            # Wave 1: Explorers (Dispatched on initial iteration if not already provided)
            if explorer_handoffs is None:
                if self.spawn_count > 0 and self.spawn_count + 2 > self.config.succession_threshold:
                    successor = self._trigger_succession()
                    return successor.execute_milestone(
                        milestone_id=milestone_id,
                        milestone_title=milestone_title,
                        scope_files=scope_files,
                        max_iterations=max_iter,
                        explorer_handoffs=None,
                        defect_ledger=defect_ledger,
                        start_iteration=start_iteration,
                    )
                explorer_handoffs = self._run_wave1_explorers(milestone_id, milestone_title, scope_files)

            for iteration in range(start_iteration, end_iteration):
                # Pre-wave budget check: Wave 2 (1) + Wave 3 (5) = 6 spawns
                if self.spawn_count > 0 and self.spawn_count + 6 > self.config.succession_threshold:
                    successor = self._trigger_succession()
                    remaining_iterations = end_iteration - iteration
                    if remaining_iterations > 0:
                        return successor.execute_milestone(
                            milestone_id=milestone_id,
                            milestone_title=milestone_title,
                            scope_files=scope_files,
                            max_iterations=remaining_iterations,
                            explorer_handoffs=explorer_handoffs,
                            defect_ledger=defect_ledger,
                            start_iteration=iteration,
                        )
                    milestone_obj.status = MilestoneStatus.FAILED
                    return False

                if (self._prior_iterations + self._own_iterations + 1) > self.config.max_overall_iterations:
                    milestone_obj.status = MilestoneStatus.FAILED
                    return False

                self._own_iterations += 1
                milestone_obj.iteration = iteration

                self.run_state.init_gate_status(milestone_id, iteration)

                # Wave 2: Implementation Worker
                worker_res = self._run_wave2_worker(
                    milestone_id=milestone_id,
                    milestone_title=milestone_title,
                    scope_files=scope_files,
                    iteration=iteration,
                    explorer_handoffs=explorer_handoffs,
                    defect_ledger=defect_ledger,
                )

                # Wave 3: Adversarial Verifier Wave (Parallel 5 Agents)
                _, gate_verdicts = self._run_wave3_verifiers(
                    milestone_id=milestone_id,
                    scope_files=scope_files,
                    iteration=iteration,
                    worker_res=worker_res,
                )

                # Record verdicts into GATE_STATUS.md
                for v in gate_verdicts:
                    self.run_state.append_gate_verdict(v.agent_name, v.role, v.verdict, notes=v.details)

                # Gate Evaluation (Strict Quorum)
                gate_result = AdversarialGate.evaluate(gate_verdicts, strict_quorum=True)

                if gate_result.passed:
                    milestone_obj.status = MilestoneStatus.DONE
                    self.run_state.record_gate_result("PASS", gate_result.reason)
                    successor = self._check_succession()
                    if successor is not None:
                        self.active_successor = successor
                    return True
                else:
                    self.run_state.record_gate_result("FAIL", gate_result.reason)
                    self._record_dead_end_failure(iteration, worker_res, gate_result, scope_files)
                    defect_ledger = gate_result.defect_ledger

                successor = self._check_succession()
                if successor is not None:
                    self.active_successor = successor
                    remaining_iterations = end_iteration - (iteration + 1)
                    if remaining_iterations > 0:
                        return successor.execute_milestone(
                            milestone_id=milestone_id,
                            milestone_title=milestone_title,
                            scope_files=scope_files,
                            max_iterations=remaining_iterations,
                            explorer_handoffs=explorer_handoffs,
                            defect_ledger=defect_ledger,
                            start_iteration=iteration + 1,
                        )
                    milestone_obj.status = MilestoneStatus.FAILED
                    return False

            milestone_obj.status = MilestoneStatus.FAILED
            return False
        except Exception:
            self._cancel_active_timers()
            raise

    def _run_wave1_explorers(self, milestone_id: str, title: str, scope_files: List[str]) -> List[Path]:
        """Wave 1: Dispatches 2-3 explorers in parallel."""
        e1_id = f"explorer_{milestone_id.lower()}_1"
        e2_id = f"explorer_{milestone_id.lower()}_2"

        res1 = self._spawn_agent(
            agent_id=e1_id,
            archetype="explorer",
            task=f"Explore architecture, contracts, and interfaces for {milestone_id}: {title}. Files: {scope_files}",
        )
        res2 = self._spawn_agent(
            agent_id=e2_id,
            archetype="explorer",
            task=f"Explore edge cases, failure boundaries, and testing traps for {milestone_id}: {title}. Files: {scope_files}",
        )

        handoffs = []
        for r in (res1, res2):
            if isinstance(r, dict) and r.get("handoff_path"):
                handoffs.append(Path(r["handoff_path"]))
        return handoffs

    def _run_wave2_worker(
        self,
        milestone_id: str,
        milestone_title: str,
        scope_files: List[str],
        iteration: int,
        explorer_handoffs: List[Path],
        defect_ledger: List[str],
    ) -> Dict[str, Any]:
        """Wave 2: Dispatches 1 implementation worker."""
        worker_id = f"worker_{milestone_id.lower()}_iter{iteration}"
        task = f"Implement changes and unit tests for {milestone_id}: {milestone_title}. Target files: {scope_files}."

        context_files: List[Path] = []
        if explorer_handoffs and iteration == 1:
            context_files.extend(explorer_handoffs)
        if defect_ledger:
            task += "\nAddress defects from prior iteration:\n" + "\n".join(f"- {d}" for d in defect_ledger)
        if (iteration > 1 or defect_ledger) and self.run_state.dead_ends_file.exists():
            context_files.append(self.run_state.dead_ends_file)

        return self._spawn_agent(agent_id=worker_id, archetype="worker", task=task, context_files=context_files)

    def _run_wave3_verifiers(
        self,
        milestone_id: str,
        scope_files: List[str],
        iteration: int,
        worker_res: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], List[GateVerdict]]:
        """Wave 3: Dispatches 2 Reviewers, 2 Challengers, and 1 Forensic Auditor in parallel."""
        m_id = milestone_id.lower()
        r1_id = f"reviewer_{m_id}_iter{iteration}_full"
        r2_id = f"reviewer_{m_id}_iter{iteration}_scoped"
        c1_id = f"challenger_{m_id}_iter{iteration}_edge"
        c2_id = f"challenger_{m_id}_iter{iteration}_soundness"
        a_id = f"auditor_{m_id}_iter{iteration}"

        res_r1 = self._spawn_agent(
            agent_id=r1_id,
            archetype="reviewer",
            task=f"Perform full-suite regression review and contract adherence verification for {milestone_id}.",
        )
        res_r2 = self._spawn_agent(
            agent_id=r2_id,
            archetype="reviewer",
            task=f"Perform target-scoped code review on files: {scope_files}.",
        )
        res_c1 = self._spawn_agent(
            agent_id=c1_id,
            archetype="challenger",
            task="Adversarial falsification: attack edge cases, malformed inputs, boundary breaches.",
        )
        res_c2 = self._spawn_agent(
            agent_id=c2_id,
            archetype="challenger",
            task="Adversarial falsification: attack concurrency, race conditions, mathematical invariants.",
        )
        res_a = self._spawn_agent(
            agent_id=a_id,
            archetype="auditor",
            task="Perform forensic git diff audit. Verify zero unauthorized touches and zero test weakening.",
        )

        w_res = worker_res if isinstance(worker_res, dict) else {}
        r1 = res_r1 if isinstance(res_r1, dict) else {}
        r2 = res_r2 if isinstance(res_r2, dict) else {}
        c1 = res_c1 if isinstance(res_c1, dict) else {}
        c2 = res_c2 if isinstance(res_c2, dict) else {}
        a = res_a if isinstance(res_a, dict) else {}

        gate_verdicts = [
            GateVerdict(
                agent_name=w_res.get("agent_id") or f"worker_{m_id}_iter{iteration}",
                role="worker",
                verdict=w_res.get("verdict") or "FAIL",
                details=w_res.get("details") or "",
            ),
            GateVerdict(
                agent_name=a.get("agent_id") or a_id,
                role="auditor",
                verdict=a.get("verdict") or "FAIL",
                details=a.get("details") or "",
                defect=a.get("defect"),
            ),
            GateVerdict(
                agent_name=r1.get("agent_id") or r1_id,
                role="reviewer",
                verdict=r1.get("verdict") or "REQUEST_CHANGES",
                details=r1.get("details") or "",
                defect=r1.get("defect"),
            ),
            GateVerdict(
                agent_name=r2.get("agent_id") or r2_id,
                role="reviewer",
                verdict=r2.get("verdict") or "REQUEST_CHANGES",
                details=r2.get("details") or "",
                defect=r2.get("defect"),
            ),
            GateVerdict(
                agent_name=c1.get("agent_id") or c1_id,
                role="challenger",
                verdict=c1.get("verdict") or "REQUEST_CHANGES",
                details=c1.get("details") or "",
                defect=c1.get("defect"),
            ),
            GateVerdict(
                agent_name=c2.get("agent_id") or c2_id,
                role="challenger",
                verdict=c2.get("verdict") or "REQUEST_CHANGES",
                details=c2.get("details") or "",
                defect=c2.get("defect"),
            ),
        ]

        return [r1, r2, c1, c2, a], gate_verdicts

    # -------------------------------------------------------------------------
    # Succession Protocol
    # -------------------------------------------------------------------------
    def _should_trigger_succession(self) -> bool:
        if self.active_successor is not None:
            return False
        return self.spawn_count >= self.config.succession_threshold

    def _check_succession(self) -> Optional["ProjectOrchestrator"]:
        if self._should_trigger_succession():
            return self._trigger_succession()
        return None

    def _trigger_succession(self) -> "ProjectOrchestrator":
        """
        Executes the 4-phase Succession Protocol:
        1. Generates structured soft handoff.md
        2. Cancels all active heartbeat crons and safety timers
        3. Spawns successor orchestrator (gen N+1) with 0/16 count & clean context
        4. Updates lineage tracking in BRIEFING.md
        """
        if self.active_successor is not None:
            return self.active_successor

        handoff_path = self.state.state_dir / "handoff.md"
        handoff_content = self._generate_soft_handoff_content()
        handoff_path.write_text(handoff_content, encoding="utf-8")

        self._cancel_active_timers()

        successor_gen = self.generation + 1
        successor = ProjectOrchestrator(
            run_state=self.run_state,
            runner=self.runner,
            generation=successor_gen,
            predecessor_handoff=handoff_path,
            config=self.config,
            is_sub_orchestrator=self.is_sub_orchestrator,
            sub_orchestrator_id=self._next_successor_id() if self.is_sub_orchestrator else None,
        )
        successor.milestones = dict(self.milestones)
        successor._prior_iterations = self._prior_iterations + self._own_iterations
        self.active_successor = successor
        return successor

    def _generate_soft_handoff_content(self) -> str:
        milestone_rows = "\n".join(
            f"| {m.id} | {m.title} | {m.status.value} | Iteration {m.iteration} |"
            for m in self.milestones.values()
        ) or "| None | No milestones tracked | PENDING | - |"

        successor_id = self._next_successor_id()
        reason_label = (
            "Threshold Reached"
            if self.spawn_count >= self.config.succession_threshold
            else "Preemptive Handoff (Budget Remaining < Next Wave)"
        )

        return f"""# Soft Handoff Report: {self.agent_name} -> Successor (Gen {self.generation + 1})

**Agent**: `{self.agent_name}`  
**Role**: `orchestrator`  
**Verdict**: **DONE**  
**Predecessor Agent**: `{self.agent_name}`  
**Predecessor State Folder**: `{self.state.state_dir}`  
**Successor Generation**: `gen{self.generation + 1}`  
**Date**: {utc_now_iso()}  
**Spawn Count**: {self.spawn_count} / {self.config.succession_threshold} ({reason_label})

---

## 1. Observation
### Milestone State
| Milestone | Name | Status | Iteration |
|---|---|---|---|
{milestone_rows}

### Active Subagents
- None. All subagents in generation {self.generation} have completed and retired.
- Spawn budget for generation {self.generation}: {self.spawn_count} / {self.config.succession_threshold}.
- Successor starts with fresh 0 / {self.config.succession_threshold} budget and clean context window.

---

## 2. Logic Chain
- Succession threshold of {self.config.succession_threshold} cumulative subagent spawns reached.
- Predecessor generation {self.generation} has completed active wave executions.
- Transitioning execution to generation {self.generation + 1} to maintain fresh context budget.

---

## 3. Caveats
- Hard constraints carry forward:
  1. DISPATCH-ONLY: Successor MUST NOT edit source code or execute test commands directly.
  2. Strict AND Consensus: Pass requires Worker DONE + Auditor CLEAN + Reviewers APPROVE + Challengers APPROVE.
  3. Anti-Cheating Policy: Zero hardcoding, zero facade mocks, binary veto on Auditor INTEGRITY_VIOLATION.

---

## 4. Conclusion
Key run state persisted across artifacts:
- Shared Project Scope: `{self.run_state.project_file}`
- Gate Status Ledger: `{self.run_state.gate_status_file}`
- Dead Ends Registry: `{self.run_state.dead_ends_file}`
- Original User Request: `{self.run_state.original_request_file}`

---

## 5. Verification Method
1. Read predecessor handoff at `{self.state.state_dir / 'handoff.md'}`.
2. Initialize working memory in `{successor_id}/BRIEFING.md`.
3. Resume execution on in-progress or next planned milestone.

---

## 1. Milestone State
| Milestone | Name | Status | Iteration |
|---|---|---|---|
{milestone_rows}

---

## 2. Active Subagents
- None. All subagents in generation {self.generation} have completed and retired.
- Spawn budget for generation {self.generation}: {self.spawn_count} / {self.config.succession_threshold}.
- Successor starts with fresh 0 / {self.config.succession_threshold} budget and clean context window.

---

## 3. Pending Decisions & Hard Constraints
1. **DISPATCH-ONLY**: Successor MUST NOT edit source code or execute test commands directly.
2. **Strict AND Consensus**: Pass requires Worker DONE + Auditor CLEAN + Reviewers APPROVE + Challengers APPROVE.
3. **Anti-Cheating Policy**: Zero hardcoding, zero facade mocks, binary veto on Auditor INTEGRITY_VIOLATION.

---

## 4. Key Artifacts
- Shared Project Scope: `{self.run_state.project_file}`
- Gate Status Ledger: `{self.run_state.gate_status_file}`
- Dead Ends Registry: `{self.run_state.dead_ends_file}`
- Original User Request: `{self.run_state.original_request_file}`

---

## 5. Concrete Next Steps for Successor
1. Read predecessor handoff at `{self.state.state_dir / 'handoff.md'}`.
2. Initialize working memory in `{successor_id}/BRIEFING.md`.
3. Resume execution on in-progress or next planned milestone.
"""

    def _cancel_active_timers(self) -> None:
        """Cancels all registered safety timers and heartbeat crons."""
        self.active_timers.clear()

    def register_timer(self, timer_id: str) -> None:
        """Registers an active safety timer or cron."""
        self.active_timers.append(timer_id)

    # -------------------------------------------------------------------------
    # Subagent Spawning Primitive
    # -------------------------------------------------------------------------
    def _spawn_agent(
        self,
        agent_id: str,
        archetype: str,
        task: str,
        context_files: Optional[List[Path]] = None,
    ) -> Dict[str, Any]:
        """
        Dispatches a subagent via runner, increments spawn_count, and returns execution result.
        """
        self.spawn_count += 1
        agent_state = AgentState.create(self.run_state.run_dir, agent_id, archetype)
        dispatch_file = agent_state.write_dispatch(task, context_files)

        timer_id = f"safety_timer_{agent_id}"
        self.register_timer(timer_id)

        system_prompt = get_system_prompt(
            archetype,
            state_dir=agent_state.state_dir,
            generation=self.generation,
        )
        fail_verdict = "REQUEST_CHANGES" if archetype in ("reviewer", "challenger") else "FAIL"

        try:
            res = self.runner.run_agent(
                agent_id=agent_id,
                archetype=archetype,
                system_prompt=system_prompt,
                dispatch_file=dispatch_file,
                state_dir=agent_state.state_dir,
                workspace_dir=self.run_state.workspace_root,
            )
        except Exception as exc:
            res = {
                "agent_id": agent_id,
                "archetype": archetype,
                "verdict": fail_verdict,
                "details": f"Subagent execution failed with {type(exc).__name__}: {exc}",
                "defect": f"{type(exc).__name__}: {exc}",
                "error": str(exc),
            }
        finally:
            if timer_id in self.active_timers:
                self.active_timers.remove(timer_id)

        if not isinstance(res, dict):
            res = {
                "agent_id": agent_id,
                "archetype": archetype,
                "verdict": fail_verdict,
                "details": f"Subagent runner returned invalid non-dict result: {type(res).__name__}",
                "defect": "Invalid non-dict agent result",
            }

        return res

    # -------------------------------------------------------------------------
    # Helper & State Updaters
    # -------------------------------------------------------------------------
    def _record_dead_end_failure(
        self,
        iteration: int,
        worker_res: Dict[str, Any],
        gate_result: GateResult,
        scope_files: List[str],
    ) -> None:
        """Records failed iteration into DEAD_ENDS.md."""
        worker_id = worker_res.get("agent_id") if isinstance(worker_res, dict) else None
        worker_id = worker_id or f"worker_iter{iteration}"
        approach = f"Iteration {iteration} implementation by {worker_id}"
        reason = gate_result.reason
        self.run_state.record_dead_end(
            iteration=iteration,
            approach=approach,
            why_failed=reason,
            files_touched=scope_files,
        )

    def _init_briefing_lineage(self) -> None:
        """Initializes BRIEFING.md with locked sections and lineage."""
        content = f"""# BRIEFING — {utc_now_iso()}

## Mission
Project Orchestration for run {self.run_state.run_id}

## 🔒 My Identity
- Archetype: orchestrator
- Agent ID: {self.agent_name}
- Generation: gen{self.generation}
- State folder: {self.state.state_dir.resolve()}
- Predecessor: {self.predecessor_handoff or 'None (Root Generation)'}

## 🔒 Key Constraints
- DISPATCH-ONLY: Never modify source code, never run test commands directly.
- STRICT AND GATE: Worker DONE + Auditor CLEAN + Reviewers APPROVE + Challengers APPROVE.
- SUCCESSION THRESHOLD: 16 cumulative subagent spawns per generation.

## Succession Status
- Generation: {self.generation}
- Spawn budget: {self.spawn_count} / {self.config.succession_threshold}
- Predecessor handoff: {self.predecessor_handoff or 'None'}

## Active Timers
- Registered timers: {len(self.active_timers)}
"""
        briefing_path = self.state.state_dir / "BRIEFING.md"
        briefing_path.write_text(content, encoding="utf-8")

    def _update_project_md_milestone(self, milestone_id: str, status_mark: str) -> None:
        """Updates milestone checkbox in PROJECT.md."""
        if not self.run_state.project_file.exists():
            return
        text = self.run_state.project_file.read_text(encoding="utf-8")
        old_pattern = f"- [ ] {milestone_id}:"
        new_pattern = f"- {status_mark} {milestone_id}:"
        if old_pattern in text:
            text = text.replace(old_pattern, new_pattern)
            self.run_state.project_file.write_text(text, encoding="utf-8")
