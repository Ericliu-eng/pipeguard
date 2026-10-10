import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pipeguard.config import get_settings
from pipeguard.models import PipelineRun, QualityCheck, RunQualityStatus, RunStatus
from pipeguard.schemas import RunReportRequest
from pipeguard.services.pipeline import prune_old_runs
from pipeguard.services.quality_checks import check_row_count_anomaly, summarize_check_statuses


class RunReportConflictError(ValueError):
    """Raised when an idempotency key is reused for different run data."""


def record_reported_run(db: Session, report: RunReportRequest) -> tuple[PipelineRun, bool]:
    """Store a run reported by an external pipeline, with its checks.

    The reporting pipeline sends the checks only it can evaluate, because only
    it touched the data. This side adds the row-count anomaly, because only it
    has the run history to compare against. An in-pipeline check is an assertion
    about one batch; the anomaly check is a statement about a trend, and no
    single run can make it.
    """
    fingerprint = _report_fingerprint(report)
    existing = _find_reported_run(db, report.pipeline_name, report.external_run_id)
    if existing is not None:
        _ensure_matching_report(existing, fingerprint)
        return existing, False

    run = PipelineRun(
        pipeline_name=report.pipeline_name,
        external_run_id=report.external_run_id,
        report_fingerprint=fingerprint,
        started_at=report.started_at,
        finished_at=report.finished_at,
        status=RunStatus(report.status),
        rows_processed=report.rows_processed,
        duration_ms=_duration_ms(report.started_at, report.finished_at),
        error_type=report.error_type,
        error_message=report.error_message,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        # A concurrent retry may have inserted the same external run after the
        # lookup above. The database constraint is the final arbiter.
        db.rollback()
        existing = _find_reported_run(db, report.pipeline_name, report.external_run_id)
        if existing is None:
            raise
        _ensure_matching_report(existing, fingerprint)
        return existing, False

    recorded_at = datetime.now(UTC)
    checks = [
        QualityCheck(
            run_id=run.id,
            check_name=reported.check_name,
            metric_value=reported.metric_value,
            threshold=reported.threshold,
            status=reported.status,
            message=reported.message,
            created_at=recorded_at,
        )
        for reported in report.checks
    ]

    # Only for a run that finished: a failed run reports zero rows because it
    # stopped, not because the source shrank, and flagging that as an anomaly
    # would bury the real failure under a second false one.
    if run.status == RunStatus.success:
        checks.append(_row_count_anomaly(db, run=run, now=recorded_at))
        run.quality_status = summarize_check_statuses(check.status for check in checks)
    else:
        run.quality_status = RunQualityStatus.not_evaluated

    if checks:
        db.add_all(checks)

    db.commit()
    # Refresh before pruning: a backfilled run older than the retention window
    # is pruned at once, and refreshing a deleted row raised instead of answering.
    db.refresh(run)

    prune_old_runs(db, limit=get_settings().run_retention_limit)

    return run, True


def _find_reported_run(db: Session, pipeline_name: str, external_run_id: str) -> PipelineRun | None:
    return db.scalar(
        select(PipelineRun).where(
            PipelineRun.pipeline_name == pipeline_name,
            PipelineRun.external_run_id == external_run_id,
        )
    )


def _ensure_matching_report(existing: PipelineRun, fingerprint: str) -> None:
    if existing.report_fingerprint != fingerprint:
        raise RunReportConflictError(
            "external_run_id is already associated with different run data"
        )


def _report_fingerprint(report: RunReportRequest) -> str:
    payload = report.model_dump(mode="json")
    payload["started_at"] = report.started_at.astimezone(UTC).isoformat()
    payload["finished_at"] = report.finished_at.astimezone(UTC).isoformat()
    payload["checks"] = sorted(
        payload["checks"],
        key=lambda check: json.dumps(check, sort_keys=True, separators=(",", ":")),
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _row_count_anomaly(db: Session, *, run: PipelineRun, now: datetime) -> QualityCheck:
    settings = get_settings()
    historical_counts = list(
        db.scalars(
            select(PipelineRun.rows_processed)
            .where(
                PipelineRun.pipeline_name == run.pipeline_name,
                PipelineRun.status == RunStatus.success,
                PipelineRun.quality_status.in_([RunQualityStatus.passed, RunQualityStatus.warning]),
                PipelineRun.id != run.id,
            )
            .order_by(PipelineRun.started_at.desc())
            .limit(settings.row_count_history_size)
        )
    )
    result = check_row_count_anomaly(
        run.rows_processed,
        historical_counts=historical_counts,
        threshold=settings.row_count_drop_threshold,
    )

    return QualityCheck(
        run_id=run.id,
        check_name=result.check_name,
        metric_value=result.metric_value,
        threshold=result.threshold,
        status=result.status,
        message=result.message,
        created_at=now,
    )


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    return max(0, round((finished_at - started_at).total_seconds() * 1000))
