from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import agents, health, metrics

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