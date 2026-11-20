# Hermes Teamwork: Runnable Examples & Integration Tutorial

Welcome to the **Hermes Teamwork** runnable examples and integration tutorial. This guide provides copy-pasteable, verified walkthroughs for orchestrating multi-agent tasks across four primary operational patterns:

1. [Offline Deterministic Mock Workflow](#1-offline-deterministic-mock-workflow)
2. [Live Local 9router Integration (Port 20128)](#2-live-local-9router-integration-port-20128)
3. [Standalone CLI Execution (`hermes-teamwork`)](#3-standalone-cli-execution)
4. [Programmatic Python API Usage](#4-programmatic-python-api-usage)
5. [State Directory Anatomy & Triage](#5-state-directory-anatomy--triage)

---

## Prerequisites & Installation

Ensure you have installed Hermes Teamwork in editable mode:

```bash
git clone https://github.com/NousResearch/hermes-agent.git hermes_teamwork
cd hermes_teamwork
pip install -e .
```

Verify that the CLI is available:

```bash
hermes-teamwork --version
```

---

## 1. Offline Deterministic Mock Workflow

### Overview

The offline deterministic mock workflow executes using `MockAgentRunner`. It simulates subagent interactions without making network requests, consuming tokens, or requiring GPU resources. It is ideal for CI pipelines, automated integration testing, and local architectural validation.

### Running the Example Script

Run the standalone executable script:

```bash
python3 examples/run_offline_mock.py
```

To run in a persistent workspace directory so you can inspect generated state files:

```bash
python3 examples/run_offline_mock.py --workspace ./my_mock_run
```

### Running Specific Architectural Demonstrations

The script includes specialized demonstration modes:

```bash
# 1. Full E2E Sentinel Mission (Happy path + Victory Audit confirmation)
python3 examples/run_offline_mock.py

# 2. Adversarial Review Gate Defect Remediation & Self-Healing
# (Simulates Challenger rejecting Iteration 1 with a boundary defect; heals in Iteration 2)
python3 examples/run_offline_mock.py --simulate-defect

# 3. Succession Protocol & Soft Handoff Transfer
# (Simulates spawn budget exhaustion at threshold 14, generating soft handoff and spawning Gen 2)
python3 examples/run_offline_mock.py --simulate-succession
```

### Execution Lifecycle Breakdown

When `run_offline_mock.py` executes:
1. **Sentinel Request Ingestion**: Freezes the prompt into `.agents/teamwork/<run_id>/ORIGINAL_REQUEST.md` and initializes `PROJECT.md`.
2. **Step 0 Survey Phase**: Orchestrator dispatches three parallel explorers (`explorer_survey_codebase`, `spec_miner_survey`, `explorer_survey_tests`).
3. **Wave 1 (Explorers)**: Dispatches parallel explorers to map interfaces and edge cases, producing structured observation chains.
4. **Wave 2 (Worker)**: Dispatches implementation worker (`worker_m1_iter1`) with the explorer reports.
5. **Wave 3 (Adversarial Verifiers)**: Dispatches 5 verifiers in parallel:
   - Full regression reviewer & scoped code reviewer.
   - 2 adversarial challengers attacking boundaries and race conditions.
   - Forensic integrity auditor verifying git diffs and test assertion integrity.
6. **Adversarial Review Gate**: Strict AND consensus evaluates all verdicts.
7. **Victory Audit**: Sentinel dispatches `VictoryAuditor` in an isolated probe directory (`teamwork_probe.XXXXXX`), confirming victory and delivering the final report.

---

## 2. Live Local 9router Integration (Port 20128)

### Overview

The live integration workflow connects Hermes Teamwork to local LLM inference engines (such as [9router](https://github.com/NousResearch/9router) or local OpenAI-compatible endpoints) serving Nous Research models like `nous-hermes-2-yi-34b`.

### Starting 9router or Local Server

Before running live verification, launch your local endpoint on port `20128`:

```bash
# Option A: 9router CLI
9router --port 20128 --model nous-hermes-2-yi-34b

# Option B: vLLM Server
python3 -m vllm.entrypoints.openai.api_server \
  --port 20128 \
  --model NousResearch/Nous-Hermes-2-Yi-34B \
  --served-model-name nous-hermes-2-yi-34b

# Option C: llama.cpp Server
./llama-server -m models/nous-hermes-2-yi-34b.Q4_K_M.gguf --port 20128 -c 4096
```

### Running the Live Example Script

Execute the standalone script:

```bash
python3 examples/run_live_9router.py
```

### Graceful Offline Fallback

If 9router is not currently listening on port 20128, `run_live_9router.py` detects this immediately via an early TCP socket probe, prints actionable launch instructions, and exits cleanly with exit code `0`:

```text
=== 9router Live Integration Runner ===
Target: 127.0.0.1:20128 (http://127.0.0.1:20128/v1)
Model:  nous-hermes-2-yi-34b

[1/4] Probing TCP port 20128 on 127.0.0.1...

========================================================================
[INFO] 9router server not detected at 127.0.0.1:20128.
The local OpenAI-compatible endpoint is currently offline or unreachable.
========================================================================

To start a local 9router daemon:
  $ 9router --port 20128 --model nous-hermes-2-yi-34b

[OK] Skipping live verification cleanly (exit code 0).
```

To enforce strict failure (exit code 1) in production CI environments where 9router is expected to be running:

```bash
python3 examples/run_live_9router.py --strict
```

### Command Options

```bash
python3 examples/run_live_9router.py --help
# Flags:
#   --host HOST          Target host (default: 127.0.0.1)
#   --port PORT          Target port (default: 20128)
#   --model MODEL        Model identifier (default: nous-hermes-2-yi-34b)
#   --timeout SECONDS    Probe timeout in seconds (default: 5.0)
#   --probe-only         Only probe TCP/HTTP connectivity; skip full mission
#   --strict             Fail with exit code 1 if endpoint is offline
#   --workspace DIR      Target directory for state persistence
```

---

## 3. Standalone CLI Execution

The `hermes-teamwork` CLI provides terminal-based orchestration.

### Basic Examples

#### 1. Quick Mock Mission
```bash
hermes-teamwork "Design a high-performance token bucket rate limiter" --runner mock
```

#### 2. Specifying a Persistent Project Directory
```bash
hermes-teamwork "Refactor database access layer" --runner mock --workspace /tmp/my_project
```

#### 3. Simulating Challenger Defect Remediation
Simulate a scenario where adversarial challengers reject the initial implementation in round 1, forcing a self-healing retry in round 2:
```bash
hermes-teamwork "Fix race condition in connection pool" --runner mock --fail-rounds 1
```

#### 4. Running with Live 9router
```bash
hermes-teamwork "Implement secure password hashing" --runner 9router
```

### YAML Configuration File Integration

Store your configuration in `hermes_teamwork.yaml`:

```yaml
runner: "9router"
base_url: "http://localhost:20128/v1"
model: "nous-hermes-2-yi-34b"
timeout: 120
max_iterations: 4
succession_threshold: 16
```

Then run:

```bash
hermes-teamwork "Run full security audit" --config hermes_teamwork.yaml
```

---

## 4. Programmatic Python API Usage

You can embed Hermes Teamwork directly into existing Python codebases or custom agents.

### Pattern 1: High-Level Sentinel Mission Execution

The simplest pattern dispatches a complete mission through `Sentinel`:

```python
from pathlib import Path
from hermes_teamwork.core.sentinel import Sentinel
from hermes_teamwork.runners.mock_runner import MockAgentRunner

# 1. Initialize runner and workspace
workspace = Path("./my_task_workspace").resolve()
runner = MockAgentRunner()

# 2. Launch Sentinel mission
sentinel = Sentinel(workspace_root=workspace, runner=runner)
result = sentinel.run("Build an asynchronous queue consumer with exponential backoff")

# 3. Check results
print(f"Status:          {result.status}")
print(f"Victory Verdict: {result.victory_verdict}")
print(f"Audits Run:      {result.audit_count}")
print(f"Artifacts Dir:   {result.run_dir}")
```

### Pattern 2: Custom Milestone Orchestration with Defect Retry

For granular control, instantiate `ProjectOrchestrator` directly:

```python
from pathlib import Path
from hermes_teamwork.core.orchestrator import ProjectOrchestrator, OrchestratorConfig
from hermes_teamwork.core.state import TeamworkRunState
from hermes_teamwork.runners.mock_runner import MockAgentRunner

workspace = Path("./custom_orchestration").resolve()
run_state = TeamworkRunState(workspace_root=workspace, run_id="orchestrator_demo")
run_state.record_original_request("Build safe database interface")

# Configure succession threshold and simulated challenger defect
config = OrchestratorConfig(succession_threshold=16, max_milestone_iterations=3)
runner = MockAgentRunner(simulate_challenger_failure_rounds=1)

orch = ProjectOrchestrator(run_state=run_state, runner=runner, config=config)

# Step 0: Run survey explorers
survey_results = orch.run_survey_phase()

# Execute 3-wave milestone
success = orch.execute_milestone(
    milestone_id="M1",
    milestone_title="Database Layer",
    scope_files=["src/db.py"],
    max_iterations=3,
)

print(f"Milestone Success: {success}")
print(f"Total Iterations:  {orch.total_iterations}")
```

### Pattern 3: Adversarial Review Gate Evaluation

Evaluate verdicts directly using `AdversarialGate`:

```python
from hermes_teamwork.core.gate import AdversarialGate, GateVerdict, Verdict

verdicts = [
    GateVerdict(agent_name="worker_01", role="worker", verdict=Verdict.DONE.value),
    GateVerdict(agent_name="auditor_01", role="auditor", verdict=Verdict.CLEAN.value),
    GateVerdict(agent_name="rev_full", role="reviewer", verdict=Verdict.APPROVE.value),
    GateVerdict(agent_name="chal_edge", role="challenger", verdict=Verdict.APPROVE.value),
]

result = AdversarialGate.evaluate(verdicts, strict_quorum=True)

print(f"Gate Passed: {result.passed}")
print(f"Status Line: {result.format_status_line()}")
```

### Pattern 4: State Engine Working Memory & Heartbeats

Manage persistent agent state with locked sections:

```python
from pathlib import Path
from hermes_teamwork.core.state import TeamworkRunState

run_state = TeamworkRunState(workspace_root=Path("./workspace"), run_id="agent_demo")
agent_state = run_state.get_or_create_agent_state(
    agent_name="worker_01",
    archetype="worker",
    mission="Refactor logging subsystem",
    key_constraints=["Do not modify third-party dependencies"],
)

# Read initialized BRIEFING.md
briefing = agent_state.read_briefing()
print("Initialized Briefing has locked sections:", "🔒" in briefing)

# Emit liveness heartbeat
agent_state.write_progress(
    status="Running tests",
    items=[("Analyze code", True), ("Run pytest", True)],
    notes="All unit tests pass cleanly.",
)

# Verify health
assert agent_state.is_healthy(timeout_seconds=600.0) is True
```

---

## 5. State Directory Anatomy & Triage

All state files are written to `.agents/teamwork/<run_id>/`:

```
.agents/teamwork/<run_id>/
├── ORIGINAL_REQUEST.md          # Frozen user prompt (immutable ground truth)
├── PROJECT.md                   # Shared project boundaries, contracts, milestones
├── GATE_STATUS.md               # Cumulative gate tables and iteration logs
├── DEAD_ENDS.md                 # Negative knowledge base of failed approaches
│
├── sentinel/
│   ├── BRIEFING.md              # Sentinel persistent memory
│   ├── DISPATCH.md              # Received dispatches
│   └── progress.md              # Liveness heartbeat
│
├── orchestrator_gen1/
│   ├── BRIEFING.md              # Working memory (<100 lines, locked sections)
│   ├── BRIEFING_ARCHIVE.md      # Archived history if briefing exceeded 100 lines
│   ├── DISPATCH.md
│   ├── progress.md
│   └── handoff.md               # Predecessor soft handoff
│
└── <subagent_name>/
    ├── BRIEFING.md
    ├── DISPATCH.md
    ├── progress.md
    └── handoff.md               # Structured 5-component report
```

### Triaging Issues from State Artifacts

1. **Gate Rejection**: Inspect `GATE_STATUS.md` to see which role requested changes or flagged defects.
2. **Cheating or Assertion Tampering**: If the Forensic Auditor issued a binary veto, inspect `GATE_STATUS.md` for `binary_veto_triggered=True` and check git diffs in the auditor's handoff.
3. **Dead Ends**: Inspect `DEAD_ENDS.md` to see approaches that previously failed and why.
4. **Agent Stalls**: Check `progress.md` in the agent's folder. Compare `Last visited:` with the current UTC clock.

---

## 6. Related Documentation

- Complete system architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Installation instructions: [INSTALLATION.md](INSTALLATION.md)
- Configuration options: [CONFIGURATION.md](CONFIGURATION.md)
- API reference: [API_REFERENCE.md](API_REFERENCE.md)
- Executable script references:
  - [examples/run_offline_mock.py](../examples/run_offline_mock.py)
  - [examples/run_live_9router.py](../examples/run_live_9router.py)
- Return to repository root: [README.md](../README.md)
