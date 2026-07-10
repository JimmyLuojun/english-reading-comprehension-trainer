"""Tests for the coverage policy checker."""

from __future__ import annotations

from pathlib import Path

from scripts.check_coverage import coverage_failures


def test_coverage_failures_accepts_policy_compliant_modules(tmp_path: Path) -> None:
    report = tmp_path / "coverage.xml"
    report.write_text(
        """<coverage><packages><package><classes>
        <class filename=\"review/sm2_scheduler.py\" line-rate=\"1\" />
        <class filename=\"cards/example.py\" line-rate=\"0.97\" />
        </classes></package></packages></coverage>""",
        encoding="utf-8",
    )

    assert coverage_failures(report) == []


def test_coverage_failures_reports_regular_and_critical_shortfalls(tmp_path: Path) -> None:
    report = tmp_path / "coverage.xml"
    report.write_text(
        """<coverage><packages><package><classes>
        <class filename=\"ai/json_output_validator.py\" line-rate=\"0.99\" />
        <class filename=\"cards/example.py\" line-rate=\"0.96\" />
        </classes></package></packages></coverage>""",
        encoding="utf-8",
    )

    assert coverage_failures(report) == [
        "ai/json_output_validator.py: 99.00% below required 100%",
        "cards/example.py: 96.00% below required 97%",
    ]
