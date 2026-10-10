from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ErrorResponse(BaseModel):
    detail: str = Field(examples=["Run not found"])


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    database: str


class QualityCheckReport(BaseModel):
    """One check a reporting pipeline already evaluated for itself."""

    check_name: str = Field(min_length=1, max_length=120, examples=["not_null"])
    status: Literal["PASS", "WARN", "FAIL"]
    # NaN and infinity are rejected: SQLite stores NaN as NULL and JSON cannot
    # carry either, so accepting them turned a bad report into a 500.
    metric_value: float = Field(
        allow_inf_nan=False, description="What the check measured, e.g. a null rate."
    )
    threshold: float = Field(
        allow_inf_nan=False, description="The limit the metric was compared against."
    )
    message: str = Field(min_length=1, examples=["market_bars.ts has no nulls."])


class RunReportRequest(BaseModel):
    """A finished run, reported by the pipeline that ran it.

    Only the checks a pipeline can evaluate from its own data belong here.
    Anything derived from run history — the row-count anomaly, for one — is
    computed on this side, because a pipeline cannot see its own past runs.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "pipeline_name": "market_data_lakehouse_pipeline",
                    "external_run_id": "market-data-2026-09-28T12:00:00Z",
                    "status": "SUCCESS",
                    "started_at": "2026-09-28T12:00:00Z",
                    "finished_at": "2026-09-28T12:00:04Z",
                    "rows_processed": 500,
                    "checks": [
                        {
                            "check_name": "not_null",
                            "status": "PASS",
                            "metric_value": 0.0,
                            "threshold": 0.0,
                            "message": "market_bars.ts has no nulls.",
                        }
                    ],
                }
            ]
        }
    )

    pipeline_name: str = Field(min_length=1, max_length=120)
    external_run_id: str = Field(
        min_length=1,
        max_length=200,
        description="The pipeline's own ID for this run. Retries must reuse it.",
    )
    status: Literal["SUCCESS", "FAILED"]
    started_at: datetime = Field(description="Must include a timezone.")
    finished_at: datetime = Field(description="Must include a timezone; not before started_at.")
    rows_processed: int = Field(ge=0)
    error_type: str | None = Field(default=None, max_length=120)
    error_message: str | None = None
    checks: list[QualityCheckReport] = Field(
        default_factory=list,
        description="Checks the pipeline evaluated on its own data. "
        "PipeGuard adds the row-count anomaly check itself.",
    )

    @model_validator(mode="after")
    def _check_ordering(self) -> Self:
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("started_at and finished_at must include a timezone")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        return self


class PipelineRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pipeline_name: str
    external_run_id: str | None
    started_at: datetime
    finished_at: datetime | None
    status: Literal["RUNNING", "SUCCESS", "FAILED"]
    quality_status: Literal["NOT_EVALUATED", "PASS", "WARN", "FAIL"]
    rows_processed: int
    duration_ms: int | None
    error_type: str | None
    error_message: str | None


class PipelineRunSummaryResponse(BaseModel):
    successful: int = Field(ge=0)
    failed: int = Field(ge=0)
    running: int = Field(ge=0)
    quality_incidents: int = Field(ge=0)


class PipelineRunPageResponse(BaseModel):
    items: list[PipelineRunResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    has_more: bool
    summary: PipelineRunSummaryResponse


class QualityCheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    check_name: str
    metric_value: float
    threshold: float
    status: str
    message: str
    created_at: datetime


class IncidentAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    summary: str
    severity: str
    likely_causes: list[str]
    recommended_steps: list[str]
    model_name: str
    created_at: datetime
