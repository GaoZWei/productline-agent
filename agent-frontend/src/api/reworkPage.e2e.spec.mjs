// @vitest-environment node
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createWebServer } from "../../server.mjs";
import { businessHttpClient, requestBusinessData } from "./businessClient";
import { fetchReworkDetail, fetchReworkHistory } from "./reworkClient";

const javaUrl = process.env.AGENT_REWORK_QUERY_TEST_BUSINESS_URL;
const reworks = process.env.REWORK_PAGE_TEST_IDS?.split(",");
let server;
let methods = [];
let interceptor;
let originalBase;
let originalProxy;
describe.skipIf(!javaUrl || !reworks)("T831真实Java与页面代理", () => {
  beforeAll(async () => {
    server = createWebServer({ businessApiUrl: javaUrl });
    await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
    originalBase = businessHttpClient.defaults.baseURL;
    originalProxy = businessHttpClient.defaults.proxy;
    businessHttpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}/business-api`;
    businessHttpClient.defaults.proxy = false;
    interceptor = businessHttpClient.interceptors.request.use(config => { methods.push(config.method); return config; });
  });
  afterAll(async () => {
    businessHttpClient.defaults.baseURL = originalBase;
    businessHttpClient.defaults.proxy = originalProxy;
    businessHttpClient.interceptors.request.eject(interceptor);
    await new Promise(resolve => server.close(resolve));
  });
  it("真实两轮详情、22条分页、失败检查、退回历史和只读边界", async () => {
    const task = "TASK-T831-E2E";
    const second = await fetchReworkDetail(task, reworks[1]);
    expect(second.data.roundNumber).toBe(2);
    expect(second.data.previousReworkTaskId).toBe(reworks[0]);
    expect(second.data.processing.artifact.artifactVersion).toBe("002.0");
    expect(second.data.review).toBeNull();
    expect(second.data.allowedActions).toEqual(["SUBMIT_REWORK_REVIEW"]);
    const first = await fetchReworkDetail(task, reworks[0]);
    expect(first.data.review.status).toBe("REWORK_REQUIRED");
    expect(first.data.allowedActions).toEqual([]);
    const page1 = await fetchReworkHistory(task, reworks[0], "results");
    expect(page1.data.records).toHaveLength(20);
    expect(page1.data.nextCursor).toBeTypeOf("string");
    const page2 = await fetchReworkHistory(task, reworks[0], "results", page1.data.nextCursor);
    expect(page2.data.records.map(row => row.processingRevision)).toEqual([21, 22]);
    expect(page2.data.nextCursor).toBeNull();
    expect(page1.data.records[0].artifact.artifactVersion).toBe("001.0");
    const inspections = await fetchReworkHistory(task, reworks[0], "inspections");
    expect(inspections.data.records.map(row => row.result)).toEqual(["FAILED", "PASSED"]);
    const reviews = await fetchReworkHistory(task, reworks[0], "reviews");
    expect(reviews.data.records[0].status).toBe("REWORK_REQUIRED");
    await expect(fetchReworkDetail("TASK-003", reworks[0])).rejects.toMatchObject({ status: 409 });
    const overview = await requestBusinessData("/api/orders/ORDER-003/overview");
    expect(overview.data.tasks[0].task.status).toBe("COMPLETED");
    expect(overview.data.tasks[0].qualityIssues[0].issue.status).toBe("OPEN");
    expect(overview.data.tasks[0].qualityIssues[0].reviews[0].status).toBe("PENDING");
    expect(overview.data.deliveryRecords[0].status).toBe("BLOCKED");
    expect(methods.every(method => method === "get")).toBe(true);
  });
});
