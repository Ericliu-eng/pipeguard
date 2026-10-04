import math
import os
from typing import Any

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.getenv(
    "API_BASE_URL",
    "http://127.0.0.1:8000",
)


st.set_page_config(
    page_title="PipeGuard",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ PipeGuard")
st.subheader("Data Pipeline Monitoring Dashboard")


def analyze_run(run_id: int) -> dict[str, Any] | None:
    try:
        response = requests.post(
            f"{API_BASE_URL}/runs/{run_id}/analyze",
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as exc:
        st.error(f"Failed to analyze pipeline run: {exc}")
        return None


# Streamlit reruns this whole script on every interaction, so the read endpoints are
# cached briefly to avoid refetching unchanged history. Triggering a run clears the
# cache, so the TTL only bounds how long a run started elsewhere stays invisible.
# Only successful calls are cached: an exception propagates and is rendered by the
# caller, so a transient API outage is retried on the next rerun instead of being
# cached as an empty result.
CACHE_TTL_SECONDS = 30


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_runs(
    pipeline_name: str | None,
    run_status: str | None,
    quality_status: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    params: dict[str, str | int] = {"limit": limit, "offset": offset}
    if pipeline_name:
        params["pipeline_name"] = pipeline_name
    if run_status:
        params["status"] = run_status
    if quality_status:
        params["quality_status"] = quality_status

    response = requests.get(
        f"{API_BASE_URL}/runs/page",
        params=params,
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()

    if (
        not isinstance(data, dict)
        or not isinstance(data.get("items"), list)
        or not isinstance(data.get("total"), int)
        or not isinstance(data.get("limit"), int)
        or not isinstance(data.get("offset"), int)
        or not isinstance(data.get("has_more"), bool)
        or not isinstance(data.get("summary"), dict)
    ):
        raise ValueError("Unexpected response format from GET /runs/page.")

    return data


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_run_analysis(run_id: int) -> dict[str, Any] | None:
    response = requests.get(
        f"{API_BASE_URL}/runs/{run_id}/analysis",
        timeout=10,
    )

    if response.status_code == 404:
        return None

    response.raise_for_status()

    return response.json()


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_run_checks(run_id: int) -> list[dict[str, Any]]:
    response = requests.get(
        f"{API_BASE_URL}/runs/{run_id}/checks",
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        raise ValueError("Unexpected response format from checks API.")

    return data


def clear_run_caches() -> None:
    fetch_runs.clear()
    fetch_run_checks.clear()
    fetch_run_analysis.clear()


def get_stored_analysis(run_id: int) -> dict[str, Any] | None:
    try:
        return fetch_run_analysis(run_id)

    except requests.exceptions.RequestException as exc:
        st.error(f"Failed to load incident analysis: {exc}")
        return None


def get_runs(
    pipeline_name: str | None,
    run_status: str | None,
    quality_status: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any] | None:
    try:
        return fetch_runs(
            pipeline_name,
            run_status,
            quality_status,
            limit,
            offset,
        )

    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to the FastAPI backend.")
        return None

    except (requests.exceptions.RequestException, ValueError) as exc:
        st.error(f"Failed to load pipeline runs: {exc}")
        return None


def get_run_checks(run_id: int) -> list[dict[str, Any]]:
    try:
        return fetch_run_checks(run_id)

    except (requests.exceptions.RequestException, ValueError) as exc:
        st.error(f"Failed to load quality checks: {exc}")
        return []


def trigger_demo_run(scenario: str) -> dict[str, Any] | None:
    try:
        params = {
            "simulate_failure": scenario == "pipeline_failure",
            "data_scenario": ("quality_failure" if scenario == "quality_issue" else "normal"),
        }
        response = requests.post(
            f"{API_BASE_URL}/runs/demo",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as exc:
        st.error(f"Failed to trigger demo pipeline: {exc}")
        return None


def reset_run_page() -> None:
    st.session_state["runs_offset"] = 0


def reset_run_filters() -> None:
    st.session_state["run_filter_pipeline"] = ""
    st.session_state["run_filter_status"] = "ALL"
    st.session_state["run_filter_quality"] = "ALL"
    reset_run_page()


def previous_run_page(page_size: int) -> None:
    st.session_state["runs_offset"] = max(
        0,
        st.session_state["runs_offset"] - page_size,
    )


def next_run_page(page_size: int) -> None:
    st.session_state["runs_offset"] += page_size


st.session_state.setdefault("runs_offset", 0)


st.subheader("Run Demo Pipeline")

scenario = st.selectbox(
    "Select a demo scenario",
    options=["normal", "pipeline_failure", "quality_issue"],
)

if st.button("Run Pipeline"):
    result = trigger_demo_run(scenario)

    if result is not None:
        if result["status"] == "FAILED":
            st.error("Demo pipeline failed. Select the run below to inspect it.")
        elif result["quality_status"] == "FAIL":
            st.warning("Demo pipeline completed with data-quality failures.")
        else:
            st.success("Demo pipeline completed successfully.")
        clear_run_caches()
        reset_run_page()
        st.rerun()

st.subheader("Run History")

filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2, 1, 1, 1])
pipeline_filter = filter_col1.text_input(
    "Pipeline (exact match)",
    key="run_filter_pipeline",
    on_change=reset_run_page,
)
status_filter = filter_col2.selectbox(
    "Execution Status",
    options=["ALL", "RUNNING", "SUCCESS", "FAILED"],
    key="run_filter_status",
    on_change=reset_run_page,
)
quality_filter = filter_col3.selectbox(
    "Quality Status",
    options=["ALL", "NOT_EVALUATED", "PASS", "WARN", "FAIL"],
    key="run_filter_quality",
    on_change=reset_run_page,
)
page_size = filter_col4.selectbox(
    "Page Size",
    options=[10, 25, 50, 100],
    index=2,
    key="run_page_size",
    on_change=reset_run_page,
)
st.button("Reset Filters", on_click=reset_run_filters)

active_pipeline_filter = pipeline_filter if pipeline_filter.strip() else None
active_status_filter = None if status_filter == "ALL" else status_filter
active_quality_filter = None if quality_filter == "ALL" else quality_filter
offset = st.session_state["runs_offset"]

runs_page = get_runs(
    active_pipeline_filter,
    active_status_filter,
    active_quality_filter,
    page_size,
    offset,
)

if runs_page is not None:
    runs = runs_page["items"]
    total_runs = runs_page["total"]
    summary = runs_page["summary"]

    # Retention can remove older rows while a user is viewing the last page.
    # Move back to the new last page instead of presenting a misleading empty page.
    if total_runs > 0 and offset >= total_runs:
        st.session_state["runs_offset"] = ((total_runs - 1) // page_size) * page_size
        st.rerun()

    filters_active = any([active_pipeline_filter, active_status_filter, active_quality_filter])

    if total_runs > 0 and not runs:
        st.warning("This page changed while it was loading. Reset the page or refresh to retry.")
    elif total_runs == 0:
        if filters_active:
            st.info("No runs match the current filters.")
        else:
            st.warning("No pipeline runs found.")
    else:
        success_rate = summary["successful"] / total_runs * 100
        col1, col2, col3, col4, col5 = st.columns(5)

        col1.metric("Matching Runs" if filters_active else "Total Runs", total_runs)
        col2.metric("Success Rate", f"{success_rate:.1f}%")
        col3.metric("Successful Runs", summary["successful"])
        col4.metric("Failed Runs", summary["failed"])
        col5.metric("Quality Incidents", summary["quality_incidents"])

        runs_df = pd.DataFrame(runs)
        st.dataframe(
            runs_df,
            width="stretch",
            hide_index=True,
        )

        page_number = offset // page_size + 1
        page_count = max(1, math.ceil(total_runs / page_size))
        first_visible = offset + 1
        last_visible = offset + len(runs)
        previous_col, page_col, next_col = st.columns([1, 3, 1])
        previous_col.button(
            "Previous",
            disabled=offset == 0,
            on_click=previous_run_page,
            args=(page_size,),
            width="stretch",
        )
        page_col.caption(
            f"Page {page_number} of {page_count} · "
            f"showing {first_visible}–{last_visible} of {total_runs}"
        )
        next_col.button(
            "Next",
            disabled=not runs_page["has_more"],
            on_click=next_run_page,
            args=(page_size,),
            width="stretch",
        )

        st.subheader("Quality Check Details")

        run_ids = [run["id"] for run in runs]
        runs_by_id = {run["id"]: run for run in runs}
        if st.session_state.get("selected_run_id") not in run_ids:
            st.session_state["selected_run_id"] = run_ids[0]

        def format_run(run_id: int) -> str:
            run = runs_by_id[run_id]
            started_at = run["started_at"].replace("T", " ")[:16]
            return f"#{run_id} · {run['pipeline_name']} · {run['status']} · {started_at}"

        selected_run_id = st.selectbox(
            "Select a pipeline run",
            options=run_ids,
            key="selected_run_id",
            format_func=format_run,
        )

        checks = get_run_checks(selected_run_id)

        if not checks:
            st.info("No quality checks found for this run.")
        else:
            checks_df = pd.DataFrame(checks)

            check_status_series = checks_df["status"].astype(str).str.upper()

            passed_checks = (check_status_series == "PASS").sum()
            warned_checks = (check_status_series == "WARN").sum()
            failed_checks = (check_status_series == "FAIL").sum()

            check_col1, check_col2, check_col3 = st.columns(3)

            check_col1.metric("Passed Checks", int(passed_checks))
            check_col2.metric("Warning Checks", int(warned_checks))
            check_col3.metric("Failed Checks", int(failed_checks))

            st.dataframe(
                checks_df,
                width="stretch",
                hide_index=True,
            )

        # Execution failures do not have quality checks, but they are the runs that
        # most need incident analysis. Keep this section independent of check data.
        st.subheader("Incident Analysis")

        analysis = get_stored_analysis(selected_run_id)
        selected_run_is_running = runs_by_id[selected_run_id]["status"] == "RUNNING"

        if selected_run_is_running:
            st.info("This run is still in progress and cannot be analyzed yet.")

        if st.button("Analyze Selected Run", disabled=selected_run_is_running):
            created = analyze_run(selected_run_id)

            if created is not None:
                analysis = created
                fetch_run_analysis.clear()
                st.success("Incident analysis completed.")

        if analysis is None:
            st.info("This run has not been analyzed yet.")
        else:
            st.write("**Severity:**", analysis["severity"])
            st.write("**Summary:**", analysis["summary"])
            st.write("**Likely Causes:**")
            for cause in analysis["likely_causes"]:
                st.write(f"- {cause}")

            st.write("**Recommended Steps:**")
            for step in analysis["recommended_steps"]:
                st.write(f"- {step}")
            st.write("**Analysis Model:**", analysis["model_name"])
