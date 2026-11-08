package com.productline.business.domain.model;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/** 保存成果版本、人工处理说明和证据引用，不验证原件存在或形成质量结论。 */
public record ReworkProcessingEvidence(
        ReworkArtifact artifact,
        String processingComment,
        List<String> evidenceReferences) {

    public ReworkProcessingEvidence {
        Objects.requireNonNull(artifact, "artifact");
        requireText(processingComment, "processingComment");
        Objects.requireNonNull(evidenceReferences, "evidenceReferences");
        evidenceReferences = new ArrayList<>(evidenceReferences);
        if (evidenceReferences.isEmpty()) {
            throw new IllegalArgumentException("evidenceReferences must not be empty");
        }
        for (String reference : evidenceReferences) {
            requireText(reference, "evidence reference");
        }
        // 确认和检查绑定的是登记时的证据，调用方之后修改列表不能悄悄改变它。
        evidenceReferences = List.copyOf(evidenceReferences);
    }

    private static void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
    }
}
