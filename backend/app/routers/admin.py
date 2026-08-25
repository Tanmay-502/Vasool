"""
Day 4 — global kill switch. One flag, flipped at runtime (no redeploy, no
restart), read by app/policy_runner.py on every single case evaluation. When
engaged, evaluate_policy()'s kill_switch check fails first and every case's
verdict becomes HUMAN_REVIEW regardless of confidence, amount, or action —
see app/policy_engine.py's verdict-priority block, kill switch checked
before anything else.

This directly answers the question every judge on a "money agent" project
asks: "what happens if this needs to stop right now?" — one POST call.
"""
from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.post("/admin/kill-switch/engage")
def engage_kill_switch():
    settings.KILL_SWITCH_ENGAGED = True
    return {"kill_switch_engaged": True}


@router.post("/admin/kill-switch/disengage")
def disengage_kill_switch():
    settings.KILL_SWITCH_ENGAGED = False
    return {"kill_switch_engaged": False}


@router.get("/admin/kill-switch")
def get_kill_switch_status():
    return {"kill_switch_engaged": settings.KILL_SWITCH_ENGAGED}