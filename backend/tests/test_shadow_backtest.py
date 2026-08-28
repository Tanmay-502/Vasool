"""
Tests for scripts/shadow_backtest.py.

Covers:
  - _render_report(): pure function, no DB/LLM — headline numbers, verdict
    breakdown, tier usage, coverage %, and the "n/a" branch when nothing
    was ever escalated.
  - _load_existing_cases() / _save_cases(): round-trip through a
    monkeypatched CASES_FILE. This is a deliberate regression test for a
    real bug caught before shipping — an earlier draft read CASES_FILE as
    a bound default parameter value (evaluated once, at function-
    definition time), so monkeypatching the module attribute in a test
    silently had no effect and the script kept writing to the real
    reports/ folder. Referencing the module-level name directly inside the
    function body fixes it; this test would have caught the original bug.
  - main(): end-to-end against the real pipeline + policy engine (Gemini
    and Groq keys forced empty so every case lands on rules_fallback —
    deterministic, zero network calls), using db_session/monkeypatch to
    stand in for a real DB and a real quota-limited run. Verifies
    accumulation across two separate calls to main() never re-scores an
    already-scored case_id, and that dev+holdout cases are BOTH included
    (unlike evaluate_holdout.py, which is holdout-only by design).
"""
import json
from datetime import datetime, timezone

from app.agents import llm_clients
from app.models import Customer, GroundTruth, Merchant, Order, Payment, RecoveryCase
from scripts import shadow_backtest
from scripts.evaluate_holdout import ScoredCase
from scripts.shadow_backtest import _load_existing_cases, _render_report, _save_cases


# ---- _render_report() — pure function ------------------------------------

def _case(
    case_id, amount_paise, predicted, actual, verdict, tier="rules_fallback", correctly_escalated=None
):
    return ScoredCase(
        case_id=case_id,
        amount_paise=amount_paise,
        predicted_recoverable=predicted,
        actual_recoverable=actual,
        verdict=verdict,
        root_cause_tier=tier,
        strategy_tier=tier,
        correctly_escalated=correctly_escalated,
    )


def test_render_report_includes_coverage_and_headline_numbers():
    scored = [
        _case(1, 10000, True, True, "EXECUTE"),
        _case(2, 20000, False, False, "HUMAN_REVIEW", correctly_escalated=True),
    ]
    report = _render_report(
        scored, total_dataset_size=10, generated_at=datetime(2026, 8, 28, tzinfo=timezone.utc)
    )

    assert "2 / 10 failed payments scored (20.0%)" in report
    assert "Revenue at risk (scored subset)" in report
    assert "300.00" in report  # (10000+20000)/100


def test_render_report_handles_no_escalated_cases():
    scored = [_case(1, 10000, True, True, "EXECUTE")]
    report = _render_report(
        scored, total_dataset_size=1, generated_at=datetime(2026, 8, 28, tzinfo=timezone.utc)
    )
    assert "n/a (no cases routed to human review or blocked)" in report


def test_render_report_shows_tier_usage_breakdown():
    scored = [
        _case(1, 10000, True, True, "EXECUTE", tier="gemini"),
        _case(2, 10000, True, True, "EXECUTE", tier="groq"),
        _case(3, 10000, True, True, "EXECUTE", tier="rules_fallback"),
        _case(4, 10000, True, True, "EXECUTE", tier="rules_fallback"),
    ]
    report = _render_report(
        scored, total_dataset_size=4, generated_at=datetime(2026, 8, 28, tzinfo=timezone.utc)
    )
    assert "- gemini: 1" in report
    assert "- groq: 1" in report
    assert "- rules_fallback: 2" in report


def test_render_report_verdict_breakdown_is_sorted():
    scored = [
        _case(1, 1000, True, False, "HUMAN_REVIEW", correctly_escalated=True),
        _case(2, 1000, True, True, "EXECUTE"),
        _case(3, 1000, True, False, "BLOCK", correctly_escalated=True),
    ]
    report = _render_report(
        scored, total_dataset_size=3, generated_at=datetime(2026, 8, 28, tzinfo=timezone.utc)
    )
    block_idx = report.index("- BLOCK")
    execute_idx = report.index("- EXECUTE")
    human_idx = report.index("- HUMAN_REVIEW")
    assert block_idx < execute_idx < human_idx


# ---- _load_existing_cases() / _save_cases() — regression test for the ----
# ---- "bound default parameter" bug ---------------------------------------

def test_save_and_load_round_trip_uses_patched_cases_file(tmp_path, monkeypatch):
    patched_path = tmp_path / "nested" / "cases.json"
    monkeypatch.setattr(shadow_backtest, "CASES_FILE", patched_path)

    assert _load_existing_cases() == {}

    payload = {"1": {"case_id": 1, "amount_paise": 5000}}
    _save_cases(payload)

    # Regression check: if _load_existing_cases/_save_cases had captured
    # CASES_FILE as a bound default argument instead of reading the module
    # global fresh, this file would never get written and the real project
    # reports/ folder would silently take the hit instead.
    assert patched_path.exists()
    assert json.loads(patched_path.read_text()) == payload
    assert _load_existing_cases() == payload


def test_load_existing_cases_returns_empty_dict_when_file_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow_backtest, "CASES_FILE", tmp_path / "does_not_exist.json")
    assert _load_existing_cases() == {}


# ---- main() — end to end, rules_fallback tier only -----------------------

def _seed_case(db, *, is_recoverable, eval_split, failure_reason="card_declined", opted_out=False):
    merchant = Merchant(name="Test Merchant")
    db.add(merchant)
    db.flush()
    customer = Customer(
        merchant_id=merchant.id, name="Test User", email="t@example.com",
        phone="9000000000", opted_out=opted_out,
    )
    db.add(customer)
    db.flush()
    order = Order(merchant_id=merchant.id, customer_id=customer.id, amount_paise=20000, status="failed")
    db.add(order)
    db.flush()
    payment = Payment(
        order_id=order.id, method="upi", status="failed",
        failure_reason=failure_reason, attempt_number=1,
    )
    db.add(payment)
    db.flush()
    case = RecoveryCase(payment_id=payment.id, status="detected")
    db.add(case)
    db.flush()
    db.add(
        GroundTruth(
            payment_id=payment.id,
            is_recoverable=is_recoverable,
            ideal_action="escalate_human" if not is_recoverable else "send_payment_link",
            eval_split=eval_split,
            rationale="test",
        )
    )
    db.commit()
    return case


def test_main_scores_both_dev_and_holdout_cases(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(shadow_backtest, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(shadow_backtest, "CASES_FILE", tmp_path / "cases.json")
    monkeypatch.setattr(shadow_backtest, "REPORT_FILE", tmp_path / "report.md")

    _seed_case(db_session, is_recoverable=False, eval_split="dev")
    _seed_case(db_session, is_recoverable=False, eval_split="holdout")

    shadow_backtest.main(limit=None, run_all=True)

    cases_data = json.loads((tmp_path / "cases.json").read_text())
    assert len(cases_data) == 2  # both dev AND holdout scored — not holdout-only

    report_text = (tmp_path / "report.md").read_text()
    assert "2 / 2 failed payments scored (100.0%)" in report_text
    # every seeded case is is_recoverable=False -> rules_fallback's
    # HUMAN_REVIEW verdict is correct for all of them regardless of confidence
    assert "Correctly escalated | 100.0%" in report_text


def test_main_accumulates_across_two_runs_without_rescoring(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(shadow_backtest, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(shadow_backtest, "CASES_FILE", tmp_path / "cases.json")
    monkeypatch.setattr(shadow_backtest, "REPORT_FILE", tmp_path / "report.md")

    _seed_case(db_session, is_recoverable=False, eval_split="dev")
    _seed_case(db_session, is_recoverable=False, eval_split="dev")
    _seed_case(db_session, is_recoverable=False, eval_split="holdout")

    shadow_backtest.main(limit=1, run_all=False)
    first_pass = json.loads((tmp_path / "cases.json").read_text())
    assert len(first_pass) == 1

    shadow_backtest.main(limit=None, run_all=True)
    second_pass = json.loads((tmp_path / "cases.json").read_text())
    assert len(second_pass) == 3
    # the case scored in the first pass must still be present under the
    # same key — proves the second run merged rather than overwrote
    assert set(first_pass.keys()).issubset(second_pass.keys())


def test_main_is_idempotent_when_everything_already_scored(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(shadow_backtest, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(shadow_backtest, "CASES_FILE", tmp_path / "cases.json")
    monkeypatch.setattr(shadow_backtest, "REPORT_FILE", tmp_path / "report.md")

    _seed_case(db_session, is_recoverable=False, eval_split="dev")

    shadow_backtest.main(limit=None, run_all=True)
    shadow_backtest.main(limit=None, run_all=True)  # should not error, not duplicate

    cases_data = json.loads((tmp_path / "cases.json").read_text())
    assert len(cases_data) == 1


def test_main_handles_empty_dataset_without_writing_files(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(shadow_backtest, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    cases_file = tmp_path / "cases.json"
    report_file = tmp_path / "report.md"
    monkeypatch.setattr(shadow_backtest, "CASES_FILE", cases_file)
    monkeypatch.setattr(shadow_backtest, "REPORT_FILE", report_file)

    shadow_backtest.main(limit=None, run_all=True)

    assert not cases_file.exists()
    assert not report_file.exists()