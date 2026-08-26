"""M6.2复核草稿字段、跨字段规则和规范引用测试。"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas import Citation, Conclusion, ReviewDraft, ReworkSuggestion, ReworkType


def _citation_values(*, chunk_id: str = "CHUNK-COORD-001") -> dict[str, Any]:
    return {
        "document_id": "SPEC-COORD-001",
        "document_name": "坐标系统处理规范",
        "document_version": "2.0",
        "section": ["质量复核", "坐标系统"],
        "chunk_id": chunk_id,
        "chunk_ids": [chunk_id],
        "content": "坐标系统问题关闭后方可重新提交复核。",
        "relevance_score": 0.98,
    }


def _draft_values(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "task_id": "TASK-003",
        "conclusion": "REWORK_REQUIRED",
        "problem_summary": "存在未关闭的坐标系质量问题",
        "review_comment": "建议完成坐标系统处理后重新提交复核",
        "specification_references": [],
        "suggested_rework": {
            "required": True,
            "type": "COORDINATE_SYSTEM_FIX",
        },
    }
    values.update(changes)
    return values


@pytest.mark.unit
def test_review_draft_accepts_golden_contract_and_serializes_stable_values() -> None:
    draft = ReviewDraft.model_validate(_draft_values())

    assert draft.task_id == "TASK-003"
    assert draft.conclusion is Conclusion.REWORK_REQUIRED
    assert draft.suggested_rework.type is ReworkType.COORDINATE_SYSTEM_FIX
    assert draft.specification_references == ()
    assert draft.model_dump(mode="json") == _draft_values()


@pytest.mark.unit
@pytest.mark.parametrize("conclusion", ["PENDING", "UNKNOWN", 1])
def test_review_draft_rejects_non_final_or_invalid_conclusion(conclusion: object) -> None:
    with pytest.raises(ValidationError):
        ReviewDraft.model_validate(_draft_values(conclusion=conclusion))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("problem_summary", " "),
        ("problem_summary", "问" * 2049),
        ("review_comment", " "),
        ("review_comment", "评" * 1001),
    ],
)
def test_review_draft_rejects_empty_or_oversized_text(
    field_name: str,
    invalid_value: str,
) -> None:
    with pytest.raises(ValidationError):
        ReviewDraft.model_validate(_draft_values(**{field_name: invalid_value}))


@pytest.mark.unit
def test_rework_suggestion_requires_type_if_and_only_if_required() -> None:
    with pytest.raises(ValidationError):
        ReworkSuggestion(required=True, type=None)
    with pytest.raises(ValidationError):
        ReworkSuggestion(required=False, type=ReworkType.COORDINATE_SYSTEM_FIX)

    assert ReworkSuggestion(required=False).type is None


@pytest.mark.unit
def test_review_conclusion_must_match_rework_suggestion() -> None:
    with pytest.raises(ValidationError):
        ReviewDraft.model_validate(
            _draft_values(
                conclusion="APPROVED",
                suggested_rework={
                    "required": True,
                    "type": "COORDINATE_SYSTEM_FIX",
                },
            )
        )
    with pytest.raises(ValidationError):
        ReviewDraft.model_validate(
            _draft_values(
                conclusion="REWORK_REQUIRED",
                suggested_rework={"required": False, "type": None},
            )
        )


@pytest.mark.unit
def test_specification_references_reuse_citation_contract_and_reject_duplicates() -> None:
    reference = _citation_values()
    draft = ReviewDraft.model_validate(_draft_values(specification_references=[reference]))

    assert len(draft.specification_references) == 1
    assert isinstance(draft.specification_references[0], Citation)
    assert draft.specification_references[0].chunk_id == "CHUNK-COORD-001"

    with pytest.raises(ValidationError):
        ReviewDraft.model_validate(_draft_values(specification_references=[reference, reference]))
    with pytest.raises(ValidationError):
        ReviewDraft.model_validate(
            _draft_values(
                specification_references=[{**reference, "chunk_ids": ["CHUNK-DIFFERENT"]}]
            )
        )


@pytest.mark.unit
def test_review_draft_rejects_extra_fields_and_is_immutable() -> None:
    with pytest.raises(ValidationError):
        ReviewDraft.model_validate(_draft_values(model_comment="不得进入草稿"))

    draft = ReviewDraft.model_validate(_draft_values())
    with pytest.raises(ValidationError):
        draft.__setattr__("review_comment", "确认外修改")
