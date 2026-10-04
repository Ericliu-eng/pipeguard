from dataclasses import dataclass
from datetime import UTC, datetime

from pipeguard.models import CheckStatus, IncidentAnalysis, PipelineRun, QualityCheck, RunStatus

MODEL_NAME = "rule-based"


@dataclass(frozen=True)
class _Guidance:
    cause: str
    steps: tuple[str, ...]


# Advice keyed by check name, covering both this project's own checks and the
# names an external pipeline reports through POST /runs. A failed check should
# be explained in terms of what that check actually measures: telling someone
# whose row count collapsed to "inspect the data for nulls" sends them looking
# in the wrong place at exactly the moment the analysis is supposed to help.
_NULLS = _Guidance(
    cause=(
        "Required fields arrived empty, which usually means the source changed its "
        "schema, renamed a field, or sent partial records."
    ),
    steps=(
        "Find which fields are empty and the first run where they started.",
        "Compare the raw payload with the expected schema for renamed or dropped fields.",
    ),
)
_DUPLICATES = _Guidance(
    cause=(
        "The same record arrived more than once, often from a retried request, an "
        "overlapping date range, or a load that ran twice."
    ),
    steps=(
        "Identify the duplicated keys and the runs that loaded them.",
        "Check whether a retry or a backfill overlapped with a regular load.",
    ),
)
_GUIDANCE: dict[str, _Guidance] = {
    "row_count_anomaly": _Guidance(
        cause=(
            "Far fewer rows arrived than in recent successful runs. The source may have "
            "truncated its response, throttled the request, or stopped publishing part "
            "of the data — and every row that did arrive can still pass its own checks."
        ),
        steps=(
            "Compare this run's row count with the previous successful runs of the same pipeline.",
            "Check the upstream response for truncation, throttling, or an error payload "
            "returned with a success status.",
            "Confirm that the requested entities, date range, and pagination did not change.",
        ),
    ),
    "freshness": _Guidance(
        cause=(
            "The newest data is older than expected: the source may not have published "
            "yet, or the pipeline is reading a stale window."
        ),
        steps=(
            "Check when the source last published, ruling out expected gaps such as "
            "weekends or holidays.",
            "Confirm that the requested window and any watermark advanced as expected.",
        ),
    ),
    "range": _Guidance(
        cause=(
            "Values fell outside their valid range, such as a negative price or volume, "
            "which points to a parsing error or a malformed source record."
        ),
        steps=(
            "Find the out-of-range rows and the raw records they were parsed from.",
            "Check the parsing and type conversion for the affected field.",
        ),
    ),
    "foreign_key": _Guidance(
        cause=(
            "Rows reference keys that do not exist, typically because loads ran out of "
            "order or a load they depend on failed."
        ),
        steps=(
            "List the orphaned keys and the table they should exist in.",
            "Check that the referenced table loaded before this one did.",
        ),
    ),
    "null_rate": _NULLS,
    "not_null": _NULLS,
    "duplicate_rate": _DUPLICATES,
    "unique": _DUPLICATES,
}
_UNKNOWN_CHECK = _Guidance(
    cause="A quality check failed against its threshold.",
    steps=("Review the failed check's metric against its threshold and recent runs.",),
)


def build_incident_analysis(
    run: PipelineRun,
    checks: list[QualityCheck],
) -> IncidentAnalysis:
    failed_checks = [check for check in checks if check.status == CheckStatus.failed]

    if run.status == RunStatus.failed:
        summary = run.error_message or "The pipeline run failed."
        severity = "high"
        likely_causes = [
            run.error_type or "Unknown pipeline error",
            "Upstream service or network failure",
        ]
        recommended_steps = [
            "Review the pipeline error message and logs.",
            "Check the upstream service availability.",
            "Retry the pipeline after verifying connectivity.",
        ]

    elif failed_checks:
        failed_names = _unique(check.check_name for check in failed_checks)
        guidance = [_GUIDANCE.get(name, _UNKNOWN_CHECK) for name in failed_names]
        noun = "check" if len(failed_names) == 1 else "checks"

        summary = (
            f"The pipeline completed, but {len(failed_names)} data quality {noun} "
            f"failed: {', '.join(failed_names)}."
        )
        severity = "medium"
        likely_causes = _unique(item.cause for item in guidance)
        recommended_steps = _unique(step for item in guidance for step in item.steps)

    else:
        summary = "The pipeline completed successfully with no detected incidents."
        severity = "low"
        likely_causes = []
        recommended_steps = ["No immediate action is required."]

    return IncidentAnalysis(
        run_id=run.id,
        summary=summary,
        severity=severity,
        likely_causes=likely_causes,
        recommended_steps=recommended_steps,
        model_name=MODEL_NAME,
        created_at=datetime.now(UTC),
    )


def _unique(values) -> list[str]:
    """Drop repeats while keeping first-seen order.

    A pipeline can report several checks under one name — one not_null per
    column, say — and two names can share the same advice. Either way, the
    reader should see each cause and step once.
    """
    return list(dict.fromkeys(values))
