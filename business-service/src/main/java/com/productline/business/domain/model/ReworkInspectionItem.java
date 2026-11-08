package com.productline.business.domain.model;

import com.productline.business.domain.enums.ReworkInspectionResult;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/** 一项实际人工检查的结论、说明和证据；该对象不会执行成果检查程序。 */
public record ReworkInspectionItem(
        String checkItem,
        ReworkInspectionResult result,
        String comment,
        List<String> evidenceReferences) {

    public ReworkInspectionItem {
        requireText(checkItem, "checkItem");
        Objects.requireNonNull(result, "result");
        requireText(comment, "comment");
        Objects.requireNonNull(evidenceReferences, "evidenceReferences");
        evidenceReferences = new ArrayList<>(evidenceReferences);
        if (evidenceReferences.isEmpty()) {
            throw new IllegalArgumentException("evidenceReferences must not be empty");
        }
        for (String reference : evidenceReferences) {
            requireText(reference, "evidence reference");
        }
        evidenceReferences = List.copyOf(evidenceReferences);
    }

    private static void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
    }
}
