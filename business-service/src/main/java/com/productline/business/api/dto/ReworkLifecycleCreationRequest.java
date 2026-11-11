package com.productline.business.api.dto;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.error.InvalidRequestException;

/** 受控首轮只接收问题、版本和原因；轮次、人员及创建时间由Java确定。 */
public record ReworkLifecycleCreationRequest(String sourceIssueId, long expectedVersion, String reason) {
    public ReworkLifecycleCreationRequest {
        if (sourceIssueId == null || sourceIssueId.length() > 64
                || !sourceIssueId.matches("[A-Z]+-[A-Z0-9][A-Z0-9-]*")) throw invalid();
        new ReworkInterruptionRequest(expectedVersion, reason);
    }

    public static ReworkLifecycleCreationRequest parse(String body, ObjectMapper mapper) {
        if (body == null) throw invalid();
        try {
            JsonNode node = mapper.reader().with(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(body);
            if (node == null || !node.isObject() || node.size() != 3 || !node.has("sourceIssueId")
                    || !node.has("expectedVersion") || !node.has("reason")
                    || !node.get("sourceIssueId").isTextual() || !node.get("reason").isTextual()
                    || !node.get("expectedVersion").isIntegralNumber()
                    || !node.get("expectedVersion").canConvertToLong()) throw invalid();
            return new ReworkLifecycleCreationRequest(node.get("sourceIssueId").textValue(),
                    node.get("expectedVersion").longValue(), node.get("reason").textValue());
        } catch (JsonProcessingException exception) { throw invalid(); }
    }

    private static InvalidRequestException invalid() {
        return new InvalidRequestException("creation requires only sourceIssueId, safe expectedVersion and nonblank reason of at most 1000 UTF-16 units");
    }
}
