from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db

router = APIRouter()


@router.get("/health")
def health():
    """Liveness endpoint: process is up and serving requests."""
    return {"status": "ok", "env": settings.ENV}


@router.get("/ready")
def readiness(db: Session = Depends(get_db)):
    """Readiness endpoint: application can reach its configured database."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return {"status": "not_ready", "env": settings.ENV, "database": "unavailable"}
    return {"status": "ready", "env": settings.ENV, "database": "ok"}
