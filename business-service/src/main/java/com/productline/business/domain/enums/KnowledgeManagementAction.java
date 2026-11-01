package com.productline.business.domain.enums;

import com.fasterxml.jackson.annotation.JsonCreator;

/** 知识管理动作白名单；授权查询本身不执行这些动作。 */
public enum KnowledgeManagementAction {
    READ,
    UPLOAD,
    PUBLISH,
    DISABLE,
    RETRY_INDEX;

    @JsonCreator
    public static KnowledgeManagementAction fromValue(String value) {
        // 使用显式名称解析，避免JSON数字被作为枚举序号授予权限。
        return KnowledgeManagementAction.valueOf(value);
    }

    public boolean requiresConfirmation() {
        return this != READ;
    }
}
