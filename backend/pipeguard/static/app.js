"use strict";

// Dashboard for the PipeGuard API. It reads the same endpoints any client can:
// /runs/page for the list and KPIs, /runs/{id}/checks and /analysis for detail,
// and the pipeline's own run history for the row-count trend.

const PAGE_SIZE = 20;
const TREND_RUNS = 8; // the selected run plus up to seven before it
const BASELINE_RUNS = 5; // matches the server's default ROW_COUNT_HISTORY_SIZE
const REFRESH_MS = 15000;
const WAKE_HINT_MS = 2500; // free hosting sleeps; say so instead of looking broken

const state = {
  filters: { pipeline: "", status: "", quality: "" },
  offset: 0,
  page: null,
  selectedId: null,
  seenIds: new Set(),
  metrics: { total: 0, rate: 0, failed: 0, incidents: 0 },
  pipelines: new Set(),
  busy: false,
};

const $ = (id) => document.getElementById(id);
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Pipeline names, messages and check names come from external reporters, so
// everything rendered as HTML goes through this.
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { Accept: "application/json" }, ...options });
  if (response.status === 404 && options.allow404) return null;
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* keep the status line */ }
    throw new Error(detail);
  }
  return response.json();
}

/* ---------- formatting ---------- */

const numberFormat = new Intl.NumberFormat("en-US");

// The API stores UTC. PostgreSQL returns the offset; SQLite drops it, and a
// timestamp without one would otherwise be read as the viewer's local time.
function parseTime(iso) {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
}

function relativeTime(iso) {
  const seconds = Math.round((Date.now() - parseTime(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const units = [["day", 86400], ["hour", 3600], ["min", 60]];
  for (const [unit, size] of units) {
    if (seconds >= size) {
      const n = Math.floor(seconds / size);
      return `${n} ${unit}${n > 1 && unit !== "min" ? "s" : ""} ago`;
    }
  }
  return "1 min ago";
}

function fullTime(iso) {
  return iso ? parseTime(iso).toLocaleString() : "—";
}

function duration(ms) {
  if (ms == null) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function checkValue(name, value) {
  if (value == null || !Number.isFinite(value)) return "—";
  if (/rate|anomaly/.test(name)) return `${(value * 100).toFixed(1)}%`;
  if (/fresh/.test(name)) return `${value.toFixed(1)} h`;
  return Number.isInteger(value) ? numberFormat.format(value) : value.toFixed(2);
}

const TONE = { SUCCESS: "ok", PASS: "ok", WARN: "warn", FAILED: "bad", FAIL: "bad", RUNNING: "live" };
const LABEL = { NOT_EVALUATED: "Not evaluated", SUCCESS: "Success", FAILED: "Failed", RUNNING: "Running", PASS: "Pass", WARN: "Warn", FAIL: "Fail" };

function pill(value, prefix = "") {
  const label = `${prefix}${LABEL[value] ?? value}`;
  return `<span class="pill ${TONE[value] ?? ""}">${esc(label)}</span>`;
}

/* ---------- connection ---------- */

async function checkHealth() {
  const box = $("connection");
  const text = $("connection-text");
  const hint = setTimeout(() => {
    box.className = "connection waking";
    text.textContent = "Waking up the API (free tier, up to a minute)…";
  }, WAKE_HINT_MS);
  try {
    const response = await fetch("/health");
    const body = await response.json().catch(() => ({}));
    box.className = `connection ${response.ok ? "online" : "degraded"}`;
    text.textContent = response.ok ? "API healthy" : `Degraded: database ${body.database ?? "unavailable"}`;
  } catch {
    box.className = "connection offline";
    text.textContent = "API unreachable";
  } finally {
    clearTimeout(hint);
  }
}

/* ---------- metrics ---------- */

function animateNumber(el, from, to, format) {
  if (reduceMotion || from === to) {
    el.textContent = format(to);
    return;
  }
  const start = performance.now();
  const step = (now) => {
    const k = Math.min(1, (now - start) / 700);
    const eased = 1 - (1 - k) ** 3;
    el.textContent = format(from + (to - from) * eased);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function renderMetrics(page) {
  const { summary, total } = page;
  const finished = summary.successful + summary.failed;
  const next = {
    total,
    rate: finished ? (summary.successful / finished) * 100 : 0,
    failed: summary.failed,
    incidents: summary.quality_incidents,
  };
  const filtered = Object.values(state.filters).some(Boolean);
  $("metric-total-label").textContent = filtered ? "Matching runs" : "Runs";
  $("metric-total-detail").textContent = filtered ? "with the current filters" : "all pipelines";
  const int = (v) => numberFormat.format(Math.round(v));
  const formats = { total: int, rate: (v) => (finished ? `${v.toFixed(1)}%` : "—"), failed: int, incidents: int };
  for (const key of Object.keys(next)) {
    const el = document.querySelector(`[data-metric="${key}"]`);
    animateNumber(el, state.metrics[key], next[key], formats[key]);
  }
  state.metrics = next;
}

/* ---------- run list ---------- */

function showSkeleton() {
  const list = $("run-list");
  list.innerHTML = "";
  const template = $("skeleton-row");
  for (let i = 0; i < 6; i += 1) list.append(template.content.cloneNode(true));
}

function rowHtml(run, fresh) {
  const quality = run.status === "SUCCESS" ? pill(run.quality_status) : "";
  return `<li class="run-row${fresh ? " fresh" : ""}" role="option" tabindex="-1" data-id="${run.id}" aria-selected="${run.id === state.selectedId}">
    <span class="run-id mono">#${run.id}</span>
    <span title="${esc(run.pipeline_name)}">${esc(run.pipeline_name)}</span>
    <span class="run-time" title="${esc(fullTime(run.started_at))}">${esc(relativeTime(run.started_at))}</span>
    <span class="run-rows">${numberFormat.format(run.rows_processed)}</span>
    <span class="pills">${pill(run.status)}${quality}</span>
  </li>`;
}

function renderList(page, { markNew }) {
  const list = $("run-list");
  list.setAttribute("role", "listbox");
  if (!page.items.length) {
    const filtered = Object.values(state.filters).some(Boolean);
    list.innerHTML = `<li class="empty"><strong>${filtered ? "No runs match these filters" : "No runs yet"}</strong>${
      filtered ? "Change or clear a filter to see more." : "Run the demo pipeline, or report a run with POST /runs."}</li>`;
  } else {
    list.innerHTML = page.items
      .map((run, i) => rowHtml(run, markNew && !state.seenIds.has(run.id)).replace("<li ", `<li style="animation-delay:${Math.min(i, 12) * 25}ms" `))
      .join("");
  }
  page.items.forEach((run) => state.seenIds.add(run.id));

  const first = page.total ? page.offset + 1 : 0;
  const last = page.offset + page.items.length;
  $("page-info").textContent = page.total ? `${first}–${last} of ${numberFormat.format(page.total)}` : "";
  $("prev-page").disabled = page.offset === 0;
  $("next-page").disabled = !page.has_more;

  const active = list.querySelector('[aria-selected="true"]') ?? list.querySelector(".run-row");
  if (active) active.tabIndex = 0;
}

function addPipelines(items) {
  const before = state.pipelines.size;
  items.forEach((run) => state.pipelines.add(run.pipeline_name));
  if (state.pipelines.size === before) return;
  const select = $("filter-pipeline");
  const current = select.value;
  select.innerHTML = `<option value="">All pipelines</option>${[...state.pipelines].sort()
    .map((name) => `<option value="${esc(name)}">${esc(name)}</option>`).join("")}`;
  select.value = current;
}

async function loadRuns({ quiet = false, select = null } = {}) {
  if (!quiet) showSkeleton();
  const params = new URLSearchParams({ limit: PAGE_SIZE, offset: state.offset });
  if (state.filters.pipeline) params.set("pipeline_name", state.filters.pipeline);
  if (state.filters.status) params.set("status", state.filters.status);
  if (state.filters.quality) params.set("quality_status", state.filters.quality);
  try {
    const page = await api(`/runs/page?${params}`);
    // Retention can shrink the history under an open page; step back to the last one.
    if (page.total && state.offset >= page.total) {
      state.offset = Math.floor((page.total - 1) / PAGE_SIZE) * PAGE_SIZE;
      return loadRuns({ quiet, select });
    }
    const firstLoad = state.page === null;
    state.page = page;
    addPipelines(page.items);
    renderMetrics(page);
    const ids = page.items.map((run) => run.id);
    const wanted = select ?? state.selectedId;
    const nextId = ids.includes(wanted) ? wanted : (ids[0] ?? null);
    const changed = nextId !== state.selectedId;
    state.selectedId = nextId;
    renderList(page, { markNew: quiet && !firstLoad });
    if (changed || !quiet) await renderDetail();
  } catch (error) {
    if (!quiet) {
      $("run-list").innerHTML = `<li class="empty"><strong>Couldn't load runs</strong>${esc(error.message)}</li>`;
      $("detail").innerHTML = "";
    }
  }
}

function selectRun(id, { focus = false } = {}) {
  if (id === state.selectedId) return;
  state.selectedId = id;
  history.replaceState(null, "", `#run-${id}`); // shareable link to this run
  document.querySelectorAll(".run-row").forEach((row) => {
    const on = Number(row.dataset.id) === id;
    row.setAttribute("aria-selected", on);
    row.tabIndex = on ? 0 : -1;
    if (on && focus) row.focus();
  });
  renderDetail();
}

/* ---------- detail ---------- */

let detailToken = 0;

async function renderDetail() {
  const token = ++detailToken;
  const box = $("detail");
  const run = state.page?.items.find((item) => item.id === state.selectedId);
  if (!run) {
    box.innerHTML = `<div class="empty"><strong>No run selected</strong>Pick a run to see its checks and analysis.</div>`;
    return;
  }
  box.innerHTML = headHtml(run) + `<div class="section"><h3>ROW COUNT</h3><div class="trend skeleton"><span style="flex:1;height:60%"></span></div></div>`;

  const [checks, analysis, history] = await Promise.all([
    api(`/runs/${run.id}/checks`).catch(() => []),
    api(`/runs/${run.id}/analysis`, { allow404: true }).catch(() => null),
    api(`/runs/page?${new URLSearchParams({ pipeline_name: run.pipeline_name, limit: 200 })}`)
      .then((page) => page.items).catch(() => []),
  ]);
  if (token !== detailToken) return; // the user picked another run meanwhile

  box.innerHTML = [
    headHtml(run),
    trendHtml(run, history, checks),
    run.status === "FAILED" ? errorHtml(run) : checksHtml(checks),
    `<div class="section" id="analysis-slot">${analysisHtml(run, analysis)}</div>`,
  ].join("");
  requestAnimationFrame(() => requestAnimationFrame(() => {
    box.querySelectorAll("[data-height]").forEach((bar) => { bar.style.height = bar.dataset.height; });
    box.querySelectorAll("[data-width]").forEach((bar) => { bar.style.width = bar.dataset.width; });
    box.querySelector(".trend")?.classList.add("grown");
  }));
  bindAnalyze(run);
}

function headHtml(run) {
  const quality = run.status === "SUCCESS" ? pill(run.quality_status, "Quality: ") : "";
  return `<div>
    <div class="detail-head"><h2>Run #${run.id}</h2>${pill(run.status)}${quality}</div>
    <p class="detail-sub">${esc(run.pipeline_name)}${run.external_run_id ? ` · <span class="mono">${esc(run.external_run_id)}</span>` : ""}</p>
    <dl class="facts">
      <div><dt>Started</dt><dd title="${esc(fullTime(run.started_at))}">${esc(relativeTime(run.started_at))}</dd></div>
      <div><dt>Duration</dt><dd>${esc(duration(run.duration_ms))}</dd></div>
      <div><dt>Rows</dt><dd>${numberFormat.format(run.rows_processed)}</dd></div>
    </dl>
  </div>`;
}

function trendHtml(run, history, checks) {
  // history is newest first; take the selected run and the runs before it.
  const index = history.findIndex((item) => item.id === run.id);
  if (index === -1) return "";
  const window = history.slice(index, index + TREND_RUNS).reverse();
  const before = window.slice(0, -1);
  const baselineRuns = before
    .filter((item) => item.status === "SUCCESS" && ["PASS", "WARN"].includes(item.quality_status))
    .slice(-BASELINE_RUNS);
  const baseline = baselineRuns.length
    ? baselineRuns.reduce((sum, item) => sum + item.rows_processed, 0) / baselineRuns.length
    : null;
  const anomaly = checks.find((check) => check.check_name === "row_count_anomaly");
  const drop = anomaly?.status === "FAIL";
  const max = Math.max(1, baseline ?? 0, ...window.map((item) => item.rows_processed));

  const bars = window.map((item) => {
    const classes = ["trend-bar"];
    if (item.id === run.id) classes.push("current");
    if (item.id === run.id && drop) classes.push("drop");
    if (item.status === "FAILED") classes.push("failed");
    const height = `${(item.rows_processed / max) * 100}%`;
    return `<div class="${classes.join(" ")}" data-height="${height}" title="#${item.id}: ${numberFormat.format(item.rows_processed)} rows"><span>${numberFormat.format(item.rows_processed)}</span></div>`;
  }).join("");
  const avg = baseline == null ? "" :
    `<div class="trend-avg" style="bottom:${(baseline / max) * 78}px"><em>avg ${numberFormat.format(Math.round(baseline))}</em></div>`;
  const labels = window.map((item) => `<span class="mono">#${item.id}</span>`).join("");

  let note = "";
  if (anomaly && Number.isFinite(anomaly.metric_value) && baseline != null) {
    note = drop
      ? `<p class="trend-note" style="color:var(--red)">${(anomaly.metric_value * 100).toFixed(1)}% below the average of the last healthy runs (limit ${(anomaly.threshold * 100).toFixed(0)}%).</p>`
      : `<p class="trend-note">Within ${(anomaly.threshold * 100).toFixed(0)}% of the average of the last healthy runs.</p>`;
  } else if (anomaly) {
    note = `<p class="trend-note">${esc(anomaly.message)}</p>`;
  }
  return `<div class="section"><h3>ROW COUNT VS. RECENT RUNS</h3>
    <div class="trend">${avg}${bars}</div><div class="trend-labels">${labels}</div>${note}</div>`;
}

function checksHtml(checks) {
  if (!checks.length) {
    return `<div class="section"><h3>QUALITY CHECKS</h3><p class="muted">No checks were recorded for this run.</p></div>`;
  }
  const items = checks.map((check, i) => {
    const tone = { FAIL: " failed", WARN: " warned" }[check.status] ?? "";
    const ratio = check.threshold > 0 && Number.isFinite(check.metric_value)
      ? Math.min(1, Math.max(0, check.metric_value) / (check.threshold * 2)) : null;
    const meter = ratio == null ? "" :
      `<div class="meter" title="The mark is the limit"><i data-width="${(ratio * 100).toFixed(1)}%"></i></div>`;
    return `<li class="check${tone}" style="animation-delay:${i * 50}ms">
      <div class="check-top"><span class="mono">${esc(check.check_name)}</span>
        <span><span class="check-metric">${esc(checkValue(check.check_name, check.metric_value))} / limit ${esc(checkValue(check.check_name, check.threshold))}</span> ${pill(check.status)}</span></div>
      ${meter}<p class="check-msg">${esc(check.message)}</p></li>`;
  }).join("");
  return `<div class="section"><h3>QUALITY CHECKS</h3><ul class="checks">${items}</ul></div>`;
}

function errorHtml(run) {
  return `<div class="section"><h3>ERROR</h3><div class="error-box"><code>${esc(run.error_type ?? "Error")}</code>${esc(run.error_message ?? "The run failed.")}</div></div>`;
}

function analysisHtml(run, analysis) {
  if (!analysis) {
    const running = run.status === "RUNNING";
    return `<h3>INCIDENT ANALYSIS</h3><div class="analysis analysis-empty">
      <span>${running ? "This run is still in progress." : "Not analyzed yet."}</span>
      <button class="button secondary small" id="analyze-button" type="button"${running ? " disabled" : ""}>Analyze run</button></div>`;
  }
  const list = (items) => (items.length ? `<ul>${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>` : "");
  const tone = { high: "bad", medium: "warn", low: "ok" }[analysis.severity] ?? "";
  return `<h3>INCIDENT ANALYSIS</h3><div class="analysis sev-${esc(analysis.severity)}">
    <div class="analysis-top"><span class="pill ${tone}">Severity: ${esc(analysis.severity)}</span></div>
    <p>${esc(analysis.summary)}</p>
    ${analysis.likely_causes.length ? `<strong>Likely causes</strong>${list(analysis.likely_causes)}` : ""}
    <strong>Recommended steps</strong>${list(analysis.recommended_steps)}
    <small>${esc(analysis.model_name)} · ${esc(fullTime(analysis.created_at))}</small></div>`;
}

function bindAnalyze(run) {
  const button = $("analyze-button");
  if (!button) return;
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.classList.add("busy");
    button.textContent = "Analyzing";
    try {
      const analysis = await api(`/runs/${run.id}/analyze`, { method: "POST" });
      if (state.selectedId !== run.id) return;
      const slot = $("analysis-slot");
      slot.innerHTML = analysisHtml(run, analysis);
      slot.style.animation = "none";
      void slot.offsetWidth;
      slot.style.animation = "";
    } catch (error) {
      toast(`Couldn't analyze run #${run.id}: ${error.message}`, "bad");
      button.disabled = false;
      button.classList.remove("busy");
      button.textContent = "Analyze run";
    }
  });
}

/* ---------- demo + toast ---------- */

let toastTimer;
function toast(message, tone = "ok") {
  const el = $("toast");
  el.className = `toast ${tone}`;
  el.textContent = message;
  el.hidden = false;
  el.style.animation = "none";
  void el.offsetWidth;
  el.style.animation = "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4500);
}

async function runDemo(event) {
  event.preventDefault();
  if (state.busy) return;
  const scenario = new FormData(event.target).get("scenario");
  const button = $("demo-button");
  state.busy = true;
  button.disabled = true;
  button.classList.add("busy");
  button.textContent = "Running";
  try {
    const params = new URLSearchParams({
      simulate_failure: scenario === "pipeline_failure",
      data_scenario: scenario === "quality_issue" ? "quality_failure" : "normal",
    });
    const run = await api(`/runs/demo?${params}`, { method: "POST" });
    if (run.status === "FAILED") toast(`Run #${run.id} failed: ${run.error_message ?? "error"}`, "bad");
    else if (run.quality_status === "FAIL") toast(`Run #${run.id} succeeded, but a quality check failed`, "warn");
    else toast(`Run #${run.id} succeeded and passed its checks`, "ok");
    state.offset = 0;
    await loadRuns({ quiet: true, select: run.id });
  } catch (error) {
    toast(`Couldn't run the demo pipeline: ${error.message}`, "bad");
  } finally {
    state.busy = false;
    button.disabled = false;
    button.classList.remove("busy");
    button.textContent = "Run demo pipeline";
  }
}

/* ---------- wiring ---------- */

function bind() {
  $("demo-form").addEventListener("submit", runDemo);
  $("filters").addEventListener("change", (event) => {
    const key = { "filter-pipeline": "pipeline", "filter-status": "status", "filter-quality": "quality" }[event.target.id];
    if (!key) return;
    state.filters[key] = event.target.value;
    state.offset = 0;
    loadRuns();
  });
  $("prev-page").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - PAGE_SIZE);
    loadRuns();
  });
  $("next-page").addEventListener("click", () => {
    state.offset += PAGE_SIZE;
    loadRuns();
  });
  const list = $("run-list");
  list.addEventListener("click", (event) => {
    const row = event.target.closest(".run-row");
    if (row) selectRun(Number(row.dataset.id));
  });
  list.addEventListener("keydown", (event) => {
    const rows = [...list.querySelectorAll(".run-row")];
    const index = rows.findIndex((row) => Number(row.dataset.id) === state.selectedId);
    const move = { ArrowDown: 1, ArrowUp: -1 }[event.key];
    if (move && rows.length) {
      event.preventDefault();
      const next = rows[Math.min(rows.length - 1, Math.max(0, index + move))];
      selectRun(Number(next.dataset.id), { focus: true });
    }
  });
  // Keep the list current without a reload; new runs flash as they appear.
  setInterval(() => {
    if (document.visibilityState === "visible" && !state.busy) loadRuns({ quiet: true });
  }, REFRESH_MS);
}

async function start() {
  bind();
  showSkeleton();
  await checkHealth();
  const linked = Number(/^#run-(\d+)$/.exec(location.hash)?.[1]);
  await loadRuns({ select: linked || null });
  // Fill the pipeline filter with every pipeline, not just those on the first page.
  api("/runs/page?limit=200").then((page) => addPipelines(page.items)).catch(() => {});
}

start();
