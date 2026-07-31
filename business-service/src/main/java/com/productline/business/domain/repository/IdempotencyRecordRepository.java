package com.productline.business.domain.repository;

import com.productline.business.domain.model.IdempotencyRecord;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface IdempotencyRecordRepository
        extends JpaRepository<IdempotencyRecord, String> {

    @Modifying
    @Query(
            value =
                    """
                    INSERT INTO idempotency_records (
                        idempotency_key, operation_type, request_hash, actor_user_id
                    ) VALUES (
                        :key, :operationType, :requestHash, :actorUserId
                    )
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """,
            nativeQuery = true)
    int reserve(
            @Param("key") String key,
            @Param("operationType") String operationType,
            @Param("requestHash") String requestHash,
            @Param("actorUserId") String actorUserId);
}
