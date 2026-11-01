package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.productline.business.application.KnowledgeAuthorizationService;
import com.productline.business.domain.enums.KnowledgeManagementAction;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestExecutionListeners;
import org.springframework.test.context.support.DependencyInjectionTestExecutionListener;
import org.springframework.test.context.web.ServletTestExecutionListener;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

@WebMvcTest(KnowledgeAuthorizationController.class)
@Import(KnowledgeAuthorizationService.class)
// 纯MVC切片不使用mock或事务，避免无关Mockito监听器在受限环境触发JVM动态挂载。
@TestExecutionListeners({ServletTestExecutionListener.class, DependencyInjectionTestExecutionListener.class})
class KnowledgeAuthorizationApiTest {

    @Autowired private MockMvc mvc;

    @ParameterizedTest
    @EnumSource(KnowledgeManagementAction.class)
    void returnsServerOwnedScopeAndConfirmationPolicy(KnowledgeManagementAction action) throws Exception {
        request("{\"action\":\"" + action.name() + "\"}", "reviewer-001", "REVIEWER")
                .andExpect(status().isOk())
                .andExpect(header().string("X-Trace-Id", "trace-knowledge-001"))
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.code").value("SUCCESS"))
                .andExpect(jsonPath("$.retryable").value(false))
                .andExpect(jsonPath("$.trace_id").value("trace-knowledge-001"))
                .andExpect(jsonPath("$.data.userId").value("reviewer-001"))
                .andExpect(jsonPath("$.data.action").value(action.name()))
                .andExpect(jsonPath("$.data.permissionScope").value("INTERNAL_REVIEWER"))
                .andExpect(jsonPath("$.data.confirmationRequired").value(action != KnowledgeManagementAction.READ))
                .andExpect(jsonPath("$.data.token").doesNotExist());
    }

    @Test
    void missingActorIs401AndMissingRoleIs403() throws Exception {
        assertError(request("{\"action\":\"READ\"}", null, "REVIEWER"), 401, "PERMISSION_DENIED");
        assertError(request("{\"action\":\"READ\"}", "reviewer-001", null), 403, "PERMISSION_DENIED");
    }

    @ParameterizedTest
    @ValueSource(strings = {"OPERATOR", "ADMIN", "reviewer"})
    void rejectsUnauthorizedRoles(String role) throws Exception {
        assertError(request("{\"action\":\"PUBLISH\"}", "reviewer-001", role), 403, "PERMISSION_DENIED");
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "{}", "{\"action\":null}", "{\"action\":\"DELETE\"}",
            "{\"action\":\"read\"}", "{\"action\":0}", "{\"action\":true}",
            "{\"action\":[]}", "{\"action\":{}}", "null", "{not-json", ""
    })
    void rejectsInvalidOrMissingActions(String body) throws Exception {
        assertError(request(body, "reviewer-001", "REVIEWER"), 400, "PARAM_VALIDATION_ERROR");
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "\"permissionScope\":\"INTERNAL_REVIEWER\"", "\"userRole\":\"REVIEWER\"",
            "\"confirmed\":true", "\"documentId\":\"DOC-001\"", "\"expectedVersion\":1",
            "\"currentStatus\":\"PUBLISHED\""
    })
    void rejectsClientSuppliedAuthorizationAndStateClaims(String extraField) throws Exception {
        assertError(request("{\"action\":\"PUBLISH\"," + extraField + "}", "reviewer-001", "REVIEWER"),
                400, "PARAM_VALIDATION_ERROR");
    }

    @Test
    void rejectsOversizedActorWithoutEchoingIt() throws Exception {
        String actor = "x".repeat(129);
        String content = assertError(request("{\"action\":\"READ\"}", actor, "REVIEWER"),
                400, "PARAM_VALIDATION_ERROR").andReturn().getResponse().getContentAsString();
        assertThat(content).doesNotContain(actor);
    }

    @Test
    void repeatedAuthorizationDoesNotProduceAnExecutionCredential() throws Exception {
        String first = request("{\"action\":\"PUBLISH\"}", "reviewer-001", "REVIEWER")
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        String second = request("{\"action\":\"PUBLISH\"}", "reviewer-001", "REVIEWER")
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        assertThat(first).isEqualTo(second);
    }

    private ResultActions request(String body, String userId, String role) throws Exception {
        var request = post("/api/knowledge/authorize")
                .contentType(MediaType.APPLICATION_JSON)
                .header("X-Trace-Id", "trace-knowledge-001").content(body);
        if (userId != null) {
            request.header("X-User-Id", userId);
        }
        if (role != null) {
            request.header("X-User-Role", role);
        }
        return mvc.perform(request);
    }

    private ResultActions assertError(ResultActions response, int statusCode, String code) throws Exception {
        return response.andExpect(status().is(statusCode))
                .andExpect(header().string("X-Trace-Id", "trace-knowledge-001"))
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value(code))
                .andExpect(jsonPath("$.data").isEmpty())
                .andExpect(jsonPath("$.retryable").value(false))
                .andExpect(jsonPath("$.trace_id").value("trace-knowledge-001"));
    }
}
