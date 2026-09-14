"""Global automation kill switch persisted in the application database."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_db
from app.state import get_kill_switch, set_kill_switch

router = APIRouter()


@router.post("/admin/kill-switch/engage", dependencies=[Depends(require_api_key)])
def engage_kill_switch(db: Session = Depends(get_db)):
    return {"kill_switch_engaged": set_kill_switch(db, True)}


@router.post("/admin/kill-switch/disengage", dependencies=[Depends(require_api_key)])
def disengage_kill_switch(db: Session = Depends(get_db)):
    return {"kill_switch_engaged": set_kill_switch(db, False)}


@router.get("/admin/kill-switch")
def get_kill_switch_status(db: Session = Depends(get_db)):
    return {"kill_switch_engaged": get_kill_switch(db)}
