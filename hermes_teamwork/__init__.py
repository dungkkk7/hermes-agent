"""
Hermes Teamwork - Antigravity Multi-Agent Architecture for Hermes Agent.
"""
from hermes_teamwork.config import ConfigDict, load_config
from hermes_teamwork.runners import (
    BaseAgentRunner,
    HermesAgentRunner,
    MockAgentRunner,
    OpenAICompatibleRunner,
)

__version__ = "0.1.0"

__all__ = [
    "BaseAgentRunner",
    "MockAgentRunner",
    "OpenAICompatibleRunner",
    "HermesAgentRunner",
    "ConfigDict",
    "load_config",
    "__version__",
]
