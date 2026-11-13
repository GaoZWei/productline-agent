package com.productline.business.api.dto;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.error.InvalidRequestException;

/** 无副作用查询只接收原幂等键，不接受自报用户、动作或确认信息。 */
public record ReworkOperationQueryRequest(String idempotencyKey) {
    public ReworkOperationQueryRequest {
        if (idempotencyKey == null || !idempotencyKey.matches("[A-Za-z0-9._:-]{1,128}")) throw invalid();
    }

    public static ReworkOperationQueryRequest parse(String body, ObjectMapper mapper) {
        if (body == null) throw invalid();
        try {
            JsonNode node = mapper.reader().with(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(body);
            if (node == null || !node.isObject() || node.size() != 1 || !node.has("idempotencyKey")
                    || !node.get("idempotencyKey").isTextual()) throw invalid();
            return new ReworkOperationQueryRequest(node.get("idempotencyKey").textValue());
        } catch (JsonProcessingException exception) {
            throw invalid();
        }
    }

    private static InvalidRequestException invalid() {
        return new InvalidRequestException("operation query requires only a safe idempotencyKey");
    }
}
