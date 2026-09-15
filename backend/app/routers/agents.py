from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.agents.pipeline import run_pipeline_for_case
from app.auth import require_api_key
from app.db import get_db
from app.models import RecoveryCase
from app.rate_limit import RateLimitExceeded, caller_bucket_key, check_and_record
from app.status import TERMINAL_STATUSES

router = APIRouter()
ANALYZE_RATE_LIMIT_PER_MINUTE = 20


@router.post("/cases/{case_id}/analyze", dependencies=[Depends(require_api_key)])
def analyze_case(request: Request, case_id: int, force: bool = False, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    if case.payment.status == "paid" or case.status in TERMINAL_STATUSES:
        if force:
            raise HTTPException(
                status_code=409,
                detail=f"Case {case_id} is terminal or already paid; force re-analysis is blocked for safety.",
            )
        raise HTTPException(status_code=409, detail=f"Case {case_id} cannot be analyzed in status '{case.status}'.")

    if case.status != "detected" and not force:
        raise HTTPException(
            status_code=409,
            detail=f"Case {case_id} already has status '{case.status}'. Use the explicit re-analysis action to retry.",
        )

    try:
        check_and_record(ANALYZE_RATE_LIMIT_PER_MINUTE, key=caller_bucket_key(request))
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    result = run_pipeline_for_case(db, case)
    return {"case_id": case.id, **result}
