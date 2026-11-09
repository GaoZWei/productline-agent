package com.productline.business.api.dto;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.error.InvalidRequestException;

/** 开始请求只接受安全整数版本；局部严格解析不改变旧接口的Jackson行为。 */
public record ReworkStartRequest(long expectedVersion) {
    public static final long MAX_SAFE_INTEGER = 9007199254740991L;

    public ReworkStartRequest {
        if (expectedVersion < 0 || expectedVersion > MAX_SAFE_INTEGER) {
            throw invalid();
        }
    }

    public static ReworkStartRequest parse(String body, ObjectMapper mapper) {
        if (body == null) throw invalid();
        try {
            JsonNode node = mapper.reader()
                    .with(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(body);
            if (node == null || !node.isObject() || node.size() != 1 || !node.has("expectedVersion")) {
                throw invalid();
            }
            JsonNode version = node.get("expectedVersion");
            if (!version.isIntegralNumber() || !version.canConvertToLong()) throw invalid();
            return new ReworkStartRequest(version.longValue());
        } catch (JsonProcessingException exception) {
            throw invalid();
        }
    }

    private static InvalidRequestException invalid() {
        return new InvalidRequestException("start request requires only an integer expectedVersion in the safe range");
    }
}
