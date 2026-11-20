# Hermes Teamwork: Configuration Guide

This document details the configuration system for **Hermes Teamwork**, covering YAML file configuration, environment variable overrides, parameter precedence, and setting up local LLM inference engines (such as 9router) serving Nous Research models.

---

## 1. Configuration Resolution & Precedence

When initializing agents and orchestrators, `load_config()` evaluates configuration sources in the following strict order of precedence (highest to lowest):

```
┌───────────────────────────────────────────────────────────┐
│ 1. CLI Arguments (e.g. `--runner`, `--workspace`)         │  (Highest)
├───────────────────────────────────────────────────────────┤
│ 2. Environment Variables (`HERMES_TEAMWORK_*`)            │
├───────────────────────────────────────────────────────────┤
│ 3. YAML Configuration File (`hermes_teamwork.yaml`)       │
├───────────────────────────────────────────────────────────┤
│ 4. Built-in Internal Defaults                             │  (Lowest)
└───────────────────────────────────────────────────────────┘
```

If a value is specified at multiple levels, the higher-level source takes precedence.

---

## 2. YAML Configuration File (`hermes_teamwork.yaml`)

You can define project defaults by placing a `hermes_teamwork.yaml` file in your workspace root, or by passing the `--config <path>` flag to the CLI.

### Complete Annotated YAML Schema

```yaml
# ==============================================================================
# Hermes Teamwork Configuration Schema
# ==============================================================================

# Backend runner used to execute subagents.
# Options:
#   - 'mock': Offline deterministic simulator (zero network, fast testing)
#   - '9router': Local OpenAI-compatible gateway (recommended for local LLMs)
#   - 'openai': Generic OpenAI-compatible API endpoint
#   - 'native': Direct Hermes Agent AIAgent runtime integration
runner: "9router"

# Model identifier requested in chat completion payloads
model: "nous-hermes-2-yi-34b"

# Base URL of the OpenAI-compatible endpoint (Synonym: api_base)
base_url: "http://localhost:20128/v1"

# Authorization key for the API (default: 'mock-key' for local endpoints)
api_key: "mock-key"

# Maximum Adversarial Review Gate iterations per milestone before failure
# (Synonym: max_milestone_iterations)
max_iterations: 4

# Cumulative subagent spawn limit per Orchestrator generation before triggering Succession
succession_threshold: 16

# Timeout in seconds for runner executions and HTTP requests
timeout: 120

# Sentinel periodic progress reporting schedule (Standard cron syntax)
reporting_cron: "*/8 * * * *"

# Sentinel subagent liveness watchdog schedule (Standard cron syntax)
liveness_cron: "*/10 * * * *"

# Isolate Wave 3 verifier execution in a sandboxed temporary probe directory
probe_dir_isolation: true
```

---

## 3. Configuration Parameter Reference

The following table lists all configuration keys supported by `ConfigDict`:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `runner` | `str` | `"mock"` | Execution backend: `"mock"`, `"9router"`, `"openai"`, or `"native"`. |
| `model` | `str` | `"nous-hermes-2-yi-34b"` | Model identifier passed to inference backends. |
| `base_url` | `str` | `"http://localhost:20128/v1"` | URL for OpenAI-compatible completions. Synonym: `api_base`. |
| `api_key` | `str` | `"mock-key"` | Authorization token for endpoint. Local endpoints accept any string. |
| `max_iterations` | `int` | `4` | Maximum gate iterations allowed per milestone. Synonym: `max_milestone_iterations`. |
| `succession_threshold` | `int` | `16` | Cumulative subagent spawn limit per orchestrator generation. |
| `timeout` | `float` / `int` | `120` | Timeout in seconds for HTTP completions and runner invocations. |
| `reporting_cron` | `str` | `"*/8 * * * *"` | Cron expression for periodic progress reporting (every 8 minutes). |
| `liveness_cron` | `str` | `"*/10 * * * *"` | Cron expression for subagent liveness monitoring (every 10 minutes). |
| `probe_dir_isolation` | `bool` | `True` | Run verifiers in `mktemp -d teamwork_probe.XXXXXX` (`chmod 700`). |

### Dynamic Bidirectional Aliasing

`ConfigDict` provides automatic synchronization between common parameter aliases:
- Updating `max_iterations` automatically updates `max_milestone_iterations`, and vice-versa.
- Reading or setting `base_url` is synchronized with `api_base`.
- Access is supported via both dictionary indexing (`cfg['runner']`) and attribute syntax (`cfg.runner`).

---

## 4. Environment Variables

Environment variables allow runtime configuration without editing configuration files or command-line scripts:

| Environment Variable | Target Parameter | Accepted Values / Example |
|---|---|---|
| `HERMES_TEAMWORK_RUNNER` | `runner` | `mock`, `9router`, `openai`, `native` |
| `TEAMWORK_MODE` | `runner` (Fallback) | `mock`, `9router`, `openai`, `native` |
| `HERMES_TEAMWORK_MODEL` | `model` | `nous-hermes-2-yi-34b`, `hermes-3-llama-3.1-8b` |
| `HERMES_TEAMWORK_BASE_URL` | `base_url` | `http://127.0.0.1:20128/v1` |
| `HERMES_TEAMWORK_API_KEY` | `api_key` | `mock-key` or your API token |
| `HERMES_TEAMWORK_MAX_ITERATIONS` | `max_iterations` | `3`, `5` |
| `HERMES_TEAMWORK_SUCCESSION_THRESHOLD` | `succession_threshold` | `14`, `16`, `20` |
| `HERMES_TEAMWORK_TIMEOUT` | `timeout` | `60`, `180` |

### Example: Setting Environment Variables in Shell

```bash
export HERMES_TEAMWORK_RUNNER="9router"
export HERMES_TEAMWORK_BASE_URL="http://localhost:20128/v1"
export HERMES_TEAMWORK_MODEL="nous-hermes-2-yi-34b"
export HERMES_TEAMWORK_SUCCESSION_THRESHOLD=16

# Run mission with environment overrides active
hermes-teamwork "Refactor authentication system"
```

---

## 5. Local LLM Configuration with 9router & Nous-Hermes-2-Yi-34B

Hermes Teamwork is optimized to run locally against [9router](https://github.com/NousResearch/9router) or other OpenAI-compatible engines hosting Nous Research's **Nous-Hermes-2-Yi-34B** or **Hermes-3-Llama-3.1-8B**.

### Default Port & Endpoint Specifications

- **Default Port**: `20128`
- **Default Base URL**: `http://localhost:20128/v1`
- **Chat Completions Endpoint**: `http://localhost:20128/v1/chat/completions`
- **Target Model**: `nous-hermes-2-yi-34b`

### Starting the Local LLM Server

You can host the model using any of the following backends:

#### 1. Using 9router (Recommended)
```bash
9router --port 20128 --model nous-hermes-2-yi-34b
```

#### 2. Using vLLM
```bash
python3 -m vllm.entrypoints.openai.api_server \
  --port 20128 \
  --model NousResearch/Nous-Hermes-2-Yi-34B \
  --served-model-name nous-hermes-2-yi-34b \
  --tensor-parallel-size 1 \
  --max-model-len 4096
```

#### 3. Using llama.cpp (`llama-server`)
```bash
./llama-server \
  -m models/nous-hermes-2-yi-34b.Q4_K_M.gguf \
  --port 20128 \
  --alias nous-hermes-2-yi-34b \
  -c 4096
```

### Strict Batch Execution (`stream=False`)

`OpenAICompatibleRunner` strictly enforces `stream=False` in completion requests. This guarantees that model responses (including structured 5-component `handoff.md` reports, code diffs, and verdicts) are received atomically as a single payload, preventing partial streaming parse failures.

### Verifying Endpoint Health

Verify that your local server is responding before launching missions:

```bash
# 1. Quick curl probe for model list
curl http://localhost:20128/v1/models

# 2. Probe chat completions
curl http://localhost:20128/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer mock-key" \
  -d '{
    "model": "nous-hermes-2-yi-34b",
    "messages": [{"role": "user", "content": "ping"}],
    "stream": false
  }'
```

Alternatively, run the built-in live verification script:

```bash
python3 -m hermes_teamwork.scripts.verify_live_9router --host 127.0.0.1 --port 20128
```

If the endpoint is reachable, the probe outputs:
```text
=== 9router Live Verification ===
[1/4] Probing TCP port 20128 on 127.0.0.1... [PASS]
[2/4] Probing HTTP chat completions endpoint... [PASS]
[3/4] Testing isolated Subagent Dispatch... [PASS]
[4/4] Executing Sentinel E2E mission with live runner... [PASS]
=== Live 9router Verification PASSED (Exit Code: 0) ===
```

---

## 6. Related Documentation

- For complete architecture details: [ARCHITECTURE.md](ARCHITECTURE.md)
- For package installation: [INSTALLATION.md](INSTALLATION.md)
- For module and class APIs: [API_REFERENCE.md](API_REFERENCE.md)
- For executable examples and walkthroughs: [RUNNABLE_EXAMPLES.md](RUNNABLE_EXAMPLES.md)
- Return to repository root: [README.md](../README.md)
