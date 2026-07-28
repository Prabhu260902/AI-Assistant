import json
import urllib.error

import pytest

from services.llm import GroqProvider, get_llm_status


class _FakeResponse:
    def __init__(self, payload: dict, headers: dict | None = None):
        self._payload = payload
        self.headers = headers or {}

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_complete_without_json_mode_omits_response_format(monkeypatch):
    captured = {}

    def fake_urlopen(request):
        captured["body"] = json.loads(request.data)
        return _FakeResponse({"choices": [{"message": {"content": "hello"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = GroqProvider(api_key="k", model="m")
    result = provider.complete("hi")

    assert result == "hello"
    assert "response_format" not in captured["body"]


def test_complete_with_json_mode_sets_response_format(monkeypatch):
    captured = {}

    def fake_urlopen(request):
        captured["body"] = json.loads(request.data)
        return _FakeResponse({"choices": [{"message": {"content": '{"x": 1}'}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = GroqProvider(api_key="k", model="m")
    result = provider.complete("hi", json_mode=True)

    assert result == '{"x": 1}'
    assert captured["body"]["response_format"] == {"type": "json_object"}


def _rate_limited_error() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url="u", code=429, msg="Too Many Requests", hdrs=None, fp=None)


def test_complete_falls_back_to_next_model_on_429(monkeypatch):
    attempted_models = []

    def fake_urlopen(request):
        body = json.loads(request.data)
        attempted_models.append(body["model"])
        if body["model"] == "primary":
            raise _rate_limited_error()
        return _FakeResponse({"choices": [{"message": {"content": "from fallback"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = GroqProvider(api_key="k", model="primary", fallback_models=["fallback"])
    result = provider.complete("hi")

    assert result == "from fallback"
    assert attempted_models == ["primary", "fallback"]


def test_complete_raises_after_all_models_rate_limited(monkeypatch):
    def fake_urlopen(request):
        raise _rate_limited_error()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = GroqProvider(api_key="k", model="primary", fallback_models=["fallback"])

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        provider.complete("hi")
    assert exc_info.value.code == 429


def test_complete_captures_rate_limit_headers(monkeypatch):
    headers = {
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-remaining-requests": "956",
        "x-ratelimit-limit-tokens": "12000",
        "x-ratelimit-remaining-tokens": "10886",
    }

    def fake_urlopen(request):
        return _FakeResponse({"choices": [{"message": {"content": "hi"}}]}, headers=headers)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = GroqProvider(api_key="k", model="llama-x")
    provider.complete("hi")

    status = get_llm_status()
    assert status == {
        "model": "llama-x",
        "limit_requests": 1000,
        "remaining_requests": 956,
        "limit_tokens": 12000,
        "remaining_tokens": 10886,
    }


def test_complete_does_not_fall_back_on_non_rate_limit_error(monkeypatch):
    attempted_models = []

    def fake_urlopen(request):
        body = json.loads(request.data)
        attempted_models.append(body["model"])
        raise urllib.error.HTTPError(url="u", code=400, msg="Bad Request", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    provider = GroqProvider(api_key="k", model="primary", fallback_models=["fallback"])

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        provider.complete("hi")
    assert exc_info.value.code == 400
    assert attempted_models == ["primary"]
