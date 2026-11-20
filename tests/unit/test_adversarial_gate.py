"""
tests.unit.test_adversarial_gate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Adversarial Review Gate (hermes_teamwork.core.gate).
"""
import pytest
from hermes_teamwork.core.gate import AdversarialGate, GateVerdict, GateResult


def test_strict_and_all_pass():
    """Scenario 1: Full consensus passing gate."""
    verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE", details="All 100 tests passed"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN", details="Zero diff violations"),
        GateVerdict(agent_name="reviewer_full", role="reviewer", verdict="APPROVE", details="Full suite passed"),
        GateVerdict(agent_name="reviewer_scoped", role="reviewer", verdict="APPROVE", details="Clean code structure"),
        GateVerdict(agent_name="challenger_edge", role="challenger", verdict="APPROVE", details="Edge cases robust"),
        GateVerdict(agent_name="challenger_soundness", role="challenger", verdict="APPROVE", details="Invariants hold"),
    ]
    res = AdversarialGate.evaluate(verdicts)
    assert res.passed is True
    assert res.binary_veto_triggered is False
    assert res.adversarial_veto_triggered is False
    assert len(res.defect_ledger) == 0
    assert "All criteria satisfied" in res.reason


def test_forensic_auditor_binary_veto():
    """Scenario 2: Binary veto on INTEGRITY_VIOLATION."""
    verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE", details="Tests pass"),
        GateVerdict(
            agent_name="auditor_1",
            role="auditor",
            verdict="INTEGRITY_VIOLATION",
            details="Weakened test assertion in test_core.py:45",
            defect="Test weakening detected",
        ),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    res = AdversarialGate.evaluate(verdicts)
    assert res.passed is False
    assert res.binary_veto_triggered is True
    assert "FORENSIC INTEGRITY VIOLATION" in res.reason
    assert "Weakened test assertion" in res.reason


def test_forensic_auditor_non_clean_rejected():
    """Scenario 3: Auditor not reporting CLEAN."""
    verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="FAIL", details="Untracked files in git tree"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    res = AdversarialGate.evaluate(verdicts)
    assert res.passed is False
    assert res.binary_veto_triggered is False
    assert "did not report CLEAN" in res.reason


def test_challenger_adversarial_veto():
    """Scenario 4: Adversarial veto on REQUEST_CHANGES."""
    verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(
            agent_name="challenger_edge",
            role="challenger",
            verdict="REQUEST_CHANGES",
            defect="Buffer overflow on 65536 byte payload",
        ),
    ]
    res = AdversarialGate.evaluate(verdicts)
    assert res.passed is False
    assert res.adversarial_veto_triggered is True
    assert "Buffer overflow" in res.reason
    assert any("Buffer overflow" in d for d in res.defect_ledger)


def test_reviewer_request_changes():
    """Scenario 5: Reviewer code rejection."""
    verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(
            agent_name="reviewer_1",
            role="reviewer",
            verdict="REQUEST_CHANGES",
            defect="Missing error handling for null pointer",
        ),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    res = AdversarialGate.evaluate(verdicts)
    assert res.passed is False
    assert res.adversarial_veto_triggered is False
    assert "Missing error handling" in res.reason


def test_reviewer_approve_with_nits():
    """Scenario 6: Tolerant approval on non-blocking nits."""
    verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE_WITH_NITS", details="Typo in comment"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    res = AdversarialGate.evaluate(verdicts)
    assert res.passed is True
    assert len(res.defect_ledger) == 0


def test_worker_incomplete():
    """Scenario 7: Worker test failure or unfinished work."""
    verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="FAIL", details="3 unit tests failed"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    res = AdversarialGate.evaluate(verdicts)
    assert res.passed is False
    assert "Worker worker_1 incomplete" in res.reason


def test_multiple_defects_aggregation():
    """Scenario 8: Aggregation of defects across multiple verifiers."""
    verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="REQUEST_CHANGES", defect="Defect A: Memory leak"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="REQUEST_CHANGES", defect="Defect B: Race condition"),
    ]
    res = AdversarialGate.evaluate(verdicts)
    assert res.passed is False
    assert len(res.defect_ledger) == 2
    assert any("Defect A" in d for d in res.defect_ledger)
    assert any("Defect B" in d for d in res.defect_ledger)


def test_strict_quorum_enforcement():
    """Scenario 9: Mandatory role presence check."""
    # Missing Auditor in strict quorum
    verdicts_missing_auditor = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    res = AdversarialGate.evaluate(verdicts_missing_auditor, strict_quorum=True, require_auditor=True)
    assert res.passed is False
    assert any("Missing mandatory Forensic Auditor" in d for d in res.defect_ledger)

    # Insufficient Challengers (expected 2, provided 1)
    verdicts_few_challengers = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    res2 = AdversarialGate.evaluate(verdicts_few_challengers, strict_quorum=True, min_challengers=2)
    assert res2.passed is False
    assert any("Expected at least 2 Challenger(s)" in d for d in res2.defect_ledger)


def test_handoff_verdict_parsing():
    """Scenario 10: Extracts GateVerdict from markdown text."""
    handoff_text = """# Handoff Report: reviewer_m1_1

**Agent**: `reviewer_m1_1`  
**Role**: `reviewer`  
**Verdict**: **REQUEST_CHANGES**  
**Defect**: Invariant violation in auth check  

---

## 1. Observation
Observed failure on line 124.

## 2. Logic Chain
Step 1: Analyzed input. Step 2: Invariant broke.

## 3. Caveats
No caveats.

## 4. Conclusion
Security regression identified in token parser.

## 5. Verification Method
pytest tests/test_auth.py
"""
    verdict = AdversarialGate.parse_verdict_from_handoff(
        agent_name="reviewer_m1_1",
        role="reviewer",
        handoff_text=handoff_text,
    )
    assert verdict.agent_name == "reviewer_m1_1"
    assert verdict.role == "reviewer"
    assert verdict.verdict == "REQUEST_CHANGES"
    assert verdict.defect == "Invariant violation in auth check"
    assert "Security regression" in verdict.details


def test_default_strict_quorum_fails_on_empty_or_partial():
    """Defect 2 Fix: Gate evaluation must enforce strict_quorum=True by default."""
    # Empty list must fail quorum check by default without explicit strict_quorum=True
    res_empty = AdversarialGate.evaluate([])
    assert res_empty.passed is False
    assert any("Quorum violation" in d for d in res_empty.defect_ledger)

    # Partial list with only worker must fail quorum check
    res_worker_only = AdversarialGate.evaluate([GateVerdict("w", "worker", "DONE")])
    assert res_worker_only.passed is False
    assert any("Quorum violation: Missing mandatory Forensic Auditor" in d for d in res_worker_only.defect_ledger)


def test_challenger_rejects_approve_with_nits():
    """Defect 3 Fix: Challengers must strictly output APPROVE; APPROVE_WITH_NITS is rejected."""
    verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(
            agent_name="challenger_1",
            role="challenger",
            verdict="APPROVE_WITH_NITS",
            details="Minor observation on naming convention"
        ),
    ]
    res = AdversarialGate.evaluate(verdicts)
    assert res.passed is False
    assert res.adversarial_veto_triggered is True
    assert any("Challenger challenger_1 APPROVE_WITH_NITS" in d for d in res.defect_ledger)


def test_gate_null_verdict_or_role_fails_closed():
    """Defect G-1 Fix: Null/missing verdict or role must fail closed without crashing."""
    # Test null verdict
    v_none = GateVerdict("worker_1", "worker", None)
    res_none = AdversarialGate.evaluate([v_none])
    assert res_none.passed is False
    assert any("Malformed verdict" in d or "incomplete" in d for d in res_none.defect_ledger)

    # Test null role
    v_role_none = GateVerdict("worker_1", None, "DONE")
    res_role_none = AdversarialGate.evaluate([v_role_none])
    assert res_role_none.passed is False
    assert any("Malformed verdict" in d or "Quorum violation" in d for d in res_role_none.defect_ledger)

    # Test properties directly with None
    v_empty = GateVerdict("agent_1", None, None)
    assert v_empty.is_clean is False
    assert v_empty.is_integrity_violation is False
    assert v_empty.is_approved is False
    assert v_empty.is_done is False
    assert v_empty.is_request_changes is False


def test_gate_binary_veto_priority_over_non_clean_auditor():
    """Defect G-2 Fix: Binary veto integrity violation has absolute priority over non-clean auditor failure."""
    v_w = GateVerdict("w", "worker", "DONE")
    v_r = GateVerdict("r", "reviewer", "APPROVE")
    v_c = GateVerdict("c", "challenger", "APPROVE")
    v_a1 = GateVerdict("a1", "auditor", "FAIL", details="Probe failure")
    v_a2 = GateVerdict("a2", "auditor", "INTEGRITY_VIOLATION", details="Tampered test")

    res = AdversarialGate.evaluate([v_w, v_r, v_c, v_a1, v_a2])
    assert res.passed is False
    assert res.binary_veto_triggered is True
    assert "FORENSIC INTEGRITY VIOLATION" in res.reason


def test_gate_truthy_non_string_role_or_verdict_fails_closed():
    """Defect G-1b Fix: Truthy non-string role/verdict (int, bool, list, dict) fail closed without AttributeError."""
    bad_values = [123, True, ["worker"], {"v": "DONE"}]
    for bad in bad_values:
        gv_bad_verdict = GateVerdict("w", "worker", bad)  # type: ignore[arg-type]
        assert gv_bad_verdict.is_clean is False
        assert gv_bad_verdict.is_integrity_violation is False
        assert gv_bad_verdict.is_approved is False
        assert gv_bad_verdict.is_done is False
        assert gv_bad_verdict.is_request_changes is False

        res_strict = AdversarialGate.evaluate([gv_bad_verdict], strict_quorum=True)
        assert res_strict.passed is False
        res_non_strict = AdversarialGate.evaluate([gv_bad_verdict], strict_quorum=False)
        assert res_non_strict.passed is False

        gv_bad_role = GateVerdict("w", bad, "DONE")  # type: ignore[arg-type]
        res_role = AdversarialGate.evaluate([gv_bad_role], strict_quorum=False)
        assert res_role.passed is False
        assert any("Malformed verdict" in d for d in res_role.defect_ledger)


def test_gate_empty_whitespace_fails_closed_non_strict():
    """Defect G-1b Fix: Empty/whitespace role or verdict fails closed even with full quorum & strict_quorum=False."""
    base_quorum = [
        GateVerdict("w", "worker", "DONE"),
        GateVerdict("a", "auditor", "CLEAN"),
        GateVerdict("r", "reviewer", "APPROVE"),
        GateVerdict("c", "challenger", "APPROVE"),
    ]
    for bad_verdict in [GateVerdict("x", "", ""), GateVerdict("x", "   ", "   ")]:
        res = AdversarialGate.evaluate(base_quorum + [bad_verdict], strict_quorum=False)
        assert res.passed is False
        assert any("Malformed verdict" in d for d in res.defect_ledger)


def test_gate_unrecognized_and_empty_roles_fail_closed():
    """Unrecognized/empty roles carrying INTEGRITY_VIOLATION, FAIL, or arbitrary verdicts fail closed."""
    base_quorum = [
        GateVerdict("w", "worker", "DONE"),
        GateVerdict("a", "auditor", "CLEAN"),
        GateVerdict("r", "reviewer", "APPROVE"),
        GateVerdict("c", "challenger", "APPROVE"),
    ]

    res_empty_iv = AdversarialGate.evaluate(
        base_quorum + [GateVerdict("rogue", "", "INTEGRITY_VIOLATION")]
    )
    assert res_empty_iv.passed is False
    assert res_empty_iv.binary_veto_triggered is True

    res_unknown_fail = AdversarialGate.evaluate(
        base_quorum + [GateVerdict("rogue", "security_scanner", "FAIL")]
    )
    assert res_unknown_fail.passed is False
    assert any("Unrecognized role" in d for d in res_unknown_fail.defect_ledger)

    res_unknown_approve = AdversarialGate.evaluate(
        base_quorum + [GateVerdict("rogue", "unknown_role", "APPROVE")]
    )
    assert res_unknown_approve.passed is False


def test_parse_verdict_from_handoff_commonmark_and_bold_colon():
    """Defect S-2b Fix: Fences, bold-colon variants, 4-space indentation, and ### subsections parse accurately."""
    handoff = """# Handoff Report: challenger_1
**Agent**: `challenger_1`
**Role**: `challenger`
```markdown
**Verdict**: **APPROVE**
**Defect**: SPOOFED_IN_FENCE
```
**Verdict:** **REQUEST_CHANGES**
**Defect:** Colon inside bold detected

## 1. Observation
Inline marker ``` in prose should not invert fences.
```python
x = "```"
## 4. Conclusion
SPOOFED_IN_CODE_BLOCK
```
    ## 4. Conclusion
    SPOOFED_INDENTED_HEADING

## 2. Logic Chain
Reasoning intact.

## 3. Caveats
No caveats.

## 4. Conclusion
Real conclusion part 1.
### 4.1 Sub-details
Real conclusion part 2.

## 5. Verification Method
pytest -v
"""
    gv = AdversarialGate.parse_verdict_from_handoff("challenger_1", "challenger", handoff)
    assert gv.verdict == "REQUEST_CHANGES"
    assert gv.defect == "Colon inside bold detected"
    assert "SPOOFED" not in gv.details
    assert "Real conclusion part 1." in gv.details
    assert "Real conclusion part 2." in gv.details


def test_parse_verdict_from_handoff_empty_lines_no_newline_cross_and_underscore_bold():
    """Defect G-3 + __BOLD__ Fix: Empty Verdict/Defect lines never cross newlines or capture '**'; __BOLD__ strips cleanly."""
    body = (
        "\n## 1. Observation\nObs\n"
        "## 2. Logic Chain\nLog\n"
        "## 3. Caveats\nNone\n"
        "## 4. Conclusion\nConc\n"
        "## 5. Verification Method\npytest\n"
    )

    gv1 = AdversarialGate.parse_verdict_from_handoff(
        "w1", "worker", "# Handoff\n**Verdict**:\n**Summary**: All done\n" + body
    )
    assert gv1.verdict == "FAIL"

    gv2 = AdversarialGate.parse_verdict_from_handoff(
        "w1", "worker", "# Handoff\n**Verdict:**  \nPending verification\n" + body
    )
    assert gv2.verdict == "FAIL"

    gv3 = AdversarialGate.parse_verdict_from_handoff(
        "c1", "challenger", "# Handoff\n**Verdict**: **APPROVE**\n**Defect**:   \n## 1. Observation\nObs\n## 2. Logic Chain\nLog\n## 3. Caveats\nNone\n## 4. Conclusion\nConc\n## 5. Verification Method\npytest\n"
    )
    assert gv3.verdict == "APPROVE"
    assert gv3.defect is None

    gv4 = AdversarialGate.parse_verdict_from_handoff(
        "c1", "challenger", "# Handoff\n**Verdict**: **APPROVE**\n**Defect:**\r\n---\r\n" + body
    )
    assert gv4.defect is None

    for raw, expected in [
        ("__REQUEST_CHANGES__", "REQUEST_CHANGES"),
        ("__APPROVE__", "APPROVE"),
        ("__CLEAN__", "CLEAN"),
        ("__APPROVE_WITH_NITS__", "APPROVE_WITH_NITS"),
        ("__INTEGRITY_VIOLATION__", "INTEGRITY_VIOLATION"),
    ]:
        gv_u = AdversarialGate.parse_verdict_from_handoff(
            "ag", "challenger", f"# Handoff\n**Verdict**: {raw}\n" + body
        )
        assert gv_u.verdict == expected

    # Parsed __BOLD__ verdicts pass Strict AND consensus when valid
    verdicts = [
        AdversarialGate.parse_verdict_from_handoff("w", "worker", "# H\n**Verdict**: __DONE__\n" + body),
        AdversarialGate.parse_verdict_from_handoff("a", "auditor", "# H\n**Verdict**: __CLEAN__\n" + body),
        AdversarialGate.parse_verdict_from_handoff("r", "reviewer", "# H\n**Verdict**: __APPROVE__\n" + body),
        AdversarialGate.parse_verdict_from_handoff("c", "challenger", "# H\n**Verdict**: __APPROVE__\n" + body),
    ]
    assert AdversarialGate.evaluate(verdicts).passed is True


def test_gate_multi_iteration_bounds_and_status_formatting():
    """F35: Multi-iteration gate evaluation bounds, status line formatting, and defect ledger isolation."""
    # Iteration 1: Challenger defect -> FAIL with adversarial veto
    iter1_verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE", details="Tasks finished"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN", details="Clean diff"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE", details="Good code"),
        GateVerdict(
            agent_name="challenger_1",
            role="challenger",
            verdict="REQUEST_CHANGES",
            details="Race condition in queue",
            defect="Race condition detected in queue implementation",
        ),
    ]
    res1 = AdversarialGate.evaluate(iter1_verdicts)
    assert res1.passed is False
    assert res1.adversarial_veto_triggered is True
    assert res1.binary_veto_triggered is False
    assert "Race condition" in res1.reason
    assert len(res1.defect_ledger) == 1
    status1 = res1.format_status_line()
    assert status1.startswith("Gate Result: **FAIL**")
    assert "Race condition" in status1

    # Iteration 2: Reviewer defect -> FAIL
    iter2_verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE", details="Addressed race condition"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN", details="Clean diff"),
        GateVerdict(
            agent_name="reviewer_1",
            role="reviewer",
            verdict="REQUEST_CHANGES",
            details="Missing unit tests",
            defect="Missing unit test for concurrency edge case",
        ),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE", details="Race condition resolved"),
    ]
    res2 = AdversarialGate.evaluate(iter2_verdicts)
    assert res2.passed is False
    assert res2.adversarial_veto_triggered is False
    assert "Missing unit test" in res2.reason
    status2 = res2.format_status_line()
    assert status2.startswith("Gate Result: **FAIL**")
    assert "Missing unit test" in status2

    # Iteration 3: Full consensus -> PASS with empty defect ledger
    iter3_verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE", details="Added unit tests"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN", details="Clean diff"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE", details="All tests verified"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE", details="Sound implementation"),
    ]
    res3 = AdversarialGate.evaluate(iter3_verdicts)
    assert res3.passed is True
    assert res3.binary_veto_triggered is False
    assert res3.adversarial_veto_triggered is False
    assert len(res3.defect_ledger) == 0
    assert res3.format_status_line() == "Gate Result: **PASS**"


def test_gate_tie_breaking_and_veto_precedence_hierarchy():
    """F35: Conflict resolution & tie-breaking precedence: Binary veto > Challenger veto > Reviewer veto."""
    # Case A: Binary Veto Priority overriding concurrent worker, reviewer, and challenger failures
    veto_priority_verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="FAIL", details="Worker failed build"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="REQUEST_CHANGES", defect="Style issues"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="REQUEST_CHANGES", defect="Security breach"),
        GateVerdict(
            agent_name="auditor_1",
            role="auditor",
            verdict="INTEGRITY_VIOLATION",
            details="Unauthorized modification to tests/e2e/test_auth.py",
            defect="Test tampering detected",
        ),
    ]
    res_a = AdversarialGate.evaluate(veto_priority_verdicts)
    assert res_a.passed is False
    assert res_a.binary_veto_triggered is True
    assert res_a.adversarial_veto_triggered is False
    assert res_a.reason.startswith("FORENSIC INTEGRITY VIOLATION")

    # Case B: Reviewer Split Tie-Breaking (1 APPROVE vs 1 REQUEST_CHANGES -> Strict AND fails)
    reviewer_split_verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(agent_name="reviewer_full", role="reviewer", verdict="APPROVE"),
        GateVerdict(
            agent_name="reviewer_scoped",
            role="reviewer",
            verdict="REQUEST_CHANGES",
            defect="Flaky timing in test loop",
        ),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    res_b = AdversarialGate.evaluate(reviewer_split_verdicts)
    assert res_b.passed is False
    assert "Flaky timing" in res_b.reason

    # Case C: Challenger Split Tie-Breaking (1 APPROVE vs 1 REQUEST_CHANGES -> Adversarial Veto)
    challenger_split_verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(agent_name="challenger_edge", role="challenger", verdict="APPROVE"),
        GateVerdict(
            agent_name="challenger_soundness",
            role="challenger",
            verdict="REQUEST_CHANGES",
            defect="Integer overflow vulnerability",
        ),
    ]
    res_c = AdversarialGate.evaluate(challenger_split_verdicts)
    assert res_c.passed is False
    assert res_c.adversarial_veto_triggered is True
    assert "Integer overflow" in res_c.reason

    # Case D: Global Binary Veto from non-auditor role (e.g., worker)
    global_binary_verdicts = [
        GateVerdict(
            agent_name="worker_1",
            role="worker",
            verdict="INTEGRITY_VIOLATION",
            details="Cheating detected in harness mock",
        ),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    res_d = AdversarialGate.evaluate(global_binary_verdicts)
    assert res_d.passed is False
    assert res_d.binary_veto_triggered is True
    assert "FORENSIC INTEGRITY VIOLATION by worker_1" in res_d.reason


def test_gate_role_specific_rejection_of_approve_with_nits():
    """F35: APPROVE_WITH_NITS is only valid for reviewers; rejected for auditor (requires CLEAN) and worker (requires DONE)."""
    # Auditor with APPROVE_WITH_NITS -> REJECTED
    auditor_nits = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="APPROVE_WITH_NITS", details="Minor lint note"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    res_auditor = AdversarialGate.evaluate(auditor_nits)
    assert res_auditor.passed is False
    assert any("Auditor auditor_1 did not report CLEAN" in d for d in res_auditor.defect_ledger)

    # Worker with APPROVE_WITH_NITS -> REJECTED
    worker_nits = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="APPROVE_WITH_NITS", details="Finished with minor TODO"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    res_worker = AdversarialGate.evaluate(worker_nits)
    assert res_worker.passed is False
    assert any("Worker worker_1 incomplete" in d for d in res_worker.defect_ledger)


def test_parse_verdict_from_handoff_corrupt_and_tilde_fences():
    """F35: Parsing handoffs with tilde fences, quad backticks, unknown tokens, and corrupt inputs."""
    body = (
        "\n## 1. Observation\nObservation details\n"
        "## 2. Logic Chain\nStep by step logic\n"
        "## 3. Caveats\nNo caveats\n"
        "## 4. Conclusion\nFinal conclusion\n"
        "## 5. Verification Method\npytest tests/\n"
    )

    # Tilde code fence masking ignores fenced APPROVE and finds true REQUEST_CHANGES
    tilde_handoff = (
        "# Handoff Report: c1\n"
        "~~~markdown\n"
        "**Verdict**: APPROVE\n"
        "~~~\n"
        "**Verdict**: REQUEST_CHANGES\n"
        "**Defect**: Real defect outside code block\n"
        + body
    )
    gv_tilde = AdversarialGate.parse_verdict_from_handoff("c1", "challenger", tilde_handoff)
    assert gv_tilde.verdict == "REQUEST_CHANGES"
    assert gv_tilde.defect == "Real defect outside code block"

    # Quad backticks fence masking
    quad_handoff = (
        "# Handoff Report: c2\n"
        "````markdown\n"
        "**Verdict**: APPROVE\n"
        "````\n"
        "**Verdict**: REQUEST_CHANGES\n"
        + body
    )
    gv_quad = AdversarialGate.parse_verdict_from_handoff("c2", "challenger", quad_handoff)
    assert gv_quad.verdict == "REQUEST_CHANGES"

    # Unknown verdict tokens (e.g. LGTM) are extracted and fail closed during gate evaluation
    lgtm_handoff = "# Handoff Report: c3\n**Verdict**: LGTM\n" + body
    gv_lgtm = AdversarialGate.parse_verdict_from_handoff("c3", "challenger", lgtm_handoff)
    assert gv_lgtm.verdict == "LGTM"
    res_lgtm = AdversarialGate.evaluate([
        GateVerdict("w1", "worker", "DONE"),
        GateVerdict("a1", "auditor", "CLEAN"),
        GateVerdict("r1", "reviewer", "APPROVE"),
        gv_lgtm,
    ])
    assert res_lgtm.passed is False
    assert res_lgtm.adversarial_veto_triggered is True

    # Empty text or missing verdict returns FAIL
    gv_empty = AdversarialGate.parse_verdict_from_handoff("c4", "challenger", "")
    assert gv_empty.verdict == "FAIL"

    gv_no_verdict = AdversarialGate.parse_verdict_from_handoff("c5", "challenger", "# Handoff\nSome random notes\n" + body)
    assert gv_no_verdict.verdict == "FAIL"


def test_gate_result_tuple_unpacking():
    """Verify that GateResult supports native tuple unpacking: passed, reason = res."""
    res = GateResult(passed=True, reason="All checks passed")
    passed, reason = res
    assert passed is True
    assert reason == "All checks passed"

    # Also verify with real AdversarialGate.evaluate call
    verdicts = [
        GateVerdict(agent_name="worker_1", role="worker", verdict="DONE"),
        GateVerdict(agent_name="auditor_1", role="auditor", verdict="CLEAN"),
        GateVerdict(agent_name="reviewer_1", role="reviewer", verdict="APPROVE"),
        GateVerdict(agent_name="challenger_1", role="challenger", verdict="APPROVE"),
    ]
    eval_res = AdversarialGate.evaluate(verdicts)
    p, r = eval_res
    assert p is True
    assert "All criteria satisfied" in r






