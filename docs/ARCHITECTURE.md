# Hermes Teamwork: Architecture Specification

## 1. System Overview & Design Philosophy

Hermes Teamwork integrates the autonomous multi-agent operating architecture pioneered by Google Antigravity into [Nous Research's Hermes Agent](https://nousresearch.com) runtime. It provides a modular, production-grade integration layer that transforms single-agent task execution into a structured, verifiable multi-agent pipeline governed by strict negative invariants, adversarial evaluation, file-based persistence, and automatic succession.

### 1.1 High-Level Architecture Flow

```
                      User / CLI / Hermes Chat
                                 │
                                 ▼
                     [ Sentinel Lifecycle Agent ]
             Permanent User Liaison | Relay-Only Invariant
             Immutable Request Freezing (`ORIGINAL_REQUEST.md`)
             Dual Crons: Reporting (`*/8m`) | Liveness Watchdog (`*/10m`)
                                 │
                                 ▼
                    [ Project Orchestrator ]
             Strict Dispatch-Only Invariant | Succession @ 16 Spawns
                                 │
     ┌───────────────────────────┴───────────────────────────┐
     ▼                                                       ▼
[ Path 2A: Decomposition ]                      [ Path 2B: Direct 3-Wave Execution ]
(Spawns Sub-Orchestrator per Epic)              ├── Wave 1: Explorers (2-3 parallel)
                                                ├── Wave 2: Worker (1 implementer)
                                                └── Wave 3: Adversarial Verifiers (5 parallel)
                                                           │
                                                           ▼
                                                [ Adversarial Review Gate ]
                                                Strict AND Quorum | Forensic Binary Veto
                                                `GATE_STATUS.md` & `DEAD_ENDS.md`
                                                           │
                                                           ▼ (Upon Victory Claim)
                                                [ Independent Victory Audit ]
                                                Isolated Probe (`teamwork_probe.XXXXXX`)
                                                Zero Test Tampering Guarantee (Max 2 Audits)
```

### 1.2 Core Architectural Principles & Negative Invariants

1. **Sentinel Relay-Only Invariant**: The Sentinel is the sole liaison to the user. It freezes user requests into `ORIGINAL_REQUEST.md` at run start and generates executive summaries. It **never** writes implementation code, modifies workspace files, or debugs failing tests.
2. **Orchestrator Dispatch-Only Invariant**: The `ProjectOrchestrator` governs task scheduling, wave decomposition, and succession. It is strictly prohibited from directly editing source code (`modify_source_file`) or running test commands (`execute_test_command`); violating this raises `DispatchOnlyViolationError`. All work is performed by dispatched subagents.
3. **Zero-Trust Adversarial Review**: Code is never merged or marked done based solely on the implementer's report. An adversarial gate enforces independent verification by reviewers, edge/soundness challengers, and an integrity auditor.
4. **Forensic Binary Veto**: The Forensic Integrity Auditor inspects git diffs, test suite assertions, and scope boundaries. If test assertions are weakened, mocked out, or unauthorized files are touched, the Auditor issues an instant binary veto (`INTEGRITY_VIOLATION`), failing the gate immediately.
5. **Succession & Lineage Preservation**: Agents maintain bounded lifecycles. Orchestrators reset context and spawn budgets after 16 cumulative subagent dispatches, transferring execution to the next generation via structured soft handoffs.
6. **File-Based Observability**: No hidden in-memory states. All inter-agent communication, briefings, heartbeats, dead ends, and handoff reports are persisted as Markdown artifacts under `.agents/teamwork/<run_id>/`.

---

## 2. Sentinel Mission Lifecycle

The Sentinel manages the end-to-end mission lifecycle, safeguarding user intent against conversational drift and ensuring deliverables pass independent audit before completion.

```
       [User Task Prompt]
               │
               ▼
   [Step 1: Ingest & Freeze] ──> Write ORIGINAL_REQUEST.md (Immutable)
               │
   [Step 2: Task Interview] ───> Classify TaskArchetype & Generate PROJECT.md
               │
   [Step 3: Launch Watchdogs] ──> Start Reporting Cron (*/8m) & Liveness Watchdog (*/10m)
               │
   [Step 4: Dispatch Project] ──> ProjectOrchestrator (Generation 1)
               │
               ▼ (Orchestrator Claims Victory)
   [Step 5: Independent Audit] ─> VictoryAuditor in isolated probe (Round 1)
               │
        ┌──────┴──────┐
     [PASS]         [FAIL] ───> Feed defects to Orchestrator (Remediation Round)
        │               │
        ▼               ▼
[Deliver Final Report]  [VictoryAuditor Round 2]
                        ├── [PASS] ──> Deliver Final Report
                        └── [FAIL] ──> Abort: MAX_VICTORY_AUDITS_EXCEEDED
```

### 2.1 Task Interview & Routing Table

Upon receiving a prompt, `Sentinel.classify_task()` matches intent against canonical `TaskArchetype` categories:

| Archetype | Characteristics | Routing Decision |
|---|---|---|
| `SWE_LIGHT` | One-liner bugs, typos, minor documentation edits, small script tweaks. | Single milestone, lightweight verification. |
| `MILESTONE_PIPELINE` | Multi-file features, architectural refactoring, production integrations (Default). | Full 3-wave orchestrator with adversarial gate. |
| `DOCUMENT_REVIEW` | Architecture audits, design reviews, specification mining. | Deep explorer waves, structured review synthesis. |
| `FORMAL_PROOF` | Lean 4, Coq, formal verification, mathematical invariants. | Rigorous challenger falsification waves. |
| `PIPELINE` | Multi-stage pipeline conductors and ETL flows. | Phased sub-orchestrator decomposition. |

### 2.2 Verbatim Request Freezing (`ORIGINAL_REQUEST.md`)

The Sentinel writes the verbatim prompt to `.agents/teamwork/<run_id>/ORIGINAL_REQUEST.md`. This file represents ground truth:
- Any subsequent attempt to modify or overwrite `ORIGINAL_REQUEST.md` raises `ImmutableStateViolationError`.
- All Victory Audits evaluate the final workspace directly against this frozen prompt.

### 2.3 Background Dual Crons

1. **Reporting Cron (`*/8 * * * *` / 480 seconds)**:
   - Evaluates active phase, recent file modifications, and agent status.
   - Generates a concise 3–5 bullet progress summary for the user without polluting subagent context windows.
2. **Liveness Watchdog Cron (`*/10 * * * *` / 600 seconds)**:
   - Scans subagent `progress.md` files for `Last visited: <ISO 8601 UTC timestamp>`.
   - Tiered escalation:
     * `< 10 min`: `HEALTHY` — Normal operation.
     * `10–20 min`: `NUDGE_REQUIRED` — Sends wake-up ping to subagent.
     * `20–60 min`: `WARNING_STALLED` — Warns orchestrator of potential deadlock.
     * `≥ 60 min`: `CRITICAL_KILL` — Terminates hung subagent process and triggers recovery.

### 2.4 Independent Victory Audit

When the `ProjectOrchestrator` completes all planned milestones, it claims victory. Rather than trusting the orchestrator's self-assessment, Sentinel dispatches an independent `VictoryAuditor`:
- Executed in an isolated probe directory (`teamwork_probe.XXXXXX`, permissions `chmod 700`).
- Validates the entire codebase against `ORIGINAL_REQUEST.md`.
- **Max 2 Audits**:
  - If Round 1 confirms victory: Mission succeeds with status `SUCCESS` (`VICTORY_CONFIRMED`).
  - If Round 1 rejects: Defects are recorded into `DEAD_ENDS.md` and returned to the orchestrator for a targeted remediation milestone (`M1_remediate_round1`). Round 2 is then dispatched.
  - If Round 2 fails: Mission terminates with `MAX_VICTORY_AUDITS_EXCEEDED`.

---

## 3. Project Orchestrator & 3-Wave Execution Model

The `ProjectOrchestrator` decomposes projects and guides workers and verifiers through iterative milestones.

### 3.1 Step 0 Survey Phase

Before decomposing tasks into milestones, the orchestrator dispatches three specialized parallel survey explorers:
1. `explorer_survey_codebase`: Maps architecture boundaries, directory layout, and module entry points.
2. `spec_miner_survey`: Extracts authoritative contracts, interface types, and invariants from docs/specs.
3. `explorer_survey_tests`: Catalogs test suites, mock fixtures, and establishes regression baseline execution times.

### 3.2 Path 2A (Decomposition) vs Path 2B (Direct Wave)

- `should_decompose(milestone_count, has_dual_tracks)`:
  - If a project spans multiple complex submodules (e.g. separate core and E2E tracks), Path 2A spawns dedicated sub-orchestrators (`sub_orch_<milestone_id>`).
  - If a project is focused on a linear epic or single milestone, Path 2B directly runs the 3-wave execution loop.

### 3.3 The 3-Wave Milestone Cycle

Each milestone executes in a 3-wave cycle:

```
[Wave 1: Explorers] ──(Handoffs)──> [Wave 2: Worker] ──(Diff & Test Report)──> [Wave 3: Verifiers (x5)]
                                                                                       │
                                                                                       ▼
                                                                            [Adversarial Review Gate]
                                                                                       │
                                                                   ┌───────────────────┴───────────────────┐
                                                                [PASS]                                  [FAIL]
                                                                   │                                       │
                                                            Milestone Done                       Log Defect to DEAD_ENDS.md
                                                                                                 Retry Wave 2 (Iteration N+1)
```

1. **Wave 1: Parallel Explorers (2 subagents)**
   - `explorer_<milestone>_1`: Investigates code paths, architectural integration points, and concrete line numbers.
   - `explorer_<milestone>_2`: Investigates failure modes, edge cases, and test harness requirements.
   - Output: Structured `handoff.md` reports with verified observation chains.
2. **Wave 2: Implementation Worker (1 subagent)**
   - `worker_<milestone>_iter<N>`: Receives explorer handoffs, previous iteration defect ledgers, and `DEAD_ENDS.md`.
   - Modifies source code following the minimal-change principle.
   - Writes co-located unit/integration tests covering new behaviors and edge cases.
   - Produces a structured 5-component `handoff.md`.
3. **Wave 3: Parallel Adversarial Verifiers (5 subagents)**
   - **Reviewer 1 (`reviewer_<m>_iter<N>_full`)**: Full regression suite verification and interface contract adherence.
   - **Reviewer 2 (`reviewer_<m>_iter<N>_scoped`)**: Target-scoped code review on modified lines and styling.
   - **Challenger 1 (`challenger_<m>_iter<N>_edge`)**: Falsification attacks on boundaries, malformed inputs, and type limits.
   - **Challenger 2 (`challenger_<m>_iter<N>_soundness`)**: Falsification attacks on concurrency, race conditions, and negative invariants.
   - **Forensic Auditor (`auditor_<m>_iter<N>`)**: Git diff hygiene, test assertion tampering, and unauthorized scope modifications.

---

## 4. Adversarial Review Gate

The `AdversarialGate` aggregates Wave 3 verdicts and determines whether the milestone deliverables meet production standards.

### 4.1 Strict AND Consensus Pipeline

Evaluation executes in a deterministic 6-step pipeline (`AdversarialGate.evaluate`):

```
                       Incoming Verdicts (Worker, Verifiers, Auditor)
                                              │
                     [Step 0: Fail-Closed Malformed Input Check]
                                 ├── Malformed/Empty ────────> GATE FAILS (Fail-Closed)
                                 └── Valid Syntax
                                              │
                     [Step 1: Forensic Binary Veto Check]
                                 ├── Auditor != CLEAN ───────> GATE FAILS (Binary Veto)
                                 ├── Any VIOLATION ──────────> GATE FAILS (Binary Veto)
                                 └── Auditor == CLEAN
                                              │
                     [Step 2: Worker Completion Check]
                                 ├── Worker != DONE ─────────> Log Defect
                                 └── Worker == DONE
                                              │
                     [Step 3: Challenger Adversarial Check]
                                 ├── Challenger REQUEST_CHANGES ──> Log Defect (Adversarial Veto)
                                 └── Challenger APPROVE
                                              │
                     [Step 4: Reviewer Quality Check]
                                 ├── Reviewer REQUEST_CHANGES ───> Log Defect
                                 └── Reviewer APPROVE / APPROVE_WITH_NITS
                                              │
                     [Step 5: Quorum & Role Validation]
                                 ├── Missing Role / Unknown Role ──> Log Defect
                                 └── Quorum Satisfied
                                              │
                     [Step 6: Consensus Synthesis]
                                 ├── Any Defects Logged ─────> GATE FAILS
                                 └── Zero Defects ───────────> GATE PASSES
```

### 4.2 Gate Rules Summary

- **Strict AND Quorum**: To pass, the gate requires:
  1. Worker verdict is `DONE`.
  2. Forensic Auditor verdict is `CLEAN`.
  3. All Challengers issue `APPROVE`.
  4. All Reviewers issue `APPROVE` or `APPROVE_WITH_NITS`.
- **Instant Binary Veto**: Any `INTEGRITY_VIOLATION` verdict immediately triggers `binary_veto_triggered=True` and fails the gate.
- **Adversarial Veto**: Any Challenger requesting changes immediately triggers `adversarial_veto_triggered=True` and fails the gate.
- **Defect Ledger & Dead Ends**: When a gate fails, the aggregated defect ledger is appended to `GATE_STATUS.md` and saved into `DEAD_ENDS.md`. Wave 2 workers in iteration $N+1$ receive these records to prevent repeating failed approaches.

---

## 5. Succession Protocol

Long-running autonomous agent missions face context degradation, attention dilution, and token budget exhaustion. The Succession Protocol guarantees continuous execution by cleanly handing off state across generations.

### 5.1 Trigger Mechanics

Succession is triggered automatically by the orchestrator:
1. **Hard Threshold**: When cumulative subagent dispatches reach `config.succession_threshold` (default: 16 spawns).
2. **Preemptive Wave Protection**: When the remaining spawn budget cannot accommodate the upcoming wave (e.g. 6 spawns required for Wave 2 + Wave 3, but only 4 remain).

### 5.2 4-Phase Succession Procedure

```
[Generation N Orchestrator] (Reaches Spawn Threshold: 16/16)
         │
         ▼
[Phase 1: Soft Handoff Creation] ──> Generate handoff.md with lineage & pending tasks
         │
         ▼
[Phase 2: Cleanup Resources] ─────> Cancel active safety timers & background crons
         │
         ▼
[Phase 3: Spawn Successor] ───────> Launch Generation N+1 with clean context & 0/16 spawns
         │
         ▼
[Phase 4: Lineage Transfer] ──────> Successor ingests predecessor handoff into BRIEFING.md
```

1. **Structured Soft Handoff**: The predecessor orchestrator writes a structured `handoff.md` detailing:
   - Completed milestones and current active milestone.
   - Defect ledger and active entries in `DEAD_ENDS.md`.
   - Architectural decisions made.
   - Clear, concrete next actions for the successor.
2. **Resource Cleanup**: Cancels active heartbeat timers, cron registrations, and background subagent processes.
3. **Successor Spawning**: Instantiates `ProjectOrchestrator(generation=N+1, predecessor_handoff=...)` with an empty context window and a fresh 16-spawn budget.
4. **Lineage Preservation**: The successor inherits cumulative iteration counters and references predecessor state artifacts under `.agents/teamwork/<run_id>/orchestrator_gen{N}/`.

---

## 6. File-Based State Persistence Engine

All system state is stored directly on disk under `.agents/teamwork/<run_id>/`, providing full auditability and eliminating hidden in-memory state.

### 6.1 State Directory Layout

```
.agents/teamwork/<run_id>/
├── ORIGINAL_REQUEST.md          # Immutable frozen user prompt
├── PROJECT.md                   # Shared project specifications, contracts, and milestones
├── GATE_STATUS.md               # Cumulative gate verdicts and evaluation logs
├── DEAD_ENDS.md                 # Negative knowledge base of failed approaches
├── sentinel/
│   ├── BRIEFING.md              # Sentinel working memory
│   ├── DISPATCH.md              # Dispatches received
│   └── progress.md              # Liveness heartbeat
├── orchestrator_gen1/
│   ├── BRIEFING.md              # Working memory with locked sections
│   ├── BRIEFING_ARCHIVE.md      # Archived history when BRIEFING exceeds 100 lines
│   ├── DISPATCH.md
│   ├── progress.md
│   └── handoff.md               # Predecessor soft handoff
└── <subagent_name>/             # Dedicated directory per subagent
    ├── BRIEFING.md
    ├── DISPATCH.md
    ├── progress.md
    └── handoff.md
```

### 6.2 Working Memory (`BRIEFING.md`) & Locked Sections

Each agent maintains a persistent working memory file (`BRIEFING.md`):
- **100-Line Ceiling**: When `BRIEFING.md` exceeds 100 lines, the agent state engine automatically prunes older mutable entries and archives them into `BRIEFING_ARCHIVE.md`.
- **Locked Sections (🔒)**: Sections beginning with:
  - `## 🔒 My Identity`
  - `## 🔒 Key Constraints`
  - `## 🔒 My Workflow`
  These sections are strictly append-only. Modifying or deleting any existing line raises `LockedSectionTamperError`.

### 6.3 Liveness Heartbeat (`progress.md`)

Agents emit periodic heartbeats to `progress.md`:
```markdown
# Progress — worker_m1_iter1
- State: In Progress
- Last visited: 2026-11-20T08:00:00Z

## Checklist
- [x] Analyze interfaces
- [x] Apply code changes
- [ ] Run test suite
```
The Sentinel and Orchestrator parse the `Last visited:` timestamp using `utc_now_iso()` to detect stalled or crashed agents.

### 6.4 Structured 5-Component Handoff (`handoff.md`)

Every completed task must produce a `handoff.md` conforming to the 5 mandatory sections:
1. **Observation**: Verbatim facts, file paths, line numbers, and error outputs observed directly.
2. **Logic Chain**: Deductive step-by-step reasoning from observations to proposed changes.
3. **Caveats**: Scope limitations, assumptions made, or edge cases not evaluated.
4. **Conclusion**: Summary of actions taken and final verdict (`DONE`, `APPROVE`, `CLEAN`, `REQUEST_CHANGES`).
5. **Verification Method**: Exact terminal commands used to independently verify deliverables.

---

## 7. Runner Abstraction Hierarchy & Hermes Native Integration

Hermes Teamwork abstracts agent execution behind the `BaseAgentRunner` interface, allowing identical orchestration logic to run offline with simulated models, against local OpenAI-compatible endpoints, or within the native Hermes runtime.

```
                         [ BaseAgentRunner ]
                       (Abstract Interface Contract)
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     ▼                           ▼                           ▼
[ MockAgentRunner ]  [ OpenAICompatibleRunner ]     [ HermesAgentRunner ]
• Zero network       • Local 9router / vLLM         • Native AIAgent
• Multi-round mocks  • Stream=False enforced        • SubagentLifecycle
• Deterministic CI   • Port 20128 ready             • Toolset bridges
```

### 7.1 `BaseAgentRunner` Contract

All runners implement:
```python
def run_agent(
    self,
    agent_id: str,
    archetype: str,
    system_prompt: str,
    dispatch_file: Path,
    state_dir: Path,
    workspace_dir: Path,
) -> Dict[str, Any]: ...
```

### 7.2 Runner Implementations

1. **`MockAgentRunner`**:
   - Executes deterministically without network calls.
   - Generates syntactically valid `BRIEFING.md`, `progress.md`, and 5-component `handoff.md` artifacts.
   - Supports failure simulation flags (`simulate_challenger_failure_rounds`, `simulate_auditor_integrity_violation`, etc.) for comprehensive testing of self-healing and recovery flows.
2. **`OpenAICompatibleRunner`**:
   - Interfaces with OpenAI-compatible servers (such as local 9router instances serving `Nous-Hermes-2-Yi-34B` on port 20128).
   - Enforces `stream=False` to ensure atomic, parseable responses.
   - Includes graceful offline fallback handling.
3. **`HermesAgentRunner`**:
   - Bridges directly to Hermes `AIAgent` and tool execution engines.
   - Dynamically loads tool registries and executes tool calls within the Hermes runtime.

---

## 8. Summary of Navigation & Related Documents

- To install Hermes Teamwork: see [INSTALLATION.md](INSTALLATION.md).
- To configure YAML settings and local LLMs: see [CONFIGURATION.md](CONFIGURATION.md).
- For complete class and method signatures: see [API_REFERENCE.md](API_REFERENCE.md).
- For step-by-step tutorials and scripts: see [RUNNABLE_EXAMPLES.md](RUNNABLE_EXAMPLES.md).
- Return to repository root: [README.md](../README.md).
