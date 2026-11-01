package com.productline.business.api.dto;

import com.productline.business.domain.enums.KnowledgeManagementAction;
import com.productline.business.domain.enums.KnowledgePermissionScope;

/** 仅代表当次角色权限判断，不是执行凭证或已完成人工确认的证明。 */
public record KnowledgeAuthorizationResponse(
        String userId,
        KnowledgeManagementAction action,
        KnowledgePermissionScope permissionScope,
        boolean confirmationRequired) {
}
