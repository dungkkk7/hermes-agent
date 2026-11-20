"""
hermes_teamwork.core.state
~~~~~~~~~~~~~~~~~~~~~~~~~~
File-based state persistence engine for Hermes Antigravity Teamwork.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class StateError(Exception):
    """Base exception for teamwork state errors."""
    pass


class LockedSectionTamperError(StateError):
    """Raised when an append-only locked section (🔒) is modified or deleted."""
    pass


class ImmutableStateViolationError(StateError):
    """Raised when attempting to overwrite an immutable file like ORIGINAL_REQUEST.md."""
    pass


class HandoffValidationError(StateError):
    """Raised when handoff.md does not satisfy the 5-component protocol."""
    pass


LOCKED_SECTION_HEADERS = [
    "## 🔒 My Identity",
    "## 🔒 Key Constraints",
    "## 🔒 My Workflow",
]

MANDATORY_HANDOFF_SECTIONS = [
    "Observation",
    "Logic Chain",
    "Caveats",
    "Conclusion",
    "Verification Method",
]

MAX_BRIEFING_LINES = 100
DEFAULT_LIVENESS_TIMEOUT_SECONDS = 600.0  # 10 minutes


def utc_now_iso() -> str:
    """Returns current UTC timestamp in strict ISO 8601 format."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_timestamp(ts_str: str) -> Optional[datetime.datetime]:
    """Parses ISO timestamp string to timezone-aware UTC datetime."""
    if not isinstance(ts_str, str) or not ts_str.strip():
        return None
    try:
        clean_str = ts_str.strip()
        if clean_str.endswith(("Z", "z")):
            clean_str = clean_str[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(clean_str)
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            return dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None


_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_LINE_SPLIT_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")


def mask_fenced_code_blocks(text: str) -> str:
    """
    Masks CommonMark fenced code blocks (``` or ~~~) by replacing non-newline
    characters inside fenced blocks (including opening/closing fence lines)
    with 'X', preserving exact character offsets and line numbers.
    """
    if not isinstance(text, str) or not text:
        return ""

    masked_parts: List[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0

    for raw_line in _LINE_SPLIT_RE.findall(text):
        line_body = raw_line.rstrip("\r\n")
        line_end = raw_line[len(line_body):]

        if not in_fence:
            m_open = _FENCE_OPEN_RE.match(line_body)
            if m_open:
                marker, info = m_open.group(1), m_open.group(2)
                # CommonMark §4.5: backtick code fence info strings cannot contain backticks
                if not (marker[0] == "`" and "`" in info):
                    in_fence = True
                    fence_char = marker[0]
                    fence_len = len(marker)
                    masked_parts.append(("X" * len(line_body)) + line_end)
                    continue
            masked_parts.append(raw_line)
        else:
            masked_parts.append(("X" * len(line_body)) + line_end)
            m_close = _FENCE_OPEN_RE.match(line_body)
            if m_close:
                close_marker, trailing = m_close.group(1), m_close.group(2)
                if (
                    close_marker[0] == fence_char
                    and len(close_marker) >= fence_len
                    and trailing.strip(" \t") == ""
                ):
                    in_fence = False
                    fence_char = ""
                    fence_len = 0

    return "".join(masked_parts)


@dataclass
class HandoffReport:
    """Structured representation of a 5-component handoff."""
    agent_name: str
    role: str
    verdict: str  # DONE, APPROVE, APPROVE_WITH_NITS, REQUEST_CHANGES, CLEAN, INTEGRITY_VIOLATION, FAIL
    observation: str
    logic_chain: str
    conclusion: str
    verification_method: str
    caveats: str = "No caveats."
    summary: str = ""
    defect: Optional[str] = None
    remaining_work: Optional[str] = None  # Populated for soft handoffs
    source_file: str = "handoff.md"

    def render_markdown(self) -> str:
        """Renders standard 5-component handoff report in markdown."""
        md = [
            f"# Handoff Report: {self.agent_name}",
            "",
            f"**Agent**: `{self.agent_name}`  ",
            f"**Role**: `{self.role}`  ",
            f"**Verdict**: **{self.verdict}**  ",
            f"**Timestamp**: {utc_now_iso()}  ",
        ]
        if self.defect:
            md.append(f"**Defect**: {self.defect}  ")
        if self.summary:
            md.extend(["", f"**Summary**: {self.summary}", ""])
        else:
            md.append("")

        md.extend([
            "---",
            "",
            "## 1. Observation",
            self.observation.strip(),
            "",
            "## 2. Logic Chain",
            self.logic_chain.strip(),
            "",
            "## 3. Caveats",
            self.caveats.strip() if self.caveats.strip() else "No caveats.",
            "",
            "## 4. Conclusion",
            self.conclusion.strip(),
            "",
            "## 5. Verification Method",
            self.verification_method.strip(),
            ""
        ])
        if self.remaining_work:
            md.extend([
                "## Remaining Work",
                self.remaining_work.strip(),
                ""
            ])
        return "\n".join(md)

    def validate(self) -> List[str]:
        """Validates that all 5 components are present and non-empty."""
        errors = []
        if not self.observation or not self.observation.strip():
            errors.append("Section 'Observation' is missing or empty.")
        if not self.logic_chain or not self.logic_chain.strip():
            errors.append("Section 'Logic Chain' is missing or empty.")
        if not self.caveats or not self.caveats.strip():
            errors.append("Section 'Caveats' is missing or empty.")
        if not self.conclusion or not self.conclusion.strip():
            errors.append("Section 'Conclusion' is missing or empty.")
        if not self.verification_method or not self.verification_method.strip():
            errors.append("Section 'Verification Method' is missing or empty.")
        return errors


@dataclass
class DeadEndRecord:
    """Record of a failed approach in DEAD_ENDS.md."""
    iteration: int
    approach: str
    why_failed: str
    files_touched: List[str]
    milestone: Optional[str] = None
    timestamp: str = field(default_factory=utc_now_iso)


@dataclass
class ProgressState:
    """Parsed progress status from progress.md."""
    agent_name: str
    last_visited: Optional[datetime.datetime]
    status: str
    checklist: List[Tuple[str, bool]]
    notes: str = ""


class AgentState:
    """
    Manages persistent state for an individual subagent under:
    .agents/teamwork/<run_id>/<agent_name>/
    """
    def __init__(self, run_dir: Path, agent_name: str, archetype: str):
        self.run_dir = run_dir.resolve()
        self.agent_name = agent_name
        self.archetype = archetype
        self.state_dir = self.run_dir / agent_name
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.briefing_path = self.state_dir / "BRIEFING.md"
        self.briefing_archive_path = self.state_dir / "BRIEFING_ARCHIVE.md"
        self.dispatch_path = self.state_dir / "DISPATCH.md"
        self.progress_path = self.state_dir / "progress.md"
        self.handoff_path = self.state_dir / "handoff.md"

    @property
    def agent_id(self) -> str:
        """Alias for agent_name."""
        return self.agent_name

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
        workflow: str = ""
    ) -> "AgentState":
        """Factory method that instantiates AgentState and initializes BRIEFING.md."""
        obj = cls(run_dir=run_dir, agent_name=agent_name, archetype=archetype)
        if not obj.briefing_path.exists():
            obj.init_briefing(
                mission=mission or f"Task execution for {agent_name}",
                roles=roles or [archetype],
                working_dir=working_dir or obj.run_dir.parent.parent,
                parent_id=parent_id,
                milestone=milestone,
                key_constraints=key_constraints or [
                    "Obey archetype negative invariants",
                    "Write handoff.md upon completion"
                ],
                workflow=workflow
            )
        return obj

    def init_briefing(
        self,
        mission: str,
        roles: List[str],
        working_dir: Path,
        parent_id: str,
        milestone: str = "",
        key_constraints: Optional[List[str]] = None,
        workflow: str = ""
    ) -> Path:
        """Creates initial BRIEFING.md with mandatory locked sections."""
        constraints_list = key_constraints or ["Obey archetype negative invariants"]
        rendered_constraints = "\n".join(f"- {c}" for c in constraints_list)
        rendered_roles = ", ".join(roles)

        workflow_block = ""
        if workflow:
            workflow_block = f"\n## 🔒 My Workflow\n{workflow.strip()}\n"

        content = f"""# BRIEFING — {utc_now_iso()}

## Mission
{mission.strip()}

## 🔒 My Identity
- Archetype: {self.archetype}
- Roles: {rendered_roles}
- Working directory: {working_dir.resolve()}
- State folder: {self.state_dir.resolve()}
- Original parent: {parent_id or 'none'}
- Milestone: {milestone or 'none'}

## 🔒 Key Constraints
{rendered_constraints}
{workflow_block}
## Current Parent
- Conversation ID: {parent_id or 'none'}
- Updated: {utc_now_iso()}

## Investigation State
- **Explored paths**: None
- **Key findings**: Initialized
- **Unexplored areas**: Entire assigned scope

## Key Decisions Made
- Task initialized

## Artifact Index
- BRIEFING.md — Persistent memory
- DISPATCH.md — Task instructions
- progress.md — Liveness heartbeat
- handoff.md — Final deliverable
"""
        self.briefing_path.write_text(content, encoding="utf-8")
        return self.briefing_path

    def read_briefing(self) -> str:
        """Reads current BRIEFING.md content."""
        if not self.briefing_path.exists():
            return ""
        return self.briefing_path.read_text(encoding="utf-8")

    def _split_briefing_sections(self, content: str) -> List[Dict[str, Any]]:
        """
        Splits BRIEFING.md content into structured sections using fence-aware
        CommonMark heading boundaries.
        - Splits on level-2 headings (`^ {0,3}##(?!#)(?:\\s|$)`) outside code fences.
        - Splits on level-1 headings (`^ {0,3}#(?!#)(?:\\s|$)`) outside code fences
          ONLY when NOT currently inside a locked (`## 🔒`) section, so `# ` comments
          inside locked blocks cannot fragment or expose locked content to pruning.
        """
        sections: List[Dict[str, Any]] = []
        current_header = ""
        current_lines: List[str] = []
        current_is_locked = False

        in_fence = False
        fence_char = ""
        fence_len = 0

        for line in content.splitlines():
            if in_fence:
                current_lines.append(line)
                m_close = _FENCE_OPEN_RE.match(line)
                if m_close:
                    close_marker, trailing = m_close.group(1), m_close.group(2)
                    if (
                        close_marker[0] == fence_char
                        and len(close_marker) >= fence_len
                        and trailing.strip(" \t") == ""
                    ):
                        in_fence = False
                        fence_char = ""
                        fence_len = 0
                continue

            m_open = _FENCE_OPEN_RE.match(line)
            if m_open:
                marker, info = m_open.group(1), m_open.group(2)
                if not (marker[0] == "`" and "`" in info):
                    in_fence = True
                    fence_char = marker[0]
                    fence_len = len(marker)
                    current_lines.append(line)
                    continue

            is_h2 = re.match(r"^ {0,3}##(?!#)(?:\s|$)", line) is not None
            is_h1 = (not is_h2) and (re.match(r"^ {0,3}#(?!#)(?:\s|$)", line) is not None)

            if is_h2 or (is_h1 and not current_is_locked):
                if current_header or current_lines:
                    sections.append({
                        "header": current_header,
                        "lines": current_lines,
                        "is_locked": current_is_locked,
                    })
                current_header = line
                current_lines = []
                stripped_h = line.strip()
                current_is_locked = (
                    "🔒" in stripped_h
                    or any(stripped_h.startswith(lh) for lh in LOCKED_SECTION_HEADERS)
                )
            else:
                current_lines.append(line)

        if current_header or current_lines:
            sections.append({
                "header": current_header,
                "lines": current_lines,
                "is_locked": current_is_locked,
            })

        return sections

    def _extract_locked_sections(self, content: str) -> Dict[str, str]:
        """Extracts content of all locked sections (🔒) from markdown text."""
        sections: Dict[str, str] = {}
        for sec in self._split_briefing_sections(content):
            h_stripped = sec["header"].strip()
            for header in LOCKED_SECTION_HEADERS:
                if h_stripped == header or h_stripped.startswith(header + " "):
                    full_sec = "\n".join([sec["header"]] + sec["lines"]).strip()
                    sections[header] = full_sec
                    break
        return sections

    def update_briefing(self, new_content: str, max_lines: int = MAX_BRIEFING_LINES) -> Path:
        """
        Updates BRIEFING.md while enforcing append-only locked sections (🔒)
        and max line limit (<100 lines).
        Raises LockedSectionTamperError if locked section contents are altered or missing.
        """
        old_content = self.read_briefing()
        old_locked = self._extract_locked_sections(old_content)
        new_locked = self._extract_locked_sections(new_content)

        # Invariant: Locked sections from old_content must be present in new_content
        for header, old_sec_text in old_locked.items():
            if header not in new_locked:
                raise LockedSectionTamperError(f"Locked section '{header}' was deleted from BRIEFING.md!")
            
            # Check line by line if any original line was modified/deleted
            old_lines = [l.strip() for l in old_sec_text.splitlines() if l.strip()]
            new_lines = [l.strip() for l in new_locked[header].splitlines() if l.strip()]
            for line in old_lines:
                if line not in new_lines:
                    raise LockedSectionTamperError(
                        f"Locked section '{header}' was tampered with! Missing original line: '{line}'"
                    )

        # Check line limit
        lines = new_content.splitlines()
        if len(lines) > max_lines:
            archive_entry = f"\n# ARCHIVE — {utc_now_iso()}\n" + new_content
            if self.briefing_archive_path.exists():
                with open(self.briefing_archive_path, "a", encoding="utf-8") as f:
                    f.write(archive_entry)
            else:
                self.briefing_archive_path.write_text(archive_entry, encoding="utf-8")

            # Prune mutable sections while strictly preserving locked sections
            pruned_content = self._prune_mutable_sections(new_content, max_lines)
            self.briefing_path.write_text(pruned_content, encoding="utf-8")
            return self.briefing_path

        self.briefing_path.write_text(new_content, encoding="utf-8")
        return self.briefing_path

    def _prune_mutable_sections(self, content: str, max_lines: int) -> str:
        """
        Truncates verbose mutable sections while strictly preserving locked sections.
        Locked sections (## 🔒 ...) are NEVER truncated, split, or modified.
        """
        lines = content.splitlines()
        if len(lines) <= max_lines:
            return content

        # Parse content into structured sections using unified fence-aware splitter
        sections = self._split_briefing_sections(content)

        # Strip any prior archive notice section or standalone notice lines from mutable sections
        archive_heading = "## Archive Notice"
        archive_notice_line = "[... Mutable history archived to BRIEFING_ARCHIVE.md ...]"
        archive_notice = [archive_heading, archive_notice_line]
        notice_line_count = len(archive_notice)

        cleaned_sections: List[Dict[str, Any]] = []
        for s in sections:
            if not s["is_locked"]:
                if re.match(r"^ {0,3}##[ \t]+Archive Notice[ \t]*$", s["header"], re.IGNORECASE):
                    continue
                s["lines"] = [ln for ln in s["lines"] if ln.strip() != archive_notice_line]
            cleaned_sections.append(s)
        sections = cleaned_sections

        def total_lines() -> int:
            cnt = sum((1 if s["header"] else 0) + len(s["lines"]) for s in sections)
            return cnt + notice_line_count

        # Iteratively prune mutable sections until total lines <= max_lines
        while total_lines() > max_lines:
            # Candidates for body line pruning: non-locked sections with body lines
            mutable_with_lines = [
                s for s in sections
                if not s["is_locked"] and not s["header"].startswith("# BRIEFING") and len(s["lines"]) > 0
            ]
            if mutable_with_lines:
                # Shed lines from the mutable section with the most body lines
                largest = max(mutable_with_lines, key=lambda s: len(s["lines"]))
                excess = total_lines() - max_lines
                pop_count = min(excess, len(largest["lines"]))
                largest["lines"] = largest["lines"][:-pop_count]
                continue

            # If all mutable sections have 0 body lines, remove non-essential mutable section headers
            removable_headers = [
                s for s in sections
                if not s["is_locked"]
                and not s["header"].startswith("# BRIEFING")
                and not s["header"].startswith("## Mission")
            ]
            if removable_headers:
                sections.remove(removable_headers[-1])
                continue

            # Only title, Mission, and locked sections remain; stop pruning
            break

        # Reconstruct pruned briefing text
        rendered: List[str] = []
        for s in sections:
            if s["header"]:
                rendered.append(s["header"])
            rendered.extend(s["lines"])

        rendered.extend(archive_notice)
        return "\n".join(rendered)

    def write_dispatch(
        self,
        task_description: str,
        context_files: Optional[List[Path]] = None,
        constraints: Optional[List[str]] = None,
        caller_id: Optional[str] = None
    ) -> Path:
        """
        Appends incoming dispatch instruction with UTC timestamp header.
        Deduplicates if the latest dispatch matches.
        """
        timestamp = utc_now_iso()
        refs = "\n".join(f"- `{f.resolve()}`" for f in (context_files or []))
        c_block = "\n".join(f"- {c}" for c in (constraints or []))

        entry = f"""## {timestamp}
**Caller**: {caller_id or 'parent'}

### Task
{task_description.strip()}

### Context Files
{refs if refs else "- None provided"}

### Specific Constraints
{c_block if c_block else "- Default archetype constraints apply"}
"""
        if self.dispatch_path.exists():
            existing = self.dispatch_path.read_text(encoding="utf-8", errors="replace")
            entry_split_re = r"(?m)(?=^## \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\n]*\n\*\*Caller\*\*:)"
            chunks = re.split(entry_split_re, existing)
            dispatch_entries = [
                c for c in chunks
                if re.match(r"^## \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\n]*\n\*\*Caller\*\*:", c)
            ]
            if dispatch_entries:
                latest_body = dispatch_entries[-1].partition("\n")[2].strip()
                current_body = entry.partition("\n")[2].strip()
                if latest_body == current_body:
                    return self.dispatch_path
            with open(self.dispatch_path, "a", encoding="utf-8") as f:
                f.write(f"\n{entry}\n")
        else:
            header = f"# DISPATCH — {self.agent_name}\n\n{entry}\n"
            self.dispatch_path.write_text(header, encoding="utf-8")

        return self.dispatch_path

    def write_progress(
        self,
        status: str,
        items: Optional[List[Tuple[str, bool]]] = None,
        notes: str = ""
    ) -> Path:
        """
        Writes progress.md heartbeat with Last visited timestamp and checklist.
        """
        checklist_str = ""
        if items:
            lines = []
            for text, checked in items:
                mark = "x" if checked else " "
                lines.append(f"- [{mark}] {text}")
            checklist_str = "\n## Steps\n" + "\n".join(lines) + "\n"

        notes_str = f"\n## Notes\n{notes.strip()}\n" if notes.strip() else ""

        content = f"""# Progress: {self.agent_name}

Last visited: {utc_now_iso()}
Status: {status}
{checklist_str}{notes_str}"""
        self.progress_path.write_text(content, encoding="utf-8")
        return self.progress_path

    def get_last_visited(self) -> Optional[datetime.datetime]:
        """Parses Last visited timestamp from progress.md; falls back to mtime."""
        if not self.progress_path.exists():
            return None
        text = self.progress_path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("Last visited:"):
                raw_ts = line.replace("Last visited:", "").strip()
                dt = parse_iso_timestamp(raw_ts)
                if dt:
                    return dt
        return datetime.datetime.fromtimestamp(
            self.progress_path.stat().st_mtime, tz=datetime.timezone.utc
        )

    def is_healthy(self, timeout_seconds: float = DEFAULT_LIVENESS_TIMEOUT_SECONDS) -> bool:
        """Checks if agent reported progress within timeout_seconds."""
        last_dt = self.get_last_visited()
        if not last_dt:
            return False
        if last_dt.tzinfo is None or last_dt.tzinfo.utcoffset(last_dt) is None:
            last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        return (now_dt - last_dt).total_seconds() <= timeout_seconds

    def write_handoff(self, report: HandoffReport) -> Path:
        """Validates and writes 5-component handoff.md."""
        validation_errors = report.validate()
        if validation_errors:
            raise HandoffValidationError(f"Invalid handoff report: {'; '.join(validation_errors)}")
        content = report.render_markdown()
        self.handoff_path.write_text(content, encoding="utf-8")
        return self.handoff_path

    def read_handoff(self) -> Optional[str]:
        """Reads handoff.md content if it exists."""
        if self.handoff_path.exists():
            return self.handoff_path.read_text(encoding="utf-8")
        return None

    def parse_handoff(self) -> HandoffReport:
        """Parses handoff.md into a structured HandoffReport dataclass."""
        text = self.read_handoff()
        if not text:
            raise HandoffValidationError(f"handoff.md does not exist at {self.handoff_path}")
        return parse_handoff_text(text, default_agent_name=self.agent_name, default_role=self.archetype)


class TeamworkRunState:
    """
    Manages top-level run isolation directory:
    .agents/teamwork/<run_id>/
    """
    def __init__(
        self,
        base_dir: Optional[Union[Path, str]] = None,
        workspace_root: Optional[Union[Path, str]] = None,
        run_id: Optional[str] = None,
        base_state_dir: Optional[Union[Path, str]] = None,
    ):
        if workspace_root:
            self.workspace_root = Path(workspace_root).resolve()
        else:
            self.workspace_root = Path.cwd().resolve()

        if not run_id:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            run_id = f"run_{ts}"
        self.run_id = run_id

        # Use base_state_dir or base_dir if provided
        chosen_base = base_state_dir or base_dir
        if chosen_base:
            self.run_dir = (Path(chosen_base) / run_id).resolve()
        else:
            self.run_dir = (self.workspace_root / ".agents" / "teamwork" / run_id).resolve()

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.original_request_file = self.run_dir / "ORIGINAL_REQUEST.md"
        self.project_file = self.run_dir / "PROJECT.md"
        self.gate_status_file = self.run_dir / "GATE_STATUS.md"
        self.dead_ends_file = self.run_dir / "DEAD_ENDS.md"
        self._agents: Dict[str, AgentState] = {}

    def get_or_create_agent_state(
        self,
        agent_name: str,
        archetype: str = "worker",
        **kwargs
    ) -> AgentState:
        """Retrieves cached AgentState or instantiates a new one."""
        if agent_name in self._agents:
            return self._agents[agent_name]
        agent_state = AgentState.create(
            run_dir=self.run_dir,
            agent_name=agent_name,
            archetype=archetype,
            **kwargs
        )
        self._agents[agent_name] = agent_state
        return agent_state

    def record_original_request(self, user_request: str, overwrite: bool = False) -> Path:
        """
        Verbatim immutable freezing of user request.
        Raises ImmutableStateViolationError if already exists with different content and not overwrite.
        """
        content = f"""# Original User Request
## Initial Request — {utc_now_iso()}
{user_request.strip()}
"""
        if self.original_request_file.exists():
            existing_content = self.original_request_file.read_text(encoding="utf-8")
            if not overwrite:
                extracted = existing_content.strip()
                parts = re.split(r"##\s*Initial Request\s*—.*?\n", existing_content, maxsplit=1)
                if len(parts) > 1:
                    extracted = parts[1].strip()

                if user_request.strip() == extracted or user_request.strip() == existing_content.strip():
                    return self.original_request_file
                raise ImmutableStateViolationError(
                    f"ORIGINAL_REQUEST.md already exists at {self.original_request_file} and is immutable! "
                    "Cannot overwrite frozen ground truth."
                )
        self.original_request_file.write_text(content, encoding="utf-8")
        return self.original_request_file

    def read_original_request(self) -> str:
        """Reads frozen user request."""
        if not self.original_request_file.exists():
            return ""
        return self.original_request_file.read_text(encoding="utf-8")

    def init_gate_status(self, milestone: str, iteration: int) -> Path:
        """Initializes or appends milestone iteration table header in GATE_STATUS.md."""
        header = f"""
## Gate — Milestone {milestone} — Iteration {iteration}
| Agent | Role | Verdict | Source | Notes |
|-------|------|---------|--------|-------|
"""
        if not self.gate_status_file.exists():
            initial_text = f"# Gate Status: Milestone {milestone}\n{header}"
            self.gate_status_file.write_text(initial_text, encoding="utf-8")
        else:
            with open(self.gate_status_file, "a", encoding="utf-8") as f:
                f.write(header)
        return self.gate_status_file

    def append_gate_verdict(
        self,
        agent_name: str,
        role: str,
        verdict: str,
        source: str = "handoff.md",
        notes: str = ""
    ) -> None:
        """Appends a single verdict row to the active table in GATE_STATUS.md."""
        clean_notes = str(notes).replace("|", "/").replace("\n", " ").strip()
        line = f"| {agent_name} | {role} | {verdict} | {source} | {clean_notes} |\n"
        with open(self.gate_status_file, "a", encoding="utf-8") as f:
            f.write(line)

    def record_gate_result(self, result: str, reason: str = "") -> None:
        """Appends Gate Result block: Gate Result: **PASS** or Gate Result: **FAIL**."""
        line = f"\nGate Result: **{result}**"
        if reason:
            line += f" ({reason})"
        line += "\n\n"
        with open(self.gate_status_file, "a", encoding="utf-8") as f:
            f.write(line)

    def update_gate_status(
        self,
        milestone: str,
        iteration: int,
        verdicts: List[Any],
        result: Any
    ) -> Path:
        """High-level atomic updater for GATE_STATUS.md."""
        self.init_gate_status(milestone=milestone, iteration=iteration)
        for v in verdicts:
            notes = getattr(v, "details", "") or getattr(v, "defect", "") or ""
            self.append_gate_verdict(
                agent_name=getattr(v, "agent_name", "unknown"),
                role=getattr(v, "role", "unknown"),
                verdict=getattr(v, "verdict", "UNKNOWN"),
                source=getattr(v, "source_file", "handoff.md"),
                notes=notes
            )
        res_str = "PASS" if getattr(result, "passed", False) else "FAIL"
        reason_str = getattr(result, "reason", "")
        self.record_gate_result(result=res_str, reason=reason_str)
        return self.gate_status_file

    def record_dead_end(
        self,
        iteration: int,
        approach: str,
        reason: str = "",
        files: Optional[List[str]] = None,
        why_failed: str = "",
        files_touched: Optional[List[str]] = None,
        milestone: str = ""
    ) -> Path:
        """
        Appends a failed hypothesis/approach to DEAD_ENDS.md negative knowledge base.
        Supports both (reason, files) and (why_failed, files_touched) keyword signatures.
        """
        eff_why = why_failed or reason or "Defect detected"
        eff_files = files_touched if files_touched is not None else (files or [])

        if not self.dead_ends_file.exists():
            header = f"# Dead Ends{f' — {milestone}' if milestone else ''}\n\n"
            header += "| Iteration | Approach Tried | Why It Failed | Files Touched |\n"
            header += "|-----------|---------------|---------------|---------------|\n"
            self.dead_ends_file.write_text(header, encoding="utf-8")

        esc_approach = approach.replace("|", "/").replace("\n", " ").strip()
        esc_why = eff_why.replace("|", "/").replace("\n", " ").strip()
        esc_files = ", ".join(f"`{f}`" for f in eff_files)
        row = f"| {iteration} | {esc_approach} | {esc_why} | {esc_files} |\n"

        with open(self.dead_ends_file, "a", encoding="utf-8") as f:
            f.write(row)
        return self.dead_ends_file

    def read_dead_ends(self) -> List[DeadEndRecord]:
        """Parses DEAD_ENDS.md into structured DeadEndRecord objects."""
        if not self.dead_ends_file.exists():
            return []
        records = []
        lines = self.dead_ends_file.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if not line.startswith("|") or "Approach Tried" in line or "---" in line:
                continue
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 4:
                try:
                    iter_num = int(parts[0])
                except ValueError:
                    iter_num = 0
                approach = parts[1]
                why = parts[2]
                files = [f.strip().strip("`") for f in parts[3].split(",") if f.strip()]
                records.append(DeadEndRecord(
                    iteration=iter_num,
                    approach=approach,
                    why_failed=why,
                    files_touched=files
                ))
        return records


_HANDOFF_META_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*|__)?(Agent|Role|Verdict|Defect)(?:\*\*|__)?\s*:(?:\*\*|__)?\s*(.*)",
    re.IGNORECASE,
)


def parse_handoff_text(text: str, default_agent_name: str = "", default_role: str = "") -> HandoffReport:
    """Extracts 5 components and metadata from handoff markdown text."""
    if not isinstance(text, str):
        text = ""

    agent_name = default_agent_name
    role = default_role
    verdict = "FAIL"
    defect = None

    # Mask code fences before metadata and section extraction so fenced content cannot spoof
    masked_text = mask_fenced_code_blocks(text)

    for orig_line, masked_line in zip(text.splitlines()[:20], masked_text.splitlines()[:20]):
        m_masked = _HANDOFF_META_RE.match(masked_line)
        if not m_masked:
            continue
        m_orig = _HANDOFF_META_RE.match(orig_line)
        if not m_orig:
            continue
        key = m_masked.group(1).strip().lower()
        val = m_orig.group(2).strip()
        if key == "agent":
            cleaned = val.replace("`", "").replace("*", "").strip()
            if cleaned:
                agent_name = cleaned
        elif key == "role":
            cleaned = val.replace("`", "").replace("*", "").strip()
            if cleaned:
                role = cleaned
        elif key == "verdict":
            verdict_part_raw = val.replace("*", "").replace("`", "").strip().strip("_").strip()
            upper_raw = verdict_part_raw.upper()
            if upper_raw.startswith("VICTORY CONFIRMED"):
                verdict = "VICTORY CONFIRMED"
            elif upper_raw.startswith("VICTORY REJECTED"):
                verdict = "VICTORY REJECTED"
            else:
                tokens = verdict_part_raw.split()
                if tokens:
                    cleaned_tok = tokens[0].strip("_*`.,;:()").upper()
                    if cleaned_tok:
                        verdict = cleaned_tok
        elif key == "defect":
            cleaned = val.strip()
            if cleaned:
                defect = cleaned

    def get_section(heading_regex: str) -> str:
        pattern = (
            rf"^[ ]{{0,3}}##(?!#)[ \t]*(?:{heading_regex})[ \t]*(?:\r?\n|\Z)"
            rf"(.*?)(?=^[ ]{{0,3}}##(?!#)|\Z)"
        )
        m = re.search(pattern, masked_text, re.DOTALL | re.IGNORECASE | re.MULTILINE)
        if m:
            return text[m.start(1):m.end(1)].strip()
        return ""

    observation = get_section(r"(?:1\.\s*)?Observation")
    if not observation:
        observation = get_section(r"(?:1\.\s*)?Milestone State")

    logic_chain = get_section(r"(?:2\.\s*)?Logic Chain")
    if not logic_chain:
        logic_chain = get_section(r"(?:2\.\s*)?Active Subagents")

    caveats = get_section(r"(?:3\.\s*)?Caveats")
    if not caveats:
        caveats = get_section(r"(?:3\.\s*)?Pending Decisions\b[^\r\n]*")

    conclusion = get_section(r"(?:4\.\s*)?Conclusion")
    if not conclusion:
        conclusion = get_section(r"(?:4\.\s*)?Key Artifacts")

    verification = get_section(r"(?:5\.\s*)?Verification Method")
    if not verification:
        verification = get_section(r"(?:5\.\s*)?Concrete Next Steps for Successor")
        if not verification:
            verification = get_section(r"Remaining Work")

    remaining_work = get_section(r"(?:5\.\s*)?Concrete Next Steps for Successor")
    if not remaining_work:
        remaining_work = get_section(r"Remaining Work")

    report = HandoffReport(
        agent_name=agent_name,
        role=role,
        verdict=verdict,
        observation=observation,
        logic_chain=logic_chain,
        caveats=caveats or "No caveats.",
        conclusion=conclusion,
        verification_method=verification,
        defect=defect,
        remaining_work=remaining_work or None,
    )
    errors = report.validate()
    if errors:
        raise HandoffValidationError(f"Invalid handoff: {'; '.join(errors)}")
    return report
