# Project File Comments

This file collects short comments describing the purpose of each project file. It documents the current project inventory; it does not add comments inside the source or data files.

## Project Overview and Analysis

- `README.md` - Explains the ShopSphere scenario, source data, investigation tasks, and suggested deliverables.
- `PROJECT_FILE_GUIDE.md` - Collects concise descriptions of every authored project file in one place.
- `CASE_STUDY.md` - Defines the incident case study and the investigation context for the synthetic logs.
- `INSTRUCTOR_ANSWER_KEY.md` - Contains the instructor-only reference findings and expected conclusions.
- `analysis.py` - Provides a standard-library starter script for request totals, status rates, latency percentiles, and five-minute summaries.
- `generate_logs.py` - Deterministically generates the synthetic requests, application logs, and infrastructure metrics.
- `src/log_analyzer.py` - Loads and validates input data, calculates log/request/metric analyses, and generates report tables and charts.
- `src/generate_project_report.py` - Builds a detailed PDF report from the RCA, analysis tables, and charts.
- `tests/test_log_analyzer.py` - Checks data totals, error counting, UTC time windows, metric joins, trace evidence, and chart generation.

## Source Data

- `requests.csv` - Request-level records; one row per trace, used for request counts, status rates, and latency calculations.
- `application_logs.csv` - Tabular application log events, including service, trace, status, error, and event details.
- `application_logs.jsonl` - The same application log events in newline-delimited JSON format.
- `metrics.csv` - Five-minute infrastructure and dependency measurements by region.

## Reports and Analysis Outputs

- `reports/INCIDENT_RCA.md` - Written root-cause analysis with impact, timeline, evidence, limitations, and remediation actions.
- `reports/SHOPSPHERE_PROJECT_REPORT.pdf` - Formatted PDF version of the project investigation report.
- `reports/summary.json` - Machine-readable summary of headline counts, rates, validation findings, and generated artifacts.
- `reports/http_status.csv` - Request counts and percentages grouped by HTTP status.
- `reports/error_codes.csv` - Request-level counts and rates grouped by error code.
- `reports/latency.csv` - Request latency percentiles grouped overall, by region, endpoint, and region plus endpoint.
- `reports/time_windows.csv` - Five-minute request counts, 4xx/5xx rates, latency percentiles, and anomaly comparisons.
- `reports/worst_intervals.csv` - Highest-ranked overall five-minute intervals by 5xx rate and impact.
- `reports/onset_evidence.csv` - Request-level examples supporting the detected start of sustained 5xx elevation.
- `reports/metric_join.csv` - Time-window request results joined to regional infrastructure metrics.
- `reports/services.csv` - Service log volumes, error event counts, unique error traces, and HTTP error events.
- `reports/log_error_codes.csv` - ERROR log counts and unique affected traces grouped by error code.
- `reports/log_dimensions.csv` - Log event and unique trace counts across service, region, event, level, and error code.
- `reports/service_region_errors.csv` - ERROR log entries and unique affected traces grouped by service and region.
- `reports/validation.csv` - Data quality checks for required fields, timestamps, IDs, statuses, latencies, and metric values.

## Charts

- `charts/error_timeline.png` - Five-minute 4xx/5xx request rates, baseline and threshold, incident onset, and p95 latency.
- `charts/service_region_error_heatmap.png` - Heatmap of unique traces with ERROR logs by service and region.

## Supporting Documents

- `Manual analysis.docx` - Word document containing manual investigation notes.
- `Copilot analysis.docx` - Word document containing a separate analysis write-up.