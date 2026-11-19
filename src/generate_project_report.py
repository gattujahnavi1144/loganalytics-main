"""Generate a detailed, standalone ShopSphere project report PDF."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Iterable

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"
CHARTS_DIR = PROJECT_ROOT / "charts"
OUTPUT_PATH = REPORTS_DIR / "SHOPSPHERE_PROJECT_REPORT.pdf"


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="CoverTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=26,
            leading=32,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#17324D"),
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CoverSubTitle",
            parent=styles["Normal"],
            fontSize=12,
            leading=18,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#435466"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading1"],
            fontSize=17,
            leading=21,
            textColor=colors.HexColor("#17324D"),
            spaceBefore=12,
            spaceAfter=8,
            keepWithNext=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubSectionHeading",
            parent=styles["Heading2"],
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#236B73"),
            spaceBefore=9,
            spaceAfter=5,
            keepWithNext=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyCompact",
            parent=styles["BodyText"],
            fontSize=8.5,
            leading=12,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BulletCompact",
            parent=styles["BodyCompact"],
            leftIndent=14,
            firstLineIndent=-8,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableText",
            parent=styles["BodyText"],
            fontSize=7,
            leading=9,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SmallNote",
            parent=styles["BodyText"],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#435466"),
        )
    )
    return styles


def inline_markup(text: str) -> str:
    value = escape(text, quote=False)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', value)
    return value


def parse_markdown(markdown: str, styles) -> list:
    """Convert the report's headings, paragraphs, lists, and pipe tables."""
    lines = markdown.splitlines()
    story: list = []
    paragraph_lines: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph_lines:
            text = " ".join(part.strip() for part in paragraph_lines)
            story.append(Paragraph(inline_markup(text), styles["BodyCompact"]))
            paragraph_lines.clear()

    while index < len(lines):
        line = lines[index].strip()
        if not line:
            flush_paragraph()
            index += 1
            continue

        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            style = "SectionHeading" if level <= 2 else "SubSectionHeading"
            story.append(Paragraph(inline_markup(heading.group(2)), styles[style]))
            index += 1
            continue

        if line.startswith("|"):
            flush_paragraph()
            rows: list[list[str]] = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if cells and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
                    index += 1
                    continue
                rows.append(cells)
                index += 1
            if rows:
                story.append(make_markdown_table(rows, styles))
                story.append(Spacer(1, 7))
            continue

        if line.startswith("- "):
            flush_paragraph()
            items = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                item_text = lines[index].strip()[2:]
                items.append(ListItem(Paragraph(inline_markup(item_text), styles["BodyCompact"])))
                index += 1
            story.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    leftIndent=16,
                    bulletFontName="Helvetica",
                    bulletFontSize=7,
                    spaceAfter=5,
                )
            )
            continue

        numbered = re.match(r"^(\d+)\.\s+(.*)$", line)
        if numbered:
            flush_paragraph()
            items = []
            while index < len(lines):
                match = re.match(r"^\s*(\d+)\.\s+(.*)$", lines[index])
                if not match:
                    break
                items.append(
                    ListItem(
                        Paragraph(inline_markup(match.group(2)), styles["BodyCompact"]),
                        value=int(match.group(1)),
                    )
                )
                index += 1
            story.append(
                ListFlowable(
                    items,
                    bulletType="1",
                    leftIndent=20,
                    bulletFontName="Helvetica",
                    bulletFontSize=8,
                    spaceAfter=5,
                )
            )
            continue

        paragraph_lines.append(line)
        index += 1

    flush_paragraph()
    return story


def make_markdown_table(rows: list[list[str]], styles) -> Table:
    column_count = max(len(row) for row in rows)
    normalized = [row + [""] * (column_count - len(row)) for row in rows]
    cells = [
        [Paragraph(inline_markup(str(value)), styles["TableText"]) for value in row]
        for row in normalized
    ]
    usable_width = letter[0] - 1.2 * inch
    if column_count == 3:
        widths = [0.95 * inch, 1.75 * inch, usable_width - 2.7 * inch]
    elif column_count == 4:
        widths = [1.0 * inch, 1.1 * inch, 1.1 * inch, usable_width - 3.2 * inch]
    else:
        widths = [usable_width / column_count] * column_count
    table = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C7D0D9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F7")]),
            ]
        )
    )
    return table


def dataframe_table(frame: pd.DataFrame, styles, max_rows: int | None = None) -> Table:
    shown = frame.head(max_rows) if max_rows else frame
    headers = [str(column) for column in shown.columns]
    rows = [headers] + shown.astype(object).where(pd.notna(shown), "").values.tolist()
    text_rows = [[str(value) for value in row] for row in rows]
    return make_markdown_table(text_rows, styles)


def image_flowable(path: Path, max_width: float, max_height: float) -> Image:
    image = Image(str(path))
    scale = min(max_width / image.imageWidth, max_height / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    image.hAlign = "CENTER"
    return image


def add_page_number(canvas, document) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D5DDE5"))
    canvas.line(0.6 * inch, 0.55 * inch, letter[0] - 0.6 * inch, 0.55 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#596A79"))
    canvas.drawString(0.65 * inch, 0.36 * inch, "ShopSphere production support analysis")
    canvas.drawRightString(letter[0] - 0.65 * inch, 0.36 * inch, f"Page {document.page}")
    canvas.restoreState()


def build_appendices(story: list, styles) -> None:
    story.extend([PageBreak(), Paragraph("Project Method and Evidence Appendices", styles["SectionHeading"])])
    overview = [
        ["Area", "What was done"],
        ["Inputs", "Read requests.csv, application_logs.csv, and metrics.csv. Source data was not modified."],
        ["Time handling", "Parsed timestamps as UTC and floored requests/metrics into five-minute windows."],
        ["Request grain", "Used requests.csv for HTTP status denominators and request-level error rates."],
        ["Trace handling", "Reported log-event counts separately from unique trace counts to avoid counting propagated gateway errors as extra failed requests."],
        ["Metrics join", "Joined infrastructure samples to request windows by aligned UTC timestamp and region; regional samples remain separate."],
        ["Validation", "Checked required fields, parseable timestamps, duplicate/missing request trace IDs, status ranges, and non-negative numeric values."],
        ["Tests", "Seven pytest checks cover source totals, request error codes, log-vs-trace counts, UTC bucketing, metric joins, trace-backed RCA evidence, and chart inputs/output."],
    ]
    story.append(make_markdown_table(overview, styles))
    story.append(Spacer(1, 10))

    table_specs = [
        ("HTTP Status Distribution", "http_status.csv", None),
        ("Request-Level Error Codes", "error_codes.csv", None),
        ("Service ERROR Summary", "services.csv", None),
        ("Ranked Log Error Codes", "log_error_codes.csv", None),
        ("Ten Worst Five-Minute Intervals", "worst_intervals.csv", 10),
        ("Data Validation Results", "validation.csv", None),
    ]
    for title, filename, max_rows in table_specs:
        path = REPORTS_DIR / filename
        if not path.exists():
            continue
        story.append(Paragraph(title, styles["SubSectionHeading"]))
        story.append(dataframe_table(pd.read_csv(path), styles, max_rows=max_rows))
        story.append(Spacer(1, 10))

    metric_path = REPORTS_DIR / "metric_join.csv"
    if metric_path.exists():
        metrics = pd.read_csv(metric_path, parse_dates=["window_start"])
        timestamps = pd.to_datetime(
            [
                "2026-11-18T10:45:00Z",
                "2026-11-18T11:25:00Z",
                "2026-11-18T11:45:00Z",
                "2026-11-18T12:00:00Z",
                "2026-11-18T12:45:00Z",
            ],
            utc=True,
        )
        sample = metrics.loc[
            metrics["region"].ne("ALL") & metrics["window_start"].isin(timestamps),
            [
                "window_start", "region", "request_count", "requests_5xx",
                "5xx_rate_pct", "db_pool_active", "provider_p95_ms",
                "queue_lag_messages", "heap_used_pct",
            ],
        ]
        story.append(Paragraph("Selected Aligned Metric Windows", styles["SubSectionHeading"]))
        story.append(dataframe_table(sample, styles))
        story.append(Spacer(1, 10))

    for title, chart_path, note in (
        (
            "Five-Minute Request Failure Timeline",
            CHARTS_DIR / "error_timeline.png",
            "Shows request-level 4xx/5xx rates and p95 latency, with the first-hour baseline, anomaly threshold, and detected sustained increase.",
        ),
        (
            "Service-Region ERROR Heatmap",
            CHARTS_DIR / "service_region_error_heatmap.png",
            "Cells show unique traces with ERROR logs per service and region. A trace can appear under multiple services, so do not sum cells as unique failed requests.",
        ),
    ):
        if chart_path.exists():
            story.append(PageBreak())
            story.append(Paragraph(title, styles["SectionHeading"]))
            story.append(Paragraph(escape(note), styles["SmallNote"]))
            story.append(Spacer(1, 10))
            story.append(image_flowable(chart_path, letter[0] - 1.4 * inch, 6.3 * inch))


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    rca_path = REPORTS_DIR / "INCIDENT_RCA.md"
    if not rca_path.exists():
        raise FileNotFoundError(f"Missing RCA source: {rca_path}")

    styles = build_styles()
    story: list = [
        Spacer(1, 1.45 * inch),
        Paragraph("ShopSphere", styles["CoverTitle"]),
        Paragraph("Production Support Incident Analysis", styles["CoverSubTitle"]),
        Paragraph("Detailed report | Incident window: 2026-11-18 09:00-13:00 UTC", styles["CoverSubTitle"]),
        Spacer(1, 0.25 * inch),
        Paragraph(
            "Request outcomes, distributed logs, infrastructure metrics, incident evidence, and response recommendations.",
            styles["CoverSubTitle"],
        ),
        Spacer(1, 0.35 * inch),
        Paragraph(
            f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | Synthetic teaching dataset",
            styles["SmallNote"],
        ),
        PageBreak(),
        Paragraph("How to Read This Report", styles["SectionHeading"]),
        Paragraph(
            "This report separates request-level impact from service log events. A single request can create multiple log records, including a downstream service error and a gateway response. Request failure rates therefore use requests.csv; trace IDs connect related service logs; infrastructure metrics are aligned by five-minute UTC window and region.",
            styles["BodyCompact"],
        ),
        Paragraph(
            "Evidence is labeled as verified when directly present in the records. Explanations that the data cannot prove are called out as hypotheses or limitations. The dataset is synthetic and should not be used to infer real customer or infrastructure impact.",
            styles["BodyCompact"],
        ),
        PageBreak(),
    ]
    story.extend(parse_markdown(rca_path.read_text(encoding="utf-8"), styles))
    build_appendices(story, styles)

    document = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=letter,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.62 * inch,
        bottomMargin=0.72 * inch,
        title="ShopSphere Production Support Incident Analysis",
        author="ShopSphere Production Support",
        subject="Request, log, and infrastructure metric RCA",
    )
    document.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"PDF written to: {OUTPUT_PATH}")
    print(f"Size: {OUTPUT_PATH.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()