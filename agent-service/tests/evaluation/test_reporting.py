"""统一报告Schema、导出和历史对比测试。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.evaluation.acceptance import AcceptanceEvaluationOutcome, evaluate_acceptance
from app.evaluation.reporting import (
    EvaluationReportError,
    EvaluationRunMetadata,
    EvaluationSubjectKind,
    build_unified_evaluation_report,
    compare_evaluation_reports,
    evaluation_comparison_json,
    evaluation_report_json,
    evaluation_report_markdown,
    load_evaluation_report,
    write_evaluation_report_json,
    write_evaluation_report_markdown,
)
from app.evaluation.tools import (
    ToolEvaluationOutcome,
    ToolEvaluationReport,
    evaluate_tool_metrics,
)


def _metadata(
    evaluation_id: str,
    *,
    subject_kind: EvaluationSubjectKind = EvaluationSubjectKind.CONTROLLED,
) -> EvaluationRunMetadata:
    return EvaluationRunMetadata(
        evaluation_id=evaluation_id,
        generated_at=datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
        subject_kind=subject_kind,
        subject_name="expected-output-subject",
        dataset_versions={
            "router": "router-v1",
            "tools": "tool-v1",
            "approval": "approval-v1",
        },
    )


def _tool_report(*, succeeded: bool = True) -> ToolEvaluationReport:
    return evaluate_tool_metrics(
        (
            ToolEvaluationOutcome(
                case_id="tool-001",
                initial_validation_passed=succeeded,
                final_call_succeeded=succeeded,
            ),
        )
    )


def test_builds_round_trippable_report_and_marks_non_live_markdown(tmp_path: Path) -> None:
    report = build_unified_evaluation_report(
        _metadata("eval-controlled-001"),
        {"tools": _tool_report()},
    )

    assert report.schema_version == "1.0"
    assert report.suites[0].suite_name == "tools"
    assert report.suites[0].report_type == "ToolEvaluationReport"
    assert report.suites[0].total_cases == 1
    assert "live provider quality" in evaluation_report_markdown(report)

    json_path = tmp_path / "nested" / "report.json"
    markdown_path = tmp_path / "nested" / "report.md"
    write_evaluation_report_json(report, json_path)
    write_evaluation_report_markdown(report, markdown_path)

    assert load_evaluation_report(json_path) == report
    assert json.loads(evaluation_report_json(report))["schema_version"] == "1.0"
    assert markdown_path.read_text(encoding="utf-8").startswith("# Evaluation report")


def test_live_report_omits_controlled_subject_disclaimer() -> None:
    report = build_unified_evaluation_report(
        _metadata(
            "eval-live-provider-001",
            subject_kind=EvaluationSubjectKind.LIVE_PROVIDER,
        ),
        {"tools": _tool_report()},
    )

    assert "does not represent live provider quality" not in evaluation_report_markdown(
        report
    )


def test_rejects_unsafe_payload_and_invalid_metadata(tmp_path: Path) -> None:
    class _UnsafeReport(BaseModel):
        prompt: str

    with pytest.raises(EvaluationReportError, match="forbidden"):
        build_unified_evaluation_report(
            _metadata("eval-unsafe-001"),
            {"tools": _UnsafeReport(prompt="do not persist")},
        )
    with pytest.raises(EvaluationReportError, match="version is missing"):
        build_unified_evaluation_report(
            EvaluationRunMetadata(
                evaluation_id="eval-missing-version-001",
                generated_at=datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
                subject_kind=EvaluationSubjectKind.REPLAY,
                subject_name="replay",
                dataset_versions={"router": "v1"},
            ),
            {"tools": _tool_report()},
        )
    with pytest.raises(ValueError, match="timezone"):
        EvaluationRunMetadata(
            evaluation_id="eval-invalid-001",
            generated_at=datetime(2026, 9, 13, 8, 0),
            subject_kind=EvaluationSubjectKind.REPLAY,
            subject_name="replay",
            dataset_versions={"tools": "v1"},
        )

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text('{"schema_version":"1.0"}', encoding="utf-8")
    with pytest.raises(EvaluationReportError, match="could not be loaded"):
        load_evaluation_report(invalid_path)


def test_compares_shared_metrics_and_reports_coverage_changes() -> None:
    baseline = build_unified_evaluation_report(
        _metadata("eval-baseline-001"),
        {"tools": _tool_report(succeeded=False)},
    )
    candidate = build_unified_evaluation_report(
        _metadata("eval-candidate-001"),
        {
            "tools": _tool_report(succeeded=True),
            "approval": evaluate_acceptance(
                (AcceptanceEvaluationOutcome(case_id="approval-001", succeeded=True),)
            ),
        },
    )

    comparison = compare_evaluation_reports(baseline, candidate)

    assert comparison.added_suites == ("approval",)
    assert comparison.removed_suites == ()
    final_success_delta = next(
        delta
        for delta in comparison.metric_deltas
        if delta.metric_path == "final_valid_call_success_rate"
    )
    assert final_success_delta.baseline_value == 0.0
    assert final_success_delta.candidate_value == 1.0
    assert final_success_delta.delta == 1.0
    assert json.loads(evaluation_comparison_json(comparison))["added_suites"] == [
        "approval"
    ]
