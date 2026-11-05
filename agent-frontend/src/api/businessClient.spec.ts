import MockAdapter from "axios-mock-adapter";
import { afterEach, describe, expect, it } from "vitest";

import {
  BusinessApiError,
  businessHttpClient,
  requestBusinessData,
} from "./businessClient";

const mock = new MockAdapter(businessHttpClient);

afterEach(() => mock.reset());

describe("business API client", () => {
  it("解包统一成功响应并保留 trace id", async () => {
    mock.onGet("/api/orders/ORDER-003").reply(200, {
      success: true,
      code: "SUCCESS",
      message: "success",
      data: { orderId: "ORDER-003" },
      trace_id: "trace-success",
      retryable: false,
    });

    await expect(
      requestBusinessData<{ orderId: string }>("/api/orders/ORDER-003"),
    ).resolves.toEqual({ data: { orderId: "ORDER-003" }, traceId: "trace-success" });
  });

  it("将统一失败响应转换为可判断的业务错误", async () => {
    mock.onGet("/api/orders/ORDER-404").reply(404, {
      success: false,
      code: "RESOURCE_NOT_FOUND",
      message: "order not found",
      data: null,
      trace_id: "trace-not-found",
      retryable: false,
    });

    const error = await requestBusinessData("/api/orders/ORDER-404").catch(
      (reason: unknown) => reason,
    );

    expect(error).toBeInstanceOf(BusinessApiError);
    expect(error).toMatchObject({
      code: "RESOURCE_NOT_FOUND",
      traceId: "trace-not-found",
      retryable: false,
      status: 404,
    });
  });

  it("拒绝字段缺失的伪成功响应", async () => {
    mock.onGet("/api/orders/ORDER-003").reply(200, {
      success: true,
      code: "SUCCESS",
      message: "success",
      trace_id: "trace-invalid",
      retryable: false,
    });

    await expect(requestBusinessData("/api/orders/ORDER-003")).rejects.toMatchObject({
      code: "RESPONSE_VALIDATION_ERROR",
      traceId: "trace-invalid",
    });
  });
});
