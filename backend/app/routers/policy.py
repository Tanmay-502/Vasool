from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.executor import CaseNotPendingExecutionError, CircuitOpenError, execute_case
from app.models import RecoveryCase
from app.policy_runner import CaseNotAnalyzedError, run_policy_for_case
from app.rate_limit import RateLimitExceeded
from app.razorpay_client import RazorpayError

router = APIRouter()


@router.post("/cases/{case_id}/evaluate-policy")
def evaluate_case_policy(case_id: int, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    try:
        result = run_policy_for_case(db, case)
    except CaseNotAnalyzedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"case_id": case.id, **result}


@router.post("/cases/{case_id}/execute")
def execute_case_route(case_id: int, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    try:
        result = execute_case(db, case)
    except CaseNotPendingExecutionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CircuitOpenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except RazorpayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"case_id": case.id, **result}