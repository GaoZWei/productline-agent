"""M7.8七类生产Suite接线与统一报告闭环测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.evaluation.acceptance import AcceptanceEvaluationOutcome
from app.evaluation.agents import AgentEvaluationOutcome
from app.evaluation.observability import ObservabilityEvaluationOutcome
from app.evaluation.rag import (
    RagEvaluationCase,
    RagEvaluationPrediction,
    RagEvaluationStrategy,
    RagRetrievedFragment,
)
from app.evaluation.reporting import EvaluationRunMetadata, EvaluationSubjectKind
from app.evaluation.router import RouterEvaluationCase, RouterEvaluationPrediction
from app.evaluation.runner import EvalRunner, EvaluationSuite
from app.evaluation.suites import (
    STANDARD_EVALUATION_SUITE_NAMES,
    assert_standard_suite_catalog,
    standard_evaluation_suites,
)
from app.evaluation.tools import ToolEvaluationOutcome

_EVALUATION_ROOT = Path(__file__).parents[2] / "evaluation"


class _ExpectedRouterSubject:
    async def predict(self, case: RouterEvaluationCase) -> RouterEvaluationPrediction:
        return RouterEvaluationPrediction(
            case_id=case.case_id,
            intent=case.expected_intent,
            entities=case.expected_entities,
            status=case.expected_status,
            clarification_reason=case.expected_clarification_reason,
        )


class _ExpectedRagSubject:
    async def retrieve(
        self,
        case: RagEvaluationCase,
        strategy: RagEvaluationStrategy,
        *,
        top_k: int,
    ) -> RagEvaluationPrediction:
        return RagEvaluationPrediction(
            case_id=case.case_id,
            strategy=strategy,
            results=(
                RagRetrievedFragment(
                    chunk_ids=(f"KCH-{case.case_id.upper()}-{strategy.value}",),
                    document_id=case.expected_document_id,
                    section_path=case.expected_section,
                ),
            )[:top_k],
            version_filter_passed=True,
            citation_document_correct=True,
        )


async def _tool_outcomes() -> tuple[ToolEvaluationOutcome, ...]:
    return (
        ToolEvaluationOutcome(
            case_id="tool-001",
            initial_validation_passed=True,
            final_call_succeeded=True,
        ),
    )


async def _agent_outcomes() -> tuple[AgentEvaluationOutcome, ...]:
    return (
        AgentEvaluationOutcome(
            case_id="agent-001",
            e2e_succeeded=True,
            executed_tool_calls=1,
            total_tool_call_attempts=1,
        ),
    )


async def _diagnosis_outcomes() -> tuple[AcceptanceEvaluationOutcome, ...]:
    return (
        AcceptanceEvaluationOutcome(
            case_id="diagnosis-001",
            succeeded=True,
            duration_ms=20,
        ),
    )


async def _approval_outcomes() -> tuple[AcceptanceEvaluationOutcome, ...]:
    return (AcceptanceEvaluationOutcome(case_id="approval-001", succeeded=True),)


async def _fault_outcomes() -> tuple[ObservabilityEvaluationOutcome, ...]:
    return (
        ObservabilityEvaluationOutcome(
            case_id="obs-001",
            expected_error_type="TOOL_TIMEOUT",
            observed_error_type="TOOL_TIMEOUT",
            expected_error_step="get_order",
            located_error_step="get_order",
        ),
    )


@pytest.mark.asyncio
async def test_standard_catalog_runs_all_seven_suites_into_one_report(
    tmp_path: Path,
) -> None:
    suites = standard_evaluation_suites(
        router_dataset_path=_EVALUATION_ROOT / "router_cases.jsonl",
        router_subject=_ExpectedRouterSubject(),
        tool_outcomes=_tool_outcomes,
        rag_dataset_path=_EVALUATION_ROOT / "rag_cases.jsonl",
        rag_subject=_ExpectedRagSubject(),
        diagnosis_outcomes=_diagnosis_outcomes,
        agent_policy_outcomes=_agent_outcomes,
        approval_outcomes=_approval_outcomes,
        fault_injection_outcomes=_fault_outcomes,
        failure_directory=tmp_path / "failures",
    )
    runner = EvalRunner(suites)

    report = await runner.run_report(
        EvaluationRunMetadata(
            evaluation_id="eval-standard-controlled-001",
            generated_at=datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
            subject_kind=EvaluationSubjectKind.CONTROLLED,
            subject_name="expected-output-subject",
            dataset_versions={name: "v1" for name in STANDARD_EVALUATION_SUITE_NAMES},
        )
    )

    assert runner.suite_names == STANDARD_EVALUATION_SUITE_NAMES
    assert tuple(suite.suite_name for suite in report.suites) == (
        STANDARD_EVALUATION_SUITE_NAMES
    )
    assert report.suites[0].total_cases == 60
    assert report.suites[2].total_cases == 50
    assert tuple(suite.report_type for suite in report.suites) == (
        "RouterEvaluationReport",
        "ToolEvaluationReport",
        "RagEvaluationReport",
        "AcceptanceEvaluationReport",
        "AgentEvaluationReport",
        "AcceptanceEvaluationReport",
        "ObservabilityEvaluationReport",
    )
    assert (tmp_path / "failures" / "router.jsonl").read_text() == ""
    assert (tmp_path / "failures" / "rag.jsonl").read_text() == ""


def test_standard_catalog_rejects_missing_or_reordered_suites() -> None:
    async def execute() -> BaseModel:
        raise AssertionError

    with pytest.raises(ValueError, match="incomplete"):
        assert_standard_suite_catalog((EvaluationSuite("router", execute),))
