import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pipeguard.config import get_settings
from pydantic import SecretStr

RESULT = {
    "summary": "The upstream request timed out.",
    "likely_causes": ["The upstream service may be unavailable."],
    "recommended_steps": ["Check upstream availability before retrying."],
}


def _enable(monkeypatch, provider="anthropic"):
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "llm_provider", provider)
    monkeypatch.setattr(settings, "llm_model", "test-model")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr("test-secret"))


def _transport(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(
        "pipeguard.services.llm_analysis.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_llm_analysis_is_stored_and_called_once(client: TestClient, monkeypatch, provider):
    _enable(monkeypatch, provider)
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        if provider == "anthropic":
            assert str(request.url) == "https://api.anthropic.com/v1/messages"
            assert request.headers["x-api-key"] == "test-secret"
            assert body["max_tokens"] == 1024
            evidence = json.loads(body["messages"][0]["content"])
            payload = {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(RESULT)}],
            }
        else:
            assert str(request.url) == "https://api.openai.com/v1/chat/completions"
            assert request.headers["Authorization"] == "Bearer test-secret"
            assert body["max_completion_tokens"] == 1024
            evidence = json.loads(body["messages"][1]["content"])
            payload = {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(RESULT)}}]
            }
        assert evidence["status"] == "FAILED"
        assert "timeout" in evidence["error_message"].lower()
        return httpx.Response(200, json=payload)

    _transport(monkeypatch, handler)
    run_id = client.post("/runs/demo?simulate_failure=true").json()["id"]
    response = client.post(f"/runs/{run_id}/analyze")
    assert response.status_code == 201
    payload = response.json()
    assert payload["model_name"] == "test-model"
    assert payload["severity"] == "high"
    assert payload["summary"] == RESULT["summary"]
    repeated = client.post(f"/runs/{run_id}/analyze")
    assert repeated.status_code == 200
    assert repeated.json() == payload
    assert len(requests) == 1


@pytest.mark.parametrize("failure", ["timeout", "http", "json", "schema", "truncated", "refusal"])
def test_provider_failures_fall_back(client: TestClient, monkeypatch, caplog, failure):
    _enable(monkeypatch)

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("test-secret", request=request)
        if failure == "http":
            return httpx.Response(401, text="test-secret")
        content = json.dumps(RESULT)
        if failure == "json":
            content = "not json"
        elif failure == "schema":
            content = json.dumps({**RESULT, "recommended_steps": "not an array"})
        return httpx.Response(
            200,
            json={
                "stop_reason": {"truncated": "max_tokens", "refusal": "refusal"}.get(
                    failure, "end_turn"
                ),
                "content": [{"type": "text", "text": content}],
            },
        )

    _transport(monkeypatch, handler)
    run_id = client.post("/runs/demo?simulate_failure=true").json()["id"]
    response = client.post(f"/runs/{run_id}/analyze")
    assert response.status_code == 201
    assert response.json()["model_name"] == "rule-based"
    assert "test-secret" not in caplog.text
    assert "test-secret" not in response.text


def test_haiku_disables_default_thinking(client: TestClient, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(get_settings(), "llm_model", "claude-haiku-5-5")

    def handler(request):
        assert json.loads(request.content)["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(RESULT)}],
            },
        )

    _transport(monkeypatch, handler)
    run_id = client.post("/runs/demo?simulate_failure=true").json()["id"]
    result = client.post(f"/runs/{run_id}/analyze")
    assert result.json()["model_name"] == "claude-haiku-5-5"


@pytest.mark.parametrize("scenario", ["disabled", "missing_key", "missing_model", "healthy"])
def test_no_provider_call_when_not_needed(client: TestClient, monkeypatch, scenario):
    _enable(monkeypatch)
    settings = get_settings()
    if scenario == "disabled":
        monkeypatch.setattr(settings, "llm_enabled", False)
    elif scenario == "missing_key":
        monkeypatch.setattr(settings, "llm_api_key", SecretStr(""))
    elif scenario == "missing_model":
        monkeypatch.setattr(settings, "llm_model", "")

    def handler(request):
        pytest.fail("Unexpected paid request")

    _transport(monkeypatch, handler)
    suffix = "" if scenario == "healthy" else "?simulate_failure=true"
    run_id = client.post(f"/runs/demo{suffix}").json()["id"]
    response = client.post(f"/runs/{run_id}/analyze")
    assert response.status_code == 201
    assert response.json()["model_name"] == "rule-based"
