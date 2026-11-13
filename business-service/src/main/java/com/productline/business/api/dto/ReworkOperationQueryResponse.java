package com.productline.business.api.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

/** 未见成功回执不等于未提交，receipt必须显式为null，不能授权重发。 */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record ReworkOperationQueryResponse(boolean found, ReworkWriteReceipt receipt) {
    public ReworkOperationQueryResponse {
        if (found != (receipt != null)) throw new IllegalArgumentException("invalid operation query result");
    }
}
