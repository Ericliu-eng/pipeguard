from datetime import UTC, datetime, timedelta

import pytest
from pipeguard.models import CheckStatus
from pipeguard.services.quality_checks import (
    check_duplicate_rate,
    check_freshness,
    check_null_rate,
    check_row_count_anomaly,
)


def test_null_rate_passes_at_threshold() -> None:
    result = check_null_rate([{"value": 1}, {"value": None}], field="value", threshold=0.5)

    assert result.status is CheckStatus.passed
    assert result.metric_value == 0.5


def test_duplicate_rate_fails_above_threshold() -> None:
    result = check_duplicate_rate(
        [{"event_id": 1}, {"event_id": 1}, {"event_id": 2}],
        key_fields=("event_id",),
        threshold=0.1,
    )

    assert result.status is CheckStatus.failed
    assert result.metric_value == pytest.approx(1 / 3)


def test_freshness_fails_for_old_events() -> None:
    now = datetime(2026, 8, 3, tzinfo=UTC)
    result = check_freshness(
        [{"event_time": now - timedelta(hours=25)}],
        threshold_hours=24,
        now=now,
    )

    assert result.status is CheckStatus.failed
    assert result.metric_value == 25


def test_row_count_warns_without_history() -> None:
    result = check_row_count_anomaly(10, historical_counts=[], threshold=0.3)

    assert result.status is CheckStatus.warning


def test_row_count_increase_is_described_as_an_increase() -> None:
    result = check_row_count_anomaly(900, historical_counts=[500], threshold=0.3)

    assert result.status is CheckStatus.passed
    assert result.message.endswith("(80.0% increase).")


def test_row_count_fails_for_large_drop() -> None:
    result = check_row_count_anomaly(6, historical_counts=[10, 10, 10], threshold=0.3)

    assert result.status is CheckStatus.failed
    assert result.metric_value == pytest.approx(0.4)
