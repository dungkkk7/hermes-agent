# Hermes Teamwork: Complete API Reference

This document provides formal API specifications, type signatures, parameter descriptions, return types, and exceptions for all modules and classes in `hermes_teamwork`.

---

## Table of Contents

1. [`hermes_teamwork.core.state`](#1-hermes_teamworkcorestate)
2. [`hermes_teamwork.core.gate`](#2-hermes_teamworkcoregate)
3. [`hermes_teamwork.core.orchestrator`](#3-hermes_teamworkcoreorchestrator)
4. [`hermes_teamwork.core.sentinel`](#4-hermes_teamworkcoresentinel)
5. [`hermes_teamwork.runners`](#5-hermes_teamworkrunners)
6. [`hermes_teamwork.config`](#6-hermes_teamworkconfig)
7. [`hermes_teamwork.cli`](#7-hermes_teamworkcli)
8. [Related Documentation](#8-related-documentation)

---

## 1. `hermes_teamwork.core.state`

Provides state persistence, run isolation under `.agents/teamwork/<run_id>/`, immutable frozen prompts, working memory (`BRIEFING.md`) with append-only locked sections, liveness heartbeats (`progress.md`), structured handoffs (`handoff.md`), and negative knowledge base management (`DEAD_ENDS.md`).

### Exceptions

#### `class StateError(Exception)`
Base class for all state engine exceptions.

#### `class LockedSectionTamperError(StateError)`
Raised when an agent modifies or deletes existing lines in append-only locked sections (e.g. `## 🔒 My Identity`, `## 🔒 Key Constraints`, `## 🔒 My Workflow`).

#### `class ImmutableStateViolationError(StateError)`
Raised when attempting to overwrite or mutate frozen state files, notably `ORIGINAL_REQUEST.md`.

#### `class HandoffValidationError(StateError)`
Raised when a `handoff.md` report is missing one or more of the 5 mandatory sections.

---

### Constants

```python
LOCKED_SECTION_HEADERS: List[str] = [
    "## 🔒 My Identity",
    "## 🔒 Key Constraints",
    "## 🔒 My Workflow",
]

MANDATORY_HANDOFF_SECTIONS: List[str] = [
    "Observation",
    "Logic Chain",
    "Caveats",
    "Conclusion",
    "Verification Method",
]

MAX_BRIEFING_LINES: int = 100
DEFAULT_LIVENESS_TIMEOUT_SECONDS: float = 600.0
```

---

### Data Models

#### `dataclass HandoffReport`
Encapsulates a structured 5-component handoff report.

```python
@dataclass
class HandoffReport:
    agent_name: str
    role: str
    verdict: str
    observation: str
    logic_chain: str
    conclusion: str
    verification_method: str
    caveats: str = "No caveats."
    summary: str = ""
    defect: Optional[str] = None
    remaining_work: Optional[str] = None
    source_file: str = "handoff.md"
```

- **`render_markdown() -> str`**: Renders the handoff into standard Markdown formatting.
- **`validate() -> List[str]`**: Validates that all five mandatory sections are populated. Returns list of missing section names (empty if valid).

#### `dataclass DeadEndRecord`
Represents an entry in the negative knowledge base (`DEAD_ENDS.md`).

```python
@dataclass
class DeadEndRecord:
    iteration: int
    approach: str
    why_failed: str
    files_touched: List[str]
    milestone: Optional[str] = None
    timestamp: str = ""
```

#### `dataclass ProgressState`
Parsed state of an agent's `progress.md` heartbeat.

```python
@dataclass
class ProgressState:
    agent_name: str
    last_visited: Optional[datetime.datetime]
    status: str
    checklist: List[Tuple[str, bool]]
    notes: str = ""
```

---

### Classes

#### `class AgentState`
Manages an individual agent's directory under `.agents/teamwork/<run_id>/<agent_name>/`.

```python
class AgentState:
    def __init__(self, run_dir: Path, agent_name: str, archetype: str) -> None: ...
```

- **`classmethod create(...) -> AgentState`**:
  ```python
  @classmethod
  def create(
      cls,
      run_dir: Path,
      agent_name: str,
      archetype: str,
      mission: str = "",
      roles: Optional[List[str]] = None,
      working_dir: Optional[Path] = None,
      parent_id: str = "",
      milestone: str = "",
      key_constraints: Optional[List[str]] = None,
      workflow: str = "",
  ) -> AgentState: ...
  ```
  Initializes directory layout and default `BRIEFING.md` with locked sections.
- **`init_briefing(...) -> Path`**: Writes initial `BRIEFING.md`.
- **`read_briefing() -> str`**: Returns current contents of `BRIEFING.md`.
- **`update_briefing(new_content: str, max_lines: int = 100) -> Path`**: Updates `BRIEFING.md`. Verifies that append-only locked sections (`## 🔒 ...`) have not been tampered with; prunes older mutable sections into `BRIEFING_ARCHIVE.md` if line limit is exceeded.
- **`write_dispatch(task_description: str, context_files: Optional[List[Path]] = None, constraints: Optional[List[str]] = None, caller_id: Optional[str] = None) -> Path`**: Appends or writes a dispatch task to `DISPATCH.md`.
- **`write_progress(status: str, items: Optional[List[Tuple[str, bool]]] = None, notes: str = "") -> Path`**: Writes `progress.md` with current UTC timestamp (`Last visited: ...`).
- **`get_last_visited() -> Optional[datetime.datetime]`**: Returns parsed timestamp of last visit.
- **`is_healthy(timeout_seconds: float = 600.0) -> bool`**: Returns `True` if `Last visited` timestamp is within `timeout_seconds`.
- **`write_handoff(report: HandoffReport) -> Path`**: Writes and validates `handoff.md`.
- **`parse_handoff() -> HandoffReport`**: Parses and validates `handoff.md` from disk into a `HandoffReport`.

#### `class TeamworkRunState`
Root state manager for a run instance located at `<base_state_dir | workspace_root/.agents/teamwork>/<run_id>/`.

```python
class TeamworkRunState:
    def __init__(
        self,
        base_dir: Optional[Union[Path, str]] = None,
        workspace_root: Optional[Union[Path, str]] = None,
        run_id: Optional[str] = None,
        base_state_dir: Optional[Union[Path, str]] = None,
    ) -> None: ...
```

- **`get_or_create_agent_state(agent_name: str, archetype: str = "worker", **kwargs) -> AgentState`**: Returns or initializes an `AgentState`.
- **`record_original_request(user_request: str, overwrite: bool = False) -> Path`**: Writes `ORIGINAL_REQUEST.md`. Raises `ImmutableStateViolationError` if already present with differing content and `overwrite=False`.
- **`read_original_request() -> str`**: Reads frozen prompt from disk.
- **`init_gate_status(milestone: str, iteration: int) -> Path`**: Initializes table header in `GATE_STATUS.md`.
- **`append_gate_verdict(agent_name: str, role: str, verdict: str, source: str = "handoff.md", notes: str = "") -> None`**: Appends individual verdict line to `GATE_STATUS.md`.
- **`record_gate_result(result: str, reason: str = "") -> None`**: Appends gate outcome summary to `GATE_STATUS.md`.
- **`record_dead_end(iteration: int, approach: str, reason: str = "", files: Optional[List[str]] = None, why_failed: str = "", files_touched: Optional[List[str]] = None, milestone: str = "") -> Path`**: Appends failed approach to `DEAD_ENDS.md`.
- **`read_dead_ends() -> List[DeadEndRecord]`**: Parses all failure records from `DEAD_ENDS.md`.

---

## 2. `hermes_teamwork.core.gate`

Implements the zero-trust Adversarial Review Gate and the 6-step consensus pipeline.

### Enums & Models

#### `class Verdict(str, Enum)`
Supported agent verdict tokens:
- `APPROVE`: Unconditional approval.
- `APPROVE_WITH_NITS`: Approval with non-blocking suggestions.
- `REQUEST_CHANGES`: Rejection requiring implementation fixes.
- `CLEAN`: Forensic Auditor confirms clean git diff, scope hygiene, and untampered test assertions.
- `INTEGRITY_VIOLATION`: Forensic Auditor detects test weakening, cheating, or unauthorized scope modifications. Triggers instant binary veto.
- `DONE`: Worker completed all assigned requirements.
- `FAIL`: Execution failure or incomplete task.

#### `dataclass GateVerdict`
```python
@dataclass
class GateVerdict:
    agent_name: str
    role: str
    verdict: str
    details: str = ""
    defect: Optional[str] = None
    source_file: str = "handoff.md"
```
- Properties: `is_clean`, `is_integrity_violation`, `is_approved`, `is_done`, `is_request_changes`.

#### `dataclass GateResult`
```python
@dataclass
class GateResult:
    passed: bool
    reason: str
    defect_ledger: List[str]
    binary_veto_triggered: bool
    adversarial_veto_triggered: bool
    verdicts_evaluated: List[GateVerdict]
```
- **`format_status_line() -> str`**: Returns formatted string summarizing gate outcome.
- Supports tuple unpacking: `passed, reason = gate_result`.

---

### Class `AdversarialGate`

```python
class AdversarialGate:
    @classmethod
    def evaluate(
        cls,
        verdicts: List[GateVerdict],
        strict_quorum: bool = True,
        min_reviewers: int = 1,
        min_challengers: int = 1,
        require_auditor: bool = True,
        require_worker: bool = True,
    ) -> GateResult: ...

    @classmethod
    def parse_verdict_from_handoff(
        cls,
        agent_name: str,
        role: str,
        handoff_text: str,
        source_file: str = "handoff.md",
    ) -> GateVerdict: ...
```

---

## 3. `hermes_teamwork.core.orchestrator`

Implements the multi-wave Project Orchestrator, dispatch-only invariant enforcement, and the Succession Protocol.

### Exceptions & Enums

#### `class DispatchOnlyViolationError(RuntimeError)`
Raised when the orchestrator attempts to edit source files (`modify_source_file`) or run tests directly (`execute_test_command`).

#### `class MilestoneStatus(str, Enum)`
`PLANNED`, `IN_PROGRESS`, `DONE`, `FAILED`, `BLOCKED`.

---

### Data Models

#### `dataclass OrchestratorConfig`
```python
@dataclass
class OrchestratorConfig:
    succession_threshold: int = 16
    max_milestone_iterations: int = 4
    max_overall_iterations: int = 32
    default_explorers_count: int = 3
    probe_isolation: bool = True
    hang_nudge_timeout_seconds: int = 600
    hang_kill_timeout_seconds: int = 3600
```

#### `dataclass Milestone`
```python
@dataclass
class Milestone:
    id: str
    title: str
    scope_files: List[str]
    dependencies: List[str] = field(default_factory=list)
    status: MilestoneStatus = MilestoneStatus.PLANNED
    iteration: int = 0
    max_iterations: int = 4
```

---

### Class `ProjectOrchestrator`

```python
class ProjectOrchestrator:
    def __init__(
        self,
        run_state: TeamworkRunState,
        runner: BaseAgentRunner,
        generation: int = 1,
        predecessor_handoff: Optional[Path] = None,
        config: Optional[OrchestratorConfig] = None,
        is_sub_orchestrator: bool = False,
        sub_orchestrator_id: Optional[str] = None,
    ) -> None: ...
```

- **`modify_source_file(...)`**: Raises `DispatchOnlyViolationError`.
- **`execute_test_command(...)`**: Raises `DispatchOnlyViolationError`.
- **`run_survey_phase() -> Dict[str, Any]`**: Dispatches 3 parallel survey explorers (`explorer_survey_codebase`, `spec_miner_survey`, `explorer_survey_tests`).
- **`should_decompose(milestone_count: int, has_dual_tracks: bool = False) -> bool`**: Returns `True` if Path 2A decomposition is required.
- **`execute_milestones_2a(milestones: List[Milestone]) -> bool`**: Executes Path 2A by dispatching dedicated sub-orchestrators.
- **`execute_milestone(...) -> bool`**:
  ```python
  def execute_milestone(
      self,
      milestone_id: str,
      milestone_title: str,
      scope_files: List[str],
      max_iterations: Optional[int] = None,
      explorer_handoffs: Optional[List[Path]] = None,
      defect_ledger: Optional[List[str]] = None,
      start_iteration: int = 1,
  ) -> bool: ...
  ```
  Executes the 3-wave milestone loop (Explorers -> Worker -> 5 Verifiers -> Gate). Triggers Succession when `spawn_count >= succession_threshold`.
- **`register_timer(timer_id: str) -> None`**: Registers an active safety timer for cleanup during succession.

---

## 4. `hermes_teamwork.core.sentinel`

Implements the user-facing Sentinel lifecycle agent, background watchdog crons, and the independent Victory Audit loop.

### Enums & Models

#### `class TaskArchetype(str, Enum)`
`SWE_LIGHT`, `MILESTONE_PIPELINE`, `DOCUMENT_REVIEW`, `FORMAL_PROOF`, `PIPELINE`.

#### `class VictoryAuditVerdict(str, Enum)`
`VICTORY_CONFIRMED`, `VICTORY_REJECTED`, `EXHAUSTED`.

#### `class LivenessStatus(str, Enum)`
`HEALTHY`, `NUDGE_REQUIRED`, `WARNING_STALLED`, `CRITICAL_KILL`.

#### `dataclass SentinelResult`
```python
@dataclass
class SentinelResult:
    status: str
    run_id: str
    run_dir: str
    archetype: TaskArchetype
    victory_verdict: Optional[str] = None
    audit_count: int = 0
    final_report: str = ""
    error_message: Optional[str] = None
    milestones_completed: List[str] = field(default_factory=list)
```
- Methods: `to_dict() -> Dict[str, Any]`, dictionary key access via `result['status']` or `result.get('status')`.

---

### Class `Sentinel`

```python
class Sentinel:
    def __init__(
        self,
        workspace_root: Union[Path, str],
        runner: BaseAgentRunner,
        run_id: Optional[str] = None,
        base_state_dir: Optional[Union[Path, str]] = None,
        auto_start_crons: bool = False,
    ) -> None: ...
```

- **`classify_task(user_request: str) -> TaskArchetype`**: Regex intent classification into `TaskArchetype`.
- **`record_original_request(user_request: str) -> Path`**: Freezes immutable user request.
- **`initialize_project_spec(user_request: str, archetype: TaskArchetype) -> Path`**: Writes initial `PROJECT.md`.
- **`generate_progress_report() -> str`**: Produces 3–5 bullet summary for the user (Reporting Cron).
- **`check_liveness(target_agent_id: Optional[str] = None) -> Dict[str, Any]`**: Checks subagent `progress.md` timestamps against thresholds (Watchdog Cron).
- **`start_background_crons() -> None`**: Launches reporting (`*/8m`) and liveness (`*/10m`) background threads.
- **`stop_background_crons() -> None`**: Stops active background cron threads.
- **`dispatch_victory_audit(audit_round: int) -> Dict[str, Any]`**: Dispatches `VictoryAuditor` in isolated probe directory (`teamwork_probe.XXXXXX`).
- **`run_mission(user_request: str) -> SentinelResult`**: Executes full Sentinel mission. (Alias: `sentinel.run(user_request)`).

---

## 5. `hermes_teamwork.runners`

Execution backend abstraction hierarchy.

### `class BaseAgentRunner(ABC)`

```python
class BaseAgentRunner(ABC):
    @abstractmethod
    def run_agent(
        self,
        agent_id: str,
        archetype: str,
        system_prompt: str,
        dispatch_file: Path,
        state_dir: Path,
        workspace_dir: Path,
    ) -> Dict[str, Any]:
        """
        Executes a subagent and returns dictionary containing:
        {'status': str, 'verdict': str, 'handoff_file': Path, ...}
        """
```

### `class MockAgentRunner(BaseAgentRunner)`

```python
class MockAgentRunner(BaseAgentRunner):
    def __init__(
        self,
        simulate_challenger_failure_rounds: int = 0,
        simulate_auditor_integrity_violation: bool = False,
        simulate_auditor_fail: bool = False,
        simulate_worker_failure: bool = False,
        simulate_reviewer_rejection: bool = False,
        simulate_reviewer_nits: bool = False,
        simulate_victory_audit_failure_rounds: int = 0,
        agent_handler: Optional[Callable[[str, str, Dict[str, Any]], Dict[str, Any]]] = None,
    ) -> None: ...
```
Zero-network deterministic test runner supporting programmable failure injections.

### `class OpenAICompatibleRunner(BaseAgentRunner)`

```python
class OpenAICompatibleRunner(BaseAgentRunner):
    def __init__(
        self,
        api_base: str = "http://localhost:20128/v1",
        base_url: Optional[str] = None,
        model: str = "nous-hermes-2-yi-34b",
        api_key: str = "mock-key",
        timeout: float = 60.0,
        stream: bool = False,
        **kwargs: Any,
    ) -> None: ...
```
Interfaces with 9router or local OpenAI-compatible endpoints. Enforces `stream=False` strictly for deterministic batch completions.

### `class HermesAgentRunner(BaseAgentRunner)`

```python
class HermesAgentRunner(BaseAgentRunner):
    def __init__(
        self,
        model: str = "nous-hermes-2-yi-34b",
        config: Optional[Dict[str, Any]] = None,
        tool_registry: Optional[Any] = None,
        **kwargs: Any,
    ) -> None: ...
```
Native integration with Hermes `AIAgent` and tool execution engines.

---

## 6. `hermes_teamwork.config`

### `class ConfigDict(dict)`
Subclasses standard Python `dict`. Supports both attribute syntax (`cfg.runner`) and dictionary keys (`cfg["runner"]`). Synchronizes bidirectional aliases (`max_iterations` $\leftrightarrow$ `max_milestone_iterations`, `base_url` $\leftrightarrow$ `api_base`).

### `function load_config`

```python
def load_config(config_path: Optional[Union[str, Path]] = None) -> ConfigDict: ...
```
Loads configuration respecting the precedence hierarchy: CLI Arguments > Environment Variables > YAML file > Built-in defaults.

---

## 7. `hermes_teamwork.cli`

Standalone CLI entrypoints.

- **`create_parser() -> argparse.ArgumentParser`**: Constructs CLI argument parser supporting `--runner`, `--mode`, `--request`, `-r`, `--workspace`, `-w`, `--config`, `-c`, `--fail-rounds`, and `--version`.
- **`cli_main(argv: Optional[List[str]] = None) -> int`**: Main execution logic returning integer exit code (`0` for success, `1` for mission failure, `2` for invalid arguments).
- **`main(argv: Optional[List[str]] = None) -> None`**: Console script entrypoint registered in `pyproject.toml` as `hermes-teamwork`.

---

## 8. Related Documentation

- System architecture and execution model: [ARCHITECTURE.md](ARCHITECTURE.md)
- Installation and prerequisites: [INSTALLATION.md](INSTALLATION.md)
- Configuration options: [CONFIGURATION.md](CONFIGURATION.md)
- Runnable scripts and walkthroughs: [RUNNABLE_EXAMPLES.md](RUNNABLE_EXAMPLES.md)
- Return to repository root: [README.md](../README.md)
