package com.productline.business.api.dto;

import com.fasterxml.jackson.annotation.JsonAnySetter;
import com.productline.business.domain.enums.KnowledgeManagementAction;
import jakarta.validation.constraints.NotNull;

public record KnowledgeAuthorizationRequest(@NotNull KnowledgeManagementAction action) {

    @JsonAnySetter
    public void rejectUnknownField(String name, Object value) {
        // 本接口不接收客户端自报的权限、确认结果或知识当前状态。
        throw new IllegalArgumentException("unsupported knowledge authorization field");
    }
}
