package com.productline.business.domain.repository;

import com.productline.business.domain.model.ReviewRecord;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ReviewRecordRepository extends JpaRepository<ReviewRecord, String> {

    @Query(
            """
            select review
            from ReviewRecord review
            join review.issue issue
            join issue.task task
            where task.taskId = :taskId
            order by review.reviewId
            """)
    List<ReviewRecord> findAllByTaskIdOrderByReviewIdAsc(@Param("taskId") String taskId);
}
