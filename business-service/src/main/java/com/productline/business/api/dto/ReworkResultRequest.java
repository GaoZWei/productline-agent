package com.productline.business.api.dto;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.domain.model.ReworkArtifact;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/** 成果身份及证据按原值登记；只校验材料格式，不证明成果真实或检查通过。 */
public record ReworkResultRequest(long expectedVersion, ReworkArtifact artifact,
        String processingComment, List<String> evidenceReferences) {
    public ReworkResultRequest {
        if (expectedVersion < 0 || expectedVersion > ReworkStartRequest.MAX_SAFE_INTEGER || artifact == null) throw invalid();
        text(artifact.artifactId(), 256, true);
        text(artifact.artifactVersion(), 128, true);
        text(processingComment, 1000, false);
        if (evidenceReferences == null || evidenceReferences.isEmpty() || evidenceReferences.size() > 20) throw invalid();
        for (String reference : evidenceReferences) text(reference, 1024, true);
        evidenceReferences = List.copyOf(evidenceReferences);
    }

    public static ReworkResultRequest parse(String body, ObjectMapper mapper) {
        if (body == null) throw invalid();
        try {
            JsonNode node = mapper.reader().with(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
                    .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(body);
            if (node == null || !node.isObject() || node.size() != 4 || !node.has("expectedVersion")
                    || !node.has("artifact") || !node.has("processingComment") || !node.has("evidenceReferences")) throw invalid();
            JsonNode version = node.get("expectedVersion");
            JsonNode artifact = node.get("artifact");
            JsonNode refs = node.get("evidenceReferences");
            if (!version.isIntegralNumber() || !version.canConvertToLong() || !artifact.isObject() || artifact.size() != 2
                    || !artifact.has("artifactId") || !artifact.has("artifactVersion") || !refs.isArray()) throw invalid();
            List<String> references = new ArrayList<>();
            for (JsonNode ref : refs) references.add(string(ref));
            String artifactId = string(artifact.get("artifactId"));
            String artifactVersion = string(artifact.get("artifactVersion"));
            text(artifactId, 256, true); text(artifactVersion, 128, true);
            return new ReworkResultRequest(version.longValue(), new ReworkArtifact(artifactId, artifactVersion),
                    string(node.get("processingComment")), references);
        } catch (JsonProcessingException exception) {
            throw invalid();
        }
    }

    private static String string(JsonNode node) {
        if (node == null || !node.isTextual()) throw invalid();
        return node.textValue();
    }

    private static void text(String value, int maximum, boolean trimmed) {
        if (value == null || value.isBlank() || value.length() > maximum || value.indexOf('\0') >= 0
                || !StandardCharsets.UTF_8.newEncoder().canEncode(value)
                || (trimmed && !value.equals(value.strip()))) throw invalid();
    }

    private static InvalidRequestException invalid() {
        return new InvalidRequestException("result requires only a safe expectedVersion, artifact, processingComment and evidenceReferences matching the rework contract");
    }
}
