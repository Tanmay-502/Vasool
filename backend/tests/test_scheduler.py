import asyncio
import time
from types import SimpleNamespace

import httpx

from app import scheduler
from app.main import app


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self):
        self.detected_case = SimpleNamespace(id=1, status="detected")

    def query(self, model):
        if model is scheduler.RecoveryCase:
            return _FakeQuery([self.detected_case])
        return _FakeQuery([])

    def get(self, *args, **kwargs):
        return None

    def close(self):
        pass


def test_scheduler_sweep_does_not_block_health(monkeypatch):
    monkeypatch.setattr(scheduler, "SessionLocal", _FakeDb)
    monkeypatch.setattr(scheduler, "get_kill_switch", lambda db: False)

    def blocking_pipeline(db, case):
        time.sleep(1)

    monkeypatch.setattr(scheduler, "run_pipeline_for_case", blocking_pipeline)
    monkeypatch.setattr(scheduler, "run_policy_for_case", lambda db, case: None)

    async def exercise():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            started = time.perf_counter()
            health_task = asyncio.create_task(client.get("/health"))
            sweep_task = asyncio.create_task(scheduler._sweep_once())
            response = await asyncio.wait_for(health_task, timeout=0.5)
            elapsed = time.perf_counter() - started
            await sweep_task
            return response, elapsed

    response, elapsed = asyncio.run(exercise())

    assert response.status_code == 200
    assert elapsed < 0.5
