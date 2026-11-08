package com.productline.business.domain.model;

/** 标识人工修复后登记的具体成果版本，不代表成果已经通过检查。 */
public record ReworkArtifact(String artifactId, String artifactVersion) {

    public ReworkArtifact {
        requireText(artifactId, "artifactId");
        requireText(artifactVersion, "artifactVersion");
    }

    private static void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
    }
}
