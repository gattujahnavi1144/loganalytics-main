import json

import pandas as pd
import pytest

from src.log_analyzer import (
    analyze_error_codes,
    analyze_http_status,
    analyze_service_region_errors,
    analyze_services,
    analyze_time_windows,
    generate_error_timeline,
    generate_service_region_heatmap,
    join_request_metrics,
    load_data,
)


@pytest.fixture(scope="module")
def data():
    # Load the shared source datasets once for the module's report checks.
    return load_data()


def test_source_request_totals_and_rates_match_reports(data):
    requests = data["requests"]
    # Every source request has one distinct, non-null trace identifier.
    assert len(requests) == 12_000
    assert requests["trace_id"].nunique() == 12_000
    assert requests["trace_id"].isna().sum() == 0

    # Status buckets must preserve the report totals and overall 5xx rate.
    statuses = analyze_http_status(requests).set_index("status")
    assert statuses.loc["200", "request_count"] == 10_265
    assert statuses.loc["401", "request_count"] == 201
    assert statuses.loc["409", "request_count"] == 387
    assert statuses.loc["500", "request_count"] == 657
    assert statuses.loc["503", "request_count"] == 311
    assert statuses.loc["504", "request_count"] == 179
    assert statuses["request_count"].sum() == 12_000
    five_xx_count = statuses.loc[["500", "503", "504"], "request_count"].sum()
    assert five_xx_count == 1_147
    assert round(100 * five_xx_count / len(requests), 4) == 9.5583


def test_request_error_codes_are_counted_once_per_trace(data):
    # Error summaries count affected requests, not repeated log events.
    errors = analyze_error_codes(data["requests"]).set_index("error_code")
    assert errors.loc["NULL_CUSTOMER_CONTEXT", "request_count"] == 460
    assert errors.loc["INVENTORY_DEADLOCK", "request_count"] == 387
    assert errors.loc["DB_POOL_EXHAUSTED", "request_count"] == 311
    assert errors.loc["PAYMENT_PROVIDER_TIMEOUT", "request_count"] == 179


def test_log_entries_and_unique_traces_are_not_interchangeable(data):
    # Repeated error events can outnumber the unique requests they represent.
    services = analyze_services(data["logs"]).set_index("service")
    assert services.loc["api-gateway", "error_log_events"] == 1_147
    assert services.loc["api-gateway", "unique_error_traces"] == 1_147

    log_errors = data["logs"].loc[data["logs"]["level"].eq("ERROR")]
    pool_errors = log_errors.loc[log_errors["error_code"].eq("DB_POOL_EXHAUSTED")]
    assert len(pool_errors) == 622
    assert pool_errors["trace_id"].nunique() == 311


def test_five_minute_buckets_use_utc_and_include_boundaries():
    # Equivalent offsets normalize to UTC; an exact 09:05 timestamp starts a new bucket.
    requests = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-11-18T09:00:00.001Z",
                    "2026-11-18T04:04:59.999-05:00",
                    "2026-11-18T09:05:00Z",
                    "2026-11-18T09:06:00Z",
                ],
                utc=True,
                format="mixed",
            ),
            "trace_id": ["a", "b", "c", "d"],
            "region": ["us-east-1"] * 4,
            "status": [200, 500, 409, 503],
            "latency_ms": [10, 100, 30, 50],
        }
    )

    windows = analyze_time_windows(requests)
    regional = windows.loc[windows["region"].eq("us-east-1")].set_index("window_start")
    first = pd.Timestamp("2026-11-18T09:00:00Z")
    second = pd.Timestamp("2026-11-18T09:05:00Z")
    assert regional.loc[first, "request_count"] == 2
    assert regional.loc[first, "requests_4xx"] == 0
    assert regional.loc[first, "requests_5xx"] == 1
    assert regional.loc[first, "5xx_rate_pct"] == 50.0
    assert regional.loc[first, "p95_latency_ms"] == 95.5
    assert regional.loc[second, "request_count"] == 2
    assert regional.loc[second, "requests_4xx"] == 1
    assert regional.loc[second, "requests_5xx"] == 1


def test_metric_join_matches_bucket_and_region_only():
    # Join metrics on normalized time bucket and region, keeping distinct metric names.
    windows = pd.DataFrame(
        {
            "window_start": pd.to_datetime(
                ["2026-11-18T09:00:00Z", "2026-11-18T09:00:00Z"], utc=True
            ),
            "region": ["us-east-1", "eu-west-1"],
            "request_count": [1, 1],
        }
    )
    metrics = pd.DataFrame(
        {
            "timestamp": [
                "2026-11-18T04:04:00-05:00",
                "2026-11-18T09:00:00Z",
                "2026-11-18T09:00:00Z",
            ],
            "region": ["us-east-1", "eu-west-1", "us-east-1"],
            "metric": ["db_pool_active", "db_pool_active", "provider_p95_ms"],
            "value": [30, 12, 4_500],
            "unit": ["connections", "connections", "milliseconds"],
        }
    )

    joined = join_request_metrics(windows, metrics).set_index("region")
    assert joined.loc["us-east-1", "db_pool_active"] == 30
    assert joined.loc["us-east-1", "provider_p95_ms"] == 4_500
    assert joined.loc["eu-west-1", "db_pool_active"] == 12
    assert pd.isna(joined.loc["eu-west-1", "provider_p95_ms"])


def test_trace_records_support_propagation_and_v28_context_finding(data):
    # A provider timeout should propagate through the payment and gateway events.
    requests = data["requests"].set_index("trace_id")
    logs = data["logs"]
    payment_trace = "41f4a967518b03f200b3b941c8dda779"
    payment_events = logs.loc[logs["trace_id"].eq(payment_trace)].sort_values("timestamp")
    assert requests.loc[payment_trace, "error_code"] == "PAYMENT_PROVIDER_TIMEOUT"
    assert payment_events.iloc[-2]["service"] == "payment-service"
    assert payment_events.iloc[-2]["error_code"] == "PAYMENT_PROVIDER_TIMEOUT"
    assert payment_events.iloc[-1]["service"] == "api-gateway"
    assert payment_events.iloc[-1]["error_code"] == "PAYMENT_PROVIDER_TIMEOUT"

    # The v2.8 auth trace retains the checkout context evidence in its details.
    context_trace = "724198908c1f0229b9ed1e1d7c15023b"
    context_events = logs.loc[logs["trace_id"].eq(context_trace)].sort_values("timestamp")
    assert requests.loc[context_trace, "version"] == "v2.8.0"
    auth_error = context_events.loc[
        context_events["service"].eq("auth-service")
        & context_events["error_code"].eq("NULL_CUSTOMER_CONTEXT")
    ].iloc[0]
    details = json.loads(auth_error["details"])
    assert details["feature_flag"] == "new-checkout-context"
    assert details["stack"] == "CheckoutContextResolver.resolve:118"


def test_heatmap_data_and_charts_support_reported_conclusions(data, tmp_path):
    # Check the regional hotspot and incident peak used by the report.
    regional = analyze_service_region_errors(data["logs"])
    gateway = regional.loc[regional["service"].eq("api-gateway")]
    assert gateway.sort_values("unique_affected_traces", ascending=False).iloc[0]["region"] == "us-east-1"
    assert int(gateway["unique_affected_traces"].sum()) == 1_147

    windows = analyze_time_windows(data["requests"])
    overall = windows.loc[windows["region"].eq("ALL")]
    peak = overall.loc[overall["5xx_rate_pct"].idxmax()]
    assert peak["window_start"] == pd.Timestamp("2026-11-18T12:00:00Z")
    assert peak["requests_5xx"] == 94
    assert peak["5xx_rate_pct"] == 37.6

    # Chart helpers should create non-empty output files at the requested paths.
    timeline = generate_error_timeline(
        windows,
        {"onset_window_start_utc": "2026-11-18T10:45:00+00:00"},
        tmp_path / "error_timeline.png",
    )
    heatmap = generate_service_region_heatmap(regional, tmp_path / "heatmap.png")
    assert timeline.is_file() and timeline.stat().st_size > 0
    assert heatmap.is_file() and heatmap.stat().st_size > 0