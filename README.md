<p align="center">
  <img src="assets/banner.png" alt="Hermes Teamwork" width="100%">
</p>

# Hermes Teamwork ☤

<p align="center">
  <a href="https://github.com/NousResearch/hermes-agent"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge" alt="License: MIT"></a>
  <a href="#-testing--verification"><img src="https://img.shields.io/badge/Tests-690%20Passed-brightgreen.svg?style=for-the-badge" alt="Tests: 690 Passed"></a>
  <a href="docs/CONFIGURATION.md#5-local-llm-configuration-with-9router--nous-hermes-2-yi-34b"><img src="https://img.shields.io/badge/9router-Ready-purple.svg?style=for-the-badge" alt="9router: Ready"></a>
  <a href="https://nousresearch.com"><img src="https://img.shields.io/badge/Built%20on-Nous%20Research%20Hermes-blueviolet?style=for-the-badge" alt="Built on Nous Research Hermes"></a>
</p>

**Hermes Teamwork** integrates Antigravity's autonomous multi-agent operating architecture into [Nous Research's Hermes Agent](https://nousresearch.com) as a production-grade, modular integration layer. It equips Hermes with formal wave decomposition, adversarial review gates, file-based state persistence, automatic succession, and local LLM execution via 9router.

---

## 🏛️ Architectural Overview

Hermes Teamwork operates through an invariant-driven, multi-tier agent hierarchy:

```
                      User / CLI / Hermes Chat
                                 │
                                 ▼
                     [ Sentinel Lifecycle Agent ]
             Permanent User Liaison | Relay-Only Invariant
             Immutable Request Freezing (`ORIGINAL_REQUEST.md`)
             Reporting Cron (*/8m) | Liveness Watchdog (*/10m)
                                 │
                                 ▼
                    [ Project Orchestrator ]
             Strict Dispatch-Only Invariant | Succession @ 16 Spawns
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     ▼                           ▼                           ▼
[ Wave 1: Explorers ]     [ Wave 2: Workers ]       [ Wave 3: Verifiers ]
• Codebase Miners         • Core Implementers       • Dual Reviewers (Target + Regr)
• Spec Analyzers          • Test Implementers       • Adversarial Challengers (x2)
• Architecture Surveyors  • Documentation Writers   • Forensic Integrity Auditor
                                                             │
                                                             ▼
                                                [ Adversarial Review Gate ]
                                                Strict AND Consensus Logic
                                                Auditor Forensic Binary Veto
                                                GATE_STATUS.md & DEAD_ENDS.md
                                                             │
                                                             ▼ (Upon Victory Claim)
                                                [ Independent Victory Audit ]
                                                Isolated Probe (`teamwork_probe.XXXXXX`)
                                                Zero Test Tampering Guarantee
```

---

## ✨ Key Capabilities

| Capability | Description | Architectural Contract |
|---|---|---|
| **Sentinel User Liaison** | Dedicated external interface isolating the multi-agent core from conversational drift. Freezes user requests into an immutable `ORIGINAL_REQUEST.md`. | Relay-only negative invariant; periodic reporting (`*/8m`) and watchdog (`*/10m`). |
| **3-Wave Execution Model** | Structured problem decomposition ensuring investigation precedes coding and adversarial evaluation precedes merge. | Wave 1 (Explorers) $\rightarrow$ Wave 2 (Workers) $\rightarrow$ Wave 3 (Verifiers). |
| **Strict AND Adversarial Gate** | Zero-trust verification pipeline. Requires unanimous approval from implementers, reviewers, and adversarial falsifiers. | Pass iff Worker `DONE` + Auditor `CLEAN` + Reviewers `APPROVE` + Challengers `APPROVE`. Auditor holds instant binary veto. |
| **Persistent File-Based State** | Full observability and auditability without opaque in-memory databases. State is preserved under `.agents/teamwork/<run_id>/`. | Persistent `BRIEFING.md` (<100 lines, locked 🔒 sections), `progress.md` liveness heartbeat, `GATE_STATUS.md`, and `DEAD_ENDS.md`. |
| **Succession & Lineage** | Prevents context window degradation and runaway agent execution by delegating to fresh generations. | Hard trigger at 16 cumulative subagent spawns; structured soft handoff; background task cleanup; lineage tracking (`gen1`, `gen2`, etc.). |
| **Hermes Native Integration** | Pluggable runner architecture supporting offline deterministic mocks, local OpenAI-compatible gateways (9router), and native Hermes `AIAgent`. | `BaseAgentRunner` protocol implemented by `MockAgentRunner`, `OpenAICompatibleRunner`, and `HermesAgentRunner`. |

---

## 🚀 Quick Start

### 1. Installation

Install Hermes Teamwork in editable mode from the repository root:

```bash
# Clone the repository
git clone https://github.com/NousResearch/hermes-agent.git hermes_teamwork
cd hermes_teamwork

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in editable mode
pip install -e .

# Or install without external dependencies for rapid standalone use:
pip install -e . --no-deps
```

Verify that the CLI is available:

```bash
hermes-teamwork --version
# Output: hermes-teamwork 0.1.0

hermes-teamwork --help
```

### 2. Basic CLI Execution

Run an autonomous multi-agent task using the offline mock runner:

```bash
hermes-teamwork --runner mock --request "Design a high-performance memory cache module"
```

Or execute against a live local 9router endpoint (running on port `20128` with `Nous-Hermes-2-Yi-34B`):

```bash
hermes-teamwork "Refactor authentication layer" --runner 9router --workspace /path/to/project
```

### 3. Programmatic Python API

Embed Teamwork directly into your Python scripts or custom Hermes agents:

```python
from pathlib import Path
from hermes_teamwork.core.sentinel import Sentinel
from hermes_teamwork.runners.mock_runner import MockAgentRunner

# Initialize runner and target workspace
runner = MockAgentRunner()
workspace = Path("./my_project").resolve()

# Launch Sentinel mission
sentinel = Sentinel(workspace_root=workspace, runner=runner)
result = sentinel.run("Build a rate limiting middleware with token bucket algorithm")

print(f"Status:    {result.status}")
print(f"Run ID:    {result.run_id}")
print(f"Artifacts: {result.run_dir}")
```

### 4. Running the Standalone Executable Examples

Hermes Teamwork provides ready-to-run example scripts in the `examples/` directory:

```bash
# Run offline deterministic mock workflow (Zero network required)
python3 examples/run_offline_mock.py

# Run live 9router verification (Local port 20128)
python3 examples/run_live_9router.py
```

---

## 📚 Documentation Index

For comprehensive guides, architectural deep dives, and full API references, explore our documentation suite:

| Document | Description |
|---|---|
| 📖 [Architecture Specification](docs/ARCHITECTURE.md) | In-depth breakdown of the 3-wave model, Adversarial Review Gate, State Engine, and Succession Protocol. |
| 🛠️ [Installation Guide](docs/INSTALLATION.md) | Prerequisites, environment configuration, dependency management, and CLI verification. |
| ⚙️ [Configuration Guide](docs/CONFIGURATION.md) | Configuration schema (`hermes_teamwork.yaml`), environment variables, and local 9router / LLM setup. |
| 🔍 [API Reference](docs/API_REFERENCE.md) | Complete module, class, and method signatures for Core (`state`, `gate`, `orchestrator`, `sentinel`), Runners, and Config. |
| 💡 [Runnable Examples Guide](docs/RUNNABLE_EXAMPLES.md) | Step-by-step tutorials covering offline mock runs, live 9router workflows, CLI usage, and programmatic embedding. |

---

## 🧪 Testing & Verification

Hermes Teamwork includes a dual-track automated verification suite designed to run offline deterministically or against live endpoints.

### Running Unit & Integration Tests (174 Tests)

```bash
pytest tests/unit/ tests/integration/
```

### Running Opaque-Box E2E Tests (516 Tests)

```bash
pytest tests/e2e_opaque/ -m "not live"
```

### Running Live 9router E2E Verification

```bash
# Standalone live verification runner
python3 hermes_teamwork/scripts/verify_live_9router.py

# Live pytest canary (requires running 9router endpoint on port 20128)
pytest tests/live/ -m live
```

---

## 📦 Packaging & Project Structure

```
hermes_teamwork/
├── pyproject.toml              # PEP 621 packaging & dependencies
├── hermes_teamwork/            # Core integration package
│   ├── cli.py                  # Standalone CLI entrypoint (`hermes-teamwork`)
│   ├── config.py               # YAML & environment variable configuration loader
│   ├── core/                   # Architecture engine
│   │   ├── state.py            # Isolated .agents/teamwork/ state persistence
│   │   ├── gate.py             # Strict AND Adversarial Review Gate
│   │   ├── orchestrator.py     # Wave-based Project Orchestrator & Succession
│   │   └── sentinel.py         # Sentinel lifecycle manager & Victory Auditor
│   ├── runners/                # Pluggable execution backends
│   │   ├── base.py             # BaseAgentRunner interface protocol
│   │   ├── mock_runner.py      # Offline deterministic multi-round mock runner
│   │   ├── openai_runner.py    # OpenAI-compatible / 9router runner
│   │   └── hermes_runner.py    # Native Hermes AIAgent bridge
│   ├── prompts/                # Immutable role prompt templates
│   └── scripts/
│       └── verify_live_9router.py  # Standalone live endpoint probe
├── docs/                       # Complete documentation suite
│   ├── ARCHITECTURE.md
│   ├── INSTALLATION.md
│   ├── CONFIGURATION.md
│   ├── API_REFERENCE.md
│   └── RUNNABLE_EXAMPLES.md
├── examples/                   # Executable reference scripts
│   ├── run_offline_mock.py     # Offline mock E2E example
│   └── run_live_9router.py     # Live 9router E2E example
└── tests/                      # Automated test suite (690+ tests)
    ├── unit/                   # Unit test cases
    ├── integration/            # Multi-wave & Sentinel mock integration tests
    ├── e2e_opaque/             # Opaque-box requirements verification suite
    └── live/                   # Live 9router canaries
```

---

## 📄 License

Hermes Teamwork is open-source software licensed under the [MIT License](LICENSE).
