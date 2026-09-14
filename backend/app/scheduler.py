"""Lightweight database-backed scheduler for autonomous first contact and delayed retries."""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import and_

from app.agents.pipeline import run_pipeline_for_case
from app.config import settings
from app.db import SessionLocal
from app.executor import AutomationPausedError, CaseAlreadyPaidError, CaseNotPendingExecutionError, execute_case
from app.models import Action, RecoveryCase
from app.policy_runner import CaseNotAnalyzedError, TerminalCaseError, run_policy_for_case
from app.state import get_kill_switch

logger = logging.getLogger(__name__)


async def _sweep_once() -> None:
    db = SessionLocal()
    try:
        if get_kill_switch(db):
            return
        detected = (
            db.query(RecoveryCase)
            .filter(RecoveryCase.status == "detected")
            .order_by(RecoveryCase.created_at.asc(), RecoveryCase.id.asc())
            .limit(25)
            .all()
        )
        for case in detected:
            try:
                run_pipeline_for_case(db, case)
                run_policy_for_case(db, case)
            except (CaseNotAnalyzedError, TerminalCaseError) as exc:
                logger.info("Skipping auto-analysis for case %s: %s", case.id, exc)
            except Exception:
                logger.exception("Autonomous recovery failed for case %s", case.id)

        due_actions = (
            db.query(Action)
            .filter(and_(Action.status == "scheduled", Action.not_before.isnot(None), Action.not_before <= datetime.utcnow()))
            .order_by(Action.not_before.asc(), Action.id.asc())
            .limit(25)
            .all()
        )
        for action in due_actions:
            case = db.get(RecoveryCase, action.recovery_case_id)
            if case is None:
                continue
            try:
                execute_case(db, case)
            except (AutomationPausedError, CaseAlreadyPaidError, CaseNotPendingExecutionError) as exc:
                logger.info("Skipping scheduled action %s: %s", action.id, exc)
            except Exception:
                logger.exception("Scheduled recovery failed for action %s", action.id)
    finally:
        db.close()


async def run_scheduler(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        if settings.AUTO_PROCESS_ENABLED:
            await _sweep_once()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(settings.AUTO_PROCESS_INTERVAL_SECONDS, 10))
        except asyncio.TimeoutError:
            pass
