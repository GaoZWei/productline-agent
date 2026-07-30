package com.productline.business.domain;

import static org.assertj.core.api.Assertions.assertThat;

import com.productline.business.domain.enums.DeliveryStatus;
import com.productline.business.domain.enums.OrderStatus;
import com.productline.business.domain.enums.ProductionTaskStatus;
import com.productline.business.domain.enums.QualityIssueStatus;
import com.productline.business.domain.enums.ReviewStatus;
import org.junit.jupiter.api.Test;

class BusinessStatusEnumTest {

    @Test
    void exposesTheDocumentedCrossServiceStatusVocabulary() {
        assertThat(names(OrderStatus.values()))
                .containsExactly(
                        "CREATED",
                        "PRODUCING",
                        "QUALITY_CHECKING",
                        "REVIEWING",
                        "READY_FOR_DELIVERY",
                        "DELIVERING",
                        "DELIVERED",
                        "BLOCKED");
        assertThat(names(ProductionTaskStatus.values()))
                .containsExactly("PENDING", "RUNNING", "COMPLETED", "FAILED", "BLOCKED");
        assertThat(names(QualityIssueStatus.values()))
                .containsExactly("OPEN", "PROCESSING", "RESOLVED", "CLOSED");
        assertThat(names(ReviewStatus.values()))
                .containsExactly("PENDING", "APPROVED", "REJECTED", "REWORK_REQUIRED");
        assertThat(names(DeliveryStatus.values()))
                .containsExactly("NOT_READY", "READY", "DELIVERING", "DELIVERED", "FAILED", "BLOCKED");
    }

    private static String[] names(Enum<?>[] values) {
        return java.util.Arrays.stream(values).map(Enum::name).toArray(String[]::new);
    }
}
