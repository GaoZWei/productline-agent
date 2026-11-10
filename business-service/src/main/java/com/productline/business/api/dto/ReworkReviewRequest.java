package com.productline.business.api.dto;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.domain.enums.ReviewStatus;
import java.nio.charset.StandardCharsets;
import java.util.List;

/** 只接收最终审查材料；人员、时间、轮次和当前事实由Java确定。 */
public record ReworkReviewRequest(long expectedVersion, long processingRevision, String inspectionId,
        ReviewStatus status, String reviewComment) {
    public ReworkReviewRequest {
        if (expectedVersion < 0 || expectedVersion > ReworkStartRequest.MAX_SAFE_INTEGER
                || processingRevision < 1 || processingRevision > ReworkStartRequest.MAX_SAFE_INTEGER
                || inspectionId == null || inspectionId.length() > 64 || !inspectionId.matches("[A-Z]+-[A-Z0-9][A-Z0-9-]*")
                || status == null || status == ReviewStatus.PENDING || reviewComment == null || reviewComment.isBlank()
                || reviewComment.length() > 1000 || reviewComment.indexOf('\0') >= 0
                || !StandardCharsets.UTF_8.newEncoder().canEncode(reviewComment)) throw invalid();
    }

    public static ReworkReviewRequest parse(String body, ObjectMapper mapper) {
        if (body == null) throw invalid();
        try {
            JsonNode node = mapper.reader().with(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(body);
            if (node == null || !node.isObject() || node.size() != 5 || !node.has("expectedVersion")
                    || !node.has("processingRevision") || !node.has("inspectionId")
                    || !node.has("status") || !node.has("reviewComment")) throw invalid();
            JsonNode version = node.get("expectedVersion"), revision = node.get("processingRevision");
            if (!version.isIntegralNumber() || !version.canConvertToLong() || !revision.isIntegralNumber()
                    || !revision.canConvertToLong() || !node.get("inspectionId").isTextual()
                    || !node.get("status").isTextual() || !node.get("reviewComment").isTextual()) throw invalid();
            String status = node.get("status").textValue();
            if (!List.of("APPROVED", "REJECTED", "REWORK_REQUIRED").contains(status)) throw invalid();
            return new ReworkReviewRequest(version.longValue(), revision.longValue(), node.get("inspectionId").textValue(),
                    ReviewStatus.valueOf(status), node.get("reviewComment").textValue());
        } catch (JsonProcessingException exception) { throw invalid(); }
    }

    private static InvalidRequestException invalid() {
        return new InvalidRequestException("review requires only safe expectedVersion, positive processingRevision, inspectionId, final status and nonblank reviewComment of at most 1000 UTF-16 units");
    }
}
