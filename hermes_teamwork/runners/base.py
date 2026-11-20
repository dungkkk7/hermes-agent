"""
hermes_teamwork.runners.base
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Abstract base runner for executing subagents in Teamwork.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict


class BaseAgentRunner(ABC):
    """
    Abstract interface for executing a subagent.
    """

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
        Executes a subagent with the provided configuration.
        Returns a dict summarizing the run, e.g.:
        {
            "agent_id": agent_id,
            "archetype": archetype,
            "verdict": "DONE" | "APPROVE" | "CLEAN" | "REQUEST_CHANGES" | ...,
            "details": "...",
            "defect": Optional[str],
            "handoff_path": str(handoff_path)
        }
        """
        pass
