"""Report renderers."""

from __future__ import annotations

import csv
import io

from ..models import ScanReport
from ..pipeline import opportunities_to_rows
from . import html as html_report
from . import markdown as markdown_report


def render_markdown(report: ScanReport, top_n: int = 10) -> str:
    return markdown_report.render(report, top_n=top_n)


def render_html(report: ScanReport) -> str:
    return html_report.render(report)


def render_json(report: ScanReport) -> str:
    return report.model_dump_json(indent=2)


def render_csv(report: ScanReport) -> str:
    rows = opportunities_to_rows(report.opportunities)
    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


RENDERERS = {
    "md": render_markdown,
    "html": render_html,
    "json": render_json,
    "csv": render_csv,
}

__all__ = [
    "RENDERERS",
    "render_csv",
    "render_html",
    "render_json",
    "render_markdown",
]
