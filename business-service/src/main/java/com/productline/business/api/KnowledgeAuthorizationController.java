package com.productline.business.api;

import com.productline.business.api.dto.KnowledgeAuthorizationRequest;
import com.productline.business.api.dto.KnowledgeAuthorizationResponse;
import com.productline.business.application.KnowledgeAuthorizationService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/knowledge")
public class KnowledgeAuthorizationController {

    private final KnowledgeAuthorizationService authorizationService;

    public KnowledgeAuthorizationController(KnowledgeAuthorizationService authorizationService) {
        this.authorizationService = authorizationService;
    }

    /** POST仅用于提交结构化查询条件，接口没有写入副作用。 */
    @PostMapping("/authorize")
    public KnowledgeAuthorizationResponse authorize(
            @RequestHeader(value = "X-User-Id", required = false) String userId,
            @RequestHeader(value = "X-User-Role", required = false) String userRole,
            @Valid @RequestBody KnowledgeAuthorizationRequest request) {
        return authorizationService.authorize(userId, userRole, request.action());
    }
}
