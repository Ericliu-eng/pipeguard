import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pipeguard.config import get_settings

API_KEY = "test-ingest-key"


@pytest.fixture
def report() -> dict[str, Any]:
    started_at = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    return {
        "pipeline_name": "market_data_lakehouse_pipeline",
        "external_run_id": "market-data-2026-09-28T12:00:00Z",
        "status": "SUCCESS",
        "started_at": started_at.isoformat(),
        "finished_at": (started_at + timedelta(seconds=4)).isoformat(),
        "rows_processed": 500,
        "checks": [
            {
                "check_name": "not_null_ts",
                "status": "PASS",
                "metric_value": 0.0,
                "threshold": 0.0,
                "message": "market_bars.ts has no nulls.",
            }
        ],
    }


@pytest.fixture
def with_api_key(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    def configure() -> None:
        monkeypatch.setattr(get_settings(), "ingest_api_key", API_KEY)

    return configure


def test_reporting_a_run_stores_it_with_its_checks(
    client: TestClient, report: dict[str, Any], with_api_key: Callable[[], None]
) -> None:
    with_api_key()

    response = client.post("/runs", json=report, headers={"X-API-Key": API_KEY})

    assert response.status_code == 201
    run = response.json()
    assert run["pipeline_name"] == "market_data_lakehouse_pipeline"
    assert run["external_run_id"] == report["external_run_id"]
    assert run["status"] == "SUCCESS"
    assert run["quality_status"] == "WARN"
    assert run["rows_processed"] == 500
    assert run["duration_ms"] == 4000

    checks = client.get(f"/runs/{run['id']}/checks").json()
    names = {check["check_name"] for check in checks}
    # The reported check is stored, and the anomaly check is added on this side
    # because the reporter cannot see its own history.
    assert names == {"not_null_ts", "row_count_anomaly"}


def test_row_count_anomaly_compares_against_previous_reported_runs(
    client: TestClient, report: dict[str, Any], with_api_key: Callable[[], None]
) -> None:
    with_api_key()
    headers = {"X-API-Key": API_KEY}

    for index in range(3):
        client.post(
            "/runs",
            json={**report, "external_run_id": f"healthy-{index}"},
            headers=headers,
        )

    collapsed = {**report, "external_run_id": "collapsed-1", "rows_processed": 10}
    response = client.post("/runs", json=collapsed, headers=headers)

    checks = client.get(f"/runs/{response.json()['id']}/checks").json()
    anomaly = next(c for c in checks if c["check_name"] == "row_count_anomaly")
    assert anomaly["status"] == "FAIL"
    assert response.json()["quality_status"] == "FAIL"

    # A failed batch must not lower the baseline and make the next identical
    # failure appear healthy.
    repeated = client.post(
        "/runs",
        json={**collapsed, "external_run_id": "collapsed-2"},
        headers=headers,
    )
    repeated_checks = client.get(f"/runs/{repeated.json()['id']}/checks").json()
    repeated_anomaly = next(c for c in repeated_checks if c["check_name"] == "row_count_anomaly")
    assert repeated_anomaly["status"] == "FAIL"


def test_a_failed_run_is_not_also_flagged_as_an_anomaly(
    client: TestClient, report: dict[str, Any], with_api_key: Callable[[], None]
) -> None:
    with_api_key()
    headers = {"X-API-Key": API_KEY}
    client.post("/runs", json=report, headers=headers)

    failed = {
        **report,
        "external_run_id": "failed-run-1",
        "status": "FAILED",
        "rows_processed": 0,
        "error_type": "ConnectionError",
        "error_message": "Alpha Vantage timed out",
        "checks": [],
    }
    response = client.post("/runs", json=failed, headers=headers)

    assert response.status_code == 201
    assert response.json()["quality_status"] == "NOT_EVALUATED"
    # Zero rows here means the run stopped, not that the source shrank. Flagging
    # it would bury the real failure under a second, invented one.
    checks = client.get(f"/runs/{response.json()['id']}/checks").json()
    assert checks == []


def test_reporting_requires_the_api_key(
    client: TestClient, report: dict[str, Any], with_api_key: Callable[[], None]
) -> None:
    with_api_key()

    assert client.post("/runs", json=report).status_code == 401
    assert client.post("/runs", json=report, headers={"X-API-Key": "wrong"}).status_code == 401


def test_reporting_is_disabled_when_no_key_is_configured(
    client: TestClient, report: dict[str, Any]
) -> None:
    # Fails closed: this endpoint writes on behalf of a caller, so leaving the
    # secret unset must not leave it open.
    response = client.post("/runs", json=report, headers={"X-API-Key": "anything"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Run ingestion is not configured"}


def test_a_report_that_finishes_before_it_starts_is_rejected(
    client: TestClient, report: dict[str, Any], with_api_key: Callable[[], None]
) -> None:
    with_api_key()
    backwards = {**report, "finished_at": report["started_at"]} | {
        "started_at": report["finished_at"]
    }

    response = client.post("/runs", json=backwards, headers={"X-API-Key": API_KEY})

    assert response.status_code == 422


def test_reporting_the_same_external_run_is_idempotent(
    client: TestClient, report: dict[str, Any], with_api_key: Callable[[], None]
) -> None:
    with_api_key()
    headers = {"X-API-Key": API_KEY}

    created = client.post("/runs", json=report, headers=headers)
    repeated = client.post("/runs", json=report, headers=headers)

    assert created.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json()["id"] == created.json()["id"]
    runs = client.get("/runs").json()
    assert len(runs) == 1


def test_reusing_an_external_run_id_for_different_data_is_rejected(
    client: TestClient, report: dict[str, Any], with_api_key: Callable[[], None]
) -> None:
    with_api_key()
    headers = {"X-API-Key": API_KEY}
    client.post("/runs", json=report, headers=headers)

    conflict = client.post(
        "/runs",
        json={**report, "rows_processed": report["rows_processed"] + 1},
        headers=headers,
    )

    assert conflict.status_code == 409
    assert "different run data" in conflict.json()["detail"]


def test_a_non_ascii_key_is_rejected_not_crashed_on(
    client: TestClient, report: dict[str, Any], with_api_key: Callable[[], None]
) -> None:
    with_api_key()

    response = client.post("/runs", json=report, headers={"X-API-Key": "é".encode("latin-1")})

    assert response.status_code == 401


def test_a_check_metric_must_be_a_finite_number(
    client: TestClient, report: dict[str, Any], with_api_key: Callable[[], None]
) -> None:
    with_api_key()
    body = json.dumps({**report, "checks": [{**report["checks"][0], "metric_value": float("nan")}]})

    response = client.post(
        "/runs",
        content=body,
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_a_backfilled_run_outside_the_retention_window_is_still_answered(
    client: TestClient,
    report: dict[str, Any],
    with_api_key: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with_api_key()
    monkeypatch.setattr(get_settings(), "run_retention_limit", 1)
    headers = {"X-API-Key": API_KEY}
    client.post("/runs", json=report, headers=headers)
    started_at = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    older = {
        **report,
        "external_run_id": "backfill-2026-09-27",
        "started_at": started_at.isoformat(),
        "finished_at": (started_at + timedelta(seconds=4)).isoformat(),
    }

    response = client.post("/runs", json=older, headers=headers)

    # It is pruned at once, being older than the one run kept, but the report
    # itself was valid and must not answer with a 500.
    assert response.status_code == 201
    assert response.json()["external_run_id"] == "backfill-2026-09-27"


def test_report_timestamps_must_include_a_timezone(
    client: TestClient, report: dict[str, Any], with_api_key: Callable[[], None]
) -> None:
    with_api_key()
    without_timezone = {**report, "started_at": "2026-09-28T12:00:00"}

    response = client.post(
        "/runs",
        json=without_timezone,
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 422
