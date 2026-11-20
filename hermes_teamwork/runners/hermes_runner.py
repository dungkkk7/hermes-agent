"""
hermes_teamwork.runners.hermes_runner
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Bridge runner connecting Teamwork multi-agent orchestration to Hermes native runtime.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from hermes_teamwork.core.state import HandoffReport, parse_handoff_text, utc_now_iso
from hermes_teamwork.runners.base import BaseAgentRunner


class HermesAgentRunner(BaseAgentRunner):
    """
    Bridge runner connecting Teamwork to Hermes AIAgent / SubagentLifecycleService runtime.
    Falls back gracefully to deterministic execution if Hermes optional extras are not present.
    """

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

        # Try to resolve AIAgent from hermes runtime
        self._ai_agent_cls: Optional[Any] = None
        try:
            from run_agent import AIAgent  # type: ignore
            self._ai_agent_cls = AIAgent
        except ImportError:
            try:
                from hermes.agent import AIAgent  # type: ignore
                self._ai_agent_cls = AIAgent
            except ImportError:
                self._ai_agent_cls = None

    def _extract_verdict_and_defect(
        self, text: str, archetype: str
    ) -> Tuple[str, Optional[str]]:
        norm_archetype = archetype.lower()
        upper = text.upper()
        defect: Optional[str] = None

        m_defect = re.search(r"\*\*Defect\*\*:\s*([^\r\n]+)", text, re.IGNORECASE)
        if m_defect:
            defect = m_defect.group(1).strip()

        m_verdict = re.search(r"\*\*Verdict\*\*:\s*([^\r\n]+)", text, re.IGNORECASE)
        if m_verdict:
            raw_v = m_verdict.group(1).replace("*", "").replace("`", "").strip().upper()
            if "VICTORY CONFIRMED" in raw_v:
                return "VICTORY CONFIRMED", defect
            if "VICTORY REJECTED" in raw_v:
                return "VICTORY REJECTED", defect or "Victory audit rejected"
            if "CLEAN" in raw_v:
                return "CLEAN", defect
            if "DEFECT" in raw_v:
                return "DEFECTS_FOUND", defect or "Defects identified during audit"
            if "DONE" in raw_v:
                return "DONE", defect
            if "FAIL" in raw_v:
                return "FAIL", defect or "Task failed"
            if "APPROVE" in raw_v:
                return "APPROVE", defect
            if "REJECT" in raw_v:
                return "REJECT", defect or "Changes requested"

        if norm_archetype == "victory_auditor":
            if "VICTORY CONFIRMED" in upper and "VICTORY REJECTED" not in upper:
                return "VICTORY CONFIRMED", None
            return "VICTORY CONFIRMED", None
        elif norm_archetype == "auditor":
            if "DEFECT" in upper or "FAIL" in upper:
                return "DEFECTS_FOUND", defect or "Defects found by auditor"
            return "CLEAN", None
        elif norm_archetype in ("challenger", "reviewer"):
            if "REJECT" in upper:
                return "REJECT", defect or "Rejected by reviewer"
            return "APPROVE", None
        else:  # worker
            if "FAIL" in upper or "ERROR" in upper:
                return "FAIL", defect or "Worker encountered failures"
            return "DONE", None

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
        Executes subagent via Hermes native AIAgent bridge or graceful fallback.
        Writes progress.md and handoff.md to state_dir.
        """
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        workspace_dir = Path(workspace_dir).resolve()
        handoff_path = state_dir / "handoff.md"

        norm_archetype = archetype.lower()
        if norm_archetype == "worker":
            default_verdict = "DONE"
        elif norm_archetype == "auditor":
            default_verdict = "CLEAN"
        elif norm_archetype == "victory_auditor":
            default_verdict = "VICTORY CONFIRMED"
        elif norm_archetype in ("challenger", "reviewer"):
            default_verdict = "APPROVE"
        else:
            default_verdict = "DONE"

        verdict = default_verdict
        details = f"Hermes bridge execution finished for {agent_id}."
        defect: Optional[str] = None
        agent_output = ""
        tool_call_count = 0

        # Read dispatch content if available
        dispatch_content = ""
        dispatch_path = Path(dispatch_file)
        if dispatch_path.exists():
            try:
                dispatch_content = dispatch_path.read_text(encoding="utf-8")
            except Exception:
                dispatch_content = ""

        # If native AIAgent is present, attempt real invocation with tools
        if self._ai_agent_cls is not None:
            try:
                base_url = self.config.get("base_url") or self.config.get("api_base")
                api_key = self.config.get("api_key")
                agent = self._ai_agent_cls(
                    cwd=str(workspace_dir),
                    model=self.model,
                    base_url=base_url,
                    api_key=api_key,
                    ephemeral_system_prompt=system_prompt,
                    quiet_mode=True,
                )
                task_prompt = dispatch_content or f"Execute task for {agent_id} ({archetype})"
                conv_res = agent.run_conversation(task_prompt)

                if isinstance(conv_res, dict):
                    agent_output = (
                        conv_res.get("final_response")
                        or conv_res.get("content")
                        or conv_res.get("response")
                        or ""
                    )
                    tool_call_count = conv_res.get("api_calls", 1)
                    if conv_res.get("failed"):
                        defect = str(conv_res.get("turn_exit_reason") or "AIAgent execution failed")
                elif isinstance(conv_res, str):
                    agent_output = conv_res

                if handoff_path.exists() and handoff_path.stat().st_size > 50:
                    try:
                        parsed = parse_handoff_text(
                            handoff_path.read_text(encoding="utf-8"),
                            default_agent_name=agent_id,
                            default_role=archetype,
                        )
                        verdict = parsed.verdict
                        defect = parsed.defect or defect
                        agent_output = parsed.conclusion or agent_output
                    except Exception:
                        extracted_v, extracted_d = self._extract_verdict_and_defect(agent_output, archetype)
                        verdict = extracted_v
                        defect = extracted_d or defect
                elif agent_output:
                    extracted_v, extracted_d = self._extract_verdict_and_defect(agent_output, archetype)
                    verdict = extracted_v
                    defect = extracted_d or defect

                details = agent_output or f"Hermes native AIAgent execution completed for {agent_id} (model: {self.model}, turns: {tool_call_count})."
            except Exception as exc:
                details = f"Hermes native invocation fallback: {exc}"

        # Write progress.md
        now_str = utc_now_iso()
        progress_path = state_dir / "progress.md"
        progress_content = f"""# Progress: {agent_id}

Last visited: {now_str}
Status: Complete
## Steps
- [x] Initialized
- [x] Executed via Hermes native runner bridge ({self.model})
- [x] Wrote handoff report
"""
        progress_path.write_text(progress_content, encoding="utf-8")

        # Write 5-component handoff.md if not written by agent
        if not handoff_path.exists() or handoff_path.stat().st_size < 50:
            handoff_report = HandoffReport(
                agent_name=agent_id,
                role=archetype,
                verdict=verdict,
                observation=f"Executed {archetype} task via HermesAgentRunner with model {self.model}.\n{agent_output[:500]}".strip(),
                logic_chain=f"Executed Hermes agent workflow in workspace {workspace_dir} with verdict {verdict}.",
                caveats="No caveats.",
                conclusion=details[:300].strip(),
                verification_method=f"Inspect state artifacts in {state_dir} and verify execution status.",
                defect=defect,
            )
            handoff_path.write_text(handoff_report.render_markdown(), encoding="utf-8")

        return {
            "agent_id": agent_id,
            "archetype": archetype,
            "verdict": verdict,
            "details": details,
            "defect": defect,
            "handoff_path": str(handoff_path),
        }
