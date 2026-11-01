package com.productline.business.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.productline.business.api.error.AuthenticationRequiredException;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.domain.enums.KnowledgeManagementAction;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;

class KnowledgeAuthorizationServiceTest {

    private final KnowledgeAuthorizationService service = new KnowledgeAuthorizationService();

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {" ", "\t"})
    void rejectsMissingActor(String userId) {
        assertThatThrownBy(() -> service.authorize(userId, "REVIEWER", KnowledgeManagementAction.READ))
                .isInstanceOf(AuthenticationRequiredException.class);
    }

    @ParameterizedTest
    @ValueSource(strings = {"reviewer\r001", "reviewer\n001"})
    void rejectsUnsafeActor(String userId) {
        assertThatThrownBy(() -> service.authorize(userId, "REVIEWER", KnowledgeManagementAction.READ))
                .isInstanceOf(InvalidRequestException.class);
    }

    @Test
    void rejectsOversizedActorButAcceptsTheMaximumLength() {
        assertThat(service.authorize("a".repeat(128), "REVIEWER", KnowledgeManagementAction.READ)
                .userId()).hasSize(128);
        assertThatThrownBy(() -> service.authorize(
                "a".repeat(129), "REVIEWER", KnowledgeManagementAction.READ))
                .isInstanceOf(InvalidRequestException.class);
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {"ADMIN", "OPERATOR", "reviewer", "REVIEWER "})
    void deniesUnrecognizedRoles(String role) {
        assertThatThrownBy(() -> service.authorize("reviewer-001", role, KnowledgeManagementAction.READ))
                .isInstanceOf(PermissionDeniedException.class);
    }

    @Test
    void rejectsMissingActionEvenForADirectServiceCall() {
        assertThatThrownBy(() -> service.authorize("reviewer-001", "REVIEWER", null))
                .isInstanceOf(InvalidRequestException.class);
    }
}
