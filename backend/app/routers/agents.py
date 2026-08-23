from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.pipeline import run_pipeline_for_case
from app.db import get_db
from app.models import RecoveryCase
from app.rate_limit import RateLimitExceeded, check_and_record

router = APIRouter()

ANALYZE_RATE_LIMIT_PER_MINUTE = 20  # generous for a demo, tight enough to catch a runaway loop


@router.post("/cases/{case_id}/analyze")
def analyze_case(case_id: int, force: bool = False, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    if case.status != "detected" and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Case {case_id} already has status '{case.status}'. "
                "Pass ?force=true to re-run analysis and log another AgentDecision."
            ),
        )

    try:
        check_and_record(ANALYZE_RATE_LIMIT_PER_MINUTE)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    result = run_pipeline_for_case(db, case)
    return {"case_id": case.id, **result}