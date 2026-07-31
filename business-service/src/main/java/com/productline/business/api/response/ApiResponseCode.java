package com.productline.business.api.response;

/**
 * API 响应错误码（枚举）
 */
public enum ApiResponseCode {
    SUCCESS,
    PARAM_VALIDATION_ERROR,
    RESOURCE_NOT_FOUND,
    PERMISSION_DENIED,
    BUSINESS_CONFLICT,
    INTERNAL_SERVER_ERROR
}
