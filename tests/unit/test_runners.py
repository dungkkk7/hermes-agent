"""
tests.unit.test_runners
~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for OpenAICompatibleRunner and HermesAgentRunner.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from hermes_teamwork.runners.base import BaseAgentRunner
from hermes_teamwork.runners.hermes_runner import HermesAgentRunner
from hermes_teamwork.runners.openai_runner import OpenAICompatibleRunner


class TestOpenAICompatibleRunner:
    """Tests for OpenAICompatibleRunner initialization, formatting, and agent execution."""

    def test_init_defaults(self):
        runner = OpenAICompatibleRunner()
        assert isinstance(runner, BaseAgentRunner)
        assert runner.api_base == "http://localhost:20128/v1"
        assert runner.base_url == "http://localhost:20128/v1"
        assert runner.model == "nous-hermes-2-yi-34b"
        assert runner.api_key == "mock-key"
        assert runner.timeout == 60.0
        assert runner.stream is False

    def test_init_with_base_url(self):
        runner = OpenAICompatibleRunner(base_url="http://custom-host:8080/v1")
        assert runner.api_base == "http://custom-host:8080/v1"
        assert runner.base_url == "http://custom-host:8080/v1"

    def test_stream_false_enforced(self):
        runner = OpenAICompatibleRunner(stream=True)
        assert runner.stream is False
        payload = runner.format_payload([{"role": "user", "content": "hi"}])
        assert payload["stream"] is False

    def test_format_payload_messages_only(self):
        runner = OpenAICompatibleRunner(model="test-model")
        messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "usr"}]
        payload = runner.format_payload(messages)
        assert payload["model"] == "test-model"
        assert payload["messages"] == messages
        assert payload["stream"] is False
        assert "tools" not in payload

    def test_format_payload_with_tools(self):
        runner = OpenAICompatibleRunner()
        tools = [{"type": "function", "function": {"name": "run_command"}}]
        payload = runner.format_payload([{"role": "user", "content": "call tool"}], tools=tools)
        assert payload["tools"] == tools
        assert payload["stream"] is False

    def test_run_agent_state_writing(self, tmp_path: Path):
        runner = OpenAICompatibleRunner()
        state_dir = tmp_path / "agent_sub"
        dispatch_file = tmp_path / "dispatch.md"
        dispatch_file.write_text("# Task\nExecute implementation.", encoding="utf-8")

        res = runner.run_agent(
            agent_id="worker_01",
            archetype="worker",
            system_prompt="You are a worker.",
            dispatch_file=dispatch_file,
            state_dir=state_dir,
            workspace_dir=tmp_path,
        )

        assert (state_dir / "progress.md").exists()
        assert (state_dir / "handoff.md").exists()
        progress_text = (state_dir / "progress.md").read_text(encoding="utf-8")
        assert "Progress: worker_01" in progress_text
        assert "Last visited:" in progress_text

        handoff_text = (state_dir / "handoff.md").read_text(encoding="utf-8")
        assert "Observation" in handoff_text
        assert "Logic Chain" in handoff_text
        assert "Caveats" in handoff_text
        assert "Conclusion" in handoff_text
        assert "Verification Method" in handoff_text
        assert "**Verdict**: **DONE**" in handoff_text

    def test_run_agent_verdicts_by_archetype(self, tmp_path: Path):
        runner = OpenAICompatibleRunner()
        dispatch_file = tmp_path / "dispatch.md"
        dispatch_file.write_text("Execute task", encoding="utf-8")

        cases = [
            ("worker", "DONE"),
            ("auditor", "CLEAN"),
            ("challenger", "APPROVE"),
            ("reviewer", "APPROVE"),
            ("victory_auditor", "VICTORY CONFIRMED"),
            ("explorer", "DONE"),
        ]

        for archetype, expected_verdict in cases:
            sdir = tmp_path / f"state_{archetype}"
            res = runner.run_agent(
                agent_id=f"agent_{archetype}",
                archetype=archetype,
                system_prompt="Prompt",
                dispatch_file=dispatch_file,
                state_dir=sdir,
                workspace_dir=tmp_path,
            )
            assert res["verdict"] == expected_verdict
            assert res["agent_id"] == f"agent_{archetype}"
            assert res["archetype"] == archetype
            assert res["defect"] is None
            assert res["handoff_path"] == str(sdir / "handoff.md")

    def test_run_agent_with_live_response_mock(self, tmp_path: Path):
        runner = OpenAICompatibleRunner(base_url="http://mock-openai:8000/v1")
        sdir = tmp_path / "state_live"
        disp = tmp_path / "disp.md"
        disp.write_text("Do something", encoding="utf-8")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Task executed via live endpoint mock."}}]
        }

        with patch("requests.post", return_value=mock_resp):
            res = runner.run_agent(
                agent_id="live_agent",
                archetype="worker",
                system_prompt="Prompt",
                dispatch_file=disp,
                state_dir=sdir,
                workspace_dir=tmp_path,
            )
            assert res["verdict"] == "DONE"
            assert "live endpoint" in res["details"].lower()


class TestHermesAgentRunner:
    """Tests for HermesAgentRunner initialization, graceful fallback, and execution."""

    def test_init_defaults(self):
        runner = HermesAgentRunner()
        assert isinstance(runner, BaseAgentRunner)
        assert runner.model == "nous-hermes-2-yi-34b"
        assert runner.config == {}
        assert runner.tool_registry is None

    def test_init_custom_params(self):
        cfg = {"timeout": 45, "max_iterations": 3}
        runner = HermesAgentRunner(model="hermes-3-llama-3.1-8b", config=cfg, tool_registry="custom_registry")
        assert runner.model == "hermes-3-llama-3.1-8b"
        assert runner.config == cfg
        assert runner.tool_registry == "custom_registry"

    def test_run_agent_state_writing(self, tmp_path: Path):
        runner = HermesAgentRunner()
        sdir = tmp_path / "hermes_sub"
        disp = tmp_path / "disp.md"
        disp.write_text("Do Hermes subagent task", encoding="utf-8")

        res = runner.run_agent(
            agent_id="hermes_sub_01",
            archetype="worker",
            system_prompt="System prompt",
            dispatch_file=disp,
            state_dir=sdir,
            workspace_dir=tmp_path,
        )

        assert (sdir / "progress.md").exists()
        assert (sdir / "handoff.md").exists()
        progress_text = (sdir / "progress.md").read_text(encoding="utf-8")
        assert "Progress: hermes_sub_01" in progress_text
        assert "Last visited:" in progress_text

        handoff_text = (sdir / "handoff.md").read_text(encoding="utf-8")
        assert "Observation" in handoff_text
        assert "Logic Chain" in handoff_text
        assert "Caveats" in handoff_text
        assert "Conclusion" in handoff_text
        assert "Verification Method" in handoff_text
        assert "**Verdict**: **DONE**" in handoff_text

    def test_run_agent_verdicts_by_archetype(self, tmp_path: Path):
        runner = HermesAgentRunner()
        disp = tmp_path / "disp.md"
        disp.write_text("Do task", encoding="utf-8")

        cases = [
            ("worker", "DONE"),
            ("auditor", "CLEAN"),
            ("challenger", "APPROVE"),
            ("reviewer", "APPROVE"),
            ("victory_auditor", "VICTORY CONFIRMED"),
        ]

        for archetype, expected_verdict in cases:
            sdir = tmp_path / f"hermes_state_{archetype}"
            res = runner.run_agent(
                agent_id=f"hermes_{archetype}",
                archetype=archetype,
                system_prompt="Prompt",
                dispatch_file=disp,
                state_dir=sdir,
                workspace_dir=tmp_path,
            )
            assert res["verdict"] == expected_verdict
            assert res["agent_id"] == f"hermes_{archetype}"
            assert res["archetype"] == archetype
            assert res["defect"] is None
            assert res["handoff_path"] == str(sdir / "handoff.md")

    def test_graceful_fallback_without_hermes_runtime(self, tmp_path: Path):
        runner = HermesAgentRunner()
        runner._ai_agent_cls = None  # Simulate absence of AIAgent
        sdir = tmp_path / "fallback_state"
        disp = tmp_path / "disp.md"
        disp.write_text("Task", encoding="utf-8")

        res = runner.run_agent(
            agent_id="fallback_agent",
            archetype="worker",
            system_prompt="Prompt",
            dispatch_file=disp,
            state_dir=sdir,
            workspace_dir=tmp_path,
        )
        assert res["verdict"] == "DONE"
        assert res["defect"] is None
