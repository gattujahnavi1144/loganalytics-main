"""Pandas-based analysis of ShopSphere request, log, and metric data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports"
DEFAULT_CHART_DIR = PROJECT_ROOT / "charts"


def _read_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(
            frame["timestamp"], utc=True, errors="coerce"
        )
    return frame


def load_data(data_dir: str | Path | None = None) -> dict[str, pd.DataFrame]:
    """Load the three source CSVs and normalize timestamps to UTC."""
    source_dir = Path(data_dir) if data_dir is not None else PROJECT_ROOT
    requests = _read_csv(source_dir / "requests.csv")
    logs = _read_csv(source_dir / "application_logs.csv")
    metrics = _read_csv(source_dir / "metrics.csv")

    for frame, columns in (
        (requests, ("status", "latency_ms")),
        (logs, ("http_status", "latency_ms")),
        (metrics, ("value",)),
    ):
        for column in columns:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

    return {"requests": requests, "logs": logs, "metrics": metrics}


def validate_data(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return validation checks; issue_count is zero when a check passes."""
    checks: list[dict[str, Any]] = []

    def record(name: str, count: int, details: str) -> None:
        checks.append({"check": name, "issue_count": int(count), "details": details})

    required = {
        "requests": ["timestamp", "trace_id", "status", "latency_ms"],
        "logs": ["timestamp", "service", "trace_id", "level"],
        "metrics": ["timestamp", "region", "service", "metric", "value"],
    }
    for name, columns in required.items():
        frame = data[name]
        missing_columns = [column for column in columns if column not in frame.columns]
        record(
            f"{name}_required_columns",
            len(missing_columns),
            f"Missing columns: {', '.join(missing_columns) or 'none'}",
        )
        if "timestamp" in frame.columns:
            record(
                f"{name}_invalid_timestamps",
                frame["timestamp"].isna().sum(),
                "Missing or unparsable timestamps",
            )

    requests = data["requests"]
    if "trace_id" in requests.columns:
        record(
            "requests_duplicate_trace_ids",
            requests["trace_id"].dropna().duplicated().sum(),
            "Excess request rows sharing a non-null trace_id",
        )
        record(
            "requests_missing_trace_ids",
            requests["trace_id"].isna().sum(),
            "Request rows without a trace_id",
        )
    if "status" in requests.columns:
        status = pd.to_numeric(requests["status"], errors="coerce")
        invalid_status = status.isna() | ~status.between(100, 599)
        record(
            "requests_invalid_statuses",
            invalid_status.sum(),
            "Status is missing, non-numeric, or outside HTTP 100-599",
        )
    if "latency_ms" in requests.columns:
        latency = pd.to_numeric(requests["latency_ms"], errors="coerce")
        record(
            "requests_invalid_latency",
            (latency.isna() | (latency < 0)).sum(),
            "Latency is missing, non-numeric, or negative",
        )

    metrics = data["metrics"]
    if "value" in metrics.columns:
        value = pd.to_numeric(metrics["value"], errors="coerce")
        record(
            "metrics_invalid_values",
            (value.isna() | (value < 0)).sum(),
            "Metric value is missing, non-numeric, or negative",
        )

    return pd.DataFrame(checks)


def analyze_http_status(requests: pd.DataFrame) -> pd.DataFrame:
    """Summarize request-level HTTP statuses and their share of requests."""
    status = pd.to_numeric(requests["status"], errors="coerce")
    total = len(requests)
    counts = status.value_counts(dropna=False).sort_index(key=lambda values: values.fillna(0))
    rows = []
    for code, count in counts.items():
        if pd.isna(code):
            label = "invalid_or_missing"
            status_class = "invalid"
        else:
            label = str(int(code))
            status_class = f"{int(code) // 100}xx"
        rows.append(
            {
                "status": label,
                "status_class": status_class,
                "request_count": int(count),
                "request_rate_pct": round(100 * count / total, 4) if total else 0.0,
            }
        )
    return pd.DataFrame(rows)


def analyze_error_codes(requests: pd.DataFrame) -> pd.DataFrame:
    """Rank request-level error codes without counting service log duplicates."""
    frame = requests.copy()
    frame["status"] = pd.to_numeric(frame["status"], errors="coerce")
    frame["error_code"] = frame["error_code"].fillna("").astype("string").str.strip()
    frame = frame.loc[frame["error_code"].ne("")]
    if frame.empty:
        return pd.DataFrame(
            columns=["error_code", "request_count", "request_rate_pct", "statuses"]
        )

    grouped = frame.groupby("error_code", dropna=False)
    results = grouped.size().rename("request_count").to_frame()
    results["request_rate_pct"] = (100 * results["request_count"] / len(requests)).round(4)
    results["statuses"] = grouped["status"].apply(
        lambda values: ", ".join(
            f"{int(code)}:{int(count)}"
            for code, count in values.value_counts().sort_index().items()
            if pd.notna(code)
        )
    )
    return results.sort_values("request_count", ascending=False).reset_index()


def analyze_services(logs: pd.DataFrame) -> pd.DataFrame:
    """Summarize service log volume and error impact at event and trace grains."""
    frame = logs.copy()
    frame["level"] = frame["level"].fillna("").astype("string").str.upper()
    frame["http_status"] = pd.to_numeric(frame["http_status"], errors="coerce")
    error_logs = frame.loc[frame["level"].eq("ERROR")]
    error_events = error_logs.groupby("service", dropna=False).size().rename("error_log_events")
    unique_traces = (
        error_logs.groupby("service", dropna=False)["trace_id"]
        .nunique()
        .rename("unique_error_traces")
    )
    client_errors = (
        frame.loc[frame["http_status"].between(400, 499).fillna(False)]
        .groupby("service", dropna=False)
        .size()
        .rename("4xx_log_events")
    )
    server_errors = (
        frame.loc[frame["http_status"].between(500, 599).fillna(False)]
        .groupby("service", dropna=False)
        .size()
        .rename("5xx_log_events")
    )
    results = pd.concat(
        [
            frame.groupby("service", dropna=False).size().rename("log_events"),
            error_events,
            unique_traces,
            client_errors,
            server_errors,
        ],
        axis=1,
    ).fillna(0)
    return results.astype(
        {
            "log_events": "int64",
            "error_log_events": "int64",
            "unique_error_traces": "int64",
            "4xx_log_events": "int64",
            "5xx_log_events": "int64",
        }
    ).sort_values("error_log_events", ascending=False).reset_index()


def analyze_log_dimensions(logs: pd.DataFrame) -> pd.DataFrame:
    """Count log events and unique traces by service, region, event, level, and code."""
    dimensions = ["service", "region", "event", "level", "error_code"]
    frame = logs.copy()
    frame["level"] = frame["level"].fillna("<missing>").astype("string").str.upper()
    for column in dimensions:
        frame[column] = frame[column].fillna("<missing>").astype("string").str.strip()
        frame.loc[frame[column].eq(""), column] = "<missing>"
    return (
        frame.groupby(dimensions, dropna=False)
        .agg(
            log_event_count=("trace_id", "size"),
            unique_trace_count=("trace_id", "nunique"),
        )
        .reset_index()
        .sort_values("log_event_count", ascending=False)
        .reset_index(drop=True)
    )


def analyze_log_error_codes(logs: pd.DataFrame) -> pd.DataFrame:
    """Rank ERROR log codes by unique affected traces, then log event count."""
    frame = logs.copy()
    frame["level"] = frame["level"].fillna("").astype("string").str.upper()
    frame["error_code"] = frame["error_code"].fillna("").astype("string").str.strip()
    frame = frame.loc[frame["level"].eq("ERROR") & frame["error_code"].ne("")]
    columns = [
        "error_code", "error_log_entries", "unique_affected_traces",
        "services", "regions", "events",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for code, group in frame.groupby("error_code", dropna=False):
        rows.append(
            {
                "error_code": str(code),
                "error_log_entries": int(len(group)),
                "unique_affected_traces": int(group["trace_id"].nunique()),
                "services": ", ".join(sorted(group["service"].dropna().astype(str).unique())),
                "regions": ", ".join(sorted(group["region"].dropna().astype(str).unique())),
                "events": ", ".join(sorted(group["event"].dropna().astype(str).unique())),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["unique_affected_traces", "error_log_entries"], ascending=False
    ).reset_index(drop=True)


def analyze_service_region_errors(logs: pd.DataFrame) -> pd.DataFrame:
    """Summarize ERROR log entries and unique traces by service and region."""
    frame = logs.copy()
    frame["level"] = frame["level"].fillna("").astype("string").str.upper()
    errors = frame.loc[frame["level"].eq("ERROR")]
    return (
        errors.groupby(["service", "region"], dropna=False)
        .agg(
            error_log_entries=("trace_id", "size"),
            unique_affected_traces=("trace_id", "nunique"),
        )
        .reset_index()
        .sort_values("unique_affected_traces", ascending=False)
        .reset_index(drop=True)
    )


def generate_service_region_heatmap(
    service_region_errors: pd.DataFrame,
    chart_path: str | Path | None = None,
) -> Path:
    """Plot service versus region using unique ERROR trace counts."""
    output_path = (
        Path(chart_path)
        if chart_path
        else DEFAULT_CHART_DIR / "service_region_error_heatmap.png"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(9, 6), constrained_layout=True)
    if service_region_errors.empty:
        axis.text(0.5, 0.5, "No ERROR log entries", ha="center", va="center")
        axis.set_axis_off()
    else:
        matrix = service_region_errors.pivot(
            index="service", columns="region", values="unique_affected_traces"
        ).fillna(0)
        matrix = matrix.loc[matrix.sum(axis=1).sort_values(ascending=False).index]
        image = axis.imshow(matrix.to_numpy(), cmap="YlOrRd", aspect="auto")
        axis.set_xticks(range(len(matrix.columns)), labels=matrix.columns)
        axis.set_yticks(range(len(matrix.index)), labels=matrix.index)
        axis.set_xlabel("Region")
        axis.set_ylabel("Service")
        axis.set_title("Unique traces with ERROR logs by service and region")
        for row_index in range(matrix.shape[0]):
            for column_index in range(matrix.shape[1]):
                axis.text(
                    column_index,
                    row_index,
                    f"{int(matrix.iloc[row_index, column_index])}",
                    ha="center",
                    va="center",
                )
        figure.colorbar(image, ax=axis, label="Unique affected traces")
    figure.savefig(output_path, dpi=160)
    plt.close(figure)
    return output_path


def analyze_latency(requests: pd.DataFrame) -> pd.DataFrame:
    """Calculate request latency percentiles overall and by region/endpoint."""
    frame = requests.copy()
    frame["latency_ms"] = pd.to_numeric(frame["latency_ms"], errors="coerce")
    frame = frame.dropna(subset=["latency_ms"])
    groups: list[tuple[str, list[str]]] = [
        ("overall", []),
        ("region", ["region"]),
        ("endpoint", ["endpoint"]),
        ("region_endpoint", ["region", "endpoint"]),
    ]
    rows: list[dict[str, Any]] = []
    for group_name, columns in groups:
        group_iter = [((), frame)] if not columns else frame.groupby(columns, dropna=False)
        for keys, values in group_iter:
            if not isinstance(keys, tuple):
                keys = (keys,)
            row: dict[str, Any] = {
                "group_by": group_name,
                "region": "ALL",
                "endpoint": "ALL",
                "request_count": int(len(values)),
                "mean_latency_ms": round(float(values["latency_ms"].mean()), 2),
                "p50_latency_ms": round(float(values["latency_ms"].quantile(0.50)), 2),
                "p95_latency_ms": round(float(values["latency_ms"].quantile(0.95)), 2),
                "p99_latency_ms": round(float(values["latency_ms"].quantile(0.99)), 2),
                "max_latency_ms": float(values["latency_ms"].max()),
            }
            for column, value in zip(columns, keys):
                row[column] = value
            rows.append(row)
    return pd.DataFrame(rows)


def analyze_time_windows(
    requests: pd.DataFrame, frequency: str = "5min", baseline_minutes: int = 60
) -> pd.DataFrame:
    """Summarize request volume and compare five-minute rates to an initial baseline."""
    frame = requests.dropna(subset=["timestamp"]).copy()
    frame["status"] = pd.to_numeric(frame["status"], errors="coerce")
    frame["latency_ms"] = pd.to_numeric(frame["latency_ms"], errors="coerce")
    frame["window_start"] = frame["timestamp"].dt.floor(frequency)
    frame["is_4xx"] = frame["status"].between(400, 499).fillna(False)
    frame["is_5xx"] = frame["status"].between(500, 599).fillna(False)

    def summarize(group: pd.DataFrame) -> pd.DataFrame:
        result = (
            group.groupby(["window_start", "region"], dropna=False)
            .agg(
                request_count=("trace_id", "size"),
                requests_4xx=("is_4xx", "sum"),
                requests_5xx=("is_5xx", "sum"),
                p95_latency_ms=("latency_ms", lambda values: values.quantile(0.95)),
                p99_latency_ms=("latency_ms", lambda values: values.quantile(0.99)),
            )
            .reset_index()
        )
        result["5xx_rate_pct"] = (
            100 * result["requests_5xx"] / result["request_count"]
        ).round(4)
        result["p95_latency_ms"] = result["p95_latency_ms"].round(2)
        result["p99_latency_ms"] = result["p99_latency_ms"].round(2)
        return result

    regional = summarize(frame)
    overall_source = frame.assign(region="ALL")
    overall = summarize(overall_source)
    result = pd.concat([regional, overall], ignore_index=True).sort_values(
        ["window_start", "region"]
    ).reset_index(drop=True)
    result["baseline_5xx_rate_pct"] = float("nan")
    result["baseline_5xx_std_pct"] = float("nan")
    result["5xx_upper_threshold_pct"] = float("nan")
    result["5xx_rate_delta_pp"] = float("nan")
    result["is_5xx_anomaly"] = False

    for region in result["region"].dropna().unique():
        region_mask = result["region"].eq(region)
        region_rows = result.loc[region_mask].sort_values("window_start")
        if region_rows.empty:
            continue
        baseline_end = region_rows["window_start"].min() + pd.Timedelta(
            minutes=baseline_minutes
        )
        baseline_rows = region_rows.loc[region_rows["window_start"] < baseline_end]
        if baseline_rows.empty:
            continue
        baseline_mean = float(baseline_rows["5xx_rate_pct"].mean())
        baseline_std = float(baseline_rows["5xx_rate_pct"].std(ddof=0))
        upper_threshold = baseline_mean + 3 * baseline_std
        result.loc[region_mask, "baseline_5xx_rate_pct"] = baseline_mean
        result.loc[region_mask, "baseline_5xx_std_pct"] = baseline_std
        result.loc[region_mask, "5xx_upper_threshold_pct"] = upper_threshold
        result.loc[region_mask, "5xx_rate_delta_pp"] = (
            result.loc[region_mask, "5xx_rate_pct"] - baseline_mean
        )
        result.loc[region_mask, "is_5xx_anomaly"] = (
            result.loc[region_mask, "5xx_rate_pct"].gt(upper_threshold)
            & result.loc[region_mask, "requests_5xx"].ge(3)
        )

    for column in (
        "baseline_5xx_rate_pct",
        "baseline_5xx_std_pct",
        "5xx_upper_threshold_pct",
        "5xx_rate_delta_pp",
    ):
        result[column] = result[column].round(4)
    return result


def join_request_metrics(
    time_windows: pd.DataFrame,
    metrics: pd.DataFrame,
    frequency: str = "5min",
) -> pd.DataFrame:
    """Join regional request windows to metric samples on aligned UTC buckets."""
    metric_frame = metrics.copy()
    metric_frame["timestamp"] = pd.to_datetime(
        metric_frame["timestamp"], utc=True, errors="coerce"
    )
    metric_frame["value"] = pd.to_numeric(metric_frame["value"], errors="coerce")
    metric_frame = metric_frame.dropna(subset=["timestamp", "value"])
    metric_frame["window_start"] = metric_frame["timestamp"].dt.floor(frequency)
    metric_wide = (
        metric_frame.pivot_table(
            index=["window_start", "region"],
            columns="metric",
            values="value",
            aggfunc="mean",
        )
        .reset_index()
    )
    metric_wide.columns.name = None
    return time_windows.merge(
        metric_wide,
        on=["window_start", "region"],
        how="left",
        validate="many_to_one",
    )


def find_worst_intervals(
    time_windows: pd.DataFrame, limit: int = 10
) -> pd.DataFrame:
    """Rank overall five-minute intervals by 5xx rate, count, then p95 latency."""
    overall = time_windows.loc[time_windows["region"].eq("ALL")].copy()
    return overall.sort_values(
        ["5xx_rate_pct", "requests_5xx", "p95_latency_ms"],
        ascending=[False, False, False],
    ).head(limit).reset_index(drop=True)


def analyze_failure_onset(
    requests: pd.DataFrame,
    time_windows: pd.DataFrame,
    baseline_minutes: int = 60,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Find sustained aggregate 5xx elevation and return request-level evidence."""
    overall = time_windows.loc[time_windows["region"].eq("ALL")].sort_values(
        "window_start"
    ).reset_index(drop=True)
    if overall.empty:
        return {"onset_window_start_utc": None}, pd.DataFrame()

    anomalous = overall["is_5xx_anomaly"].tolist()
    sustained_index = next(
        (index for index in range(len(anomalous) - 1) if anomalous[index] and anomalous[index + 1]),
        None,
    )
    first_anomaly_index = next(
        (index for index, value in enumerate(anomalous) if value), None
    )
    onset_index = sustained_index if sustained_index is not None else first_anomaly_index
    onset_window = overall.iloc[onset_index] if onset_index is not None else None

    statuses = pd.to_numeric(requests["status"], errors="coerce")
    failed = requests.loc[statuses.between(500, 599).fillna(False)].copy()
    first_failure: dict[str, Any] | None = None
    evidence = pd.DataFrame()
    evidence_columns = [
        "timestamp", "trace_id", "region", "endpoint", "status",
        "latency_ms", "error_code", "version",
    ]
    if not failed.empty:
        failed = failed.sort_values("timestamp")
        first_record = failed.iloc[0]
        first_failure = {
            key: (value.isoformat() if isinstance(value, pd.Timestamp) else value)
            for key, value in first_record[evidence_columns].to_dict().items()
        }

    onset_time = onset_window["window_start"] if onset_window is not None else None
    if onset_time is not None:
        interval_end = onset_time + pd.Timedelta(minutes=5)
        evidence = failed.loc[
            failed["timestamp"].ge(onset_time) & failed["timestamp"].lt(interval_end),
            evidence_columns,
        ].head(10)

    baseline_end = overall["window_start"].min() + pd.Timedelta(minutes=baseline_minutes)
    baseline = overall.loc[overall["window_start"].lt(baseline_end)]
    baseline_mean = float(baseline["5xx_rate_pct"].mean()) if not baseline.empty else 0.0
    baseline_std = float(baseline["5xx_rate_pct"].std(ddof=0)) if not baseline.empty else 0.0
    evidence_records = evidence.astype(object).where(pd.notna(evidence), None).to_dict(
        orient="records"
    )
    for record in evidence_records:
        if isinstance(record.get("timestamp"), pd.Timestamp):
            record["timestamp"] = record["timestamp"].isoformat()
    summary: dict[str, Any] = {
        "baseline_start_utc": overall["window_start"].min().isoformat(),
        "baseline_end_utc_exclusive": baseline_end.isoformat(),
        "baseline_minutes": baseline_minutes,
        "baseline_5xx_rate_pct": round(baseline_mean, 4),
        "baseline_5xx_std_pct": round(baseline_std, 4),
        "5xx_upper_threshold_pct": round(baseline_mean + 3 * baseline_std, 4),
        "onset_rule": "First two consecutive five-minute intervals above baseline mean + 3 standard deviations, each with at least 3 5xx requests; fall back to the first qualifying interval if no pair exists.",
        "onset_window_start_utc": onset_time.isoformat() if onset_time is not None else None,
        "onset_window_5xx_count": int(onset_window["requests_5xx"]) if onset_window is not None else None,
        "onset_window_5xx_rate_pct": float(onset_window["5xx_rate_pct"]) if onset_window is not None else None,
        "first_5xx_request": first_failure,
        "onset_request_examples": evidence_records,
    }
    return summary, evidence


def generate_error_timeline(
    time_windows: pd.DataFrame,
    failure_summary: dict[str, Any],
    chart_path: str | Path | None = None,
) -> Path:
    """Save an aggregate request-level error-rate and p95 time-series chart."""
    output_path = Path(chart_path) if chart_path else DEFAULT_CHART_DIR / "error_timeline.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    overall = time_windows.loc[time_windows["region"].eq("ALL")].sort_values(
        "window_start"
    )

    figure, rate_axis = plt.subplots(figsize=(13, 6), constrained_layout=True)
    rate_axis.plot(
        overall["window_start"], overall["5xx_rate_pct"],
        color="#c0392b", linewidth=2, label="5xx rate",
    )
    rate_axis.plot(
        overall["window_start"],
        100 * overall["requests_4xx"] / overall["request_count"],
        color="#d68910", linewidth=1.2, alpha=0.8, label="4xx rate",
    )
    if not overall.empty:
        rate_axis.axhline(
            overall["baseline_5xx_rate_pct"].iloc[0],
            color="#2471a3", linestyle="--", linewidth=1.4,
            label="First-hour 5xx baseline",
        )
        rate_axis.axhline(
            overall["5xx_upper_threshold_pct"].iloc[0],
            color="#7d3c98", linestyle=":", linewidth=1.4,
            label="Baseline + 3 SD threshold",
        )
    onset = failure_summary.get("onset_window_start_utc")
    if onset:
        onset_time = pd.Timestamp(onset)
        rate_axis.axvline(onset_time, color="#17202a", linestyle="-.", linewidth=1.2)
        rate_axis.annotate(
            "Sustained increase",
            xy=(onset_time, rate_axis.get_ylim()[1]),
            xytext=(6, -18), textcoords="offset points", va="top",
        )
    rate_axis.set_title("ShopSphere API request failures by five-minute interval")
    rate_axis.set_xlabel("Timestamp (UTC)")
    rate_axis.set_ylabel("Request rate (%)")
    rate_axis.grid(True, axis="y", alpha=0.25)

    latency_axis = rate_axis.twinx()
    latency_axis.plot(
        overall["window_start"], overall["p95_latency_ms"],
        color="#117864", linewidth=1.2, alpha=0.75, label="p95 latency",
    )
    latency_axis.set_ylabel("p95 latency (ms)")
    handles1, labels1 = rate_axis.get_legend_handles_labels()
    handles2, labels2 = latency_axis.get_legend_handles_labels()
    rate_axis.legend(handles1 + handles2, labels1 + labels2, loc="upper left", ncol=2)

    figure.savefig(output_path, dpi=160)
    plt.close(figure)
    return output_path


def generate_summary(
    results: dict[str, pd.DataFrame],
    data: dict[str, pd.DataFrame],
    output_dir: str | Path | None = None,
    failure_summary: dict[str, Any] | None = None,
    chart_artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write analysis tables and a JSON summary to reports/ (never source CSVs)."""
    report_dir = Path(output_dir) if output_dir is not None else DEFAULT_REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in results.items():
        frame.to_csv(report_dir / f"{name}.csv", index=False)

    requests = data["requests"]
    statuses = pd.to_numeric(requests["status"], errors="coerce")
    total_requests = int(len(requests))
    five_xx_count = int(statuses.between(500, 599).fillna(False).sum())
    timestamps = requests["timestamp"].dropna()
    summary: dict[str, Any] = {
        "request_count": total_requests,
        "request_5xx_count": five_xx_count,
        "request_5xx_rate_pct": round(100 * five_xx_count / total_requests, 4)
        if total_requests
        else 0.0,
        "request_trace_id_unique_count": int(requests["trace_id"].nunique()),
        "regions": sorted(requests["region"].dropna().astype(str).unique().tolist()),
        "timestamp_start_utc": timestamps.min().isoformat() if not timestamps.empty else None,
        "timestamp_end_utc": timestamps.max().isoformat() if not timestamps.empty else None,
        "top_request_error_codes": results["error_codes"]
        .head(10)[["error_code", "request_count"]]
        .to_dict(orient="records"),
        "failure_timeline": failure_summary or {},
        "chart_artifacts": chart_artifacts or {},
        "reports_directory": str(report_dir),
    }
    with (report_dir / "summary.json").open("w", encoding="utf-8") as output:
        json.dump(summary, output, indent=2)
        output.write("\n")
    return summary


def main() -> None:
    data = load_data()
    requests = data["requests"]
    time_windows = analyze_time_windows(requests)
    failure_summary, onset_evidence = analyze_failure_onset(requests, time_windows)
    worst_intervals = find_worst_intervals(time_windows)
    chart_path = generate_error_timeline(time_windows, failure_summary)
    log_dimensions = analyze_log_dimensions(data["logs"])
    log_error_codes = analyze_log_error_codes(data["logs"])
    service_region_errors = analyze_service_region_errors(data["logs"])
    service_region_heatmap = generate_service_region_heatmap(service_region_errors)
    failure_summary["chart_path"] = str(chart_path)
    results = {
        "validation": validate_data(data),
        "http_status": analyze_http_status(requests),
        "error_codes": analyze_error_codes(requests),
        "services": analyze_services(data["logs"]),
        "latency": analyze_latency(requests),
        "time_windows": time_windows,
        "metric_join": join_request_metrics(time_windows, data["metrics"]),
        "worst_intervals": worst_intervals,
        "onset_evidence": onset_evidence,
        "log_dimensions": log_dimensions,
        "log_error_codes": log_error_codes,
        "service_region_errors": service_region_errors,
    }
    summary = generate_summary(
        results,
        data,
        failure_summary=failure_summary,
        chart_artifacts={
            "error_timeline": str(chart_path),
            "service_region_error_heatmap": str(service_region_heatmap),
        },
    )

    print(f"Analyzed {summary['request_count']:,} requests")
    print(
        "Request-level 5xx rate: "
        f"{summary['request_5xx_rate_pct']:.4f}% "
        f"({summary['request_5xx_count']:,} requests)"
    )
    print(f"Reports written to: {summary['reports_directory']}")
    print(f"Error timeline chart: {chart_path}")
    print(
        "First observed 5xx request: "
        f"{failure_summary.get('first_5xx_request')}"
    )
    onset = failure_summary.get("onset_window_start_utc")
    if onset:
        print(
            "Sustained 5xx increase begins: "
            f"{onset} ({failure_summary['onset_window_5xx_count']} requests, "
            f"{failure_summary['onset_window_5xx_rate_pct']:.4f}%; "
            f"baseline {failure_summary['baseline_5xx_rate_pct']:.4f}%, "
            f"threshold {failure_summary['5xx_upper_threshold_pct']:.4f}%)"
        )
        print("5xx request evidence in onset interval:")
        for record in failure_summary["onset_request_examples"][:5]:
            print(
                f"  {record['timestamp']} {record['region']} {record['endpoint']} "
                f"HTTP {record['status']} {record['error_code']} "
                f"trace_id={record['trace_id']}"
            )
    else:
        print("No sustained 5xx increase met the baseline threshold.")
    print("Ten worst five-minute intervals: reports/worst_intervals.csv")
    print(f"Service-region error heatmap: {service_region_heatmap}")
    print("Services with most ERROR log entries (event count / unique traces):")
    for row in results["services"].head(10).itertuples(index=False):
        print(
            f"  {row.service}: {row.error_log_events} / "
            f"{row.unique_error_traces}"
        )
    print("Ranked ERROR log codes (entries / unique traces):")
    for row in results["log_error_codes"].head(10).itertuples(index=False):
        print(
            f"  {row.error_code}: {row.error_log_entries} / "
            f"{row.unique_affected_traces}"
        )
    print("Validation issues:")
    issues = results["validation"].loc[results["validation"]["issue_count"] > 0]
    if issues.empty:
        print("  none")
    else:
        for row in issues.itertuples(index=False):
            print(f"  {row.check}: {row.issue_count} ({row.details})")


if __name__ == "__main__":
    main()