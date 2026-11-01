package com.productline.business.application;

import com.productline.business.api.dto.KnowledgeAuthorizationResponse;
import com.productline.business.api.error.AuthenticationRequiredException;
import com.productline.business.api.error.InvalidRequestException;
import com.productline.business.api.error.PermissionDeniedException;
import com.productline.business.domain.enums.KnowledgeManagementAction;
import com.productline.business.domain.enums.KnowledgePermissionScope;
import org.springframework.stereotype.Service;

/** 演示身份下的知识管理授权，不读取知识表、业务表或外部模型。 */
@Service
public class KnowledgeAuthorizationService {

    public KnowledgeAuthorizationResponse authorize(
            String userId, String userRole, KnowledgeManagementAction action) {
        if (userId == null || userId.isBlank()) {
            throw new AuthenticationRequiredException("authenticated user is required");
        }
        if (userId.length() > 128 || userId.indexOf('\r') >= 0 || userId.indexOf('\n') >= 0) {
            throw new InvalidRequestException("X-User-Id must contain 1 to 128 safe characters");
        }
        if (!"REVIEWER".equals(userRole)) {
            throw new PermissionDeniedException("REVIEWER role is required");
        }
        if (action == null) {
            throw new InvalidRequestException("knowledge action is required");
        }
        return new KnowledgeAuthorizationResponse(
                userId, action, KnowledgePermissionScope.INTERNAL_REVIEWER,
                action.requiresConfirmation());
    }
}
