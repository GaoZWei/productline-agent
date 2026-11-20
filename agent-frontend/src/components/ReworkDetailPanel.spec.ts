import MockAdapter from "axios-mock-adapter";
import { createApp, h, nextTick, reactive, type App } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import ReworkDetailPanel from "./ReworkDetailPanel.vue";
import { agentHttpClient } from "../api/agentClient";
import { businessHttpClient } from "../api/businessClient";
import { detailFixture, envelope, historyPage, inspectionFixture, processingFixture, reviewFixture, reworkPath } from "../test/reworkFixtures";

const mock = new MockAdapter(businessHttpClient);
const agent = new MockAdapter(agentHttpClient);
let app: App | undefined;
let host: HTMLDivElement;
afterEach(() => {
  app?.unmount();
  app = undefined;
  host?.remove();
  mock.reset();
  agent.reset();
  sessionStorage.clear();
});
async function settle() { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick(); }
function setup(detail = detailFixture()) {
  mock.onGet(reworkPath).reply(200, envelope(detail));
  for (const kind of ["results", "inspections", "reviews"]) mock.onGet(`${reworkPath}/${kind}`).reply(200, envelope(historyPage()));
}
async function mount() {
  const props = reactive({ orderId: "ORDER-030", taskId: "TASK-030-A", reworkId: "REWORK-Z9" });
  host = document.createElement("div"); document.body.append(host);
  // 由父级响应式props驱动，覆盖切换与迟到响应，不修改子组件内部状态。
  app = createApp({ render: () => h(ReworkDetailPanel, props) }); app.mount(host);
  await settle(); return props;
}
function button(label: string, root: ParentNode = host) {
  const item = [...root.querySelectorAll<HTMLButtonElement>("button")].find(item => item.textContent?.trim() === label);
  expect(item).toBeTruthy(); return item!;
}

describe("返工详情与历史", () => {
  it("展示第二轮真实绑定及Java允许动作，材料安全原样展示", async () => {
    setup(); await mount();
    expect(host.textContent).toContain("第 2 轮");
    expect(host.textContent).toContain("REWORK-A1");
    expect(host.textContent).toContain("需要再次处理");
    expect(host.textContent).toContain("001.0");
    expect(host.textContent).toContain("javascript:证据只作文本");
    expect(host.querySelector("a")).toBeNull();
    expect(host.querySelector('[aria-label="Java允许动作"]')?.textContent).toContain("创建下一轮返工");
    expect(host.querySelector('[aria-label="Java允许动作"]')?.textContent).not.toContain("开始返工");
    expect(host.textContent).toContain("本轮完成不等于最终验收");
    expect(mock.history.post).toHaveLength(0);
  });
  it("按序号加载多页，错误后重试原游标，不从历史通过重算当前结论", async () => {
    setup();
    let calls = 0;
    mock.onGet(`${reworkPath}/results`).reply(() => {
      calls++;
      if (calls === 1) return [200, envelope(historyPage([processingFixture(1)], "next/+=="))];
      if (calls === 2) return [503, { ...envelope(null), success: false, code: "UPSTREAM_ERROR", message: "busy" }];
      return [200, envelope(historyPage([processingFixture(2)]))];
    });
    mock.onGet(`${reworkPath}/reviews`).reply(200, envelope(historyPage([{ ...reviewFixture(), status: "APPROVED" }])));
    await mount();
    const section = host.querySelector('[data-history-kind="results"]')!;
    button("加载更多", section).click(); button("加载更多", section).click(); await settle();
    expect(section.textContent).toContain("UPSTREAM_ERROR");
    expect(section.querySelectorAll(".rework-record")).toHaveLength(1);
    button("重试本页", section).click(); await settle();
    expect(section.querySelectorAll(".rework-record")).toHaveLength(2);
    expect(mock.history.get.filter(r => r.url?.endsWith("/results")).map(r => r.params.cursor)).toEqual([undefined, "next/+==", "next/+=="]);
    expect(host.querySelector('[aria-label="Java当前材料"]')?.textContent).toContain("REWORK_REQUIRED");
  });
  it.each(["overlap", "cycle", "wrongRound"])("历史异常%s不拼入坏记录", async change => {
    setup();
    const kind = change === "wrongRound" ? "inspections" : "results";
    const first = kind === "results" ? processingFixture(1) : inspectionFixture(1);
    const second = kind === "results" ? processingFixture(change === "overlap" ? 1 : 2) : { ...inspectionFixture(2), roundNumber: 1 };
    mock.onGet(`${reworkPath}/${kind}`).reply(config => [200, envelope(config.params.cursor === undefined
      ? historyPage([first], "next") : historyPage([second], change === "cycle" ? "next" : null))]);
    await mount();
    const section = host.querySelector(`[data-history-kind="${kind}"]`)!;
    button("加载更多", section).click(); await settle();
    expect(section.textContent).toContain("RESPONSE_VALIDATION_ERROR");
    expect(section.querySelectorAll(".rework-record")).toHaveLength(1);
  });
  it("存量记录明确缺证据，空历史不生成通过或第一轮", async () => {
    const value = detailFixture();
    Object.assign(value, { roundNumber: null, previousReworkTaskId: null, processing: null, inspection: null, review: null, allowedActions: [] });
    setup(value); await mount();
    expect(host.textContent).toContain("存量记录，未登记轮次");
    expect(host.textContent).toContain("存量记录缺少处理证据");
    expect(host.textContent).not.toContain("第 1 轮");
    expect(host.textContent).not.toContain("APPROVED");
  });
  it("切换返工和卸载隔离迟到详情及历史", async () => {
    setup(); let resolveOld!: (value: [number, unknown]) => void;
    mock.onGet(`${reworkPath}/results`).reply(() => new Promise(resolve => { resolveOld = resolve; }));
    const props = await mount();
    const next = detailFixture(); next.reworkTask.reworkTaskId = "REWORK-A1";
    Object.assign(next, { roundNumber: 1, previousReworkTaskId: null, processing: null, inspection: null, review: null, allowedActions: ["START_REWORK"] });
    const path = reworkPath.replace("REWORK-Z9", "REWORK-A1");
    mock.onGet(path).reply(200, envelope(next));
    for (const kind of ["results", "inspections", "reviews"]) mock.onGet(`${path}/${kind}`).reply(200, envelope({ ...historyPage(), reworkTaskId: "REWORK-A1" }));
    props.reworkId = "REWORK-A1"; await settle();
    resolveOld([200, envelope(historyPage([processingFixture(9)]))]); await settle();
    expect(host.textContent).toContain("第 1 轮");
    expect(host.textContent).not.toContain("处理修订 9");
    let resolveDetail!: (value: [number, unknown]) => void;
    mock.onGet(reworkPath).reply(() => new Promise(resolve => { resolveDetail = resolve; }));
    props.reworkId = "REWORK-Z9"; await settle();
    app?.unmount(); app = undefined;
    resolveDetail([200, envelope(detailFixture())]); await settle();
    expect(host.textContent).toBe("");
  });
  it("详情失败不展示旧材料，刷新后重新读取历史首屏", async () => {
    setup(); await mount();
    let reads = 0;
    mock.onGet(reworkPath).reply(() => ++reads === 1
      ? [403, { ...envelope(null, "denied-trace"), success: false, code: "PERMISSION_DENIED", message: "denied" }]
      : [200, envelope(detailFixture())]);
    button("刷新详情").click(); await settle();
    expect(host.textContent).toContain("PERMISSION_DENIED");
    expect(host.textContent).toContain("denied-trace");
    expect(host.querySelector('[aria-label="Java当前材料"]')).toBeNull();
    button("刷新详情").click(); await settle();
    expect(host.querySelectorAll(".rework-history")).toHaveLength(3);
    expect(mock.history.get.filter(r => r.url?.endsWith("/results"))).toHaveLength(2);
  });
});

const previewPath = "/api/agent/rework-actions/preview";
const decisionPath = "/api/agent/rework-actions/run-t832/approval-t832";

function actionDetail() {
  return {
    ...detailFixture(),
    processing: null,
    inspection: null,
    review: null,
    allowedActions: ["START_REWORK", "REGISTER_REWORK_RESULT"] as const,
  };
}

function previewResponse(operation: string, request: object = {}, version = 12) {
  return {
    run_id: "run-t832", approval_id: "approval-t832", order_id: "ORDER-030",
    expires_at: "2026-11-20T08:30:00Z",
    review: {
      draft: {
        operation,
        target: {
          task_id: "TASK-030-A", rework_task_id: "REWORK-Z9", task_version: version,
          round_number: 2, previous_rework_task_id: "REWORK-A1", source_issue_id: "ISSUE-030-A",
          processing_revision: null, artifact: null, inspection_id: null, review_id: null,
        },
        request: { expectedVersion: version, ...request },
      },
      effect_semantics: "EXPECTED_IF_JAVA_ACCEPTS",
      expected_effects: {
        production_status_after: "COMPLETED", rework_status_after: "RUNNING",
        issue_status_after: "PROCESSING", delivery_effect: "NONE",
      },
    },
  };
}

function enterMaterial(label: string, value: string, root: ParentNode = host) {
  const field = [...root.querySelectorAll("label")].find(item => item.textContent?.startsWith(label))
    ?.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>("input, textarea, select");
  expect(field).toBeTruthy();
  field!.value = value;
  field!.dispatchEvent(new Event(field!.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
}

describe("返工操作预览与确认", () => {
  it("预览不确认，双击只提交一次，成功后重新读取Java详情", async () => {
    const detail = actionDetail();
    setup({ ...detail, allowedActions: [...detail.allowedActions] });
    agent.onPost(previewPath).reply(200, previewResponse("START_REWORK"));
    agent.onPost(`${decisionPath}/confirm`).reply(200, {
      approval_id: "approval-t832", outcome: "SUCCEEDED", operation_id: "OP-T832",
    });
    await mount();
    button("开始返工").click();
    await settle();
    button("预览操作").click();
    await settle();
    expect(agent.history.post.map(item => item.url)).toEqual([previewPath]);
    expect(JSON.parse(agent.history.post[0]!.data)).toEqual({
      order_id: "ORDER-030",
      command: { task_id: "TASK-030-A", rework_task_id: "REWORK-Z9", operation: "START_REWORK" },
    });
    expect(host.textContent).toContain("第 2 轮 · 任务版本 12");
    const confirm = button("确认并执行");
    confirm.click();
    confirm.click();
    await settle();
    expect(agent.history.post.map(item => item.url)).toEqual([previewPath, `${decisionPath}/confirm`]);
    expect(JSON.parse(agent.history.post[1]!.data)).toEqual({ decision: "CONFIRM" });
    expect(host.textContent).toContain("OP-T832");
    expect(mock.history.get.filter(item => item.url === reworkPath)).toHaveLength(2);
  });

  it("成果证据必填并保留原文，取消只调用原审批取消入口", async () => {
    const detail = actionDetail();
    setup({ ...detail, allowedActions: [...detail.allowedActions] });
    const material = {
      artifact: { artifactId: "成果甲", artifactVersion: "001.0" },
      processingComment: "  保留原说明  ",
      evidenceReferences: ["report:甲", "javascript:只作为文本"],
    };
    agent.onPost(previewPath).reply(200, previewResponse("REGISTER_REWORK_RESULT", material));
    agent.onPost(`${decisionPath}/cancel`).reply(200, { approval_id: "approval-t832", status: "CANCELLED" });
    await mount();
    button("登记成果").click();
    await settle();
    enterMaterial("成果标识", material.artifact.artifactId);
    enterMaterial("成果版本", material.artifact.artifactVersion);
    enterMaterial("处理说明", material.processingComment);
    host.querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await settle();
    expect(agent.history.post).toHaveLength(0);
    enterMaterial("证据引用", material.evidenceReferences.join("\n"));
    button("预览操作").click();
    await settle();
    const command = JSON.parse(agent.history.post[0]!.data).command;
    expect(command.processing_comment).toBe(material.processingComment);
    expect(command.evidence_references).toEqual(material.evidenceReferences);
    expect(host.textContent).toContain(material.evidenceReferences[1]);
    expect(host.querySelector("a")).toBeNull();
    button("取消操作").click();
    await settle();
    expect(agent.history.post.map(item => item.url)).toEqual([previewPath, `${decisionPath}/cancel`]);
    expect(host.querySelector('[aria-label="返工操作预览"]')).toBeNull();
  });

  it.each(["unknown", "network"])("提交结果%s保留审批编号且没有再次提交入口", async failure => {
    const detail = actionDetail();
    setup({ ...detail, allowedActions: [...detail.allowedActions] });
    agent.onPost(previewPath).reply(200, previewResponse("START_REWORK"));
    const confirmation = agent.onPost(`${decisionPath}/confirm`);
    if (failure === "network") confirmation.networkError();
    else confirmation.reply(200, { approval_id: "approval-t832", outcome: "UNKNOWN", operation_id: null });
    await mount();
    button("开始返工").click();
    await settle();
    button("预览操作").click();
    await settle();
    button("确认并执行").click();
    await settle();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("approval-t832");
    expect(host.textContent).not.toContain("确认并执行");
    expect(agent.history.post).toHaveLength(2);
  });

  it("预览版本已变化时取消草稿并要求刷新", async () => {
    const detail = actionDetail();
    setup({ ...detail, allowedActions: [...detail.allowedActions] });
    agent.onPost(previewPath).reply(200, previewResponse("START_REWORK", {}, 13));
    agent.onPost(`${decisionPath}/cancel`).reply(200, { approval_id: "approval-t832", status: "CANCELLED" });
    await mount();
    button("开始返工").click();
    await settle();
    button("预览操作").click();
    await settle();
    expect(agent.history.post.map(item => item.url)).toEqual([previewPath, `${decisionPath}/cancel`]);
    expect(host.textContent).toContain("刷新后重新核对");
    expect(host.textContent).not.toContain("确认并执行");
  });

  it("切换返工后迟到的成功回执不刷新当前详情", async () => {
    const detail = actionDetail();
    setup({ ...detail, allowedActions: [...detail.allowedActions] });
    mock.onGet("/api/tasks/TASK-030-A/reworks/REWORK-A1").reply(200, envelope({
      ...detail, previousReworkTaskId: null, roundNumber: 1, allowedActions: [],
      reworkTask: { ...detail.reworkTask, reworkTaskId: "REWORK-A1" },
    }));
    agent.onPost(previewPath).reply(200, previewResponse("START_REWORK"));
    let complete!: (response: [number, object]) => void;
    agent.onPost(`${decisionPath}/confirm`).reply(() => new Promise(resolve => { complete = resolve; }));
    const props = await mount();
    button("开始返工").click();
    await settle();
    button("预览操作").click();
    await settle();
    button("确认并执行").click();
    await settle();
    props.reworkId = "REWORK-A1";
    await settle();
    complete([200, { approval_id: "approval-t832", outcome: "SUCCEEDED", operation_id: "OP-T832" }]);
    await settle();
    expect(host.textContent).not.toContain("操作已登记");
    expect(mock.history.get.filter(item => item.url === "/api/tasks/TASK-030-A/reworks/REWORK-A1")).toHaveLength(1);
  });
});

function qualityPreview(
  detail: ReturnType<typeof detailFixture>,
  operation: "REGISTER_REWORK_INSPECTION" | "SUBMIT_REWORK_REVIEW",
  request: object,
  reworkStatus: string,
  issueStatus: string,
  deliveryEffect = "NONE",
) {
  const value = previewResponse(operation, request);
  return {
    ...value,
    bound_materials: {
      processing: detail.processing,
      inspection: operation === "SUBMIT_REWORK_REVIEW" ? detail.inspection : null,
    },
    review: {
      ...value.review,
      draft: {
        ...value.review.draft,
        target: {
          ...value.review.draft.target,
          processing_revision: detail.processing?.processingRevision ?? null,
          artifact: detail.processing?.artifact ?? null,
          inspection_id: detail.inspection?.inspectionId ?? null,
        },
      },
      expected_effects: {
        production_status_after: "COMPLETED",
        rework_status_after: reworkStatus,
        issue_status_after: issueStatus,
        delivery_effect: deliveryEffect,
      },
    },
  };
}

describe("人工检查与再次复核", () => {
  it("检查项分别填写，缺证据不能预览，预览可核对失败项及绑定成果", async () => {
    const detail = detailFixture();
    detail.reworkTask.status = "RUNNING";
    detail.issueStatus = "PROCESSING";
    detail.inspection = detail.review = null;
    detail.allowedActions = ["REGISTER_REWORK_INSPECTION"];
    setup(detail);
    const items = [
      { checkItem: "坐标系", result: "PASSED", comment: "人工核对", evidenceReferences: ["report:check-1"] },
      { checkItem: "边界", result: "FAILED", comment: "  保留异常说明  ", evidenceReferences: ["report:check-2"] },
    ];
    agent.onPost(previewPath).reply(200, qualityPreview(
      detail, "REGISTER_REWORK_INSPECTION", { processingRevision: 1, items }, "RUNNING", "PROCESSING",
    ));
    agent.onPost(`${decisionPath}/cancel`).reply(200, { approval_id: "approval-t832", status: "CANCELLED" });
    await mount();
    button("登记人工检查").click();
    await settle();
    button("添加检查项").click();
    await settle();
    const rows = [...host.querySelectorAll("fieldset.rework-check-item")];
    expect(rows).toHaveLength(2);
    items.forEach((item, index) => {
      const row = rows[index]!;
      enterMaterial("检查项名称", item.checkItem, row);
      enterMaterial("检查结果", item.result, row);
      enterMaterial("检查说明", item.comment, row);
    });
    enterMaterial("检查证据引用", "report:check-1", rows[0]!);
    host.querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await settle();
    expect(agent.history.post).toHaveLength(0);
    enterMaterial("检查证据引用", "report:check-2", rows[1]!);
    button("预览操作").click();
    await settle();
    expect(JSON.parse(agent.history.post[0]!.data).command).toEqual({
      operation: "REGISTER_REWORK_INSPECTION", task_id: "TASK-030-A", rework_task_id: "REWORK-Z9", items,
    });
    const card = host.querySelector('[aria-label="返工操作预览"]')!;
    expect(card.textContent).toContain("处理修订 1");
    expect(card.textContent).toContain("javascript:证据只作文本");
    expect(card.textContent).toContain("边界 · 失败");
    expect(card.textContent).toContain("登记失败检查后，问题仍待处理");
    expect(card.querySelector("a")).toBeNull();
    button("取消操作", card).click();
    await settle();
    expect(agent.history.post.map(item => item.url)).toEqual([previewPath, `${decisionPath}/cancel`]);
  });

  it("复核通过预览显示检查证据，过时审批只能刷新重审", async () => {
    const detail = detailFixture();
    detail.issueStatus = "RESOLVED";
    detail.review = null;
    detail.allowedActions = ["SUBMIT_REWORK_REVIEW"];
    setup(detail);
    const preview = qualityPreview(
      detail, "SUBMIT_REWORK_REVIEW", {
        processingRevision: 1, inspectionId: "INSPECT-1", status: "APPROVED", reviewComment: "  同意结案  ",
      }, "COMPLETED", "CLOSED", "RECHECK_ONLY",
    );
    const boundInspection = preview.bound_materials.inspection!;
    preview.bound_materials.inspection = {
      ...boundInspection,
      items: [{ ...boundInspection.items[0]!, evidenceReferences: ["report:approval-snapshot"] }],
    };
    agent.onPost(previewPath).reply(200, preview);
    agent.onPost(`${decisionPath}/confirm`).reply(409, { detail: { code: "APPROVAL_STALE", trace_id: "trace-old" } });
    await mount();
    button("再次复核").click();
    await settle();
    enterMaterial("复核意见", "  同意结案  ");
    host.querySelector("form")!.dispatchEvent(new Event("submit", { cancelable: true }));
    await settle();
    expect(agent.history.post).toHaveLength(0);
    enterMaterial("复核结论", "APPROVED");
    button("预览操作").click();
    await settle();
    expect(JSON.parse(agent.history.post[0]!.data).command).toEqual({
      operation: "SUBMIT_REWORK_REVIEW", task_id: "TASK-030-A", rework_task_id: "REWORK-Z9",
      status: "APPROVED", review_comment: "  同意结案  ",
    });
    const card = host.querySelector('[aria-label="返工操作预览"]')!;
    expect(card.textContent).toContain("INSPECT-1");
    expect(card.textContent).toContain("report:approval-snapshot");
    expect(card.textContent).not.toContain("evidence://检查原件");
    expect(card.textContent).toContain("复核通过后仍需核查其他交付条件");
    button("确认并执行", card).click();
    await settle();
    expect(host.querySelector('[aria-label="返工操作预览"]')).toBeNull();
    button("刷新后重新核对").click();
    await settle();
    expect(mock.history.get.filter(item => item.url === reworkPath)).toHaveLength(2);
    expect(agent.history.post).toHaveLength(2);
  });

  it("复核预览携带其他检查的证据时不开放确认", async () => {
    const detail = detailFixture();
    detail.issueStatus = "RESOLVED";
    detail.review = null;
    detail.allowedActions = ["SUBMIT_REWORK_REVIEW"];
    setup(detail);
    const preview = qualityPreview(
      detail, "SUBMIT_REWORK_REVIEW", {
        processingRevision: 1, inspectionId: "INSPECT-1", status: "REJECTED", reviewComment: "成果需修正",
      }, "COMPLETED", "OPEN",
    );
    preview.bound_materials.inspection = { ...detail.inspection!, inspectionId: "INSPECT-OTHER" };
    agent.onPost(previewPath).reply(200, preview);
    await mount();
    button("再次复核").click();
    await settle();
    enterMaterial("复核结论", "REJECTED");
    enterMaterial("复核意见", "成果需修正");
    button("预览操作").click();
    await settle();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("RESPONSE_VALIDATION_ERROR");
    expect(host.querySelector('[aria-label="返工操作预览"]')).toBeNull();
    expect(agent.history.post.map(item => item.url)).toEqual([previewPath]);
  });
});

describe("下一轮返工与结果核对", () => {
  it("独立预览绑定上一轮退回记录，确认后展示新编号并保留旧历史", async () => {
    const detail = detailFixture();
    setup(detail);
    const value = previewResponse("CREATE_NEXT_REWORK", { reason: "  修正范围边界  " });
    agent.onPost(previewPath).reply(200, {
      ...value,
      previous_review: detail.review,
      review: {
        ...value.review,
        draft: {
          ...value.review.draft,
          target: {
            ...value.review.draft.target,
            processing_revision: detail.processing!.processingRevision,
            artifact: detail.processing!.artifact,
            inspection_id: detail.inspection!.inspectionId,
            review_id: detail.review!.reviewId,
          },
        },
        expected_effects: {
          ...value.review.expected_effects, rework_status_after: "PENDING", issue_status_after: "OPEN",
        },
      },
    });
    agent.onPost(`${decisionPath}/confirm`).reply(200, {
      approval_id: "approval-t832", outcome: "SUCCEEDED", operation_id: "OP-T834",
      next_rework_task_id: "REWORK-NEXT",
    });
    await mount();
    button("创建下一轮返工").click();
    await settle();
    enterMaterial("原因", "  修正范围边界  ");
    button("预览操作").click();
    await settle();
    expect(agent.history.post.map(item => item.url)).toEqual([previewPath]);
    expect(JSON.parse(agent.history.post[0]!.data).command).toEqual({
      operation: "CREATE_NEXT_REWORK", task_id: "TASK-030-A", rework_task_id: "REWORK-Z9",
      reason: "  修正范围边界  ",
    });
    expect(host.querySelector('[aria-label="上一轮复核"]')?.textContent).toContain("需要再次处理");
    button("确认并执行").click();
    await settle();
    expect(button("查看下一轮 REWORK-NEXT")).toBeTruthy();
    expect(host.querySelector('[aria-label="Java当前材料"]')?.textContent).toContain("REWORK_REQUIRED");
    expect(agent.history.post).toHaveLength(2);
  });

  it("丢响应后跨页面核对原审批，没有回执时持续待核对", async () => {
    setup({ ...actionDetail(), allowedActions: ["START_REWORK"] });
    agent.onPost(previewPath).reply(200, previewResponse("START_REWORK"));
    agent.onPost(`${decisionPath}/confirm`).networkError();
    let lookups = 0;
    agent.onPost(`${decisionPath}/reconcile`).reply(() => ++lookups === 1
      ? [200, { approval_id: "approval-t832", outcome: "UNKNOWN", operation_id: null }]
      : [200, { approval_id: "approval-t832", outcome: "SUCCEEDED", operation_id: "OP-RECOVERED" }]);
    await mount();
    button("开始返工").click();
    await settle();
    button("预览操作").click();
    await settle();
    button("确认并执行").click();
    await settle();
    app?.unmount();
    host.remove();
    await mount();
    expect(host.textContent).toContain("待核对审批 approval-t832");
    expect(host.textContent).not.toContain("确认并执行");
    button("核对原审批结果").click();
    await settle();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("执行结果待核对");
    button("核对原审批结果").click();
    await settle();
    expect(host.textContent).toContain("OP-RECOVERED");
    expect(host.querySelector('[aria-label="原审批结果核对"]')).toBeNull();
    expect(agent.history.post.map(item => item.url)).toEqual([
      previewPath, `${decisionPath}/confirm`, `${decisionPath}/reconcile`, `${decisionPath}/reconcile`,
    ]);
    expect(JSON.parse(agent.history.post[2]!.data)).toEqual({
      order_id: "ORDER-030", task_id: "TASK-030-A", rework_task_id: "REWORK-Z9",
    });
  });

  it("切单后丢弃核对迟到结果，回原页面仍能找到审批", async () => {
    setup({ ...actionDetail(), allowedActions: ["START_REWORK"] });
    agent.onPost(previewPath).reply(200, previewResponse("START_REWORK"));
    agent.onPost(`${decisionPath}/confirm`).networkError();
    let complete!: (response: [number, object]) => void;
    agent.onPost(`${decisionPath}/reconcile`).reply(() => new Promise(resolve => { complete = resolve; }));
    const props = await mount();
    button("开始返工").click();
    await settle();
    button("预览操作").click();
    await settle();
    button("确认并执行").click();
    await settle();
    button("核对原审批结果").click();
    await settle();
    props.orderId = "ORDER-OTHER";
    await settle();
    complete([200, { approval_id: "approval-t832", outcome: "SUCCEEDED", operation_id: "OP-LATE" }]);
    await settle();
    expect(host.textContent).not.toContain("OP-LATE");
    expect(host.querySelector('[aria-label="原审批结果核对"]')).toBeNull();
    props.orderId = "ORDER-030";
    await settle();
    expect(host.textContent).toContain("待核对审批 approval-t832");
  });
});
