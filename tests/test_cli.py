"""CLI argument handling."""

from __future__ import annotations

import pytest
import typer

from ncscout.cli import _parse_coordinates, _write_reports
from ncscout.models import ScanReport
from ncscout.report import render_markdown


class TestParseCoordinates:
    def test_parses_a_negative_longitude(self):
        """Every US longitude is negative, so this is the common case."""
        assert _parse_coordinates("41.8,-93.6") == (41.8, -93.6)

    def test_tolerates_whitespace_and_semicolons(self):
        assert _parse_coordinates(" 41.8 , -93.6 ") == (41.8, -93.6)
        assert _parse_coordinates("41.8; -93.6") == (41.8, -93.6)

    @pytest.mark.parametrize("bad", ["41.8", "", "1,2,3", "abc,def", "41.8,"])
    def test_rejects_malformed_input(self, bad):
        with pytest.raises(typer.BadParameter):
            _parse_coordinates(bad)

    @pytest.mark.parametrize("bad", ["200,-93", "41,200", "-400,10"])
    def test_rejects_out_of_range_values(self, bad):
        with pytest.raises(typer.BadParameter, match="out of range"):
            _parse_coordinates(bad)

    @pytest.mark.parametrize("swapped", ["-93.6,41.8", "-120.7,45.85"])
    def test_detects_transposed_coordinates(self, swapped):
        """The common paste error deserves a better message than 'out of range'."""
        with pytest.raises(typer.BadParameter, match="transposed"):
            _parse_coordinates(swapped)


class TestWriteReports:
    def test_writes_requested_formats_and_a_latest_alias(self, tmp_path):
        from datetime import UTC, datetime

        report = ScanReport(
            generated_at=datetime(2026, 1, 2, tzinfo=UTC),
            listings_considered=0,
            listings_enriched=0,
            opportunities=[],
        )
        _write_reports(report, tmp_path, "md,json", top=10)

        assert (tmp_path / "scan-2026-01-02.md").exists()
        assert (tmp_path / "latest.md").exists()
        assert (tmp_path / "scan-2026-01-02.json").exists()
        # latest must mirror the dated file so links to it stay correct.
        assert (tmp_path / "latest.md").read_text() == render_markdown(report)

    def test_unknown_format_is_skipped_not_fatal(self, tmp_path):
        from datetime import UTC, datetime

        report = ScanReport(
            generated_at=datetime(2026, 1, 2, tzinfo=UTC),
            listings_considered=0,
            listings_enriched=0,
            opportunities=[],
        )
        written = _write_reports(report, tmp_path, "md,pdf", top=10)
        assert not any("pdf" in str(p) for p in written)
        assert (tmp_path / "latest.md").exists()
