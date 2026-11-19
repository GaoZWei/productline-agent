import MockAdapter from "axios-mock-adapter";
import { afterEach, describe, expect, it } from "vitest";
import { businessHttpClient } from "./businessClient";
import { fetchReworkDetail, fetchReworkHistory } from "./reworkClient";
import { detailFixture, envelope, historyPage, inspectionFixture, processingFixture, reviewFixture, reworkPath } from "../test/reworkFixtures";

const mock = new MockAdapter(businessHttpClient);
afterEach(() => mock.reset());
describe("返工只读Client", () => {
  it("查询真实路径、身份及原样材料，不发送写请求", async () => {
    mock.onGet(reworkPath).reply(200, envelope(detailFixture()));
    const response = await fetchReworkDetail("TASK-030-A", "REWORK-Z9");
    expect(response.data).toEqual(detailFixture());
    expect(response.traceId).toBe("trace-t831");
    expect(response.data.processing?.artifact.artifactVersion).toBe("001.0");
    expect(mock.history.get[0]?.headers).toMatchObject({ "X-User-Id": "reviewer-001", "X-User-Role": "REVIEWER" });
    expect(mock.history.post).toHaveLength(0);
  });
  it("保留Java允许的非换行空格材料，不按JS trim改写或拒绝", async () => {
    const value = detailFixture();
    value.processing!.artifact.artifactId = "\u00a0";
    value.processing!.processingComment = "\u00a0";
    mock.onGet(reworkPath).reply(200, envelope(value));
    expect((await fetchReworkDetail("TASK-030-A", "REWORK-Z9")).data.processing).toEqual(value.processing);
  });
  it.each(["results", "inspections", "reviews"] as const)("%s按Java序号读取单页，游标原样传递", async kind => {
    const records = { results: [processingFixture()], inspections: [inspectionFixture()], reviews: [reviewFixture()] }[kind];
    mock.onGet(`${reworkPath}/${kind}`).reply(200, envelope(historyPage(records, "next/+==")));
    const response = await fetchReworkHistory("TASK-030-A", "REWORK-Z9", kind, " first/+== ");
    expect(response.data.records).toEqual(records);
    expect(mock.history.get[0]?.params).toEqual({ limit: 20, cursor: " first/+== " });
    expect(mock.history.get).toHaveLength(1);
  });
  it.each(["wrongTask", "wrongRework", "extra", "missing", "unsafeVersion", "booleanRound", "unknownAction", "duplicateAction", "wrongInspection", "wrongReview", "legacyEvidence", "contradictoryInspection"])("拒绝不可信详情：%s", async change => {
    const source = detailFixture();
    const value: Record<string, unknown> = { ...source };
    if (change === "wrongTask") source.reworkTask.taskId = "TASK-OTHER";
    if (change === "wrongRework") source.reworkTask.reworkTaskId = "REWORK-OTHER";
    if (change === "extra") value.writeToken = "must-not-accept";
    if (change === "missing") delete value.review;
    if (change === "unsafeVersion") value.taskVersion = Number.MAX_SAFE_INTEGER + 1;
    if (change === "booleanRound") value.roundNumber = true;
    if (change === "unknownAction") value.allowedActions = ["AUTO_REPAIR"];
    if (change === "duplicateAction") source.allowedActions.push("CREATE_NEXT_REWORK");
    if (change === "wrongInspection") source.inspection!.processingRevision = 2;
    if (change === "wrongReview") source.review!.inspectionId = "INSPECT-OTHER";
    if (change === "legacyEvidence") value.roundNumber = null;
    if (change === "contradictoryInspection") source.inspection!.items[0]!.result = "FAILED";
    mock.onGet(reworkPath).reply(200, envelope(value));
    await expect(fetchReworkDetail("TASK-030-A", "REWORK-Z9")).rejects.toMatchObject({ code: "RESPONSE_VALIDATION_ERROR", traceId: "trace-t831", retryable: false });
    expect(mock.history.get).toHaveLength(1);
  });
  it.each(["wrongOwner", "reverse", "duplicate", "emptyCursor", "emptyPageCursor", "unsafeSequence", "missingCursor"])("拒绝不可信历史：%s", async change => {
    const records = [processingFixture(1), processingFixture(2)];
    const value: Record<string, unknown> = { ...historyPage(records) };
    if (change === "wrongOwner") value.reworkTaskId = "REWORK-OTHER";
    if (change === "reverse") records.reverse();
    if (change === "duplicate") records[1]!.processingRevision = 1;
    if (change === "emptyCursor") value.nextCursor = "";
    if (change === "emptyPageCursor") { value.records = []; value.nextCursor = "cursor"; }
    if (change === "unsafeSequence") records[1]!.processingRevision = Number.MAX_SAFE_INTEGER + 1;
    if (change === "missingCursor") delete value.nextCursor;
    mock.onGet(`${reworkPath}/results`).reply(200, envelope(value));
    await expect(fetchReworkHistory("TASK-030-A", "REWORK-Z9", "results")).rejects.toMatchObject({ code: "RESPONSE_VALIDATION_ERROR" });
  });
  it("存量显式null/空数组保持，不补造轮次或检查", async () => {
    const value = detailFixture();
    Object.assign(value, { roundNumber: null, previousReworkTaskId: null, processing: null, inspection: null, review: null, allowedActions: [] });
    mock.onGet(reworkPath).reply(200, envelope(value));
    expect((await fetchReworkDetail("TASK-030-A", "REWORK-Z9")).data).toEqual(value);
  });
  it.each([403, 404, 409])("保留Java %s错误与Trace，不重试", async status => {
    mock.onGet(reworkPath).reply(status, { ...envelope(null, "java-denied"), success: false, code: "JAVA_DENIED", message: "denied" });
    await expect(fetchReworkDetail("TASK-030-A", "REWORK-Z9")).rejects.toMatchObject({ code: "JAVA_DENIED", status, traceId: "java-denied" });
    expect(mock.history.get).toHaveLength(1);
  });
  it("参数失败零请求，网络故障不自动重试", async () => {
    await expect(fetchReworkDetail("TASK-030-A/../X", "REWORK-Z9")).rejects.toMatchObject({ code: "PARAM_VALIDATION_ERROR" });
    await expect(fetchReworkDetail("TASK-030-A\n", "REWORK-Z9")).rejects.toMatchObject({ code: "PARAM_VALIDATION_ERROR" });
    await expect(fetchReworkHistory("TASK-030-A", "REWORK-Z9", "results", "\n")).rejects.toMatchObject({ code: "PARAM_VALIDATION_ERROR" });
    expect(mock.history.get).toHaveLength(0);
    mock.onGet(reworkPath).networkError();
    await expect(fetchReworkDetail("TASK-030-A", "REWORK-Z9")).rejects.toMatchObject({ code: "NETWORK_ERROR" });
    expect(mock.history.get).toHaveLength(1);
  });
});
