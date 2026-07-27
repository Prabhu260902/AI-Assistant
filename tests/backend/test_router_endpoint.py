from fastapi.testclient import TestClient

from main import app
from services.git_diff import GitDiffError


def test_copilot_endpoint_returns_intent_and_result(monkeypatch):
    monkeypatch.setattr(
        "main.run_copilot",
        lambda repo_id, message, top_k: {"intent": "search", "result": {"answer": "It does X.", "citations": []}},
    )

    client = TestClient(app)
    response = client.post("/copilot", json={"repo_id": "repo-x", "message": "how does X work?"})

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "search"
    assert body["result"]["answer"] == "It does X."


def test_copilot_endpoint_returns_400_on_bad_ref(monkeypatch):
    def _raise(repo_id, message, top_k):
        raise GitDiffError("bad ref")

    monkeypatch.setattr("main.run_copilot", _raise)

    client = TestClient(app)
    response = client.post("/copilot", json={"repo_id": "repo-x", "message": "review no-such-ref"})

    assert response.status_code == 400
