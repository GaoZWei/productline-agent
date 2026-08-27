import { createApp, nextTick, type App } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ReviewApproval,
  ReviewApprovalDecision,
} from "../types/agent";
import ReviewApprovalCard from "./ReviewApprovalCard.vue";

let host: HTMLDivElement | undefined;
let application: App<Element> | undefined;

afterEach(() => {
  application?.unmount();
  host?.remove();
  application = undefined;
  host = undefined;
});

describe("Review approval card", () => {
  it("展示影响对象、问题摘要和可追溯规范引用", async () => {
    mountCard(createApproval());

    expect(host?.textContent).toContain("TASK-003");
    expect(host?.textContent).toContain("ISSUE-001");
    expect(host?.textContent).toContain("版本 7");
    expect(host?.textContent).toContain("存在未关闭的坐标系质量问题");
    expect(host?.textContent).toContain("坐标系统处理规范");
    expect(host?.textContent).toContain("版本 2.0");
    expect(host?.textContent).not.toContain("坐标系统问题关闭后方可重新提交复核");

    click('[data-testid="toggle-citation-content"]');
    await nextTick();

    expect(host?.textContent).toContain("坐标系统问题关闭后方可重新提交复核");
  });

  it("允许修改意见和结论，二次确认后只提交一次规范化草稿", async () => {
    const onConfirm = vi.fn<(decision: ReviewApprovalDecision) => void>();
    mountCard(createApproval(), { onConfirm });

    input('[data-testid="review-comment"]', "  用户确认先完成返工，再重新提交复核。  ");
    change('[data-testid="review-conclusion"]', "REJECTED");
    await nextTick();

    click('[data-testid="open-review-confirmation"]');
    click('[data-testid="open-review-confirmation"]');
    await nextTick();

    expect(host?.querySelectorAll('[role="alertdialog"]')).toHaveLength(1);
    expect(host?.textContent).toContain("确认提交复核结论？");
    expect(onConfirm).not.toHaveBeenCalled();

    click('[data-testid="confirm-review-decision"]');
    click('[data-testid="confirm-review-decision"]');
    await nextTick();

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledWith({
      approval_id: "APR-003",
      draft: {
        ...createApproval().draft,
        conclusion: "REJECTED",
        review_comment: "用户确认先完成返工，再重新提交复核。",
        suggested_rework: { required: false, type: null },
      },
    });
    expect(button('[data-testid="open-review-confirmation"]')?.disabled).toBe(true);
  });

  it("结论切换为需要返工时补齐稳定返工类型", async () => {
    const onConfirm = vi.fn<(decision: ReviewApprovalDecision) => void>();
    const approval = createApproval();
    approval.draft.conclusion = "APPROVED";
    approval.draft.suggested_rework = { required: false, type: null };
    mountCard(approval, { onConfirm });

    change('[data-testid="review-conclusion"]', "REWORK_REQUIRED");
    click('[data-testid="open-review-confirmation"]');
    await nextTick();
    click('[data-testid="confirm-review-decision"]');

    expect(onConfirm).toHaveBeenCalledWith(
      expect.objectContaining({
        draft: expect.objectContaining({
          conclusion: "REWORK_REQUIRED",
          suggested_rework: {
            required: true,
            type: "COORDINATE_SYSTEM_FIX",
          },
        }),
      }),
    );
  });

  it("取消操作只发出一次，不会误发确认", async () => {
    const onCancel = vi.fn<(approvalId: string) => void>();
    const onConfirm = vi.fn<(decision: ReviewApprovalDecision) => void>();
    mountCard(createApproval(), { onCancel, onConfirm });

    click('[data-testid="cancel-review-approval"]');
    click('[data-testid="cancel-review-approval"]');
    await nextTick();

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onCancel).toHaveBeenCalledWith("APR-003");
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("草稿不合法、状态不可确认或父级正在提交时禁用操作", async () => {
    mountCard(createApproval());

    input('[data-testid="review-comment"]', "   ");
    await nextTick();
    expect(button('[data-testid="open-review-confirmation"]')?.disabled).toBe(true);
    expect(host?.textContent).toContain("复核意见不能为空");

    remountCard({ ...createApproval(), status: "STALE" });
    expect(button('[data-testid="open-review-confirmation"]')?.disabled).toBe(true);
    expect(button('[data-testid="cancel-review-approval"]')?.disabled).toBe(true);

    remountCard(createApproval(), { submitting: true });
    expect(button('[data-testid="open-review-confirmation"]')?.disabled).toBe(true);
    expect(host?.textContent).toContain("正在提交确认");
  });
});

function createApproval(): ReviewApproval {
  return {
    approval_id: "APR-003",
    run_id: "RUN-003",
    status: "WAITING_CONFIRMATION",
    operation_type: "SUBMIT_REVIEW",
    target_id: "TASK-003",
    target_version: 7,
    draft: {
      task_id: "TASK-003",
      issue_id: "ISSUE-001",
      conclusion: "REWORK_REQUIRED",
      problem_summary: "存在未关闭的坐标系质量问题",
      review_comment: "建议完成坐标系统处理后重新提交复核",
      specification_references: [
        {
          document_id: "SPEC-COORD-001",
          document_name: "坐标系统处理规范",
          document_version: "2.0",
          section: ["质量复核", "坐标系统"],
          chunk_id: "CHUNK-COORD-001",
          chunk_ids: ["CHUNK-COORD-001"],
          content: "坐标系统问题关闭后方可重新提交复核。",
          relevance_score: 0.98,
        },
      ],
      suggested_rework: {
        required: true,
        type: "COORDINATE_SYSTEM_FIX",
      },
    },
  };
}

function mountCard(
  approval: ReviewApproval,
  options: {
    onConfirm?: (decision: ReviewApprovalDecision) => void;
    onCancel?: (approvalId: string) => void;
    submitting?: boolean;
  } = {},
) {
  host = document.createElement("div");
  document.body.append(host);
  application = createApp(ReviewApprovalCard, {
    approval,
    submitting: options.submitting ?? false,
    onConfirm: options.onConfirm,
    onCancel: options.onCancel,
  });
  application.mount(host);
}

function remountCard(
  approval: ReviewApproval,
  options: {
    onConfirm?: (decision: ReviewApprovalDecision) => void;
    onCancel?: (approvalId: string) => void;
    submitting?: boolean;
  } = {},
) {
  application?.unmount();
  host?.remove();
  application = undefined;
  host = undefined;
  mountCard(approval, options);
}

function button(selector: string) {
  return host?.querySelector<HTMLButtonElement>(selector);
}

function click(selector: string) {
  const element = button(selector);
  expect(element).toBeTruthy();
  element?.click();
}

function input(selector: string, value: string) {
  const element = host?.querySelector<HTMLTextAreaElement>(selector);
  expect(element).toBeTruthy();
  if (!element) return;
  element.value = value;
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

function change(selector: string, value: string) {
  const element = host?.querySelector<HTMLSelectElement>(selector);
  expect(element).toBeTruthy();
  if (!element) return;
  element.value = value;
  element.dispatchEvent(new Event("change", { bubbles: true }));
}
