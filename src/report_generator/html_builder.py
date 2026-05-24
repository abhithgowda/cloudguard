"""CloudGuard Report Generator — pure HTML helpers.

Builds a single self-contained HTML document from findings + cost data +
remediation log. Inline CSS only — email clients strip <link> and many
strip non-trivial <style> blocks too, so styling is applied via the
`style=""` attribute on each element. Slightly verbose, maximally portable.

No I/O in this module. Every function takes its inputs as Python objects
(lists of dicts decoded from DynamoDB) and returns a string. STEP 15 unit
tests call these directly with synthetic data — no AWS, no mocks needed
beyond the dynamo Decimal type.
"""

from __future__ import annotations

import html
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

# Severity → (label colour, row tint). Ordered most-severe first so summary
# tiles and per-severity sections render in priority order.
SEVERITY_STYLE: dict[str, tuple[str, str]] = {
    "CRITICAL": ("#b91c1c", "#fee2e2"),  # red-700 / red-100
    "HIGH":     ("#c2410c", "#ffedd5"),  # orange-700 / orange-100
    "MEDIUM":   ("#a16207", "#fef9c3"),  # yellow-700 / yellow-100
    "LOW":      ("#1d4ed8", "#dbeafe"),  # blue-700 / blue-100
}
SEVERITY_ORDER = list(SEVERITY_STYLE.keys())

# Inline-style fragments reused throughout the document.
_BODY = "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1f2937;line-height:1.5;max-width:880px;margin:0 auto;padding:24px;"
_H1 = "font-size:24px;font-weight:700;margin:0 0 8px 0;color:#111827;"
_H2 = "font-size:18px;font-weight:600;margin:32px 0 12px 0;color:#111827;border-bottom:1px solid #e5e7eb;padding-bottom:6px;"
_MUTED = "color:#6b7280;font-size:13px;"
_TABLE = "width:100%;border-collapse:collapse;font-size:14px;margin:8px 0;"
_TH = "text-align:left;padding:8px 12px;background:#f3f4f6;border-bottom:1px solid #d1d5db;font-weight:600;"
_TD = "padding:8px 12px;border-bottom:1px solid #f3f4f6;vertical-align:top;"
_TILE = "display:inline-block;padding:12px 18px;margin:4px 8px 4px 0;border-radius:6px;background:#f9fafb;min-width:120px;"
_TILE_NUM = "font-size:22px;font-weight:700;display:block;"
_TILE_LBL = "font-size:11px;text-transform:uppercase;letter-spacing:0.05em;color:#6b7280;"


def _coerce_number(value: Any) -> float:
    """DynamoDB returns Decimals; templating + arithmetic want floats."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _badge(severity: str) -> str:
    fg, bg = SEVERITY_STYLE.get(severity, ("#374151", "#e5e7eb"))
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        f'background:{bg};color:{fg};font-size:11px;font-weight:600;'
        f'letter-spacing:0.03em;">{html.escape(severity)}</span>'
    )


def _executive_summary(
    findings: list[dict],
    cost_data: list[dict],
    remediations: list[dict],
) -> str:
    sev_counts = Counter(f.get("severity", "LOW") for f in findings)
    critical = sev_counts.get("CRITICAL", 0)
    high = sev_counts.get("HIGH", 0)
    total = len(findings)

    # Estimated savings = sum of monthly_cost_usd in cleanup-category findings.
    # Cleanup findings stamp this into the `metadata` map in STEP 12.
    estimated_savings = 0.0
    for f in findings:
        if f.get("category") == "cleanup":
            md = f.get("metadata") or {}
            estimated_savings += _coerce_number(md.get("monthly_cost_usd"))

    # Latest day's total spend across all services.
    today_total = 0.0
    if cost_data:
        latest_date = max(_safe_get(c, "date", "") for c in cost_data)
        today_total = sum(
            _coerce_number(c.get("unblended_cost"))
            for c in cost_data
            if _safe_get(c, "date", "") == latest_date
        )

    remediations_run = sum(
        1 for r in remediations if r.get("status") == "SUCCESS"
    )

    tiles = [
        ("Total findings", f"{total}"),
        ("Critical", f"{critical}"),
        ("High", f"{high}"),
        ("Est. monthly savings", f"${estimated_savings:,.2f}"),
        ("Latest daily spend", f"${today_total:,.2f}"),
        ("Auto-remediated", f"{remediations_run}"),
    ]
    tiles_html = "".join(
        f'<div style="{_TILE}">'
        f'<span style="{_TILE_NUM}">{html.escape(value)}</span>'
        f'<span style="{_TILE_LBL}">{html.escape(label)}</span>'
        f"</div>"
        for label, value in tiles
    )

    return f'<h2 style="{_H2}">Executive Summary</h2><div>{tiles_html}</div>'


def _cost_section(cost_data: list[dict]) -> str:
    if not cost_data:
        return (
            f'<h2 style="{_H2}">Cost Trend</h2>'
            f'<p style="{_MUTED}">No cost data available for this window.</p>'
        )

    # Pivot: rows = service, columns = sorted dates.
    by_service: dict[str, dict[str, float]] = defaultdict(dict)
    for row in cost_data:
        svc = row.get("service_name", "unknown")
        day = _safe_get(row, "date", "")
        by_service[svc][day] = _coerce_number(row.get("unblended_cost"))

    all_dates = sorted({d for s in by_service.values() for d in s.keys()})
    # Cap the table to the last 7 days so the email body stays readable.
    visible_dates = all_dates[-7:]
    # Sort services by latest-day spend descending; show top 10.
    latest = visible_dates[-1] if visible_dates else ""
    services_sorted = sorted(
        by_service.items(),
        key=lambda kv: kv[1].get(latest, 0.0),
        reverse=True,
    )[:10]

    header_cells = "".join(
        f'<th style="{_TH}">{html.escape(d)}</th>' for d in visible_dates
    )
    rows_html = []
    for svc, day_map in services_sorted:
        cells = []
        for d in visible_dates:
            v = day_map.get(d, 0.0)
            cells.append(f'<td style="{_TD};text-align:right;">${v:,.2f}</td>')
        rows_html.append(
            f'<tr><td style="{_TD};font-weight:500;">{html.escape(svc)}</td>'
            + "".join(cells)
            + "</tr>"
        )

    return (
        f'<h2 style="{_H2}">Cost Trend (top 10 services, last {len(visible_dates)} days)</h2>'
        f'<table style="{_TABLE}">'
        f'<thead><tr><th style="{_TH}">Service</th>{header_cells}</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody></table>'
    )


def _security_section(findings: list[dict]) -> str:
    sec = [f for f in findings if f.get("category") == "security"]
    cost = [f for f in findings if f.get("category") == "cost"]
    relevant = sec + cost

    if not relevant:
        return (
            f'<h2 style="{_H2}">Security &amp; Cost Findings</h2>'
            f'<p style="{_MUTED}">No security or cost findings in this window.</p>'
        )

    by_sev: dict[str, list[dict]] = defaultdict(list)
    for f in relevant:
        by_sev[f.get("severity", "LOW")].append(f)

    blocks = []
    for sev in SEVERITY_ORDER:
        items = by_sev.get(sev, [])
        if not items:
            continue
        rows = []
        for f in items:
            rows.append(
                f'<tr>'
                f'<td style="{_TD};width:96px;">{_badge(sev)}</td>'
                f'<td style="{_TD};font-family:ui-monospace,monospace;font-size:12px;">'
                f'{html.escape(str(f.get("resource_id", "—")))}</td>'
                f'<td style="{_TD}">{html.escape(str(f.get("description", "")))}'
                + (
                    f'<br><span style="{_MUTED}">→ {html.escape(str(f.get("recommendation", "")))}</span>'
                    if f.get("recommendation")
                    else ""
                )
                + "</td></tr>"
            )
        blocks.append(
            f'<h3 style="margin:20px 0 6px 0;font-size:15px;color:#111827;">'
            f'{sev} ({len(items)})</h3>'
            f'<table style="{_TABLE}"><tbody>{"".join(rows)}</tbody></table>'
        )

    return f'<h2 style="{_H2}">Security &amp; Cost Findings</h2>{"".join(blocks)}'


def _remediation_section(
    findings: list[dict], remediations: list[dict]
) -> str:
    cleanup_findings = [f for f in findings if f.get("category") == "cleanup"]
    success = [r for r in remediations if r.get("status") == "SUCCESS"]
    failed = [r for r in remediations if r.get("status") == "FAILED"]
    dry_run = [r for r in remediations if r.get("status") == "SKIPPED_DRY_RUN"]

    if not (cleanup_findings or remediations):
        return (
            f'<h2 style="{_H2}">Resource Cleanup</h2>'
            f'<p style="{_MUTED}">No cleanup activity in this window.</p>'
        )

    parts: list[str] = [f'<h2 style="{_H2}">Resource Cleanup</h2>']

    if cleanup_findings:
        rows = []
        for f in cleanup_findings:
            md = f.get("metadata") or {}
            monthly = _coerce_number(md.get("monthly_cost_usd"))
            rows.append(
                f"<tr>"
                f'<td style="{_TD};width:96px;">{_badge(f.get("severity", "LOW"))}</td>'
                f'<td style="{_TD};font-family:ui-monospace,monospace;font-size:12px;">'
                f'{html.escape(str(f.get("resource_id", "—")))}</td>'
                f'<td style="{_TD}">{html.escape(str(f.get("description", "")))}</td>'
                f'<td style="{_TD};text-align:right;">${monthly:,.2f}/mo</td>'
                f"</tr>"
            )
        parts.append(
            f'<h3 style="margin:20px 0 6px 0;font-size:15px;">'
            f'Detected zombie resources ({len(cleanup_findings)})</h3>'
            f'<table style="{_TABLE}"><tbody>{"".join(rows)}</tbody></table>'
        )

    if success or failed or dry_run:
        parts.append(
            f'<h3 style="margin:20px 0 6px 0;font-size:15px;">Remediation actions</h3>'
            f'<p style="{_MUTED}">'
            f'{len(success)} succeeded · {len(failed)} failed · {len(dry_run)} dry-run only'
            f"</p>"
        )
        if failed:
            rows = []
            for r in failed:
                rows.append(
                    f"<tr>"
                    f'<td style="{_TD};font-family:ui-monospace,monospace;font-size:12px;">'
                    f'{html.escape(str(r.get("resource_id", "—")))}</td>'
                    f'<td style="{_TD}">{html.escape(str(r.get("action", "—")))}</td>'
                    f'<td style="{_TD};color:#b91c1c;">'
                    f'{html.escape(str(r.get("error_message", "—")))}</td>'
                    f"</tr>"
                )
            parts.append(
                f'<table style="{_TABLE}"><thead><tr>'
                f'<th style="{_TH}">Resource</th>'
                f'<th style="{_TH}">Action</th>'
                f'<th style="{_TH}">Error</th>'
                f'</tr></thead><tbody>{"".join(rows)}</tbody></table>'
            )

    return "".join(parts)


def _safe_get(d: dict, key: str, default: Any) -> Any:
    """dict.get() with None coerced to default — DynamoDB sometimes returns None."""
    v = d.get(key)
    return default if v is None else v


def build_report(
    findings: Iterable[dict],
    cost_data: Iterable[dict],
    remediations: Iterable[dict],
    *,
    window_hours: int,
    environment: str,
    generated_at: datetime | None = None,
) -> str:
    """Compose the full HTML report from raw DynamoDB rows.

    Inputs may be lazy iterables — they're materialised here once.
    """
    findings = list(findings)
    cost_data = list(cost_data)
    remediations = list(remediations)
    generated_at = generated_at or datetime.now(timezone.utc)

    header = (
        f'<h1 style="{_H1}">CloudGuard Report — {html.escape(environment)}</h1>'
        f'<p style="{_MUTED}">'
        f"Window: last {window_hours}h · "
        f"Generated {html.escape(generated_at.strftime('%Y-%m-%d %H:%M UTC'))}"
        f"</p>"
    )

    return (
        "<!DOCTYPE html>"
        '<html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>CloudGuard Report — {html.escape(environment)}</title>"
        "</head>"
        f'<body style="{_BODY}">'
        + header
        + _executive_summary(findings, cost_data, remediations)
        + _cost_section(cost_data)
        + _security_section(findings)
        + _remediation_section(findings, remediations)
        + '<p style="margin-top:32px;'
        + _MUTED
        + '">CloudGuard automated report. Full data archived to S3.</p>'
        "</body></html>"
    )


def build_email_summary(
    findings: list[dict],
    cost_data: list[dict],
    remediations: list[dict],
    *,
    window_hours: int,
    environment: str,
    report_url: str,
) -> str:
    """Short HTML email body. Just the exec summary + a button-styled link.

    Kept under ~50 KB so Gmail doesn't clip it. Full report is the S3 object.
    """
    summary_block = _executive_summary(findings, cost_data, remediations)
    return (
        "<!DOCTYPE html>"
        f'<html><body style="{_BODY}">'
        f'<h1 style="{_H1}">CloudGuard Report — {html.escape(environment)}</h1>'
        f'<p style="{_MUTED}">Last {window_hours}h</p>'
        + summary_block
        + f'<p style="margin-top:24px;">'
        f'<a href="{html.escape(report_url)}" '
        f'style="display:inline-block;background:#1d4ed8;color:#ffffff;'
        f'padding:10px 18px;text-decoration:none;border-radius:6px;'
        f'font-weight:600;">View full report</a></p>'
        f'<p style="{_MUTED}">Link expires in 7 days. Re-run the report Lambda to regenerate.</p>'
        "</body></html>"
    )
