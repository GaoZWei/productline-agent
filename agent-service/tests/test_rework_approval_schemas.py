"""T826九类独立草稿、目标绑定、可编辑材料及审查副作用。没有真实确认或写入。"""

from copy import deepcopy
from typing import cast

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.approval import ReviewDraft
from app.schemas.rework import ReworkOperation
from app.schemas.rework_approval import (
    REWORK_APPROVAL_TOOLS,
    ReworkApprovalDraft,
    ReworkDraftReview,
    parse_rework_approval_draft,
    review_rework_approval_draft,
    validate_rework_draft_edit,
)
from app.schemas.rework_write_tools import ReworkExecutionSnapshot
from app.tools.rework_write import REWORK_WRITE_TOOL_NAMES
from tests.integration.tools.test_rework_write_tools import CASES, Case, receipt, snapshot
from tests.test_approval_schemas import _draft_values

pytestmark = pytest.mark.unit


def draft_values(case: Case = CASES[1]) -> dict[str, object]:
    """显式测试夹具只声明待审查事实，不生成已确认执行快照。"""

    value = snapshot(case)
    artifact: dict[str, object] | None = None
    revision, inspection, review = value.processing_revision, value.inspection_id, value.review_id
    if revision is not None:
        artifact = {"artifactId": "成果-原版本", "artifactVersion": "Release-1"}
    if case.operation == "CREATE_NEXT_REWORK":
        artifact = {"artifactId": "成果-原版本", "artifactVersion": "Release-1"}
        revision, inspection, review = 1, "CHECK-T826-PREV", "REVIEW-T826-PREV"
    return {
        "operation": case.operation,
        "target": {
            "task_id": value.task_id,
            "task_version": value.task_version,
            "source_issue_id": value.source_issue_id,
            "rework_task_id": value.rework_task_id,
            "round_number": value.round_number,
            "previous_rework_task_id": value.previous_rework_task_id,
            "processing_revision": revision,
            "artifact": artifact,
            "inspection_id": inspection,
            "review_id": review,
        },
        "request": value.request.model_dump(mode="json", by_alias=True),
    }


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.operation)
def test_nine_drafts_roundtrip_and_have_only_one_fixed_tool(case: Case) -> None:
    raw = draft_values(case)
    draft = parse_rework_approval_draft(raw)
    assert draft.model_dump(mode="json", by_alias=True) == raw
    review = review_rework_approval_draft(draft)
    assert review.pending_tool == case.name and review.draft == draft
    assert review.expected_effects.rework_status_after == receipt(case)["status"]
    assert review.expected_effects.issue_status_after == receipt(case)["issueStatus"]
    assert review.required_permission == (
        "REVIEW_WRITE" if case.operation == "SUBMIT_REWORK_REVIEW" else "REWORK_WRITE"
    )
    assert review.effect_semantics == "EXPECTED_IF_JAVA_ACCEPTS"
    assert ReworkDraftReview.model_validate_json(review.model_dump_json(by_alias=True)) == review
    assert frozenset(REWORK_APPROVAL_TOOLS.values()) == REWORK_WRITE_TOOL_NAMES
    schema = TypeAdapter[ReworkApprovalDraft](ReworkApprovalDraft).json_schema()
    assert schema["discriminator"]["propertyName"] == "operation"
    assert set(schema["discriminator"]["mapping"]) == {c.operation for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.operation)
def test_each_draft_refuses_unconfirmed_authority_or_other_request_shape(case: Case) -> None:
    raw = draft_values(case)
    for extra in [
        "confirmed",
        "approval_id",
        "idempotency_key",
        "user_id",
        "pending_tool",
        "status",
    ]:
        with pytest.raises(ValidationError):
            parse_rework_approval_draft({**raw, extra: "untrusted"})
    request = cast(dict[str, object], raw["request"])
    with pytest.raises(ValidationError):
        parse_rework_approval_draft({**raw, "request": {**request, "confirmed": True}})
    with pytest.raises(ValidationError):
        ReworkExecutionSnapshot.model_validate(raw)


@pytest.mark.parametrize("operation", ["CREATE_REWORK", "SUBMIT_REVIEW", "UNKNOWN", 1, None])
def test_old_or_unknown_actions_cannot_be_misrouted_as_new_drafts(operation: object) -> None:
    with pytest.raises(ValidationError):
        parse_rework_approval_draft({**draft_values(), "operation": operation})


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_version", 5),
        ("task_id", "TASK_bad"),
        ("round_number", 2),
        ("previous_rework_task_id", "REWORK-T823-A"),
        ("processing_revision", 1),
        ("inspection_id", "CHECK-UNBOUND"),
        ("review_id", "REVIEW-UNBOUND"),
    ],
)
def test_target_refuses_mixed_or_inconsistent_bindings(field: str, value: object) -> None:
    raw = draft_values()
    target = cast(dict[str, object], raw["target"])
    target[field] = value
    with pytest.raises(ValidationError):
        parse_rework_approval_draft(raw)


@pytest.mark.parametrize(
    "field",
    [
        "rework_task_id",
        "round_number",
        "previous_rework_task_id",
        "processing_revision",
        "artifact",
        "inspection_id",
        "review_id",
    ],
)
def test_missing_nullable_binding_is_not_silently_filled(field: str) -> None:
    raw = draft_values(CASES[0])
    del cast(dict[str, object], raw["target"])[field]
    with pytest.raises(ValidationError):
        parse_rework_approval_draft(raw)


@pytest.mark.parametrize(
    "kind",
    [
        "first-has-round",
        "wrong-source",
        "no-existing-round",
        "no-previous-review",
        "wrong-processing",
        "wrong-inspection",
        "missing-artifact",
    ],
)
def test_operation_specific_target_bindings_are_enforced(kind: str) -> None:
    raw = draft_values(
        CASES[0]
        if kind in {"first-has-round", "wrong-source"}
        else CASES[8]
        if kind == "no-previous-review"
        else CASES[7]
    )
    target = cast(dict[str, object], raw["target"])
    request = cast(dict[str, object], raw["request"])
    if kind == "first-has-round":
        target.update(rework_task_id="REWORK-OLD", round_number=1)
    elif kind == "wrong-source":
        request["sourceIssueId"] = "ISSUE-OTHER"
    elif kind == "no-existing-round":
        target.update(
            rework_task_id=None,
            round_number=None,
            processing_revision=None,
            artifact=None,
            inspection_id=None,
            review_id=None,
        )
    elif kind == "no-previous-review":
        target["review_id"] = None
    elif kind == "wrong-processing":
        request["processingRevision"] = 2
    elif kind == "wrong-inspection":
        request["inspectionId"] = "CHECK-OTHER"
    else:
        target["artifact"] = None
    with pytest.raises(ValidationError):
        parse_rework_approval_draft(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "TASK-OTHER"),
        ("source_issue_id", "ISSUE-OTHER"),
        ("rework_task_id", "REWORK-OTHER"),
        ("artifact", {"artifactId": "成果-其他", "artifactVersion": "Release-1"}),
    ],
)
def test_edit_cannot_replace_even_a_structurally_valid_target(field: str, value: object) -> None:
    before = draft_values(CASES[5])
    edited = deepcopy(before)
    cast(dict[str, object], edited["target"])[field] = value
    with pytest.raises(ValueError, match="cannot be edited"):
        validate_rework_draft_edit(before, edited)


def test_edit_cannot_switch_action_or_rebase_all_versions_and_rounds() -> None:
    before = draft_values()
    for edited in [draft_values(CASES[2]), deepcopy(before)]:
        if edited["operation"] == before["operation"]:
            target = cast(dict[str, object], edited["target"])
            if target["task_version"] == 4:
                target["task_version"] = 5
                cast(dict[str, object], edited["request"])["expectedVersion"] = 5
        with pytest.raises(ValueError, match="cannot be edited"):
            validate_rework_draft_edit(before, edited)
    edited = deepcopy(before)
    cast(dict[str, object], edited["target"]).update(
        round_number=2, previous_rework_task_id="REWORK-PREV"
    )
    with pytest.raises(ValueError, match="cannot be edited"):
        validate_rework_draft_edit(before, edited)


def test_edit_result_material_is_kept_verbatim_and_copied_for_final_review() -> None:
    before = draft_values(CASES[5])
    edited = deepcopy(before)
    request = cast(dict[str, object], edited["request"])
    request.update(
        artifact={"artifactId": "成果-新版", "artifactVersion": "Release-02"},
        processingComment="  原样说明🚀  ",
        evidenceReferences=["report:Case-B"],
    )
    final = validate_rework_draft_edit(before, edited)
    review = review_rework_approval_draft(final)
    assert review.draft.request.model_dump(mode="json", by_alias=True) == request
    cast(list[str], request["evidenceReferences"]).append("report:unreviewed")
    assert review.draft.model_dump(mode="json", by_alias=True) != edited
    assert review.expected_effects.rework_status_after == "RUNNING"
    assert review.expected_effects.issue_status_after == "PROCESSING"


@pytest.mark.parametrize("passed", [True, False])
def test_inspection_effects_are_complete_and_do_not_mean_final_acceptance(passed: bool) -> None:
    raw = draft_values(CASES[6])
    items = cast(list[dict[str, object]], cast(dict[str, object], raw["request"])["items"])
    if not passed:
        items.append(
            {
                "checkItem": "另一项",
                "result": "FAILED",
                "comment": "实际未通过",
                "evidenceReferences": ["report:failed"],
            }
        )
    review = review_rework_approval_draft(raw)
    assert review.expected_effects.production_status_after == "COMPLETED"
    assert review.expected_effects.rework_status_after == ("COMPLETED" if passed else "RUNNING")
    assert review.expected_effects.issue_status_after == ("RESOLVED" if passed else "PROCESSING")
    assert review.expected_effects.delivery_effect == "NONE"


@pytest.mark.parametrize("status", ["APPROVED", "REJECTED", "REWORK_REQUIRED"])
def test_review_effects_only_close_or_reopen_issue_and_never_deliver(status: str) -> None:
    raw = draft_values(CASES[7])
    cast(dict[str, object], raw["request"])["status"] = status
    review = review_rework_approval_draft(raw)
    assert review.expected_effects.rework_status_after == "COMPLETED"
    assert review.expected_effects.issue_status_after == (
        "CLOSED" if status == "APPROVED" else "OPEN"
    )
    assert review.expected_effects.delivery_effect == (
        "RECHECK_ONLY" if status == "APPROVED" else "NONE"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("pending_tool", "start_rework"),
        ("required_permission", "REWORK_WRITE"),
        ("effect_semantics", "ALREADY_CONFIRMED"),
        (
            "expected_effects",
            {
                "production_status_after": "COMPLETED",
                "rework_status_after": "COMPLETED",
                "issue_status_after": "CLOSED",
                "delivery_effect": "NONE",
            },
        ),
    ],
)
def test_review_package_cannot_hide_or_forge_executor_permission_or_effects(
    field: str, value: object
) -> None:
    raw = review_rework_approval_draft(draft_values(CASES[7])).model_dump(
        mode="json", by_alias=True
    )
    raw[field] = value
    with pytest.raises(ValidationError):
        ReworkDraftReview.model_validate(raw)


@pytest.mark.parametrize("value", ["5", True, 4.0, -1, 9007199254740992])
def test_expected_version_is_a_strict_safe_integer(value: object) -> None:
    raw = draft_values()
    cast(dict[str, object], raw["request"])["expectedVersion"] = value
    with pytest.raises(ValidationError):
        parse_rework_approval_draft(raw)


def test_old_review_draft_stays_separate_and_unchanged() -> None:
    raw = _draft_values()
    old = ReviewDraft.model_validate(raw)
    assert old.model_dump(mode="json") == raw
    with pytest.raises(ValidationError):
        parse_rework_approval_draft(raw)
    with pytest.raises(ValidationError):
        ReviewDraft.model_validate(draft_values(CASES[7]))


@pytest.mark.parametrize(
    "field",
    ["confirmed", "approval_id", "actor", "inspectedAt", "passed", "overallResult", "job_id"],
)
def test_manual_inspection_draft_cannot_claim_confirmation_or_automatic_check(field: str) -> None:
    raw = draft_values(CASES[6])
    cast(dict[str, object], raw["request"])[field] = True
    with pytest.raises(ValidationError):
        parse_rework_approval_draft(raw)


def test_new_draft_cannot_enter_old_confirmation_request() -> None:
    from app.schemas.approval_execution import ApprovalConfirmationRequest

    with pytest.raises(ValidationError):
        ApprovalConfirmationRequest.model_validate({"draft": draft_values(CASES[7])})


def test_comment_limit_remains_java_utf16_without_normalizing_original_text() -> None:
    raw = draft_values(CASES[2])
    cast(dict[str, object], raw["request"])["reason"] = "🚀" * 500
    assert (
        parse_rework_approval_draft(raw).request.model_dump(by_alias=True)["reason"] == "🚀" * 500
    )
    cast(dict[str, object], raw["request"])["reason"] = "🚀" * 501
    with pytest.raises(ValidationError):
        parse_rework_approval_draft(raw)


def test_registry_map_cannot_be_reassigned_and_all_operation_literals_are_covered() -> None:
    assert set(REWORK_APPROVAL_TOOLS) == {case.operation for case in CASES}
    with pytest.raises(TypeError):
        cast(dict[ReworkOperation, str], REWORK_APPROVAL_TOOLS)["START_REWORK"] = (
            "submit_rework_review"
        )
