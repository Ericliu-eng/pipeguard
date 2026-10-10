from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from pipeguard.models import CheckStatus, RunQualityStatus


@dataclass(frozen=True)
class QualityCheckResult:
    check_name: str
    metric_value: float
    threshold: float
    status: CheckStatus
    message: str


def summarize_check_statuses(statuses: Iterable[CheckStatus | str]) -> RunQualityStatus:
    """Collapse individual check outcomes into one run-level quality status."""
    normalized = {CheckStatus(status) for status in statuses}
    if not normalized:
        return RunQualityStatus.not_evaluated
    if CheckStatus.failed in normalized:
        return RunQualityStatus.failed
    if CheckStatus.warning in normalized:
        return RunQualityStatus.warning
    return RunQualityStatus.passed


def check_null_rate(
    rows: Sequence[dict[str, Any]], *, field: str, threshold: float
) -> QualityCheckResult:
    null_count = sum(row.get(field) is None for row in rows)
    null_rate = null_count / len(rows) if rows else 1.0
    status = CheckStatus.failed if null_rate > threshold else CheckStatus.passed
    return QualityCheckResult(
        check_name="null_rate",
        metric_value=null_rate,
        threshold=threshold,
        status=status,
        message=f"{field} null rate is {null_rate:.1%} ({null_count}/{len(rows)} rows).",
    )


def check_duplicate_rate(
    rows: Sequence[dict[str, Any]], *, key_fields: Iterable[str], threshold: float
) -> QualityCheckResult:
    keys = tuple(key_fields)
    seen: set[tuple[Any, ...]] = set()
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(field) for field in keys)
        if key in seen:
            duplicate_count += 1
        seen.add(key)

    duplicate_rate = duplicate_count / len(rows) if rows else 0.0
    status = CheckStatus.failed if duplicate_rate > threshold else CheckStatus.passed
    return QualityCheckResult(
        check_name="duplicate_rate",
        metric_value=duplicate_rate,
        threshold=threshold,
        status=status,
        message=f"Duplicate rate is {duplicate_rate:.1%} ({duplicate_count}/{len(rows)} rows).",
    )


def check_freshness(
    rows: Sequence[dict[str, Any]], *, threshold_hours: float, now: datetime | None = None
) -> QualityCheckResult:
    current_time = now or datetime.now(UTC)
    timestamps = [row.get("event_time") for row in rows if row.get("event_time") is not None]
    if not timestamps:
        return QualityCheckResult(
            check_name="freshness",
            metric_value=float("inf"),
            threshold=threshold_hours,
            status=CheckStatus.failed,
            message="No event_time values were available for freshness validation.",
        )

    newest_event_time = max(_as_utc_datetime(value) for value in timestamps)
    age_hours = max(0.0, (current_time - newest_event_time).total_seconds() / 3600)
    status = CheckStatus.failed if age_hours > threshold_hours else CheckStatus.passed
    return QualityCheckResult(
        check_name="freshness",
        metric_value=age_hours,
        threshold=threshold_hours,
        status=status,
        message=f"Newest event is {age_hours:.1f} hours old.",
    )


def check_row_count_anomaly(
    current_count: int, *, historical_counts: Sequence[int], threshold: float
) -> QualityCheckResult:
    if not historical_counts:
        return QualityCheckResult(
            check_name="row_count_anomaly",
            metric_value=0.0,
            threshold=threshold,
            status=CheckStatus.warning,
            message="Insufficient run history for row-count anomaly detection.",
        )

    baseline = mean(historical_counts)
    drop_ratio = (baseline - current_count) / baseline if baseline else 0.0
    status = CheckStatus.failed if drop_ratio > threshold else CheckStatus.passed
    change = f"{drop_ratio:.1%} decrease" if drop_ratio >= 0 else f"{-drop_ratio:.1%} increase"
    return QualityCheckResult(
        check_name="row_count_anomaly",
        metric_value=drop_ratio,
        threshold=threshold,
        status=status,
        message=(
            f"Current row count is {current_count}; historical average is {baseline:.1f} "
            f"({change})."
        ),
    )


def _as_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("event_time must be an ISO 8601 string or datetime")

    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
