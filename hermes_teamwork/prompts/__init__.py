"""
hermes_teamwork.prompts
~~~~~~~~~~~~~~~~~~~~~~~
Modular role prompts for Antigravity Teamwork agents.
"""
from pathlib import Path
from typing import Optional, Union

from hermes_teamwork.prompts.sentinel import SENTINEL_SYSTEM_PROMPT, SENTINEL_DISPATCH_PROMPT
from hermes_teamwork.prompts.orchestrator import ORCHESTRATOR_SYSTEM_PROMPT, ORCHESTRATOR_DISPATCH_PROMPT
from hermes_teamwork.prompts.explorer import EXPLORER_SYSTEM_PROMPT, EXPLORER_DISPATCH_PROMPT
from hermes_teamwork.prompts.worker import WORKER_SYSTEM_PROMPT, WORKER_DISPATCH_PROMPT
from hermes_teamwork.prompts.reviewer import REVIEWER_SYSTEM_PROMPT, REVIEWER_DISPATCH_PROMPT
from hermes_teamwork.prompts.challenger import CHALLENGER_SYSTEM_PROMPT, CHALLENGER_DISPATCH_PROMPT
from hermes_teamwork.prompts.auditor import AUDITOR_SYSTEM_PROMPT, AUDITOR_DISPATCH_PROMPT
from hermes_teamwork.prompts.victory_auditor import VICTORY_AUDITOR_SYSTEM_PROMPT, VICTORY_AUDITOR_DISPATCH_PROMPT

ROLE_SYSTEM_PROMPTS = {
    "sentinel": SENTINEL_SYSTEM_PROMPT,
    "orchestrator": ORCHESTRATOR_SYSTEM_PROMPT,
    "explorer": EXPLORER_SYSTEM_PROMPT,
    "worker": WORKER_SYSTEM_PROMPT,
    "implementer": WORKER_SYSTEM_PROMPT,
    "reviewer": REVIEWER_SYSTEM_PROMPT,
    "challenger": CHALLENGER_SYSTEM_PROMPT,
    "auditor": AUDITOR_SYSTEM_PROMPT,
    "victory_auditor": VICTORY_AUDITOR_SYSTEM_PROMPT,
}


def get_system_prompt(
    archetype: str,
    state_dir: Optional[Union[Path, str]] = None,
    generation: int = 1,
) -> str:
    """Returns the rendered system prompt for the given Teamwork archetype."""
    key = archetype.strip().lower() if isinstance(archetype, str) else ""
    template = ROLE_SYSTEM_PROMPTS.get(key)
    if not template:
        return f"You are a Teamwork {archetype}."
    resolved_state_dir = str(state_dir) if state_dir is not None else ".agents/teamwork"
    return (
        template
        .replace("{state_dir}", resolved_state_dir)
        .replace("{generation}", str(generation))
        .replace("{next_generation}", str(generation + 1))
    )


__all__ = [
    "SENTINEL_SYSTEM_PROMPT", "SENTINEL_DISPATCH_PROMPT",
    "ORCHESTRATOR_SYSTEM_PROMPT", "ORCHESTRATOR_DISPATCH_PROMPT",
    "EXPLORER_SYSTEM_PROMPT", "EXPLORER_DISPATCH_PROMPT",
    "WORKER_SYSTEM_PROMPT", "WORKER_DISPATCH_PROMPT",
    "REVIEWER_SYSTEM_PROMPT", "REVIEWER_DISPATCH_PROMPT",
    "CHALLENGER_SYSTEM_PROMPT", "CHALLENGER_DISPATCH_PROMPT",
    "AUDITOR_SYSTEM_PROMPT", "AUDITOR_DISPATCH_PROMPT",
    "VICTORY_AUDITOR_SYSTEM_PROMPT", "VICTORY_AUDITOR_DISPATCH_PROMPT",
    "ROLE_SYSTEM_PROMPTS", "get_system_prompt",
]
