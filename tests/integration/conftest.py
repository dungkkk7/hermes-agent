"""
tests.integration.conftest
~~~~~~~~~~~~~~~~~~~~~~~~~~
Shared fixtures for offline integration tests of hermes_teamwork.
"""
from pathlib import Path
import pytest

from hermes_teamwork.core.state import TeamworkRunState
from hermes_teamwork.runners.mock_runner import MockAgentRunner


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Fixture providing a temporary isolated workspace root."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def run_state(tmp_workspace: Path) -> TeamworkRunState:
    """Fixture providing an isolated TeamworkRunState."""
    return TeamworkRunState(
        workspace_root=tmp_workspace,
        run_id="integration_run_001",
    )


@pytest.fixture
def mock_runner() -> MockAgentRunner:
    """Fixture providing a default MockAgentRunner."""
    return MockAgentRunner()
