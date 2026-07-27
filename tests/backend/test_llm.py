import json

from services.llm import GroqProvider


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

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
