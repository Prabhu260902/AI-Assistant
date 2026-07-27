"""LLM provider interface.

Callers depend only on `LLMProvider` / `get_llm_provider()`. Swapping models
or providers (Groq, another Llama host, etc.) is a config change via
`LLM_PROVIDER`/`GROQ_MODEL`, not a code change in callers.
"""

import json
import urllib.error
import urllib.request
from typing import Protocol

from services.config import get_settings

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMProvider(Protocol):
    def complete(self, prompt: str, json_mode: bool = False) -> str:
        """Return a single completion for the given prompt.

        `json_mode` asks the provider to constrain output to valid JSON
        (Groq's `response_format: json_object`) — callers producing
        structured output should still validate/parse defensively, this is
        a reliability aid, not a schema guarantee.
        """
        ...


class GroqProvider:
    def __init__(self, api_key: str, model: str, fallback_models: list[str] | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._fallback_models = fallback_models or []

    def complete(self, prompt: str, json_mode: bool = False) -> str:
        models = [self._model, *self._fallback_models]
        for index, model in enumerate(models):
            try:
                return self._complete_with_model(model, prompt, json_mode)
            except urllib.error.HTTPError as exc:
                # Each Groq model has its own separate rate/quota bucket, so
                # a 429 on one model doesn't mean the next will also fail —
                # only fall through on 429, and only if another model is
                # left to try; any other error (bad request, auth, etc.)
                # propagates immediately since a different model won't fix it.
                is_last_model = index == len(models) - 1
                if exc.code == 429 and not is_last_model:
                    continue
                raise

    def _complete_with_model(self, model: str, prompt: str, json_mode: bool) -> str:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            GROQ_CHAT_COMPLETIONS_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                # Groq's API sits behind Cloudflare, which blocks urllib's
                # default "Python-urllib/x.y" User-Agent as a bot (Cloudflare
                # error 1010) — an explicit UA is required for requests to
                # succeed at all.
                "User-Agent": "allease-engineering-assistant/0.1",
            },
        )
        with urllib.request.urlopen(request) as response:
            response_payload = json.loads(response.read())
        return response_payload["choices"][0]["message"]["content"]


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "groq":
        return GroqProvider(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            fallback_models=settings.groq_fallback_models,
        )
    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")
