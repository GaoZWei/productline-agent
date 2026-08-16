"""M3.7 固定路由数据集、评测指标和失败样本测试。"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from app.evaluation.router import (
    EXPECTED_CATEGORY_COUNTS,
    EvaluationFailureType,
    RouterEvaluationCase,
    RouterEvaluationDataError,
    RouterEvaluationPrediction,
    evaluate_router,
    load_router_evaluation_cases,
)
from app.routing import Intent
from app.schemas import ClarificationReason, RouterEntities, RoutingDecisionStatus

_DATASET_PATH = Path(__file__).parents[2] / "evaluation" / "router_cases.jsonl"


class ExpectedPredictionSubject:
    async def predict(self, case: RouterEvaluationCase) -> RouterEvaluationPrediction:
        return RouterEvaluationPrediction(
            case_id=case.case_id,
            intent=case.expected_intent,
            entities=case.expected_entities,
            status=case.expected_status,
            clarification_reason=case.expected_clarification_reason,
        )


class FaultInjectingSubject:
    async def predict(self, case: RouterEvaluationCase) -> RouterEvaluationPrediction:
        if case.case_id == "router-001":
            return RouterEvaluationPrediction(
                case_id=case.case_id,
                intent=Intent.UNKNOWN,
                entities=RouterEntities(),
                status=RoutingDecisionStatus.NEEDS_CLARIFICATION,
                clarification_reason=ClarificationReason.UNKNOWN_INTENT,
            )
        if case.case_id == "router-002":
            return RouterEvaluationPrediction(
                case_id=case.case_id,
                intent=case.expected_intent,
                entities=RouterEntities(),
                status=case.expected_status,
                clarification_reason=case.expected_clarification_reason,
            )
        return await ExpectedPredictionSubject().predict(case)


def test_router_dataset_has_exact_planned_distribution_and_unique_ids() -> None:
    cases = load_router_evaluation_cases(_DATASET_PATH)

    assert len(cases) == 60
    assert len({case.case_id for case in cases}) == len(cases)
    assert Counter(case.category for case in cases) == Counter(
        EXPECTED_CATEGORY_COUNTS
    )


def test_router_dataset_covers_all_intents_and_clarification_paths() -> None:
    cases = load_router_evaluation_cases(_DATASET_PATH)

    assert {case.expected_intent for case in cases} == set(Intent)
    clarification_reasons = {
        case.expected_clarification_reason
        for case in cases
        if case.expected_clarification_reason is not None
    }
    assert {
        ClarificationReason.UNKNOWN_INTENT,
        ClarificationReason.ENTITY_CONFLICT,
        ClarificationReason.MISSING_PARAMETER,
        ClarificationReason.CONFIRM_INTENT,
    } <= clarification_reasons
    alias_case = next(case for case in cases if case.case_id == "router-005")
    assert alias_case.expected_entities.satellite_type == "GF-2"
    assert "GF-2" not in alias_case.user_message


def test_router_evaluation_case_rejects_inconsistent_expected_result() -> None:
    with pytest.raises(ValueError):
        RouterEvaluationCase.model_validate(
            {
                "case_id": "router-999",
                "category": "EXPLICIT_INTENT",
                "user_message": "诊断这个订单",
                "expected_intent": "ORDER_DIAGNOSIS",
                "expected_entities": {},
                "expected_status": "READY",
            }
        )


def test_dataset_loader_rejects_duplicate_ids_without_echoing_case_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "duplicate.jsonl"
    case = {
        "case_id": "router-001",
        "category": "UNRELATED",
        "user_message": "包含不应进入异常的信息",
        "expected_intent": "UNKNOWN",
        "expected_entities": {},
        "expected_status": "NEEDS_CLARIFICATION",
        "expected_clarification_reason": "UNKNOWN_INTENT",
    }
    path.write_text(
        f"{json.dumps(case, ensure_ascii=False)}\n"
        f"{json.dumps(case, ensure_ascii=False)}\n",
        encoding="utf-8",
    )

    with pytest.raises(RouterEvaluationDataError) as error:
        load_router_evaluation_cases(path, enforce_planned_distribution=False)

    assert "duplicate case_id" in str(error.value)
    assert "包含不应进入异常的信息" not in str(error.value)


@pytest.mark.asyncio
async def test_perfect_controlled_predictions_produce_diagonal_matrix() -> None:
    cases = load_router_evaluation_cases(_DATASET_PATH)

    report = await evaluate_router(cases, ExpectedPredictionSubject())

    assert report.total_cases == 60
    assert report.intent_correct == 60
    assert report.parameters_complete == 60
    assert report.intent_accuracy == 1.0
    assert report.parameter_completeness == 1.0
    assert report.failures == ()
    for expected_intent, row in report.confusion_matrix.items():
        assert row[expected_intent] > 0
        assert sum(row.values()) == row[expected_intent]


@pytest.mark.asyncio
async def test_metrics_confusion_matrix_and_safe_failure_file(
    tmp_path: Path,
) -> None:
    cases = load_router_evaluation_cases(_DATASET_PATH)
    failure_path = tmp_path / "router-failures.jsonl"

    report = await evaluate_router(
        cases,
        FaultInjectingSubject(),
        failure_path=failure_path,
    )

    assert report.intent_correct == 59
    assert report.parameters_complete == 58
    assert report.intent_accuracy == pytest.approx(59 / 60)
    assert report.parameter_completeness == pytest.approx(58 / 60)
    assert report.confusion_matrix[Intent.ORDER_DIAGNOSIS][Intent.UNKNOWN] == 1
    assert tuple(failure.case_id for failure in report.failures) == (
        "router-001",
        "router-002",
    )
    assert report.failures[0].failure_types == (
        EvaluationFailureType.INTENT,
        EvaluationFailureType.PARAMETERS,
        EvaluationFailureType.STATUS,
        EvaluationFailureType.CLARIFICATION,
    )

    failure_text = failure_path.read_text(encoding="utf-8")
    assert len(failure_text.splitlines()) == 2
    assert "user_message" not in failure_text
    assert "page_context" not in failure_text
    assert "session_context" not in failure_text


@pytest.mark.asyncio
async def test_evaluator_rejects_prediction_for_another_case() -> None:
    case = load_router_evaluation_cases(_DATASET_PATH)[0]

    class WrongCaseSubject:
        async def predict(
            self,
            evaluation_case: RouterEvaluationCase,
        ) -> RouterEvaluationPrediction:
            return RouterEvaluationPrediction(
                case_id="router-999",
                intent=evaluation_case.expected_intent,
                entities=evaluation_case.expected_entities,
                status=evaluation_case.expected_status,
                clarification_reason=evaluation_case.expected_clarification_reason,
            )

    with pytest.raises(RouterEvaluationDataError):
        await evaluate_router((case,), WrongCaseSubject())
