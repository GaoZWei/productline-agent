package com.productline.business.api.error;

public class ResourceNotFoundException extends RuntimeException {

    public ResourceNotFoundException(String resourceType, String resourceId) {
        super(resourceType + " not found: " + resourceId);
    }
}
