from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pipeguard.models import PipelineRun, RunQualityStatus, RunStatus
from sqlalchemy.orm import Session

STARTED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def add_run(
    db: Session,
    *,
    pipeline_name: str,
    status: RunStatus,
    quality_status: RunQualityStatus,
    started_at: datetime = STARTED_AT,
) -> PipelineRun:
    run = PipelineRun(
        pipeline_name=pipeline_name,
        started_at=started_at,
        finished_at=None if status == RunStatus.running else started_at + timedelta(seconds=1),
        status=status,
        quality_status=quality_status,
        rows_processed=10,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_run_history_returns_deterministic_tie_ordering_and_global_summary(
    client: TestClient, db: Session
) -> None:
    first = add_run(
        db,
        pipeline_name="orders",
        status=RunStatus.success,
        quality_status=RunQualityStatus.passed,
    )
    second = add_run(
        db,
        pipeline_name="orders",
        status=RunStatus.failed,
        quality_status=RunQualityStatus.not_evaluated,
    )
    third = add_run(
        db,
        pipeline_name="inventory",
        status=RunStatus.running,
        quality_status=RunQualityStatus.failed,
    )

    first_page = client.get("/runs/page?limit=2").json()

    assert [run["id"] for run in first_page["items"]] == [third.id, second.id]
    assert first_page["total"] == 3
    assert first_page["limit"] == 2
    assert first_page["offset"] == 0
    assert first_page["has_more"] is True
    assert first_page["summary"] == {
        "successful": 1,
        "failed": 1,
        "running": 1,
        "quality_incidents": 1,
    }

    second_page = client.get("/runs/page?limit=2&offset=2").json()

    assert [run["id"] for run in second_page["items"]] == [first.id]
    assert second_page["total"] == 3
    assert second_page["has_more"] is False
    assert second_page["summary"] == first_page["summary"]

    empty_page = client.get("/runs/page?limit=2&offset=99").json()

    assert empty_page["items"] == []
    assert empty_page["total"] == 3
    assert empty_page["has_more"] is False


def test_run_history_filters_and_counts_the_matching_set(client: TestClient, db: Session) -> None:
    matching = add_run(
        db,
        pipeline_name="orders",
        status=RunStatus.success,
        quality_status=RunQualityStatus.failed,
    )
    add_run(
        db,
        pipeline_name="orders",
        status=RunStatus.success,
        quality_status=RunQualityStatus.passed,
    )
    add_run(
        db,
        pipeline_name="orders",
        status=RunStatus.failed,
        quality_status=RunQualityStatus.failed,
    )
    add_run(
        db,
        pipeline_name="inventory",
        status=RunStatus.success,
        quality_status=RunQualityStatus.failed,
    )
    spaced_name = add_run(
        db,
        pipeline_name=" orders ",
        status=RunStatus.success,
        quality_status=RunQualityStatus.failed,
    )

    response = client.get(
        "/runs/page",
        params={
            "pipeline_name": "orders",
            "status": "SUCCESS",
            "quality_status": "FAIL",
        },
    )

    assert response.status_code == 200
    page = response.json()
    assert [run["id"] for run in page["items"]] == [matching.id]
    assert page["total"] == 1
    assert page["summary"] == {
        "successful": 1,
        "failed": 0,
        "running": 0,
        "quality_incidents": 1,
    }

    exact_name_response = client.get(
        "/runs/page",
        params={"pipeline_name": " orders "},
    )
    assert [run["id"] for run in exact_name_response.json()["items"]] == [spaced_name.id]


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=201",
        "offset=-1",
        "status=UNKNOWN",
        "quality_status=UNKNOWN",
        "pipeline_name=",
        "pipeline_name=%20%20%20",
    ],
)
def test_run_history_rejects_invalid_query_parameters(client: TestClient, query: str) -> None:
    assert client.get(f"/runs/page?{query}").status_code == 422
