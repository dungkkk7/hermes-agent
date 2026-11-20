"""
tests.live.test_live_9router_e2e
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Live 9router end-to-end verification test harness.
Decorated with @pytest.mark.live; safely skips offline when port 20128 is unreachable.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import MagicMock, patch
import pytest

from hermes_teamwork.config import load_config
from hermes_teamwork.core.sentinel import Sentinel
from hermes_teamwork.runners.openai_runner import OpenAICompatibleRunner
from hermes_teamwork.scripts.verify_live_9router import (
    check_tcp_connectivity,
    probe_http_endpoint,
    run_verification,
)

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent


def is_9router_live(host: str = "127.0.0.1", port: int = 20128, timeout: float = 1.0) -> bool:
    """Checks whether the live 9router service is reachable on the given host and port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


@pytest.mark.live
class TestLive9routerE2E:
    """Feature 39: Live 9router E2E Verification Suite."""

    @pytest.mark.live
    def test_live_socket_connectivity_or_skip(self):
        """Verifies TCP socket connectivity to port 20128 or cleanly skips offline."""
        if not is_9router_live("127.0.0.1", 20128):
            pytest.skip("Offline execution: live 9router endpoint port 20128 not active")
        assert check_tcp_connectivity("127.0.0.1", 20128) is True

    @pytest.mark.live
    def test_live_openai_runner_agent_execution(self, tmp_path: Path):
        """Verifies OpenAICompatibleRunner runs a worker subagent targeting port 20128."""
        if not is_9router_live("127.0.0.1", 20128):
            pytest.skip("Offline execution: live 9router endpoint port 20128 not active")

        runner = OpenAICompatibleRunner(
            base_url="http://127.0.0.1:20128/v1",
            model="nous-hermes-2-yi-34b",
            timeout=5.0,
        )
        sdir = tmp_path / "agent_state"
        disp = tmp_path / "dispatch.md"
        disp.write_text("Test worker dispatch via live 9router runner.", encoding="utf-8")

        res = runner.run_agent(
            agent_id="live_worker_test",
            archetype="worker",
            system_prompt="You are a live test worker.",
            dispatch_file=disp,
            state_dir=sdir,
            workspace_dir=tmp_path,
        )
        assert res["verdict"] == "DONE"
        assert (sdir / "progress.md").exists()
        assert (sdir / "handoff.md").exists()

    @pytest.mark.live
    def test_live_sentinel_e2e_mission(self, tmp_path: Path):
        """Runs a complete Sentinel mission against the live 9router endpoint."""
        if not is_9router_live("127.0.0.1", 20128):
            pytest.skip("Offline execution: live 9router endpoint port 20128 not active")

        runner = OpenAICompatibleRunner(
            base_url="http://127.0.0.1:20128/v1",
            timeout=5.0,
        )
        sentinel = Sentinel(workspace_root=tmp_path, runner=runner)
        result = sentinel.run("Live 9router E2E verification test")
        assert result.get("status") == "SUCCESS"
        assert result.get("victory_verdict") == "VICTORY CONFIRMED"

    @pytest.mark.live
    def test_verify_script_cli_help(self):
        """Verifies verify_live_9router.py supports --help and exits 0."""
        script = WORKSPACE_ROOT / "hermes_teamwork" / "scripts" / "verify_live_9router.py"
        if not script.exists():
            script = WORKSPACE_ROOT / "scripts" / "verify_live_9router.py"
        assert script.exists(), f"verify_live_9router.py missing at {script}"
        res = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "usage" in res.stdout.lower() or "--help" in res.stdout.lower()

    @pytest.mark.live
    def test_verify_script_probe_only_run(self):
        """Executes verify_live_9router.py with --probe-only and verifies clean exit code 0."""
        script = WORKSPACE_ROOT / "hermes_teamwork" / "scripts" / "verify_live_9router.py"
        if not script.exists():
            script = WORKSPACE_ROOT / "scripts" / "verify_live_9router.py"
        assert script.exists()
        res = subprocess.run(
            [sys.executable, str(script), "--timeout", "2.0", "--probe-only"],
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0
        assert "9router Live Verification" in res.stdout

    @pytest.mark.live
    def test_offline_fallback_simulation(self, monkeypatch: pytest.MonkeyPatch):
        """Verifies clean skip/exit 0 behavior when port is unreachable."""
        # Force socket.create_connection to raise OSError (simulating offline port)
        def mock_create_connection(*args, **kwargs):
            raise ConnectionRefusedError(111, "Connection refused")

        monkeypatch.setattr(socket, "create_connection", mock_create_connection)
        assert check_tcp_connectivity("127.0.0.1", 20128) is False

        # run_verification without --strict must cleanly return 0
        code = run_verification(["--host", "127.0.0.1", "--port", "20128", "--timeout", "1.0"])
        assert code == 0

        # run_verification WITH --strict must return 1
        strict_code = run_verification(["--host", "127.0.0.1", "--port", "20128", "--timeout", "1.0", "--strict"])
        assert strict_code == 1

    @pytest.mark.live
    def test_stream_false_enforcement(self):
        """Verifies stream=False is strictly enforced in OpenAICompatibleRunner."""
        runner = OpenAICompatibleRunner(stream=True)
        assert runner.stream is False
        payload = runner.format_payload([{"role": "user", "content": "ping"}])
        assert payload["stream"] is False
