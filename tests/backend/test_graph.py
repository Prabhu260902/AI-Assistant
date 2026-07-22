from fastapi.testclient import TestClient

from graphs.passthrough import run_passthrough
from main import app

client = TestClient(app)


def test_run_passthrough_returns_input_unchanged():
    assert run_passthrough("hello world") == "hello world"


def test_graph_invoke_endpoint_returns_input_unchanged():
    response = client.post("/graph/invoke", json={"input": "hello world"})

    assert response.status_code == 200
    assert response.json() == {"output": "hello world"}
