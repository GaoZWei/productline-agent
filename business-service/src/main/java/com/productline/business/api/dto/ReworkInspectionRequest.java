package com.productline.business.api.dto;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.domain.enums.ReworkInspectionResult;
import com.productline.business.domain.model.ReworkInspectionItem;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/** 只接收人工检查项；总体结论、检查人、时间及序号由Java确定。 */
public record ReworkInspectionRequest(long expectedVersion, long processingRevision, List<ReworkInspectionItem> items) {
    public ReworkInspectionRequest {
        if (expectedVersion < 0 || expectedVersion > ReworkStartRequest.MAX_SAFE_INTEGER
                || processingRevision < 1 || processingRevision > ReworkStartRequest.MAX_SAFE_INTEGER
                || items == null || items.isEmpty() || items.size() > 50) throw invalid();
        for (var item : items) {
            if (item == null || item.result() == null) throw invalid();
            text(item.checkItem(), 128, false); text(item.comment(), 1000, false);
            if (item.evidenceReferences() == null || item.evidenceReferences().isEmpty() || item.evidenceReferences().size() > 20) throw invalid();
            for (String ref : item.evidenceReferences()) text(ref, 1024, true);
        }
        items = List.copyOf(items);
    }

    public static ReworkInspectionRequest parse(String body, ObjectMapper mapper) {
        if (body == null) throw invalid();
        try {
            JsonNode node = mapper.reader().with(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(body);
            if (node == null || !node.isObject() || node.size() != 3 || !node.has("expectedVersion")
                    || !node.has("processingRevision") || !node.has("items")) throw invalid();
            JsonNode version = node.get("expectedVersion"), revision = node.get("processingRevision"), entries = node.get("items");
            if (!version.isIntegralNumber() || !version.canConvertToLong() || !revision.isIntegralNumber()
                    || !revision.canConvertToLong() || !entries.isArray() || entries.isEmpty() || entries.size() > 50) throw invalid();
            List<ReworkInspectionItem> items = new ArrayList<>();
            for (JsonNode item : entries) {
                if (!item.isObject() || item.size() != 4 || !item.has("checkItem") || !item.has("result")
                        || !item.has("comment") || !item.has("evidenceReferences")) throw invalid();
                String checkItem = string(item.get("checkItem")), comment = string(item.get("comment"));
                text(checkItem, 128, false); text(comment, 1000, false);
                String result = string(item.get("result"));
                if (!result.equals("PASSED") && !result.equals("FAILED")) throw invalid();
                JsonNode refs = item.get("evidenceReferences");
                if (!refs.isArray() || refs.isEmpty() || refs.size() > 20) throw invalid();
                List<String> references = new ArrayList<>();
                for (JsonNode ref : refs) { String value = string(ref); text(value, 1024, true); references.add(value); }
                items.add(new ReworkInspectionItem(checkItem, ReworkInspectionResult.valueOf(result), comment, references));
            }
            return new ReworkInspectionRequest(version.longValue(), revision.longValue(), items);
        } catch (JsonProcessingException exception) { throw invalid(); }
    }

    private static String string(JsonNode value) {
        if (value == null || !value.isTextual()) throw invalid();
        return value.textValue();
    }

    private static void text(String value, int limit, boolean trimmed) {
        if (value == null || value.isBlank() || value.length() > limit || value.indexOf('\0') >= 0
                || !StandardCharsets.UTF_8.newEncoder().canEncode(value)
                || (trimmed && !value.equals(value.strip()))) throw invalid();
    }

    private static InvalidRequestException invalid() {
        return new InvalidRequestException("inspection requires only safe expectedVersion, positive processingRevision and complete manual inspection items");
    }
}
