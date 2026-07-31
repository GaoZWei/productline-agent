package com.productline.business.api.response;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Objects;

public record ApiResponse<T>(
        boolean success, // 业务调用是否成功
        ApiResponseCode code, // 提供给 Tool/Workflow 判断的稳定错误码
        String message, // 用于人类排障，不建议 Agent 根据文案做字符串分支
        T data, // 成功时存放业务 DTO，失败时固定为 null
        @JsonProperty("trace_id") String traceId, // 关联响应和服务端日志的唯一标识
        boolean retryable) { // 调用方是否可以自动重试，失败时建议手动重试

    public ApiResponse {
        Objects.requireNonNull(code, "code");
        requireText(message, "message");
        requireText(traceId, "traceId");
    }

    public static <T> ApiResponse<T> success(T data, String traceId) {
        return new ApiResponse<>(
                true,
                ApiResponseCode.SUCCESS,
                "success",
                data,
                traceId,
                false);
    }

    public static ApiResponse<Void> failure(
            ApiResponseCode code,
            String message,
            String traceId,
            boolean retryable) {
        if (code == ApiResponseCode.SUCCESS) {
            throw new IllegalArgumentException("failure response cannot use SUCCESS code");
        }
        return new ApiResponse<>(false, code, message, null, traceId, retryable);
    }

    private static void requireText(String value, String name) {
        Objects.requireNonNull(value, name);
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
    }
}
