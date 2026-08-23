import logging

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_warns_when_llm_keys_are_missing(monkeypatch, caplog):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")

    with caplog.at_level(logging.WARNING):
        with TestClient(app):
            pass

    assert any("GEMINI_API_KEY not set" in r.message for r in caplog.records)
    assert any("GROQ_API_KEY not set" in r.message for r in caplog.records)


def test_no_warning_when_keys_are_present(monkeypatch, caplog):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "fake-key")

    with caplog.at_level(logging.WARNING):
        with TestClient(app):
            pass

    assert not any("GEMINI_API_KEY not set" in r.message for r in caplog.records)
    assert not any("GROQ_API_KEY not set" in r.message for r in caplog.records)