"""The API reference page: an overview on top of the stock Swagger UI.

The overview answers the first questions (what the two states mean, how to
report a run, which routes exist) before the full reference. Its endpoint list
is built from the OpenAPI schema, so it cannot drift from the routes.
"""

from html import escape
from typing import Any

from fastapi.openapi.docs import get_swagger_ui_html

GITHUB_URL = "https://github.com/Ericliu-eng/pipeguard"

QUICK_START = """curl -X POST "$PIPEGUARD_URL/runs" \\
  -H "X-API-Key: $PIPEGUARD_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "pipeline_name": "orders",
    "external_run_id": "orders-2026-10-04",
    "status": "SUCCESS",
    "started_at": "2026-10-04T12:00:00Z",
    "finished_at": "2026-10-04T12:00:04Z",
    "rows_processed": 500,
    "checks": [
      { "check_name": "not_null", "status": "PASS",
        "metric_value": 0, "threshold": 0,
        "message": "orders.id has no nulls." }
    ]
  }'"""

HEADER = f"""<header class="pg-bar"><div class="pg-bar-inner">
  <a class="pg-brand" href="/">
    <img src="/static/favicon.svg" alt="" width="22" height="22">PipeGuard</a>
  <span class="pg-sub">API reference</span>
  <span class="pg-health" id="pg-health" role="status"><i></i><span>Checking API…</span></span>
  <a class="pg-link" href="/">Dashboard</a>
  <a class="pg-link" href="{GITHUB_URL}">GitHub</a>
  <button class="pg-authorize" id="pg-authorize" type="button">Authorize</button>
</div></header>"""


def _pill(label: str, tone: str) -> str:
    return f'<span class="pg-pill {tone}">{label}</span>'


def _endpoints(schema: dict[str, Any]) -> tuple[str, int]:
    rows = []
    for path, operations in schema["paths"].items():
        for method, op in operations.items():
            anchor = f"#/{op['tags'][0]}/{op['operationId']}" if op.get("tags") else "#"
            key = '<span class="pg-key">API key</span>' if op.get("security") else ""
            rows.append(
                f'<li><a href="{escape(anchor)}">'
                f'<span class="pg-method {method}">{method.upper()}</span>'
                f'<code class="pg-path">{escape(path)}</code>'
                f'<span class="pg-summary">{escape(op.get("summary", ""))}</span>{key}</a></li>'
            )
    return "\n".join(rows), len(rows)


def overview(schema: dict[str, Any]) -> str:
    rows, count = _endpoints(schema)
    version = escape(schema["info"]["version"])
    return f"""<div class="pg-overview">
  <p class="pg-eyebrow">API REFERENCE · v{version}</p>
  <h1>PipeGuard API</h1>
  <p class="pg-lede">Report each finished pipeline run. PipeGuard compares it with recent healthy
  runs and explains what went wrong.</p>

  <div class="pg-states">
    <section class="pg-card"><code class="pg-label">status</code><h2>Did it run?</h2>
      <p>{_pill("Success", "ok")}{_pill("Failed", "bad")}</p></section>
    <section class="pg-card"><code class="pg-label">quality_status</code><h2>Is the data good?</h2>
      <p>{_pill("Pass", "ok")}{_pill("Warn", "warn")}{_pill("Fail", "bad")}</p></section>
    <section class="pg-card"><span class="pg-label">Why two?</span>
      <p class="pg-why">A run can succeed and still deliver bad data: every row valid, but far
      fewer of them than usual.</p></section>
  </div>

  <div class="pg-grid">
    <section class="pg-card pg-quick">
      <div class="pg-card-head"><div><h2>Quick start</h2>
        <p>Send one request when a run finishes. Needs an <code>X-API-Key</code> header.</p></div>
        <button class="pg-copy" type="button" data-copy="pg-curl">Copy</button></div>
      <pre id="pg-curl"><code>{escape(QUICK_START)}</code></pre>
    </section>
    <div class="pg-side">
      <section class="pg-card pg-endpoints">
        <div class="pg-card-head"><h2>Endpoints</h2><span>{count} routes</span></div>
        <ul>{rows}</ul>
      </section>
      <section class="pg-card pg-note"><h2>Good to know</h2>
        <p>Re-sending the same <code>external_run_id</code> with the same data is safe: you get
        the stored run back. Different data under that ID is rejected with <code>409</code>.
        Errors return <code>{{"detail": "..."}}</code> with 401, 404, 409 or 422.</p></section>
    </div>
  </div>

  <h2 class="pg-try">Try it out</h2>
  <p class="pg-try-note">Every route with its parameters and responses. Use <b>Authorize</b> to
  set the API key, then <b>Execute</b> sends a real request.</p>
</div>"""


def render(schema: dict[str, Any], openapi_url: str, title: str) -> str:
    """Swagger UI with the overview and the dashboard's header in front of it.

    The stock page is kept for its behavior; the overview, a stylesheet and a
    script are added around it.
    """
    page = get_swagger_ui_html(
        openapi_url=openapi_url,
        title=title,
        swagger_favicon_url="/static/favicon.svg",
        swagger_ui_parameters={
            "docExpansion": "list",
            "deepLinking": True,
            "defaultModelsExpandDepth": 0,
            "displayRequestDuration": True,
            "persistAuthorization": True,
            "tryItOutEnabled": True,
            "syntaxHighlight": {"theme": "nord"},
        },
    )
    html = page.body.decode()
    html = html.replace("</head>", '<link rel="stylesheet" href="/static/docs.css">\n</head>', 1)
    html = html.replace("<body>", f"<body>\n{HEADER}\n{overview(schema)}", 1)
    return html.replace("</body>", '<script src="/static/docs.js" defer></script>\n</body>', 1)
