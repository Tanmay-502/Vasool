import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, agents, health, metrics, policy


logger = logging.getLogger(__name__)

app = FastAPI(title="Vasool", description="Autonomous revenue recovery agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(agents.router)
app.include_router(policy.router)
app.include_router(admin.router)


@app.on_event("startup")
def warn_on_missing_llm_keys():
    """Missing keys don't crash anything — every request silently lands on
    rules_fallback. Right behavior for a request, wrong thing to discover
    20 minutes into demo-day debugging. Loud and once, at boot, instead."""
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set — gemini tier will always fall through to rules_fallback.")
    if not settings.GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not set — groq tier will always fall through to rules_fallback.")