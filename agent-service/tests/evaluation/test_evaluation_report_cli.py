"""评测报告CLI的渲染、比较和安全失败测试。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.cli.evaluation_report import EvaluationReportExitCode, main
from app.evaluation.reporting import (
    EvaluationRunMetadata,
    EvaluationSubjectKind,
    build_unified_evaluation_report,
    write_evaluation_report_json,
)
from app.evaluation.tools import ToolEvaluationOutcome, evaluate_tool_metrics


def _write_report(path: Path, *, succeeded: bool) -> None:
    domain_report = evaluate_tool_metrics(
        (
            ToolEvaluationOutcome(
                case_id="tool-001",
                initial_validation_passed=succeeded,
                final_call_succeeded=succeeded,
            ),
        )
    )
    report = build_unified_evaluation_report(
        EvaluationRunMetadata(
            evaluation_id=f"eval-cli-{str(succeeded).lower()}-001",
            generated_at=datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
            subject_kind=EvaluationSubjectKind.REPLAY,
            subject_name="fixture-replay",
            dataset_versions={"tools": "v1"},
        ),
        {"tools": domain_report},
    )
    write_evaluation_report_json(report, path)


def test_cli_renders_markdown_and_compares_reports(
    tmp_path: Path,
    capsys: Any,
) -> None:
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    markdown_path = tmp_path / "candidate.md"
    comparison_path = tmp_path / "comparison.json"
    _write_report(baseline_path, succeeded=False)
    _write_report(candidate_path, succeeded=True)

    render_code = main(
        (
            "render",
            "--input",
            str(candidate_path),
            "--markdown-output",
            str(markdown_path),
        )
    )
    compare_code = main(
        (
            "compare",
            "--baseline",
            str(baseline_path),
            "--candidate",
            str(candidate_path),
            "--output",
            str(comparison_path),
        )
    )

    assert render_code == EvaluationReportExitCode.SUCCESS
    assert compare_code == EvaluationReportExitCode.SUCCESS
    assert markdown_path.exists()
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    assert comparison["baseline_evaluation_id"] == "eval-cli-false-001"
    assert any(delta["delta"] == 1.0 for delta in comparison["metric_deltas"])
    assert '"ok": true' in capsys.readouterr().out


def test_cli_rejects_invalid_input_and_missing_output(
    tmp_path: Path,
    capsys: Any,
) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{}", encoding="utf-8")

    invalid_code = main(
        (
            "render",
            "--input",
            str(invalid_path),
            "--markdown-output",
            str(tmp_path / "unused.md"),
        )
    )
    missing_output_code = main(("render", "--input", str(invalid_path)))

    assert invalid_code == EvaluationReportExitCode.INPUT_ERROR
    assert missing_output_code == EvaluationReportExitCode.INPUT_ERROR
    output = capsys.readouterr().out
    assert "EVALUATION_REPORT_INVALID" in output
    assert "EVALUATION_OUTPUT_REQUIRED" in output


def test_cli_classifies_output_failure_without_echoing_path(
    tmp_path: Path,
    capsys: Any,
) -> None:
    report_path = tmp_path / "report.json"
    blocked_parent = tmp_path / "not-a-directory"
    _write_report(report_path, succeeded=True)
    blocked_parent.write_text("file", encoding="utf-8")

    code = main(
        (
            "render",
            "--input",
            str(report_path),
            "--markdown-output",
            str(blocked_parent / "report.md"),
        )
    )

    assert code == EvaluationReportExitCode.OUTPUT_ERROR
    output = capsys.readouterr().out
    assert "EVALUATION_REPORT_WRITE_FAILED" in output
    assert str(blocked_parent) not in output
