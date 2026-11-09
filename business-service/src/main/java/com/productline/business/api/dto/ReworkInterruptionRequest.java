package com.productline.business.api.dto;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.error.InvalidRequestException;
import java.nio.charset.StandardCharsets;

/** 异常原因及恢复说明按原值登记，UTF-16长度与Java/前端契约一致，不改变旧请求解析。 */
public record ReworkInterruptionRequest(long expectedVersion, String reason) {
    public static final long MAX_SAFE_INTEGER = ReworkStartRequest.MAX_SAFE_INTEGER;

    public ReworkInterruptionRequest {
        if (expectedVersion < 0 || expectedVersion > MAX_SAFE_INTEGER) throw invalid();
        if (reason == null || reason.isBlank() || reason.length() > 1000
                || reason.indexOf('\0') >= 0 || !StandardCharsets.UTF_8.newEncoder().canEncode(reason)) {
            throw invalid();
        }
    }

    public static ReworkInterruptionRequest parse(String body, ObjectMapper mapper) {
        if (body == null) throw invalid();
        try {
            JsonNode node = mapper.reader().with(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(body);
            if (node == null || !node.isObject() || node.size() != 2
                    || !node.has("expectedVersion") || !node.has("reason")) throw invalid();
            JsonNode version = node.get("expectedVersion");
            JsonNode reason = node.get("reason");
            if (!version.isIntegralNumber() || !version.canConvertToLong() || !reason.isTextual()) throw invalid();
            return new ReworkInterruptionRequest(version.longValue(), reason.textValue());
        } catch (JsonProcessingException exception) {
            throw invalid();
        }
    }

    private static InvalidRequestException invalid() {
        return new InvalidRequestException("interruption requires only a safe integer expectedVersion and nonblank UTF-8 reason of at most 1000 UTF-16 units");
    }
}
