"""
Direct unit tests for the two provider clients in app/agents/llm_clients.py —
previously untested surface area despite being where every real Gemini/Groq
HTTP call happens. Mocks httpx.post so these run with zero network access
and zero API keys, same spirit as tests/test_agents_fallback.py's
FakeTierClient but one level deeper: these exercise the real
GeminiClient/GroqClient code, not a stand-in for it.
"""
import json
from unittest.mock import Mock, patch

import httpx
import pytest

from app.agents.llm_clients import AgentTierError, GeminiClient, GroqClient

FAKE_SCHEMA = {"type": "object", "properties": {}}


def _mock_response(status_code: int, json_body: dict, text: str = ""):
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_body
    response.text = text or json.dumps(json_body)
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status_code} error", request=Mock(), response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


GEMINI_SUCCESS_BODY = {
    "candidates": [
        {
            "content": {
                "parts": [
                    {
                        "text": json.dumps(
                            {
                                "root_cause_category": "otp_timeout",
                                "is_transient": True,
                                "confidence": 0.8,
                                "reasoning": "clean signal",
                            }
                        )
                    }
                ]
            }
        }
    ],
    "usageMetadata": {"totalTokenCount": 55},
}

GEMINI_429_BODY_SHORT_DELAY = {
    "error": {
        "code": 429,
        "message": "Resource exhausted",
        "status": "RESOURCE_EXHAUSTED",
        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "2s"}],
    }
}

GEMINI_429_BODY_LONG_DELAY = {
    "error": {"details": [{"retryDelay": "60s"}]}
}


class TestGeminiClient:
    def test_missing_api_key_raises_without_network_call(self):
        client = GeminiClient(api_key="")
        with patch("app.agents.llm_clients.httpx.post") as mock_post:
            with pytest.raises(AgentTierError, match="not configured"):
                client.complete_json("sys", "user", FAKE_SCHEMA)
        mock_post.assert_not_called()

    def test_success_parses_response(self):
        client = GeminiClient(api_key="fake-key")
        with patch("app.agents.llm_clients.httpx.post", return_value=_mock_response(200, GEMINI_SUCCESS_BODY)):
            parsed, tokens, latency_ms = client.complete_json("sys", "user", FAKE_SCHEMA)
        assert parsed["root_cause_category"] == "otp_timeout"
        assert tokens == 55
        assert latency_ms >= 0

    def test_malformed_response_raises(self):
        client = GeminiClient(api_key="fake-key")
        with patch("app.agents.llm_clients.httpx.post", return_value=_mock_response(200, {"unexpected": "shape"})):
            with pytest.raises(AgentTierError, match="unparsable"):
                client.complete_json("sys", "user", FAKE_SCHEMA)

    def test_network_error_raises(self):
        client = GeminiClient(api_key="fake-key")
        with patch("app.agents.llm_clients.httpx.post", side_effect=httpx.ConnectError("connection refused")):
            with pytest.raises(AgentTierError, match="Gemini call failed"):
                client.complete_json("sys", "user", FAKE_SCHEMA)

    def test_retries_once_on_429_then_succeeds(self):
        client = GeminiClient(api_key="fake-key", max_retries=1, max_wait_seconds=10.0)
        responses = [_mock_response(429, GEMINI_429_BODY_SHORT_DELAY), _mock_response(200, GEMINI_SUCCESS_BODY)]
        with patch("app.agents.llm_clients.httpx.post", side_effect=responses) as mock_post, patch(
            "app.agents.llm_clients.time.sleep"
        ) as mock_sleep:
            parsed, tokens, latency_ms = client.complete_json("sys", "user", FAKE_SCHEMA)
        assert parsed["root_cause_category"] == "otp_timeout"
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(2.0)  # parsed from GEMINI_429_BODY_SHORT_DELAY's retryDelay

    def test_gives_up_after_max_retries_exceeded(self):
        client = GeminiClient(api_key="fake-key", max_retries=1, max_wait_seconds=10.0)
        with patch(
            "app.agents.llm_clients.httpx.post",
            return_value=_mock_response(429, GEMINI_429_BODY_SHORT_DELAY),
        ) as mock_post, patch("app.agents.llm_clients.time.sleep"):
            with pytest.raises(AgentTierError, match="429"):
                client.complete_json("sys", "user", FAKE_SCHEMA)
        assert mock_post.call_count == 2  # 1 initial + 1 retry, then gives up

    def test_does_not_retry_when_suggested_wait_exceeds_max_wait_seconds(self):
        client = GeminiClient(api_key="fake-key", max_retries=1, max_wait_seconds=10.0)
        with patch(
            "app.agents.llm_clients.httpx.post",
            return_value=_mock_response(429, GEMINI_429_BODY_LONG_DELAY),
        ) as mock_post, patch("app.agents.llm_clients.time.sleep") as mock_sleep:
            with pytest.raises(AgentTierError):
                client.complete_json("sys", "user", FAKE_SCHEMA)
        assert mock_post.call_count == 1  # gave up immediately, didn't wait 60s
        mock_sleep.assert_not_called()


class TestGroqClient:
    def test_missing_api_key_raises_without_network_call(self):
        client = GroqClient(api_key="")
        with patch("app.agents.llm_clients.httpx.post") as mock_post:
            with pytest.raises(AgentTierError, match="not configured"):
                client.complete_json("sys", "user", "schema_name", FAKE_SCHEMA)
        mock_post.assert_not_called()

    def test_success_parses_response(self):
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"action": "retry_now", "confidence": 0.7, "reasoning": "ok"})
                    }
                }
            ],
            "usage": {"total_tokens": 40},
        }
        client = GroqClient(api_key="fake-key")
        with patch("app.agents.llm_clients.httpx.post", return_value=_mock_response(200, body)):
            parsed, tokens, latency_ms = client.complete_json("sys", "user", "schema_name", FAKE_SCHEMA)
        assert parsed["action"] == "retry_now"
        assert tokens == 40

    def test_malformed_response_raises(self):
        client = GroqClient(api_key="fake-key")
        with patch("app.agents.llm_clients.httpx.post", return_value=_mock_response(200, {"unexpected": "shape"})):
            with pytest.raises(AgentTierError, match="unparsable"):
                client.complete_json("sys", "user", "schema_name", FAKE_SCHEMA)

    def test_network_error_raises(self):
        client = GroqClient(api_key="fake-key")
        with patch("app.agents.llm_clients.httpx.post", side_effect=httpx.ConnectError("connection refused")):
            with pytest.raises(AgentTierError, match="Groq call failed"):
                client.complete_json("sys", "user", "schema_name", FAKE_SCHEMA)

GEMINI_429_BODY_DAILY_QUOTA = {
    "error": {
        "code": 429,
        "status": "RESOURCE_EXHAUSTED",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{
                    "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                    "quotaValue": "20",
                }],
            },
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "49s"},
        ],
    }
}


class TestGeminiDailyQuota:
    def test_daily_quota_429_raises_immediately_without_retrying(self):
        client = GeminiClient(api_key="fake-key", max_retries=3, max_wait_seconds=60.0)
        with patch(
            "app.agents.llm_clients.httpx.post",
            return_value=_mock_response(429, GEMINI_429_BODY_DAILY_QUOTA),
        ) as mock_post, patch("app.agents.llm_clients.time.sleep") as mock_sleep:
            with pytest.raises(AgentTierError, match="daily quota"):
                client.complete_json("sys", "user", FAKE_SCHEMA)
        assert mock_post.call_count == 1  # no retry, even though max_retries=3 and 49s < 60s
        mock_sleep.assert_not_called()
        assert client.daily_quota_exceeded is True

    def test_daily_quota_flag_short_circuits_later_calls_on_same_instance(self):
        client = GeminiClient(api_key="fake-key")
        with patch(
            "app.agents.llm_clients.httpx.post",
            return_value=_mock_response(429, GEMINI_429_BODY_DAILY_QUOTA),
        ) as mock_post:
            with pytest.raises(AgentTierError):
                client.complete_json("sys", "user", FAKE_SCHEMA)
            with pytest.raises(AgentTierError, match="already exhausted"):
                client.complete_json("sys", "user", FAKE_SCHEMA)
        assert mock_post.call_count == 1  # second call never touched the network