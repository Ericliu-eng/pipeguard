# Problem statement

Small data teams often operate scheduled API or database ingestion jobs without dedicated
observability infrastructure. Failures, stale data, unexpected row counts, and rising null or
duplicate rates may remain unnoticed until a downstream user reports them. Raw logs then make
root-cause investigation slow and inconsistent.

PipeGuard provides a small, locally reproducible monitoring layer with a deterministic demonstration
pipeline and an authenticated endpoint for runs reported by external pipelines. The MVP records each
run, separates execution state from data-quality state, evaluates configurable quality rules, and
presents the result through an API and dashboard. Failed runs are summarized into deterministic,
structured troubleshooting guidance.

## MVP boundaries

Included:

- One demonstration pipeline and authenticated external run reporting
- Run history and failure details
- Null, duplicate, freshness, and row-count checks
- Dashboard for current state and history
- Structured incident explanation

Not included:

- User accounts or multi-user permissions (ingestion uses one shared API key)
- Pipeline registration and per-pipeline policy management
- Automated remediation
- Complex anomaly-detection models
- Slack or email alerting
