package com.productline.business.api;

import com.productline.business.api.dto.DeliveryConditionsResponse;
import com.productline.business.application.DeliveryConditionsService;
import org.springframework.util.MultiValueMap;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class DeliveryConditionsController {
    private final DeliveryConditionsService service;

    public DeliveryConditionsController(DeliveryConditionsService service) { this.service = service; }

    @GetMapping("/api/orders/{orderId}/delivery-conditions")
    public DeliveryConditionsResponse read(@PathVariable String orderId,
            @RequestHeader(value = "X-User-Id", required = false) String user,
            @RequestHeader(value = "X-User-Role", required = false) String role,
            @RequestParam MultiValueMap<String, String> query) {
        return service.read(orderId, user, role, query);
    }
}
