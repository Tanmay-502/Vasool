"""
Thin, timeout-bound clients for the two LLM tiers in the fallback chain.

Both clients expose the same shape:

    complete_json(system_prompt, user_prompt, schema, ...) -> (dict, tokens, latency_ms)

and raise AgentTierError for *any* failure mode — missing key, network error,
timeout, non-2xx response, or a response that isn't valid JSON. The agents in
root_cause_agent.py / recovery_strategy_agent.py treat AgentTierError as the
single signal to fall through to the next tier, so every possible way a
provider can fail collapses to one code path instead of being handled
ad hoc at each call site.

Endpoints/params confirmed against provider docs (Aug 2026):
  - Gemini: POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
    generationConfig.responseMimeType="application/json" + responseSchema
  - Groq (OpenAI-compatible): POST https://api.groq.com/openai/v1/chat/completions
    response_format={"type": "json_schema", "json_schema": {...}} (strict mode)
"""
import json
import time

import httpx

from app.config import settings

GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class AgentTierError(Exception):
    """Raised whenever a tier can't produce a usable structured response.
    This is the single trigger the fallback chain listens for — see
    root_cause_agent.run_root_cause_agent / recovery_strategy_agent.run_recovery_strategy_agent."""


class GeminiClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float | None = None):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.timeout = timeout or settings.AGENT_TIMEOUT_SECONDS

    def complete_json(self, system_prompt: str, user_prompt: str, schema: dict) -> tuple[dict, int | None, int]:
        if not self.api_key:
            raise AgentTierError("GEMINI_API_KEY not configured")

        url = GEMINI_URL_TEMPLATE.format(model=self.model)
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0.2,
            },
        }

        start = time.perf_counter()
        try:
            resp = httpx.post(url, params={"key": self.api_key}, json=body, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise AgentTierError(f"Gemini call failed: {exc}") from exc
        latency_ms = int((time.perf_counter() - start) * 1000)

        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AgentTierError(f"Gemini returned unparsable output: {exc}") from exc

        tokens = data.get("usageMetadata", {}).get("totalTokenCount")
        return parsed, tokens, latency_ms


class GroqClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float | None = None):
        self.api_key = api_key if api_key is not None else settings.GROQ_API_KEY
        self.model = model or settings.GROQ_MODEL
        self.timeout = timeout or settings.AGENT_TIMEOUT_SECONDS

    def complete_json(
        self, system_prompt: str, user_prompt: str, schema_name: str, schema: dict
    ) -> tuple[dict, int | None, int]:
        if not self.api_key:
            raise AgentTierError("GROQ_API_KEY not configured")

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }

        start = time.perf_counter()
        attempts = 0
        max_retries = 2  # bounded — this runs behind the live /analyze endpoint too

        while True:
            try:
                resp = httpx.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempts < max_retries:
                    try:
                        wait_s = float(exc.response.headers.get("retry-after", "2"))
                    except ValueError:
                        wait_s = 2.0
                    if wait_s <= 10:
                        time.sleep(wait_s)
                        attempts += 1
                        continue
                raise AgentTierError(
                    f"Groq call failed ({exc.response.status_code}): {exc.response.text}"
                ) from exc
            except httpx.HTTPError as exc:
                raise AgentTierError(f"Groq call failed: {exc}") from exc

        latency_ms = int((time.perf_counter() - start) * 1000)


        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise AgentTierError(f"Groq returned unparsable output: {exc}") from exc

        tokens = data.get("usage", {}).get("total_tokens")
        return parsed, tokens, latency_ms