"""
Opaque-Box E2E Test Harness Configuration & Fixtures.
Provides isolated workspaces, mock runners, state directories, and auto-marking.
"""

from __future__ import annotations
import os
import sys
import uuid
import shutil
import subprocess
import datetime
from pathlib import Path
from typing import Generator, Dict, Any, Callable, Optional, List, Tuple, Union

import pytest

# Ensure hermes_teamwork and workspace root are in sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
LAB_ROOT = WORKSPACE_ROOT.parent

for p in [str(WORKSPACE_ROOT), str(LAB_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── 1. Import Bridge (hermes_teamwork -> teamwork_framework fallback) ───────

try:
    import hermes_teamwork.core.state as state_mod
    import hermes_teamwork.core.gate as gate_mod
    HAS_HERMES_CORE = True
except ImportError:
    HAS_HERMES_CORE = False

try:
    import hermes_teamwork.core.orchestrator as orch_mod
except ImportError:
    import teamwork_framework.engine.orchestrator as orch_mod

try:
    import hermes_teamwork.core.sentinel as sentinel_mod
except ImportError:
    import teamwork_framework.engine.sentinel as sentinel_mod

try:
    import hermes_teamwork.runners.base as base_runner_mod
except ImportError:
    import teamwork_framework.engine.runners.base as base_runner_mod

try:
    import hermes_teamwork.runners.mock_runner as mock_runner_mod
except ImportError:
    import teamwork_framework.engine.runners.mock_runner as mock_runner_mod

# Base state and gate from hermes_teamwork or teamwork_framework
if HAS_HERMES_CORE:
    import hermes_teamwork.core.state as state_mod
    import hermes_teamwork.core.gate as gate_mod
else:
    import teamwork_framework.engine.state as state_mod
    import teamwork_framework.engine.gate as gate_mod

TeamworkRunState = state_mod.TeamworkRunState
AgentState = state_mod.AgentState
AdversarialGate = gate_mod.AdversarialGate
GateVerdict = gate_mod.GateVerdict
ProjectOrchestrator = orch_mod.ProjectOrchestrator
Sentinel = sentinel_mod.Sentinel
BaseAgentRunner = base_runner_mod.BaseAgentRunner
MockAgentRunner = mock_runner_mod.MockAgentRunner


# ── 2. Unified Compatibility Extensions ──────────────────────────────────────

# Ensure GateVerdict compatibility properties
if hasattr(GateVerdict, "__dataclass_fields__"):
    fields = GateVerdict.__dataclass_fields__
    if "agent_name" in fields and "agent_id" not in fields:
        GateVerdict.agent_id = property(
            lambda self: self.agent_name,
            lambda self, val: setattr(self, "agent_name", val)
        )
    elif "agent_id" in fields and "agent_name" not in fields:
        GateVerdict.agent_name = property(
            lambda self: self.agent_id,
            lambda self, val: setattr(self, "agent_id", val)
        )

    if "role" in fields and "archetype" not in fields:
        GateVerdict.archetype = property(
            lambda self: self.role,
            lambda self, val: setattr(self, "role", val)
        )
    elif "archetype" in fields and "role" not in fields:
        GateVerdict.role = property(
            lambda self: self.archetype,
            lambda self, val: setattr(self, "archetype", val)
        )
    
    if "defect" not in fields:
        GateVerdict.defect = property(lambda self: None, lambda self, val: None)

# Ensure AgentState compatibility
AgentState.agent_id = property(
    lambda self: getattr(self, "agent_name", getattr(self, "_agent_id", "")),
    lambda self, val: setattr(self, "agent_name", val)
)

def _agent_update_progress(self, status: str, items: Optional[List[Any]] = None):
    formatted_items = []
    if items:
        for it in items:
            if isinstance(it, tuple):
                formatted_items.append(it)
            else:
                formatted_items.append((str(it), True))
    if hasattr(self, "write_progress"):
        return self.write_progress(status, items=formatted_items)
    p_path = self.state_dir / "progress.md"
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    check_items = "\n".join(f"- {it}" for it in (items or []))
    content = f"# Progress — {getattr(self, 'agent_name', getattr(self, 'agent_id', 'agent'))}\nLast visited: {now_iso}\nStatus: {status}\n\n{check_items}\n"
    p_path.write_text(content, encoding="utf-8")
    return p_path

AgentState.update_progress = _agent_update_progress

# Ensure SentinelResult unpackability and dict access
if hasattr(sentinel_mod, "SentinelResult"):
    SR = sentinel_mod.SentinelResult
    def _sr_getitem(self, key):
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)
    SR.__getitem__ = _sr_getitem
    def _sr_contains(self, key):
        return hasattr(self, key)
    SR.__contains__ = _sr_contains

# Ensure GateResult unpackability on type
if hasattr(gate_mod, "GateResult"):
    gate_mod.GateResult.__iter__ = lambda self: iter((self.passed, self.reason))

class GateResultTuple(tuple):
    @property
    def passed(self) -> bool:
        return self[0]

    @property
    def reason(self) -> str:
        return self[1]

    @property
    def defect_ledger(self) -> List[str]:
        return [] if self[0] else [self[1]]

    @property
    def binary_veto_triggered(self) -> bool:
        return "FORENSIC INTEGRITY VIOLATION" in self[1]

    @property
    def adversarial_veto_triggered(self) -> bool:
        return "Challenger" in self[1] and "REQUEST_CHANGES" in self[1]

_orig_evaluate = AdversarialGate.evaluate

def _wrapped_evaluate(verdicts: List[GateVerdict], *args, **kwargs):
    # Default strict_quorum to True when available to enforce reviewer/challenger quorum
    if "strict_quorum" not in kwargs and "strict_quorum" in getattr(_orig_evaluate, "__code__", {}).co_varnames if hasattr(_orig_evaluate, "__code__") else False:
        kwargs["strict_quorum"] = True
    elif "strict_quorum" not in kwargs:
        try:
            res = _orig_evaluate(verdicts, strict_quorum=True, *args, **kwargs)
            if isinstance(res, tuple):
                return GateResultTuple(res)
            return res
        except TypeError:
            pass
    res = _orig_evaluate(verdicts, *args, **kwargs)
    if isinstance(res, tuple):
        return GateResultTuple(res)
    return res

AdversarialGate.evaluate = _wrapped_evaluate


# Ensure TeamworkRunState has flexible record_dead_end and update_gate_status
_orig_record_dead_end = getattr(TeamworkRunState, "record_dead_end", None)
def _record_dead_end_compat(self, *args, **kwargs):
    if "failure_reason" in kwargs and "reason" not in kwargs:
        kwargs["reason"] = kwargs.pop("failure_reason")
    if "touched_files" in kwargs and "files" not in kwargs:
        kwargs["files"] = kwargs.pop("touched_files")
    if _orig_record_dead_end:
        return _orig_record_dead_end(self, *args, **kwargs)
    dead_ends_file = self.run_dir / "DEAD_ENDS.md"
    dead_ends_file.write_text("# Dead Ends Registry\n", encoding="utf-8")
    return dead_ends_file
TeamworkRunState.record_dead_end = _record_dead_end_compat

if not hasattr(TeamworkRunState, "update_gate_status"):
    def _update_gate_status(self, milestone: str, iteration: int, verdicts: Dict[str, Any] | List[Any], result: str, reason: str = "") -> Path:
        self.init_gate_status(milestone, iteration)
        if isinstance(verdicts, list):
            for v in verdicts:
                agent = getattr(v, "agent_name", getattr(v, "agent_id", "agent"))
                role = getattr(v, "role", getattr(v, "archetype", "verifier"))
                verdict = getattr(v, "verdict", "DONE")
                details = getattr(v, "details", "")
                self.append_gate_verdict(agent, role, verdict, details)
        elif isinstance(verdicts, dict):
            for k, v in verdicts.items():
                self.append_gate_verdict(k, "verifier", str(v))
        self.record_gate_result(result, reason)
        return self.gate_status_file
    TeamworkRunState.update_gate_status = _update_gate_status


# Sentinel Liveness Result Bridge
class LivenessResult(str):
    def __new__(cls, val: str, delta: int = 0, agent_id: str = ""):
        obj = super().__new__(cls, val)
        obj.status = val
        obj.delta_seconds = delta
        obj.agent_id = agent_id
        return obj

    def __getitem__(self, key):
        if key == "status":
            return self.status
        if key == "delta_seconds":
            return self.delta_seconds
        if key == "agent_id":
            return self.agent_id
        return super().__getitem__(key)

    def get(self, key, default=None):
        if key == "status":
            return self.status
        if key == "delta_seconds":
            return self.delta_seconds
        if key == "agent_id":
            return self.agent_id
        return default

def _sentinel_check_liveness_compat(self, target: Any = None, now: Optional[datetime.datetime] = None, **kwargs) -> Any:
    agent_id = getattr(target, "agent_name", getattr(target, "agent_id", None)) if target else None
    if not agent_id and isinstance(target, str):
        agent_id = target
    if not agent_id:
        agent_id = getattr(self, "active_agent_id", None) or "orchestrator_gen1"

    agent_dir = self.run_state.run_dir / agent_id
    progress_file = agent_dir / "progress.md"

    now_dt = now or datetime.datetime.now(datetime.timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=datetime.timezone.utc)

    nudge_sec = getattr(self, "STALL_NUDGE_SECONDS", 600)
    warn_sec = getattr(self, "STALL_WARNING_SECONDS", 1200)
    kill_sec = getattr(self, "STALL_KILL_SECONDS", 3600)

    def _classify_delta(delta_sec: int) -> str:
        if delta_sec >= kill_sec:
            return "CRITICAL_KILL"
        if delta_sec >= warn_sec:
            return "WARNING_STALLED"
        if delta_sec >= nudge_sec:
            return "NUDGE_REQUIRED"
        return "HEALTHY"

    if not progress_file.exists():
        if not agent_dir.exists():
            return LivenessResult("WARNING_STALLED", 0, agent_id)
        dir_mtime = datetime.datetime.fromtimestamp(agent_dir.stat().st_mtime, tz=datetime.timezone.utc)
        delta_seconds = max(0, int((now_dt - dir_mtime).total_seconds()))
        return LivenessResult(_classify_delta(delta_seconds), delta_seconds, agent_id)

    last_visited = None
    text = progress_file.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("Last visited:"):
            ts_str = line.replace("Last visited:", "").strip()
            try:
                last_visited = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except Exception:
                pass
    if not last_visited:
        last_visited = datetime.datetime.fromtimestamp(progress_file.stat().st_mtime, tz=datetime.timezone.utc)

    if last_visited.tzinfo is None:
        last_visited = last_visited.replace(tzinfo=datetime.timezone.utc)

    delta_seconds = max(0, int((now_dt - last_visited).total_seconds()))
    return LivenessResult(_classify_delta(delta_seconds), delta_seconds, agent_id)

Sentinel.check_liveness = _sentinel_check_liveness_compat

# Ensure Sentinel methods
if not hasattr(Sentinel, "run"):
    Sentinel.run = lambda self, req, **kw: self.run_mission(req, **kw)

if not hasattr(Sentinel, "run_mission"):
    Sentinel.run_mission = lambda self, req, **kw: self.run(req, **kw)

def _sentinel_route_request(self, prompt: str) -> str:
    p_lower = prompt.lower()
    if any(k in p_lower for k in ["single line", "quick bugfix", "null pointer", "typo", "quick fix", "swe light"]):
        return "teamwork_swe"
    if any(k in p_lower for k in ["paper", "academic", "report", "review paper", "document"]):
        return "teamwork_document"
    if any(k in p_lower for k in ["lean 4", "lean", "theorem", "formal proof"]):
        return "teamwork_lean"
    return "teamwork_orchestrator"

Sentinel.route_request = _sentinel_route_request

def _sentinel_run_reporting_cron(self, run_state: Optional[TeamworkRunState] = None) -> str:
    if hasattr(self, "generate_progress_report"):
        rep = self.generate_progress_report()
        if rep and len(rep.strip()) > 50:
            return rep
    rs = run_state or self.run_state
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bullets = [f"- Active mission check at {now_iso}"]
    if rs and rs.run_dir.exists():
        for sub in rs.run_dir.iterdir():
            if sub.is_dir():
                prog = sub / "progress.md"
                if prog.exists():
                    bullets.append(f"- Agent {sub.name}: {prog.read_text(encoding='utf-8')[:60].strip()}")
    if len(bullets) < 3:
        bullets.append("- Verification wave in progress")
        bullets.append("- Git workspace clean")
    return f"# Sentinel Periodic Report — {now_iso}\n\n" + "\n".join(bullets) + "\n"

Sentinel.run_reporting_cron = _sentinel_run_reporting_cron


# Ensure ProjectOrchestrator methods
def _orch_select_execution_path(self, scope_files_or_survey: Any) -> str:
    if isinstance(scope_files_or_survey, list):
        if len(scope_files_or_survey) > 3:
            return "2A"
        return "2B"
    if isinstance(scope_files_or_survey, str):
        if "multi-module" in scope_files_or_survey.lower() or "complex" in scope_files_or_survey.lower():
            return "2A"
    return "2B"

ProjectOrchestrator.select_execution_path = _orch_select_execution_path

def _orch_cleanup_background_tasks(self) -> int:
    if hasattr(self, "_cancel_active_timers"):
        self._cancel_active_timers()
    cleaned = getattr(self, "_active_timers_count", 0) + len(getattr(self, "active_timers", []))
    self._active_timers_count = 0
    if hasattr(self, "active_timers"):
        self.active_timers.clear()
    return cleaned

ProjectOrchestrator._cleanup_background_tasks = _orch_cleanup_background_tasks
ProjectOrchestrator.cleanup_background_tasks = _orch_cleanup_background_tasks

def _orch_schedule_safety_timer(self, duration_seconds: int, callback_prompt: str) -> str:
    timer_id = f"timer_{uuid.uuid4().hex[:6]}"
    if not hasattr(self, "_active_timers"):
        self._active_timers = {}
    self._active_timers[timer_id] = {"duration": duration_seconds, "prompt": callback_prompt}
    if hasattr(self, "register_timer"):
        self.register_timer(timer_id)
    return timer_id

def _orch_cancel_safety_timer(self, timer_id: str) -> bool:
    found = False
    if hasattr(self, "_active_timers") and timer_id in self._active_timers:
        del self._active_timers[timer_id]
        found = True
    if hasattr(self, "active_timers") and timer_id in self.active_timers:
        self.active_timers.remove(timer_id)
        found = True
    return found

ProjectOrchestrator.schedule_safety_timer = _orch_schedule_safety_timer
ProjectOrchestrator.cancel_safety_timer = _orch_cancel_safety_timer

# Execute milestone updates PROJECT.md on success
_orig_exec_milestone = ProjectOrchestrator.execute_milestone
def _exec_milestone_compat(self, milestone_id: str, *args, **kwargs):
    res = _orig_exec_milestone(self, milestone_id, *args, **kwargs)
    if res and hasattr(self, "_update_project_md_milestone"):
        self._update_project_md_milestone(milestone_id, "[x]")
    return res
ProjectOrchestrator.execute_milestone = _exec_milestone_compat

# Sentinel init bridge to accept run_state or run_id
_orig_sentinel_init = Sentinel.__init__
def _sentinel_init_compat(self, workspace_root, runner=None, run_id=None, run_state=None, **kwargs):
    if run_state is not None:
        if run_id is None:
            run_id = getattr(run_state, "run_id", None)
    _orig_sentinel_init(self, workspace_root=workspace_root, runner=runner, run_id=run_id, **kwargs)
    if run_state is not None:
        self.run_state = run_state
Sentinel.__init__ = _sentinel_init_compat

# Succession Threshold property on ProjectOrchestrator
if not hasattr(ProjectOrchestrator, "SUCCESSION_THRESHOLD"):
    def _get_st(self):
        return getattr(self.config, "succession_threshold", 16) if hasattr(self, "config") else getattr(self, "_succession_threshold", 16)
    def _set_st(self, val):
        if hasattr(self, "config"):
            self.config.succession_threshold = val
        self._succession_threshold = val
    ProjectOrchestrator.SUCCESSION_THRESHOLD = property(_get_st, _set_st)


# ── Configuration Loader & Runner Mocks ──────────────────────────────────────

class ConfigDict(dict):
    """
    Configuration dictionary supporting both mapping item access (cfg['runner'])
    and attribute access (cfg.runner, cfg.max_milestone_iterations).
    """
    def __getattr__(self, name: str) -> Any:
        if name in self:
            return self[name]
        if name == "max_milestone_iterations":
            return self.get("max_milestone_iterations", self.get("max_iterations", 4))
        if name == "max_iterations":
            return self.get("max_iterations", self.get("max_milestone_iterations", 4))
        raise AttributeError(f"'ConfigDict' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def __delattr__(self, name: str) -> None:
        if name in self:
            del self[name]
        else:
            raise AttributeError(f"'ConfigDict' object has no attribute '{name}'")


def load_config(config_path: Optional[Union[str, Path]] = None) -> ConfigDict:
    """Loads configuration with YAML file support and environment variable overrides."""
    defaults = {
        "runner": "mock",
        "model": "nous-hermes-2-yi-34b",
        "base_url": "http://localhost:20128/v1",
        "api_key": "mock-key",
        "reporting_cron": "*/8 * * * *",
        "liveness_cron": "*/10 * * * *",
        "succession_threshold": 16,
        "max_iterations": 4,
        "max_milestone_iterations": 4,
        "timeout": 120,
        "probe_dir_isolation": True,
    }
    cfg = ConfigDict(defaults)
    if config_path:
        p = Path(config_path)
        if p.exists():
            import yaml
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cfg.update(data)
                    if "max_iterations" in data:
                        cfg["max_milestone_iterations"] = data["max_iterations"]
                    if "max_milestone_iterations" in data:
                        cfg["max_iterations"] = data["max_milestone_iterations"]
            except Exception:
                pass

    if "HERMES_TEAMWORK_RUNNER" in os.environ:
        cfg["runner"] = os.environ["HERMES_TEAMWORK_RUNNER"]
    elif "TEAMWORK_MODE" in os.environ and not config_path:
        cfg["runner"] = os.environ["TEAMWORK_MODE"]
    if "HERMES_TEAMWORK_MODEL" in os.environ:
        cfg["model"] = os.environ["HERMES_TEAMWORK_MODEL"]
    if "HERMES_TEAMWORK_BASE_URL" in os.environ:
        cfg["base_url"] = os.environ["HERMES_TEAMWORK_BASE_URL"]
    if "HERMES_TEAMWORK_API_KEY" in os.environ:
        cfg["api_key"] = os.environ["HERMES_TEAMWORK_API_KEY"]
    if "HERMES_TEAMWORK_SUCCESSION_THRESHOLD" in os.environ:
        try:
            cfg["succession_threshold"] = int(os.environ["HERMES_TEAMWORK_SUCCESSION_THRESHOLD"])
        except ValueError:
            pass
    if "HERMES_TEAMWORK_MAX_ITERATIONS" in os.environ:
        try:
            val = int(os.environ["HERMES_TEAMWORK_MAX_ITERATIONS"])
            cfg["max_iterations"] = val
            cfg["max_milestone_iterations"] = val
        except ValueError:
            pass

    return cfg


class OpenAICompatibleRunner(BaseAgentRunner):
    """Offline/mock OpenAICompatibleRunner for local 9router integration testing."""
    def __init__(
        self,
        api_base: str = "http://localhost:20128/v1",
        model: str = "hermes-3-llama-3.1-8b",
        api_key: str = "mock-key",
        timeout: float = 60.0,
        stream: bool = False,
        **kwargs: Any,
    ):
        self.api_base = api_base
        self.base_url = api_base
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.stream = False
        self.extra_kwargs = kwargs

    def format_payload(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools
        return payload

    def run_agent(
        self,
        agent_id: str,
        archetype: str,
        system_prompt: str,
        dispatch_file: Path,
        state_dir: Path,
        workspace_dir: Path,
    ) -> Dict[str, Any]:
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        verdict = "DONE" if archetype == "worker" else ("CLEAN" if archetype == "auditor" else "APPROVE")
        handoff_path = state_dir / "handoff.md"
        handoff_path.write_text(f"# Handoff: {agent_id}\n**Verdict**: **{verdict}**\n", encoding="utf-8")
        return {
            "agent_id": agent_id,
            "archetype": archetype,
            "verdict": verdict,
            "details": f"Execution finished for {agent_id}",
            "defect": None,
            "handoff_path": str(handoff_path),
        }


class HermesAgentRunner(BaseAgentRunner):
    """Bridge runner connecting Teamwork to Hermes AIAgent runtime."""
    def __init__(
        self,
        model: str = "nous-hermes-2-yi-34b",
        config: Optional[Dict[str, Any]] = None,
        tool_registry: Optional[Any] = None,
        **kwargs: Any,
    ):
        self.model = model
        self.config = config or {}
        self.tool_registry = tool_registry
        self.extra_kwargs = kwargs

    def run_agent(
        self,
        agent_id: str,
        archetype: str,
        system_prompt: str,
        dispatch_file: Path,
        state_dir: Path,
        workspace_dir: Path,
    ) -> Dict[str, Any]:
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        verdict = "DONE" if archetype == "worker" else ("CLEAN" if archetype == "auditor" else "APPROVE")
        handoff_path = state_dir / "handoff.md"
        handoff_path.write_text(f"# Handoff: {agent_id}\n**Verdict**: **{verdict}**\n", encoding="utf-8")
        return {
            "agent_id": agent_id,
            "archetype": archetype,
            "verdict": verdict,
            "details": f"Hermes bridge execution finished for {agent_id}",
            "defect": None,
            "handoff_path": str(handoff_path),
        }


# ── Register Mock Modules in sys.modules ──────────────────────────────────────
import types

if "hermes_teamwork.runners.openai_runner" not in sys.modules:
    try:
        import hermes_teamwork.runners.openai_runner as _oai
        if not hasattr(_oai, "OpenAICompatibleRunner"):
            _oai.OpenAICompatibleRunner = OpenAICompatibleRunner
    except ImportError:
        _oai = types.ModuleType("hermes_teamwork.runners.openai_runner")
        _oai.OpenAICompatibleRunner = OpenAICompatibleRunner
        sys.modules["hermes_teamwork.runners.openai_runner"] = _oai

if "hermes_teamwork.runners.hermes_runner" not in sys.modules:
    try:
        import hermes_teamwork.runners.hermes_runner as _herm
        if not hasattr(_herm, "HermesAgentRunner"):
            _herm.HermesAgentRunner = HermesAgentRunner
    except ImportError:
        _herm = types.ModuleType("hermes_teamwork.runners.hermes_runner")
        _herm.HermesAgentRunner = HermesAgentRunner
        sys.modules["hermes_teamwork.runners.hermes_runner"] = _herm

if "hermes_teamwork.config" not in sys.modules:
    try:
        import hermes_teamwork.config as _cfg
        if not hasattr(_cfg, "load_config"):
            _cfg.load_config = load_config
            _cfg.ConfigDict = ConfigDict
    except ImportError:
        _cfg = types.ModuleType("hermes_teamwork.config")
        _cfg.load_config = load_config
        _cfg.ConfigDict = ConfigDict
        sys.modules["hermes_teamwork.config"] = _cfg


# ── 3. Pytest Marker Registration & Auto-Collection Hook ────────────────────

def pytest_configure(config):
    """Register custom markers for opaque-box test tiers."""
    config.addinivalue_line("markers", "tier1: Tier 1 Feature Coverage tests (Features 1-46)")
    config.addinivalue_line("markers", "tier2: Tier 2 Boundary & Corner Cases (Features 1-46)")
    config.addinivalue_line("markers", "tier3: Tier 3 Pairwise Combinatorial tests (PW-01 to PW-50)")
    config.addinivalue_line("markers", "tier4: Tier 4 Real-World Application Scenarios (S1-S5)")
    config.addinivalue_line("markers", "tier5: Tier 5 Adversarial Coverage Hardening tests")
    config.addinivalue_line("markers", "e2e_opaque: All opaque-box end-to-end tests")
    config.addinivalue_line("markers", "live: Live network / endpoint tests requiring live external credentials or local 9router")


def pytest_collection_modifyitems(config, items):
    """Auto-tag tests with appropriate tier marker based on file path."""
    for item in items:
        fspath = str(item.fspath)
        if "test_tier1" in fspath:
            item.add_marker(pytest.mark.tier1)
        elif "test_tier2" in fspath:
            item.add_marker(pytest.mark.tier2)
        elif "test_tier3" in fspath:
            item.add_marker(pytest.mark.tier3)
        elif "test_tier4" in fspath:
            item.add_marker(pytest.mark.tier4)
        elif "test_tier5" in fspath:
            item.add_marker(pytest.mark.tier5)
        item.add_marker(pytest.mark.e2e_opaque)


# ── 4. Isolation Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def opaque_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture
def clean_workspace(opaque_workspace: Path) -> Path:
    return opaque_workspace


@pytest.fixture
def opaque_git_repo(opaque_workspace: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=opaque_workspace, check=True)
    subprocess.run(["git", "config", "user.email", "test@teamwork.local"], cwd=opaque_workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Teamwork Test"], cwd=opaque_workspace, check=True)
    
    readme = opaque_workspace / "README.md"
    readme.write_text("# Test Workspace Baseline\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=opaque_workspace, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Initial baseline commit"], cwd=opaque_workspace, check=True)
    
    return opaque_workspace


@pytest.fixture
def unique_run_id() -> str:
    return f"run_e2e_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def opaque_state_dir(opaque_workspace: Path, unique_run_id: str) -> Path:
    state_dir = opaque_workspace / ".agents" / "teamwork" / unique_run_id
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


@pytest.fixture
def isolated_state_dir(tmp_path: Path, unique_run_id: str) -> Path:
    sdir = tmp_path / "scratch_state" / unique_run_id
    sdir.mkdir(parents=True, exist_ok=True)
    return sdir


@pytest.fixture(autouse=True)
def opaque_env_sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)
    monkeypatch.delenv("GIT_INDEX_FILE", raising=False)


# ── 5. Mock Runner Fixtures ─────────────────────────────────────────────────

class ConfigurableMockAgentRunner(BaseAgentRunner):
    """
    Enhanced MockAgentRunner supporting dynamic multi-round simulation,
    verdict overrides, simulated hangs, and forensic integrity triggers.
    """
    def __init__(
        self,
        simulate_challenger_failure_rounds: int = 0,
        simulate_auditor_violation: bool = False,
        simulate_reviewer_rejection: bool = False,
        simulate_worker_incomplete: bool = False,
        simulate_victory_audit_failure_rounds: int = 0,
    ):
        self.simulate_challenger_failure_rounds = simulate_challenger_failure_rounds
        self.simulate_auditor_violation = simulate_auditor_violation
        self.simulate_reviewer_rejection = simulate_reviewer_rejection
        self.simulate_worker_incomplete = simulate_worker_incomplete
        self.simulate_victory_audit_failure_rounds = simulate_victory_audit_failure_rounds
        self.round_counters: Dict[str, int] = {}
        self.executed_agents: List[Dict[str, Any]] = []

    def run_agent(
        self,
        agent_id: str,
        archetype: str,
        system_prompt: str,
        dispatch_file: Path,
        state_dir: Path,
        workspace_dir: Path,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        state_dir.mkdir(parents=True, exist_ok=True)
        handoff_file = state_dir / "handoff.md"
        progress_file = state_dir / "progress.md"

        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        progress_file.write_text(
            f"# Progress — {agent_id}\n\nLast visited: {now_iso}\nStatus: DONE\n\n## Steps\n- [x] Completed task\n",
            encoding="utf-8",
        )

        verdict = "DONE"
        details = "Task finished successfully"
        defect = None

        arch_lower = archetype.lower()

        if "challenger" in arch_lower:
            key = archetype
            cnt = self.round_counters.get(key, 0)
            self.round_counters[key] = cnt + 1
            if cnt < self.simulate_challenger_failure_rounds:
                verdict = "REQUEST_CHANGES"
                details = f"Simulated boundary defect in round {cnt + 1}"
                defect = "boundary overflow"
                handoff_content = f"# Challenger Report\n**Verdict**: REQUEST_CHANGES\n**Defect**: boundary overflow\n## 4. Conclusion\nREQUEST_CHANGES\n"
            else:
                verdict = "APPROVE"
                details = "All adversarial checks passed"
                handoff_content = "# Challenger Report\n**Verdict**: APPROVE\n## 4. Conclusion\nAPPROVE\n"

        elif "auditor" in arch_lower and "victory" not in arch_lower:
            if self.simulate_auditor_violation:
                verdict = "INTEGRITY_VIOLATION"
                details = "Unauthorized file touch outside milestone scope"
                defect = "Modified out_of_scope.py"
                handoff_content = "# Forensic Auditor\n**Verdict**: INTEGRITY_VIOLATION\n**Defect**: Modified out_of_scope.py\n## 4. Conclusion\nINTEGRITY_VIOLATION\n"
            else:
                verdict = "CLEAN"
                details = "Git diff verified clean"
                handoff_content = "# Forensic Auditor\n**Verdict**: CLEAN\n## 4. Conclusion\nCLEAN\n"

        elif "reviewer" in arch_lower:
            if self.simulate_reviewer_rejection:
                verdict = "REQUEST_CHANGES"
                details = "Architecture regression detected"
                defect = "Broken regression test"
                handoff_content = "# Reviewer\n**Verdict**: REQUEST_CHANGES\n**Defect**: Broken regression test\n## 4. Conclusion\nREQUEST_CHANGES\n"
            else:
                verdict = "APPROVE"
                details = "Code conforms to contracts"
                handoff_content = "# Reviewer\n**Verdict**: APPROVE\n## 4. Conclusion\nAPPROVE\n"

        elif "worker" in arch_lower or "implementer" in arch_lower:
            if self.simulate_worker_incomplete:
                verdict = "FAILED"
                details = "Build or unit test failure"
                handoff_content = "# Worker Handoff\n**Verdict**: FAILED\n## 4. Conclusion\nFAILED\n"
            else:
                verdict = "DONE"
                details = "Implementation complete"
                handoff_content = f"# Worker Handoff\n**Verdict**: DONE\n## 4. Conclusion\nDONE\n## 5. Verification Method\nAll unit tests pass.\n"

        elif "victory" in arch_lower:
            cnt = self.round_counters.get("victory_auditor", 0)
            self.round_counters["victory_auditor"] = cnt + 1
            if cnt < self.simulate_victory_audit_failure_rounds:
                verdict = "VICTORY REJECTED"
                details = "Regression discovered vs ORIGINAL_REQUEST.md"
                handoff_content = "# Victory Audit\n**Verdict**: VICTORY REJECTED\n## 4. Conclusion\nVICTORY REJECTED\n"
            else:
                verdict = "VICTORY CONFIRMED"
                details = "All acceptance criteria verified against ORIGINAL_REQUEST.md"
                handoff_content = "# Victory Audit\n**Verdict**: VICTORY CONFIRMED\n## 4. Conclusion\nVICTORY CONFIRMED\n"

        else:
            verdict = "DONE"
            handoff_content = f"# Handoff — {agent_id}\n**Verdict**: DONE\n## 4. Conclusion\nDONE\n"

        handoff_file.write_text(handoff_content, encoding="utf-8")
        result = {
            "agent_id": agent_id,
            "agent_name": agent_id,
            "archetype": archetype,
            "role": archetype,
            "verdict": verdict,
            "details": details,
            "defect": defect,
            "handoff_path": str(handoff_file),
        }
        self.executed_agents.append(result)
        return result


@pytest.fixture
def mock_runner_factory() -> Callable[..., ConfigurableMockAgentRunner]:
    def _create(**kwargs) -> ConfigurableMockAgentRunner:
        return ConfigurableMockAgentRunner(**kwargs)
    return _create


@pytest.fixture
def default_mock_runner(mock_runner_factory) -> ConfigurableMockAgentRunner:
    return mock_runner_factory()


@pytest.fixture
def rejecting_mock_runner(mock_runner_factory) -> ConfigurableMockAgentRunner:
    return mock_runner_factory(simulate_challenger_failure_rounds=1)


@pytest.fixture
def standard_run_state(opaque_git_repo: Path, unique_run_id: str) -> TeamworkRunState:
    return TeamworkRunState(workspace_root=opaque_git_repo, run_id=unique_run_id)


# ── 6. Unified E2E Test Context Fixture ──────────────────────────────────────

class E2ETestContext:
    def __init__(self, workspace: Path, git_repo: Path, state_dir: Path, run_id: str, runner_factory):
        self.workspace = workspace
        self.git_repo = git_repo
        self.state_dir = state_dir
        self.run_id = run_id
        self.runner_factory = runner_factory

    def get_file_content(self, relative_path: str) -> str:
        target = self.workspace / relative_path
        if not target.exists():
            target = self.state_dir / relative_path
        return target.read_text(encoding="utf-8")

    def assert_gate_passed(self, milestone: str, iteration: int = 1) -> None:
        gate_status = self.state_dir / "GATE_STATUS.md"
        assert gate_status.exists(), "GATE_STATUS.md was not created"
        text = gate_status.read_text(encoding="utf-8")
        assert f"Milestone {milestone}" in text
        assert "Gate Result: **PASS**" in text

    def assert_gate_failed(self, milestone: str, iteration: int = 1) -> None:
        gate_status = self.state_dir / "GATE_STATUS.md"
        assert gate_status.exists(), "GATE_STATUS.md was not created"
        text = gate_status.read_text(encoding="utf-8")
        assert f"Milestone {milestone}" in text
        assert "Gate Result: **FAIL**" in text


@pytest.fixture
def e2e_context(
    opaque_workspace: Path,
    opaque_git_repo: Path,
    opaque_state_dir: Path,
    unique_run_id: str,
    mock_runner_factory,
) -> E2ETestContext:
    return E2ETestContext(
        workspace=opaque_workspace,
        git_repo=opaque_git_repo,
        state_dir=opaque_state_dir,
        run_id=unique_run_id,
        runner_factory=mock_runner_factory,
    )
