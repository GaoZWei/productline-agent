import axios, { AxiosError, type AxiosResponse } from "axios";

import type { ApiEnvelope, ApiResult } from "../types/business";

const BUSINESS_API_BASE_URL = import.meta.env.VITE_BUSINESS_API_BASE_URL ?? "/business-api";

export class BusinessApiError extends Error {
  readonly code: string;
  readonly traceId?: string;
  readonly retryable: boolean;
  readonly status?: number;

  constructor(options: {
    message: string;
    code: string;
    traceId?: string;
    retryable?: boolean;
    status?: number;
  }) {
    super(options.message);
    this.name = "BusinessApiError";
    this.code = options.code;
    this.traceId = options.traceId;
    this.retryable = options.retryable ?? false;
    this.status = options.status;
  }
}

export const businessHttpClient = axios.create({
  baseURL: BUSINESS_API_BASE_URL,
  timeout: 10_000,
  headers: { Accept: "application/json" },
});

businessHttpClient.interceptors.response.use(
  (response) => {
    const validationError = validateEnvelope(response.data, response.status);
    if (validationError) {
      return Promise.reject(validationError);
    }

    const envelope = response.data as ApiEnvelope<unknown>;
    if (!envelope.success) {
      return Promise.reject(errorFromEnvelope(envelope, response.status));
    }
    return response;
  },
  (reason: unknown) => Promise.reject(normalizeTransportError(reason)),
);

export async function requestBusinessData<T>(path: string): Promise<ApiResult<T>> {
  const response = await businessHttpClient.get<ApiEnvelope<T>>(path);
  return {
    data: response.data.data,
    traceId: response.data.trace_id,
  };
}

function validateEnvelope(value: unknown, status?: number): BusinessApiError | undefined {
  if (
    typeof value !== "object" ||
    value === null ||
    typeof Reflect.get(value, "success") !== "boolean" ||
    typeof Reflect.get(value, "code") !== "string" ||
    typeof Reflect.get(value, "message") !== "string" ||
    typeof Reflect.get(value, "trace_id") !== "string" ||
    typeof Reflect.get(value, "retryable") !== "boolean" ||
    !Object.prototype.hasOwnProperty.call(value, "data")
  ) {
    const traceId =
      typeof value === "object" &&
      value !== null &&
      typeof Reflect.get(value, "trace_id") === "string"
        ? (Reflect.get(value, "trace_id") as string)
        : undefined;
    return new BusinessApiError({
      code: "RESPONSE_VALIDATION_ERROR",
      message: "业务服务返回了无法识别的响应结构",
      traceId,
      status,
    });
  }
  return undefined;
}

function errorFromEnvelope(envelope: ApiEnvelope<unknown>, status?: number) {
  return new BusinessApiError({
    code: envelope.code,
    message: envelope.message,
    traceId: envelope.trace_id,
    retryable: envelope.retryable,
    status,
  });
}

function normalizeTransportError(reason: unknown): BusinessApiError {
  if (reason instanceof BusinessApiError) {
    return reason;
  }
  if (axios.isAxiosError(reason)) {
    return errorFromAxios(reason);
  }
  return new BusinessApiError({
    code: "UNKNOWN_CLIENT_ERROR",
    message: "读取业务数据时发生未知错误",
  });
}

function errorFromAxios(error: AxiosError): BusinessApiError {
  const status = error.response?.status;
  const validationError = validateEnvelope(error.response?.data, status);
  if (error.response?.data !== undefined && !validationError) {
    return errorFromEnvelope(error.response.data as ApiEnvelope<unknown>, status);
  }
  if (error.code === AxiosError.ETIMEDOUT || error.code === "ECONNABORTED") {
    return new BusinessApiError({
      code: "REQUEST_TIMEOUT",
      message: "业务服务响应超时，请稍后重试",
      retryable: true,
      status,
    });
  }
  if (error.response) {
    return validationError!;
  }
  return new BusinessApiError({
    code: "NETWORK_ERROR",
    message: "无法连接业务服务，请检查服务状态",
    retryable: true,
  });
}
