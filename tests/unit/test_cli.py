"""
tests.unit.test_cli
~~~~~~~~~~~~~~~~~~~
Unit tests for hermes-teamwork CLI.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import pytest

from hermes_teamwork import __version__
from hermes_teamwork.cli import cli_main, create_parser, main


class TestCLI:
    """Tests for hermes-teamwork CLI parsing, execution, and exit codes."""

    def test_cli_parser_creation(self):
        parser = create_parser()
        assert parser.prog == "hermes-teamwork"

    def test_cli_help_flag(self):
        parser = create_parser()
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--help"])
        assert exc.value.code == 0

    def test_cli_version_flag(self, capsys: pytest.CaptureFixture):
        parser = create_parser()
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--version"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert __version__ in captured.out or __version__ in captured.err

    def test_cli_missing_request_fails(self):
        exit_code = cli_main([])
        assert exit_code != 0

    def test_cli_whitespace_only_request_fails(self):
        exit_code = cli_main(["   "])
        assert exit_code != 0

    def test_cli_invalid_runner_choice_fails(self):
        parser = create_parser()
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["task", "--runner", "invalid_engine"])
        assert exc.value.code != 0

    def test_cli_mock_runner_execution_success(self, tmp_path: Path):
        ws = tmp_path / "ws_mock"
        exit_code = cli_main(["--runner", "mock", "--request", "Unit test mission", "--workspace", str(ws)])
        assert exit_code == 0
        assert ws.exists()

    def test_cli_positional_request_success(self, tmp_path: Path):
        ws = tmp_path / "ws_pos"
        exit_code = cli_main(["Build payment subsystem", "--runner", "mock", "--workspace", str(ws)])
        assert exit_code == 0
        assert ws.exists()

    def test_cli_config_yaml_loading(self, tmp_path: Path):
        ws = tmp_path / "ws_cfg"
        cfg_file = tmp_path / "custom.yaml"
        cfg_file.write_text("runner: mock\nmax_iterations: 3\n", encoding="utf-8")

        exit_code = cli_main([
            "--config", str(cfg_file),
            "--request", "Config loading mission",
            "--workspace", str(ws),
        ])
        assert exit_code == 0

    def test_cli_config_runner_not_shadowed_by_default(self, tmp_path: Path):
        ws = tmp_path / "ws_cfg_9router"
        cfg_file = tmp_path / "custom_9router.yaml"
        cfg_file.write_text("runner: 9router\nbase_url: http://127.0.0.1:9999/v1\n", encoding="utf-8")

        exit_code = cli_main([
            "--config", str(cfg_file),
            "--request", "Test 9router config mission",
            "--workspace", str(ws),
        ])
        assert exit_code == 0

    def test_cli_native_runner_execution(self, tmp_path: Path):
        ws = tmp_path / "ws_native"
        exit_code = cli_main(["--runner", "native", "--request", "Native runner mission", "--workspace", str(ws)])
        assert exit_code == 0

    def test_cli_9router_runner_execution(self, tmp_path: Path):
        ws = tmp_path / "ws_9router"
        exit_code = cli_main(["--runner", "9router", "--request", "9router mission", "--workspace", str(ws)])
        assert exit_code == 0

    def test_cli_module_execution_via_subprocess(self, tmp_path: Path):
        """Tests python -m hermes_teamwork.cli execution via subprocess."""
        env = dict(os.environ)
        ws_root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = f"{ws_root}:" + env.get("PYTHONPATH", "")

        # 1. Test --help
        res_help = subprocess.run(
            [sys.executable, "-m", "hermes_teamwork.cli", "--help"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res_help.returncode == 0
        assert "usage" in res_help.stdout.lower() or "usage" in res_help.stderr.lower()

        # 2. Test missing request fails
        res_missing = subprocess.run(
            [sys.executable, "-m", "hermes_teamwork.cli"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res_missing.returncode != 0

        # 3. Test mock execution succeeds
        ws = tmp_path / "subproc_ws"
        res_run = subprocess.run(
            [sys.executable, "-m", "hermes_teamwork.cli", "--runner", "mock", "--request", "CLI subprocess run", "--workspace", str(ws)],
            capture_output=True,
            text=True,
            env=env,
        )
        assert res_run.returncode == 0
        assert "SUCCESS" in res_run.stdout or "SUCCESS" in res_run.stderr
