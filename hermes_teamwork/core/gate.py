"""
hermes_teamwork.core.gate
~~~~~~~~~~~~~~~~~~~~~~~~~
Adversarial Review Gate Engine enforcing Strict AND Consensus,
Binary Veto on Forensic Auditor, and Adversarial Veto on Challengers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional

from hermes_teamwork.core.state import mask_fenced_code_blocks


def _norm_upper(val: Any) -> str:
    return val.strip().upper() if isinstance(val, str) else ""


def _norm_lower(val: Any) -> str:
    return val.strip().lower() if isinstance(val, str) else ""


class Verdict(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_WITH_NITS = "APPROVE_WITH_NITS"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    CLEAN = "CLEAN"
    INTEGRITY_VIOLATION = "INTEGRITY_VIOLATION"
    DONE = "DONE"
    FAIL = "FAIL"


@dataclass
class GateVerdict:
    """Individual verdict submitted by an agent for gate evaluation."""
    agent_name: str
    role: str  # worker, reviewer, challenger, auditor, victory_auditor
    verdict: str  # APPROVE, REQUEST_CHANGES, CLEAN, INTEGRITY_VIOLATION, DONE, FAIL
    details: str = ""
    defect: Optional[str] = None
    source_file: str = "handoff.md"

    @property
    def is_clean(self) -> bool:
        return _norm_upper(self.verdict) == "CLEAN"

    @property
    def is_integrity_violation(self) -> bool:
        return _norm_upper(self.verdict) == "INTEGRITY_VIOLATION"

    @property
    def is_approved(self) -> bool:
        return _norm_upper(self.verdict) in ("APPROVE", "APPROVE_WITH_NITS")

    @property
    def is_done(self) -> bool:
        return _norm_upper(self.verdict) == "DONE"

    @property
    def is_request_changes(self) -> bool:
        return _norm_upper(self.verdict) == "REQUEST_CHANGES"


@dataclass
class GateResult:
    """Comprehensive evaluation result returned by AdversarialGate."""
    passed: bool
    reason: str
    defect_ledger: List[str] = field(default_factory=list)
    binary_veto_triggered: bool = False
    adversarial_veto_triggered: bool = False
    verdicts_evaluated: List[GateVerdict] = field(default_factory=list)

    def __iter__(self):
        """Enables native tuple unpacking: `passed, reason = gate_result`."""
        return iter((self.passed, self.reason))

    def format_status_line(self) -> str:
        """Formats the terminal line for GATE_STATUS.md."""
        res = "PASS" if self.passed else "FAIL"
        if self.passed:
            return f"Gate Result: **{res}**"
        return f"Gate Result: **{res}** ({self.reason})"


class AdversarialGate:
    """
    Adversarial Gate Evaluator enforcing Strict AND Consensus Logic.

    Consensus Rules:
    1. Forensic Auditor: Binary Veto. Verdict MUST be CLEAN.
       If INTEGRITY_VIOLATION -> binary_veto_triggered = True, immediate FAIL.
    2. Challenger: Adversarial Veto. Verdict MUST be APPROVE.
       If REQUEST_CHANGES -> adversarial_veto_triggered = True, FAIL with defect logged.
    3. Reviewer: Verdict MUST be APPROVE or APPROVE_WITH_NITS.
       If REQUEST_CHANGES -> FAIL with defect logged.
    4. Worker: Verdict MUST be DONE.
       If FAIL or incomplete -> FAIL.
    5. Quorum: Minimum required roles must all be present if strict_quorum=True.
    """

    @classmethod
    def evaluate(
        cls,
        verdicts: List[GateVerdict],
        strict_quorum: bool = True,
        min_reviewers: int = 1,
        min_challengers: int = 1,
        require_auditor: bool = True,
        require_worker: bool = True
    ) -> GateResult:
        """
        Evaluates a set of agent verdicts against strict consensus rules.
        """
        defect_ledger: List[str] = []
        evaluated = list(verdicts)

        # Step 0: Fail closed on malformed verdicts (non-string, empty, or whitespace-only)
        for v in verdicts:
            role_str = _norm_lower(v.role)
            verdict_str = _norm_upper(v.verdict)
            if not role_str or not verdict_str:
                defect_ledger.append(
                    f"Malformed verdict from {v.agent_name}: role={v.role!r}, verdict={v.verdict!r}"
                )

        # -------------------------------------------------------------
        # STEP 1: GLOBAL BINARY VETO & FORENSIC AUDITOR CHECK
        # -------------------------------------------------------------
        # Pass 1: Global scan across ALL verdicts (including empty/unknown roles)
        for v in verdicts:
            if v.is_integrity_violation:
                msg = (
                    f"FORENSIC INTEGRITY VIOLATION by {v.agent_name}: "
                    f"{v.details or v.defect or 'Unauthorized modification or test tampering'}"
                )
                defect_ledger.append(msg)
                return GateResult(
                    passed=False,
                    reason=msg,
                    defect_ledger=defect_ledger,
                    binary_veto_triggered=True,
                    adversarial_veto_triggered=False,
                    verdicts_evaluated=evaluated
                )

        # Categorize verdicts by role and fail closed on unrecognized non-empty roles
        auditor_verdicts: List[GateVerdict] = []
        challenger_verdicts: List[GateVerdict] = []
        reviewer_verdicts: List[GateVerdict] = []
        worker_verdicts: List[GateVerdict] = []
        unrecognized_verdicts: List[GateVerdict] = []

        for v in verdicts:
            r = _norm_lower(v.role)
            matched = False
            if "auditor" in r and "victory" not in r:
                auditor_verdicts.append(v)
                matched = True
            if "challenger" in r:
                challenger_verdicts.append(v)
                matched = True
            if "reviewer" in r:
                reviewer_verdicts.append(v)
                matched = True
            if "worker" in r or "implementer" in r:
                worker_verdicts.append(v)
                matched = True
            if r and not matched:
                unrecognized_verdicts.append(v)

        for v in unrecognized_verdicts:
            defect_ledger.append(
                f"Unrecognized role {v.role!r} from {v.agent_name} (verdict={v.verdict!r})"
            )

        # Pass 2: Check for any auditor not reporting CLEAN
        for v in auditor_verdicts:
            if not v.is_clean:
                msg = f"Auditor {v.agent_name} did not report CLEAN (reported: {v.verdict}): {v.details or v.defect or 'Integrity audit failed'}"
                defect_ledger.append(msg)
                return GateResult(
                    passed=False,
                    reason=msg,
                    defect_ledger=defect_ledger,
                    binary_veto_triggered=False,
                    adversarial_veto_triggered=False,
                    verdicts_evaluated=evaluated
                )

        # -------------------------------------------------------------
        # STEP 2: WORKER CHECK (Must be DONE)
        # -------------------------------------------------------------
        for v in worker_verdicts:
            if not v.is_done:
                msg = f"Worker {v.agent_name} incomplete (reported: {v.verdict}): {v.details}"
                defect_ledger.append(msg)

        # -------------------------------------------------------------
        # STEP 3: ADVERSARIAL CHALLENGER CHECK (Adversarial Veto)
        # -------------------------------------------------------------
        adversarial_veto = False
        for v in challenger_verdicts:
            if _norm_upper(v.verdict) != "APPROVE":
                adversarial_veto = True
                defect_msg = v.defect or v.details or "Edge case failure"
                msg = f"Challenger {v.agent_name} {v.verdict}: {defect_msg}"
                defect_ledger.append(msg)

        # -------------------------------------------------------------
        # STEP 4: REVIEWER CHECK (Must be APPROVE or APPROVE_WITH_NITS)
        # -------------------------------------------------------------
        for v in reviewer_verdicts:
            if not v.is_approved:
                defect_msg = v.defect or v.details or "Code review objection"
                msg = f"Reviewer {v.agent_name} {v.verdict}: {defect_msg}"
                defect_ledger.append(msg)

        # -------------------------------------------------------------
        # STEP 5: QUORUM VALIDATION (If strict_quorum is enabled)
        # -------------------------------------------------------------
        if strict_quorum:
            if require_worker and not worker_verdicts:
                defect_ledger.append("Quorum violation: Missing mandatory Worker verification")
            if require_auditor and not auditor_verdicts:
                defect_ledger.append("Quorum violation: Missing mandatory Forensic Auditor verification")
            if len(reviewer_verdicts) < min_reviewers:
                defect_ledger.append(
                    f"Quorum violation: Expected at least {min_reviewers} Reviewer(s), found {len(reviewer_verdicts)}"
                )
            if len(challenger_verdicts) < min_challengers:
                defect_ledger.append(
                    f"Quorum violation: Expected at least {min_challengers} Challenger(s), found {len(challenger_verdicts)}"
                )

        # -------------------------------------------------------------
        # STEP 6: CONSENSUS SYNTHESIS
        # -------------------------------------------------------------
        if defect_ledger:
            primary_reason = "; ".join(defect_ledger)
            return GateResult(
                passed=False,
                reason=primary_reason,
                defect_ledger=defect_ledger,
                binary_veto_triggered=False,
                adversarial_veto_triggered=adversarial_veto,
                verdicts_evaluated=evaluated
            )

        return GateResult(
            passed=True,
            reason="All criteria satisfied (Worker DONE, Auditor CLEAN, Reviewers APPROVE, Challengers APPROVE)",
            defect_ledger=[],
            binary_veto_triggered=False,
            adversarial_veto_triggered=False,
            verdicts_evaluated=evaluated
        )

    @classmethod
    def parse_verdict_from_handoff(
        cls,
        agent_name: str,
        role: str,
        handoff_text: str,
        source_file: str = "handoff.md"
    ) -> GateVerdict:
        """
        Parses agent verdict and defects from handoff markdown text.
        """
        if not isinstance(handoff_text, str):
            handoff_text = ""

        verdict_str = "FAIL"
        details = ""
        defect = None

        # Mask CommonMark fenced code blocks BEFORE parsing Verdict, Defect, or Conclusion
        masked_handoff = mask_fenced_code_blocks(handoff_text)

        m_verdict = re.search(
            r"(?im)^ {0,3}(?:[-*][ \t]+)?(?:"
            r"\*\*Verdict(?:\*\*[ \t]*:[ \t]*|[ \t]*:[ \t]*\*\*[ \t]*|[ \t]*:[ \t]*(?!\*\*))"
            r"|__Verdict(?:__[ \t]*:[ \t]*|[ \t]*:[ \t]*__[ \t]*|[ \t]*:[ \t]*(?!__))"
            r"|Verdict[ \t]*:[ \t]*"
            r")[*_`]*([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*(?:[ \t]+(?:CONFIRMED|REJECTED))?)[*_`]*",
            masked_handoff,
        )
        if m_verdict:
            verdict_str = m_verdict.group(1).strip().upper()

        m_defect = re.search(
            r"(?im)^ {0,3}(?:[-*][ \t]+)?(?:"
            r"\*\*Defect(?:\*\*[ \t]*:[ \t]*|[ \t]*:[ \t]*\*\*[ \t]*|[ \t]*:[ \t]*(?!\*\*))"
            r"|__Defect(?:__[ \t]*:[ \t]*|[ \t]*:[ \t]*__[ \t]*|[ \t]*:[ \t]*(?!__))"
            r"|Defect[ \t]*:[ \t]*"
            r")(\S[^\r\n]*)",
            masked_handoff,
        )
        if m_defect:
            cleaned_defect = handoff_text[m_defect.start(1):m_defect.end(1)].strip()
            if cleaned_defect:
                defect = cleaned_defect

        m_conclusion = re.search(
            r"(?im)^ {0,3}##(?!#)[ \t]*(?:4\.[ \t]*)?Conclusion[ \t]*(?:\r?\n|\Z)"
            r"(.*?)(?=^[ ]{0,3}##(?!#)|\Z)",
            masked_handoff,
            re.DOTALL,
        )
        if m_conclusion:
            details = handoff_text[m_conclusion.start(1):m_conclusion.end(1)].strip()
        else:
            details = handoff_text[:200].strip()

        return GateVerdict(
            agent_name=agent_name,
            role=role,
            verdict=verdict_str,
            details=details,
            defect=defect,
            source_file=source_file
        )
