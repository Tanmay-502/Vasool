from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.pipeline import run_pipeline_for_case
from app.db import get_db
from app.models import RecoveryCase

router = APIRouter()


@router.post("/cases/{case_id}/analyze")
def analyze_case(case_id: int, db: Session = Depends(get_db)):
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Recovery case not found")

    result = run_pipeline_for_case(db, case)
    return {"case_id": case.id, **result}