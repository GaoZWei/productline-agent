package com.productline.business.api.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;

/** 历史记录保持原样；分页上界不代表跨页共享同一个业务快照。 */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record ReworkHistoryResponse<T>(String taskId, String reworkTaskId, List<T> records, String nextCursor) {
    public ReworkHistoryResponse {
        records = List.copyOf(records);
    }
}
