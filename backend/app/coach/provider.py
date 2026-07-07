from __future__ import annotations

import asyncio
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class LLMProviderName(StrEnum):
    NONE = "NONE"
    OPENAI = "OPENAI"
    GEMINI = "GEMINI"
    DEEPSEEK = "DEEPSEEK"
    OPENROUTER = "OPENROUTER"
    OLLAMA = "OLLAMA"


class WordingProvider(Protocol):
    name: LLMProviderName
    model: str

    async def word(self, payload: dict[str, object]) -> str: ...


@dataclass(frozen=True, slots=True)
class ProviderResult:
    message: str | None
    provider: LLMProviderName
    model: str | None
    prompt_hash: str | None


class NoneWordingProvider:
    name = LLMProviderName.NONE
    model = ""

    async def word(self, payload: dict[str, object]) -> str:
        del payload
        raise RuntimeError("external wording is disabled")


class JsonHttpWordingProvider:
    def __init__(
        self,
        name: LLMProviderName,
        model: str,
        endpoint: str,
        api_key: str | None,
        *,
        request_timeout_seconds: float = 15,
    ) -> None:
        self.name = name
        self.model = model
        self.endpoint = endpoint
        self.api_key = api_key
        self.request_timeout_seconds = request_timeout_seconds

    async def word(self, payload: dict[str, object]) -> str:
        return await asyncio.to_thread(self._word_sync, payload)

    def _word_sync(self, payload: dict[str, object]) -> str:
        if self.name != LLMProviderName.OLLAMA and not self.api_key:
            raise RuntimeError("provider API key is not configured")
        prompt = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Переформулируй рекомендацию без новых метрик или диагнозов.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            }
        ).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.request_timeout_seconds) as response:
                raw = response.read()
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError("provider request failed") from error
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise RuntimeError("invalid provider response")
        choices = decoded.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                content = message["content"]
                if isinstance(content, str):
                    return content
        message = decoded.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            content = message["content"]
            if isinstance(content, str):
                return content
        response_text = decoded.get("response")
        if isinstance(response_text, str):
            return response_text
        raise RuntimeError("provider response has no message")


class ProviderExecutor:
    def __init__(self, provider: WordingProvider, *, timeout_seconds: float, retries: int) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.retries = max(0, retries)

    async def execute(self, payload: dict[str, object]) -> ProviderResult:
        if self.provider.name == LLMProviderName.NONE:
            return ProviderResult(None, LLMProviderName.NONE, None, None)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        prompt_hash = hashlib.sha256(canonical.encode()).hexdigest()
        for attempt in range(self.retries + 1):
            try:
                message = await asyncio.wait_for(
                    self.provider.word(payload), timeout=self.timeout_seconds
                )
                if message.strip():
                    return ProviderResult(
                        message.strip(), self.provider.name, self.provider.model, prompt_hash
                    )
            except Exception:
                if attempt == self.retries:
                    break
        return ProviderResult(None, LLMProviderName.NONE, None, None)


def allowlisted_payload(
    facts: dict[str, object], recommendation: dict[str, object]
) -> dict[str, object]:
    allowed_fact_keys = {
        "calculator_version",
        "rule_version",
        "week",
        "month",
        "last_7d",
        "last_30d",
        "all_time_longest_m",
        "average_pace_30d",
        "baseline_weekly_distance_m",
        "classification_counts_30d",
        "risk_flags",
    }
    allowed_recommendation_keys = {
        "rule_version",
        "workout_type",
        "distance_m",
        "duration_sec",
        "pace_min_sec_per_km",
        "pace_max_sec_per_km",
        "reason",
        "risk_flags",
    }
    return {
        "facts": {key: facts[key] for key in sorted(allowed_fact_keys) if key in facts},
        "recommendation": {
            key: recommendation[key]
            for key in sorted(allowed_recommendation_keys)
            if key in recommendation
        },
    }
