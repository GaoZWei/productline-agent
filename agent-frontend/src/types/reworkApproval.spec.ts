import { describe, expect, expectTypeOf, it } from "vitest";

import {
  REWORK_APPROVAL_TOOLS,
  type ManagedReworkTarget,
  type ReworkApprovalDraft,
  type ReworkDraftReview,
} from "./reworkApproval";

describe("M8独立确认类型契约", () => {
  it("九类动作固定对应已有写Tool，不把旧创建或复核动作当作新确认", () => {
    expect(REWORK_APPROVAL_TOOLS).toEqual({
      CREATE_LIFECYCLE_REWORK: "create_lifecycle_rework", START_REWORK: "start_rework",
      BLOCK_REWORK: "block_rework", FAIL_REWORK: "fail_rework", RESUME_REWORK: "resume_rework",
      REGISTER_REWORK_RESULT: "register_rework_result", REGISTER_REWORK_INSPECTION: "register_rework_inspection",
      SUBMIT_REWORK_REVIEW: "submit_rework_review", CREATE_NEXT_REWORK: "create_next_rework",
    });
    expect(Object.keys(REWORK_APPROVAL_TOOLS)).toHaveLength(9);
  });

  it("再次复核需要当前材料和检查，类型不能混用开始请求或权限", () => {
    type ReviewDraft = Extract<ReworkApprovalDraft, { operation: "SUBMIT_REWORK_REVIEW" }>;
    type ReviewPackage = Extract<ReworkDraftReview, { pending_tool: "submit_rework_review" }>;
    expectTypeOf<ReviewPackage["required_permission"]>().toEqualTypeOf<"REVIEW_WRITE">();
    expectTypeOf<ReviewDraft["target"]["artifact"]>().not.toBeNullable();
    expectTypeOf<ReviewDraft["target"]["inspection_id"]>().toEqualTypeOf<string>();
    expectTypeOf<ReviewDraft["request"]["status"]>().toEqualTypeOf<"APPROVED" | "REJECTED" | "REWORK_REQUIRED">();
    expectTypeOf<Extract<ReworkApprovalDraft, { operation: "START_REWORK" }>["request"]>()
      .toEqualTypeOf<{ readonly expectedVersion: number }>();
  });

  it("开始草稿仅描述待审查内容，缺失绑定必须显式null", () => {
    const target: ManagedReworkTarget = {
      task_id: "TASK-T826", task_version: 4, source_issue_id: "ISSUE-T826",
      rework_task_id: "REWORK-T826", round_number: 1, previous_rework_task_id: null,
      processing_revision: null, artifact: null, inspection_id: null, review_id: null,
    };
    const draft = { operation: "START_REWORK", target, request: { expectedVersion: 4 } } as const satisfies ReworkApprovalDraft;
    expect(draft.target.artifact).toBeNull();
    expect(draft).not.toHaveProperty("confirmed");
    expect(draft).not.toHaveProperty("approval_id");
    // @ts-expect-error 检查草稿必须有人工检查项，不能只传版本。
    const badInspection: Extract<ReworkApprovalDraft, { operation: "REGISTER_REWORK_INSPECTION" }>["request"] = { expectedVersion: 4 };
    // @ts-expect-error 旧确认动作不属于M8独立动作。
    const oldOperation: ReworkApprovalDraft["operation"] = "SUBMIT_REVIEW";
    expect(badInspection).toEqual({ expectedVersion: 4 });
    expect(oldOperation).toBe("SUBMIT_REVIEW");
  });
});
