import json
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import OperationalError

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
    assert "300.00" in report


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


# ---- _load_existing_cases() / _save_cases() -------------------------------

def test_save_and_load_round_trip_uses_patched_cases_file(tmp_path, monkeypatch):
    patched_path = tmp_path / "nested" / "cases.json"
    monkeypatch.setattr(shadow_backtest, "CASES_FILE", patched_path)

    assert _load_existing_cases() == {}

    payload = {"1": {"case_id": 1, "amount_paise": 5000}}
    _save_cases(payload)

    assert patched_path.exists()
    assert json.loads(patched_path.read_text(encoding="utf-8")) == payload
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

    cases_data = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert len(cases_data) == 2

    report_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "2 / 2 failed payments scored (100.0%)" in report_text
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
    first_pass = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert len(first_pass) == 1

    shadow_backtest.main(limit=None, run_all=True)
    second_pass = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert len(second_pass) == 3
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
    shadow_backtest.main(limit=None, run_all=True)

    cases_data = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
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


# ---- DAY 6.2 — DB-drop retry + per-case checkpointing ---------------------

def test_main_retries_once_on_transient_db_error_and_succeeds(db_session, monkeypatch, tmp_path):
    """A single OperationalError on the first attempt (simulating Neon /
    network dropping the connection mid-run) must not kill the case — one
    rollback + retry should recover and score it normally."""
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(shadow_backtest, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(shadow_backtest, "CASES_FILE", tmp_path / "cases.json")
    monkeypatch.setattr(shadow_backtest, "REPORT_FILE", tmp_path / "report.md")

    case = _seed_case(db_session, is_recoverable=False, eval_split="dev")

    real_score_case = shadow_backtest._score_case
    call_count = {"n": 0}

    def flaky_score_case(db, c, gemini, groq):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OperationalError(
                "SELECT 1", {}, Exception("server closed the connection unexpectedly")
            )
        return real_score_case(db, c, gemini, groq)

    monkeypatch.setattr(shadow_backtest, "_score_case", flaky_score_case)
    rollback_calls = []
    monkeypatch.setattr(db_session, "rollback", lambda: rollback_calls.append(1))

    shadow_backtest.main(limit=None, run_all=True)

    assert call_count["n"] == 2
    assert len(rollback_calls) == 1
    cases_data = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert str(case.id) in cases_data


def test_main_skips_case_when_retry_also_fails_and_continues_with_next(db_session, monkeypatch, tmp_path):
    """If the retry ALSO fails, that one case is skipped (not raised) and
    the run continues scoring the rest of the batch."""
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(shadow_backtest, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(shadow_backtest, "CASES_FILE", tmp_path / "cases.json")
    monkeypatch.setattr(shadow_backtest, "REPORT_FILE", tmp_path / "report.md")

    bad_case = _seed_case(db_session, is_recoverable=False, eval_split="dev")
    good_case = _seed_case(db_session, is_recoverable=False, eval_split="dev")

    real_score_case = shadow_backtest._score_case

    def flaky_score_case(db, c, gemini, groq):
        if c.id == bad_case.id:
            raise OperationalError(
                "SELECT 1", {}, Exception("server closed the connection unexpectedly")
            )
        return real_score_case(db, c, gemini, groq)

    monkeypatch.setattr(shadow_backtest, "_score_case", flaky_score_case)
    monkeypatch.setattr(db_session, "rollback", lambda: None)

    shadow_backtest.main(limit=None, run_all=True)

    cases_data = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert str(bad_case.id) not in cases_data
    assert str(good_case.id) in cases_data


def test_main_persists_already_scored_cases_even_if_a_later_case_crashes_hard(db_session, monkeypatch, tmp_path):
    """Regression test for the actual bug: previously, _save_cases() only
    ran once, after the WHOLE loop finished — so any crash (even an
    unrelated one, like this RuntimeError, which is deliberately NOT one of
    the caught DB exception types) discarded every case scored earlier in
    the same run. Now saving happens after every case, so a hard crash on
    case 2 must not erase case 1's already-persisted result."""
    monkeypatch.setattr(llm_clients.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm_clients.settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(shadow_backtest, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(shadow_backtest, "CASES_FILE", tmp_path / "cases.json")
    monkeypatch.setattr(shadow_backtest, "REPORT_FILE", tmp_path / "report.md")

    first_case = _seed_case(db_session, is_recoverable=False, eval_split="dev")
    crashing_case = _seed_case(db_session, is_recoverable=False, eval_split="dev")

    real_score_case = shadow_backtest._score_case

    def crash_on_second(db, c, gemini, groq):
        if c.id == crashing_case.id:
            raise RuntimeError("totally unexpected bug, not a DB error")
        return real_score_case(db, c, gemini, groq)

    monkeypatch.setattr(shadow_backtest, "_score_case", crash_on_second)

    with pytest.raises(RuntimeError):
        shadow_backtest.main(limit=None, run_all=True)

    cases_data = json.loads((tmp_path / "cases.json").read_text(encoding="utf-8"))
    assert str(first_case.id) in cases_data
    assert str(crashing_case.id) not in cases_data