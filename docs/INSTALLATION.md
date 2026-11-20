# Hermes Teamwork: Installation & Setup Guide

This guide provides instructions for installing, configuring, and verifying **Hermes Teamwork** across development, testing, and production environments.

---

## 1. System Requirements & Prerequisites

Before installing Hermes Teamwork, verify that your environment meets the following specifications:

| Component | Minimum Requirement | Recommended |
|---|---|---|
| **Python** | Python 3.10+ | Python 3.11 or 3.12 |
| **Operating System** | Linux (Ubuntu 20.04+, Debian 11+, RHEL 8+), macOS (12+), Windows (WSL2) | Linux x86_64 or macOS Apple Silicon |
| **Package Manager** | `pip` >= 23.0 or `uv` >= 0.1.0 | `pip` or `uv` |
| **Version Control** | Git 2.30+ | Git 2.40+ |
| **Hardware** | 2 CPU cores, 4GB RAM (Mock Runner) | 8+ CPU cores, 32GB RAM, GPU with 24GB+ VRAM (for local 9router with 34B LLMs) |

---

## 2. Installation Methods

Hermes Teamwork is packaged as a modular, standalone component within the Hermes Agent repository.

### Option A: Local Editable Installation (Recommended for Development)

An editable installation links your active environment directly to the source code, allowing changes to take effect immediately without re-installing:

```bash
# 1. Clone the repository
git clone https://github.com/NousResearch/hermes-agent.git hermes_teamwork
cd hermes_teamwork

# 2. Create and activate a clean Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install in editable mode
pip install -e .
```

> **Note on `setup.py` Build Guard**:  
> The upstream repository includes a safety guard in `setup.py` that restricts standalone wheel builds (`pip wheel .` or `python -m build`) outside Nix environments (`HERMES_NIX_BUILD=1`). However, development installations (`pip install -e .` or `uv pip install -e .`) invoke the standard PEP 660 `build_editable` hook, which installs cleanly and correctly.

### Option B: Standalone Installation without Optional Upstream Dependencies

If you only need the multi-agent Teamwork core and want to avoid installing heavy upstream dependencies (e.g. web frameworks or optional tool bindings), install using the `--no-deps` flag:

```bash
cd hermes_teamwork
source .venv/bin/activate
pip install -e . --no-deps

# Install core runtime requirements manually
pip install requests pydantic pyyaml ruamel.yaml pytest
```

### Option C: Using Hermes Environment Activation Script

The repository provides shell environment bootstrap scripts that configure paths and dependencies:

```bash
cd hermes_teamwork

# For Bash/Zsh shells
source ./activate

# For Fish shell
source ./activate.fish

# For PowerShell (Windows)
.\activate.ps1
```

### Option D: Fast Installation with `uv`

If you use [uv](https://github.com/astral-sh/uv), environment setup and installation take only seconds:

```bash
cd hermes_teamwork
uv venv
source .venv/bin/activate
uv pip install -e .
```

---

## 3. Dependency Specification

### Core Dependencies

These packages are installed automatically or can be installed via `pip`:

| Package | Minimum Version | Purpose |
|---|---|---|
| `requests` | `>= 2.31.0` | HTTP communications with local 9router / OpenAI endpoints |
| `pydantic` | `>= 2.0.0` | Strict data validation and schema definitions |
| `pyyaml` / `ruamel.yaml` | `>= 6.0` / `>= 0.18.0` | Parsing `hermes_teamwork.yaml` configuration files |
| `prompt_toolkit` | `>= 3.0.0` | Interactive terminal UI and command parsing |

### Optional Runtime Dependencies

| Package | Purpose | Installation |
|---|---|---|
| `hermes-agent` | Official Hermes AI agent runtime and system toolsets | Included in repo |
| `llama-cpp-python` | In-process local GGUF model execution | `pip install llama-cpp-python` |
| `vllm` | High-throughput local LLM serving | `pip install vllm` |
| `pytest` | Verification and test suite execution | `pip install pytest` |

---

## 4. Verifying the Installation

After completing installation, verify that the CLI entrypoints and core modules function properly.

### 1. Verify CLI Executable

Check that the console script is registered and prints the version:

```bash
hermes-teamwork --version
```

*Expected output:*
```text
hermes-teamwork 0.1.0
```

Inspect the available command-line flags:

```bash
hermes-teamwork --help
```

### 2. Verify Module Invocation via `python3 -m`

If running without having activated the virtual environment's `PATH`, or when executing from an uninstalled source checkout, ensure `PYTHONPATH=.` is set so Python resolves the package correctly:

```bash
PYTHONPATH=. python3 -m hermes_teamwork.cli --version
```

### 3. Run an Offline Smoke Test

Execute a quick multi-agent mission using the offline mock runner:

```bash
hermes-teamwork --runner mock --request "Run installation smoke test"
```

*Expected output:*
```text
Final Result: SentinelResult(status='SUCCESS', victory_verdict='VICTORY CONFIRMED', audit_count=1, ...)
```

---

## 5. Running the Test Suite

Run the automated verification suite to confirm that all unit and integration tests pass in your environment:

```bash
# Run unit and integration tests (174 tests, zero network required)
pytest tests/unit/ tests/integration/

# Run complete opaque-box E2E test suite (516 tests)
pytest tests/e2e_opaque/ -m "not live"
```

---

## 6. Troubleshooting & FAQ

### Q1: `ModuleNotFoundError: No module named 'hermes_cli'` or `'hermes_teamwork'`
**Cause**: The package was not installed in editable mode, or the virtual environment is inactive.  
**Solution**:
1. Activate your virtual environment: `source .venv/bin/activate`.
2. Ensure you ran `pip install -e .` from the repository root.
3. Alternatively, prepend `PYTHONPATH=.` when invoking commands: `PYTHONPATH=. python3 -m hermes_teamwork.cli --help`.

### Q2: `RuntimeError: Building wheels or sdists for hermes-agent is not supported`
**Cause**: You attempted to build a standalone binary wheel using `python -m build` or `pip wheel .`.  
**Solution**: Use editable development mode (`pip install -e .`), which invokes the PEP 660 editable build backend rather than `bdist_wheel`.

### Q3: How do I test with 9router if I do not have a GPU?
**Solution**: Use the built-in offline mock runner:
```bash
hermes-teamwork --runner mock --request "My task"
```
The mock runner executes all 3 waves, gate evaluations, and Sentinel audits deterministically without requiring any external network or GPU resources.

---

## 7. Next Steps

- Learn about the system design: [ARCHITECTURE.md](ARCHITECTURE.md)
- Configure YAML options and local LLM endpoints: [CONFIGURATION.md](CONFIGURATION.md)
- Explore API documentation: [API_REFERENCE.md](API_REFERENCE.md)
- Run sample scripts: [RUNNABLE_EXAMPLES.md](RUNNABLE_EXAMPLES.md)
- Return to repository root: [README.md](../README.md)
