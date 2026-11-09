package com.productline.business.api;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.productline.business.support.PostgresIntegrationTestSupport;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;

/** 独占schema中的真实HTTP受控恢复，验证原回执与当前事实隔离、材料保留及原子性。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t809_rework_resume", "spring.flyway.default-schema=t809_rework_resume",
        "spring.datasource.hikari.schema=t809_rework_resume",
        "spring.jpa.properties.hibernate.default_schema=t809_rework_resume"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkResumeApiIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    private Map<String,Object> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T809','DOM','QUALITY_CHECKING')");
        interrupted("INVALID","BLOCKED");
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
        } finally {
            jdbc.execute("DROP SCHEMA t809_rework_resume CASCADE");
        }
    }

    private String task(String id) { return "TASK-T809-" + id; }
    private String rework(String id) { return "REWORK-T809-" + id; }
    private String issue(String id) { return "ISSUE-T809-" + id; }
    private String path(String id) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id) + "/resume"; }

    private String source(String action) { return action.equals("fail") ? "FAILED" : "BLOCKED"; }

    private void interrupted(String id, String source) { fixture(id,"COMPLETED",source,"PROCESSING",true); }

    private void fixture(String id, String taskStatus, String reworkStatus, String issueStatus, boolean lifecycle) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T809',?)",task(id),taskStatus);
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM',?,'独立恢复测试问题')",issue(id),task(id),issueStatus);
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,?,'原始创建原因')",rework(id),task(id),issue(id),reworkStatus);
        if (lifecycle) {
            jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at,started_by,started_at) VALUES (?,?,?,1,'creator-test',TIMESTAMPTZ '2026-11-09 00:00:00+00','original-handler',TIMESTAMPTZ '2026-11-09 00:01:00+00')",rework(id),task(id),issue(id));
        }
    }

    private String body(long version, String reason) throws Exception {
        return mapper.writeValueAsString(Map.of("expectedVersion",version,"reason",reason));
    }

    private ResponseEntity<JsonNode> request(String path, String body, String key, String actor, String role) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-Trace-Id","trace-t809-event");
        if (key != null) headers.set("Idempotency-Key",key);
        if (actor != null) headers.set("X-User-Id",actor);
        if (role != null) headers.set("X-User-Role",role);
        return http.exchange(path,HttpMethod.POST,new HttpEntity<>(body,headers),JsonNode.class);
    }

    private ResponseEntity<JsonNode> event(String id, String key, String reason) throws Exception {
        return request(path(id),body(0,reason),key,"reviewer-test","REVIEWER");
    }

    private JsonNode success(ResponseEntity<JsonNode> response) {
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t809-event");
        JsonNode envelope = response.getBody();
        assertThat(envelope).isNotNull();
        assertThat(envelope.size()).isEqualTo(6);
        assertThat(envelope.path("success").asBoolean()).isTrue();
        assertThat(envelope.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(envelope.path("retryable").asBoolean()).isFalse();
        assertThat(envelope.path("trace_id").asText()).isEqualTo("trace-t809-event");
        JsonNode data = envelope.path("data");
        assertThat(data.size()).isEqualTo(12);
        assertThat(data.path("operation").asText()).isEqualTo("RESUME_REWORK");
        assertThat(data.path("operationId").asText()).matches("^OPERATION-[A-Z0-9-]+$");
        assertThat(data.path("status").asText()).isEqualTo("RUNNING");
        assertThat(data.path("issueStatus").asText()).isEqualTo("PROCESSING");
        return data;
    }

    private void error(ResponseEntity<JsonNode> response, int status, String code) {
        assertThat(response.getStatusCode().value()).isEqualTo(status);
        JsonNode data = response.getBody();
        assertThat(data.path("code").asText()).isEqualTo(code);
        assertThat(data.path("success").asBoolean()).isFalse();
        assertThat(data.path("retryable").asBoolean()).isFalse();
        assertThat(data.path("data").isNull()).isTrue();
        assertThat(data.toString()).doesNotContain("原始创建原因","report:结果","request_hash");
    }

    private Map<String,Object> state(String id) {
        return jdbc.queryForMap("SELECT t.status AS task_status,t.version,r.status AS rework_status,r.reason,q.status AS issue_status,l.started_by,l.started_at FROM production_tasks t JOIN rework_tasks r ON r.task_id=t.task_id JOIN quality_issues q ON q.issue_id=r.source_issue_id LEFT JOIN rework_lifecycles l ON l.rework_task_id=r.rework_task_id WHERE r.rework_task_id=?",rework(id));
    }

    private int keyCount(String table, String key) {
        return jdbc.queryForObject("SELECT count(*) FROM "+table+" WHERE idempotency_key=?",Integer.class,key);
    }

    private int auditCount(String key) {
        return jdbc.queryForObject("SELECT count(*) FROM operation_logs WHERE idempotency_key_hash=encode(sha256(convert_to(?,'UTF8')),'hex')",Integer.class,key);
    }

    private void absent(String key) {
        assertThat(keyCount("idempotency_records",key)).isZero();
        assertThat(keyCount("rework_operation_receipts",key)).isZero();
        assertThat(auditCount(key)).isZero();
    }

    @ParameterizedTest
    @ValueSource(strings={"block","fail"})
    void recordsReasonAndStateWithoutOverwritingCreationOrStartInformation(String action) throws Exception {
        String id="SUCCESS-"+action.toUpperCase(java.util.Locale.ROOT);
        interrupted(id,source(action));
        var before=state(id);
        String reason="  具备继续处理条件\n保留说明空白  ";
        String key="t809-success-"+action;
        JsonNode data=success(event(id,key,reason));
        assertThat(data.path("taskId").asText()).isEqualTo(task(id));
        assertThat(data.path("reworkTaskId").asText()).isEqualTo(rework(id));
        assertThat(data.path("roundNumber").asLong()).isEqualTo(1);
        assertThat(data.path("taskVersion").asLong()).isEqualTo(1);
        for (String field:List.of("previousReworkTaskId","processingRevision","inspectionId","reviewId")) {
            assertThat(data.has(field)).as(field).isTrue();
            assertThat(data.get(field).isNull()).as(field).isTrue();
        }
        assertThat(state(id)).containsEntry("task_status","COMPLETED").containsEntry("version",1L)
                .containsEntry("rework_status","RUNNING").containsEntry("issue_status","PROCESSING")
                .containsEntry("reason",before.get("reason")).containsEntry("started_by",before.get("started_by"))
                .containsEntry("started_at",before.get("started_at"));
        var audit=jdbc.queryForMap("SELECT actor_user_id,idempotency_key_hash,before_state,after_state,target_type,target_id FROM operation_logs WHERE operation_id=?",data.path("operationId").asText());
        assertThat(audit).containsEntry("actor_user_id","reviewer-test").containsEntry("target_type","PRODUCTION_TASK").containsEntry("target_id",task(id));
        assertThat(audit.get("idempotency_key_hash").toString()).matches("[a-f0-9]{64}");
        assertThat(mapper.readTree(audit.get("after_state").toString()).path("reason").asText()).isEqualTo(reason);
        assertThat(mapper.readTree(audit.get("before_state").toString()).path("status").asText()).isEqualTo(before.get("rework_status"));
        assertThat(audit.get("before_state").toString()+audit.get("after_state").toString()).doesNotContain(key);
        assertThat(mapper.readTree(jdbc.queryForObject("SELECT response_data::text FROM rework_operation_receipts WHERE idempotency_key=?",String.class,key))).isEqualTo(data);
    }

    private void materials(String id) {
        for (int revision=1;revision<=2;revision++) {
            jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,?,'成果-A','v2','原始处理说明','[\"report:结果\"]'::jsonb,'handler-test',TIMESTAMPTZ '2026-11-09 00:02:00+00')",rework(id),revision);
        }
        jdbc.update("INSERT INTO rework_inspections VALUES (?, ?,1,1,'PASSED','[{\"checkItem\":\"坐标系\",\"result\":\"PASSED\",\"comment\":\"旧检查通过\",\"evidenceReferences\":[\"report:旧检查\"]}]'::jsonb,'inspector-test',TIMESTAMPTZ '2026-11-09 00:03:00+00')","CHECK-T809-OLD-"+id,rework(id));
        jdbc.update("INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,review_sequence,status,review_comment,reviewed_by,reviewed_at) VALUES (?,?,1,?,1,'APPROVED','旧修订复核','reviewer-test',TIMESTAMPTZ '2026-11-09 00:04:00+00')","REVIEW-T809-OLD-"+id,rework(id),"CHECK-T809-OLD-"+id);
        jdbc.update("INSERT INTO rework_inspections VALUES (?, ?,2,2,'FAILED','[{\"checkItem\":\"坐标系\",\"result\":\"FAILED\",\"comment\":\"当前检查失败\",\"evidenceReferences\":[\"report:当前检查\"]}]'::jsonb,'inspector-test',TIMESTAMPTZ '2026-11-09 00:05:00+00')","CHECK-T809-NEW-"+id,rework(id));
    }

    private List<Map<String,Object>> materialRows(String id) {
        return Stream.of("rework_processing_revisions","rework_inspections","rework_reviews")
                .flatMap(table -> jdbc.queryForList("SELECT to_jsonb(x)::text AS record FROM "+table+" x WHERE rework_task_id=? ORDER BY to_jsonb(x)::text",rework(id)).stream()).toList();
    }

    @ParameterizedTest
    @ValueSource(strings={"block","fail"})
    void preservesOriginalExceptionAndAllMaterialsThroughActualInterruption(String action) throws Exception {
        String id="EVIDENCE-"+action.toUpperCase(java.util.Locale.ROOT);
        fixture(id,"COMPLETED","RUNNING","PROCESSING",true);materials(id);
        String base="/api/tasks/"+task(id)+"/reworks/"+rework(id);
        var original=request(base+"/"+action,body(0,"原异常原因  "),"t809-cause-"+action,"reviewer-test","REVIEWER");
        assertThat(original.getStatusCode().value()).isEqualTo(200);
        var before=state(id);var evidence=materialRows(id);
        var history=jdbc.queryForList("SELECT to_jsonb(x)::text FROM operation_logs x WHERE target_id=?",task(id));
        var receipts=jdbc.queryForList("SELECT response_data::text FROM rework_operation_receipts WHERE task_id=?",task(id));
        JsonNode resumed=success(request(base+"/resume",body(1,"材料已具备，继续人工处理  "),"t809-evidence-"+action,"reviewer-test","REVIEWER"));
        assertThat(resumed.path("taskVersion").asLong()).isEqualTo(2);
        assertThat(resumed.path("processingRevision").asLong()).isEqualTo(2);
        assertThat(resumed.path("inspectionId").asText()).isEqualTo("CHECK-T809-NEW-"+id);
        assertThat(resumed.path("reviewId").isNull()).isTrue();
        assertThat(state(id)).containsEntry("reason",before.get("reason")).containsEntry("started_by",before.get("started_by"))
                .containsEntry("started_at",before.get("started_at")).containsEntry("rework_status","RUNNING")
                .containsEntry("issue_status","PROCESSING").containsEntry("task_status","COMPLETED");
        assertThat(materialRows(id)).isEqualTo(evidence);
        assertThat(jdbc.queryForList("SELECT to_jsonb(x)::text FROM operation_logs x WHERE target_id=? AND operation_type<> 'RESUME_REWORK'",task(id))).isEqualTo(history);
        assertThat(jdbc.queryForList("SELECT response_data::text FROM rework_operation_receipts WHERE task_id=? AND operation_type<> 'RESUME_REWORK'",task(id))).isEqualTo(receipts);
        HttpHeaders headers=new HttpHeaders();headers.set("X-User-Id","reviewer-test");headers.set("X-User-Role","REVIEWER");
        var detail=http.exchange(base,HttpMethod.GET,new HttpEntity<>(headers),JsonNode.class);
        assertThat(detail.getStatusCode().value()).isEqualTo(200);
        assertThat(detail.getBody().path("data").path("inspection").path("result").asText()).isEqualTo("FAILED");
        assertThat(detail.getBody().path("data").path("review").isNull()).isTrue();
    }

    static Stream<Arguments> illegalStates() {
        return Stream.of(
                Arguments.of("PENDING","COMPLETED","PENDING","OPEN"),
                Arguments.of("RUNNING","COMPLETED","RUNNING","PROCESSING"),
                Arguments.of("COMPLETED","COMPLETED","COMPLETED","RESOLVED"),
                Arguments.of("ISSUEOPEN","COMPLETED","BLOCKED","OPEN"),
                Arguments.of("ISSUERESOLVED","COMPLETED","FAILED","RESOLVED"),
                Arguments.of("ISSUECLOSED","COMPLETED","BLOCKED","CLOSED"),
                Arguments.of("TASKRUNNING","RUNNING","BLOCKED","PROCESSING"),
                Arguments.of("TASKFAILED","FAILED","FAILED","PROCESSING"));
    }

    @ParameterizedTest
    @MethodSource("illegalStates")
    void rejectsStatesWithoutMutatingFacts(String label,String ts,String rs,String qs) throws Exception {
        String id="STATE-"+label;fixture(id,ts,rs,qs,true);var before=state(id);String key="t809-state-"+label;
        error(event(id,key,"不允许恢复"),409,"BUSINESS_CONFLICT");
        assertThat(state(id)).isEqualTo(before);absent(key);
    }

    @Test
    void actualCycleReplaysOriginalResumeWithoutHealingLaterFailure() throws Exception {
        String id="CYCLE";fixture(id,"COMPLETED","PENDING","OPEN",false);
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,created_by,created_at) VALUES (?,?,?,1,'creator-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')",rework(id),task(id),issue(id));
        String base="/api/tasks/"+task(id)+"/reworks/"+rework(id);
        var started=request(base+"/start","{\"expectedVersion\":0}","t809-cycle-start","reviewer-test","REVIEWER");
        assertThat(started.getStatusCode().value()).isEqualTo(200);
        var startInfo=state(id);
        var blocked=request(base+"/block",body(1,"第一次阻塞"),"t809-cycle-block","reviewer-test","REVIEWER");
        assertThat(blocked.getStatusCode().value()).isEqualTo(200);
        String reason="  已排除阻塞，人工继续  ";String key="t809-cycle-resume";
        JsonNode original=success(request(base+"/resume",body(2,reason),key,"reviewer-test","REVIEWER"));
        assertThat(original.path("taskVersion").asLong()).isEqualTo(3);
        var failed=request(base+"/fail",body(3,"再次失败原因"),"t809-cycle-fail","reviewer-test","REVIEWER");
        assertThat(failed.getStatusCode().value()).isEqualTo(200);
        assertThat(success(request(base+"/resume",body(2,reason),key,"reviewer-test","REVIEWER"))).isEqualTo(original);
        assertThat(request(base+"/start","{\"expectedVersion\":0}","t809-cycle-start","reviewer-test","REVIEWER").getBody().path("data")).isEqualTo(started.getBody().path("data"));
        assertThat(request(base+"/block",body(1,"第一次阻塞"),"t809-cycle-block","reviewer-test","REVIEWER").getBody().path("data")).isEqualTo(blocked.getBody().path("data"));
        assertThat(request(base+"/fail",body(3,"再次失败原因"),"t809-cycle-fail","reviewer-test","REVIEWER").getBody().path("data")).isEqualTo(failed.getBody().path("data"));
        error(request(base+"/resume",body(2,reason.strip()),key,"reviewer-test","REVIEWER"),409,"BUSINESS_CONFLICT");
        error(request(base+"/resume",body(4,reason),key,"reviewer-test","REVIEWER"),409,"BUSINESS_CONFLICT");
        error(request(base+"/resume",body(2,reason),key,"other-user","REVIEWER"),409,"BUSINESS_CONFLICT");
        error(event("INVALID",key,reason),409,"BUSINESS_CONFLICT");
        error(request(base+"/block",body(2,reason),key,"reviewer-test","REVIEWER"),409,"BUSINESS_CONFLICT");
        error(request(base+"/resume",body(1,"第一次阻塞"),"t809-cycle-block","reviewer-test","REVIEWER"),409,"BUSINESS_CONFLICT");
        error(request(base+"/resume",body(2,reason),key,"reviewer-test","VIEWER"),403,"PERMISSION_DENIED");
        assertThat(state(id)).containsEntry("version",4L).containsEntry("rework_status","FAILED")
                .containsEntry("issue_status","PROCESSING").containsEntry("task_status","COMPLETED")
                .containsEntry("started_by",startInfo.get("started_by")).containsEntry("started_at",startInfo.get("started_at"));
        assertThat(auditCount(key)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM operation_logs WHERE target_id=?",Integer.class,task(id))).isEqualTo(4);
        HttpHeaders headers=new HttpHeaders();headers.set("X-User-Id","reviewer-test");headers.set("X-User-Role","REVIEWER");
        var current=http.exchange(base,HttpMethod.GET,new HttpEntity<>(headers),JsonNode.class).getBody().path("data");
        assertThat(current.path("reworkTask").path("status").asText()).isEqualTo("FAILED");
        assertThat(current.path("taskVersion").asLong()).isEqualTo(4);
    }

    @Test
    void rejectsSupersededRoundAndAcceptsLastSafeIncrement() throws Exception {
        String id="SUCCESSOR";interrupted(id,"BLOCKED");
        jdbc.update("INSERT INTO rework_tasks VALUES (?,?,?,'PENDING','下一轮原因')",rework("NEXT"),task(id),issue(id));
        jdbc.update("INSERT INTO rework_lifecycles(rework_task_id,task_id,source_issue_id,round_number,previous_rework_task_id,previous_round_number,created_by,created_at) VALUES (?,?,?,2,?,1,'creator-test',TIMESTAMPTZ '2026-11-09 00:00:00+00')",rework("NEXT"),task(id),issue(id),rework(id));
        error(event(id,"t809-successor","旧轮次不可恢复"),409,"BUSINESS_CONFLICT");absent("t809-successor");
        String last="LASTSAFE";interrupted(last,"BLOCKED");
        jdbc.update("UPDATE production_tasks SET version=9007199254740990 WHERE task_id=?",task(last));
        var receipt=success(request(path(last),body(9007199254740990L,"最后一个安全版本"),"t809-lastsafe","reviewer-test","REVIEWER"));
        assertThat(receipt.path("taskVersion").asLong()).isEqualTo(9007199254740991L);
    }

    @ParameterizedTest
    @ValueSource(strings={"BLOCKED","FAILED"})
    void concurrentDifferentKeysHaveOneWinnerAndNoLoserReservation(String source) throws Exception {
        String id="RACE-"+source;fixture(id,"COMPLETED",source,"PROCESSING",true);
        String a="t809-race-"+source;String b=a+"-other";
        var results=concurrent(id,a,b);
        assertThat(results.stream().map(r->r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200,409);
        int winner=results.get(0).getStatusCode().value()==200?0:1;
        success(results.get(winner));error(results.get(1-winner),409,"BUSINESS_CONFLICT");
        assertThat(state(id)).containsEntry("version",1L).containsEntry("rework_status","RUNNING");
        assertThat(auditCount(winner==0?a:b)).isEqualTo(1);absent(winner==0?b:a);
    }

    static Stream<String> invalidBodies() {
        List<String> bodies=List.of("", "null", "[]", "{}", "{not-json}",
                "{\"expectedVersion\":0}","{\"reason\":\"原因\"}",
                "{\"expectedVersion\":0,\"reason\":null}","{\"expectedVersion\":0,\"reason\":true}",
                "{\"expectedVersion\":0,\"reason\":1}","{\"expectedVersion\":0,\"reason\":[]}",
                "{\"expectedVersion\":0,\"reason\":\"\"}","{\"expectedVersion\":0,\"reason\":\"　 \"}",
                "{\"expectedVersion\":\"0\",\"reason\":\"原因\"}","{\"expectedVersion\":0.0,\"reason\":\"原因\"}",
                "{\"expectedVersion\":true,\"reason\":\"原因\"}","{\"expectedVersion\":-1,\"reason\":\"原因\"}",
                "{\"expectedVersion\":9007199254740992,\"reason\":\"原因\"}",
                "{\"expectedVersion\":0,\"reason\":\"原因\",\"confirmed\":true}",
                "{\"expectedVersion\":0,\"reason\":\"原因\",\"status\":\"COMPLETED\"}",
                "{\"expectedVersion\":0,\"reason\":\"原因\",\"role\":\"REVIEWER\"}",
                "{\"expectedVersion\":0,\"reason\":\"原因\",\"reason\":\"不同原因\"}",
                "{\"expectedVersion\":0,\"reason\":\"原因\"} {}");
        return bodies.stream();
    }

    @ParameterizedTest
    @MethodSource("invalidBodies")
    void rejectsMissingReasonCoercionUnknownFieldsAndAmbiguousJson(String body) {
        error(request(path("INVALID"),body,"t809-invalid","reviewer-test","REVIEWER"),400,"PARAM_VALIDATION_ERROR");
        absent("t809-invalid");
        assertThat(state("INVALID")).containsEntry("version",0L).containsEntry("rework_status","BLOCKED");
    }

    @ParameterizedTest
    @ValueSource(strings={"block","fail"})
    void enforcesUtf16LimitsAndPreservesNonBmpCharacters(String action) throws Exception {
        String id="UNICODE-"+action.toUpperCase(java.util.Locale.ROOT);
        interrupted(id,source(action));
        error(event(id,"t809-long-"+action,"字".repeat(1001)),400,"PARAM_VALIDATION_ERROR");
        error(event(id,"t809-long-emoji-"+action,"🚀".repeat(501)),400,"PARAM_VALIDATION_ERROR");
        String bmp=id+"-BMP";interrupted(bmp,source(action));
        success(event(bmp,"t809-bmp-"+action,"字".repeat(1000)));
        String text="🚀".repeat(500);
        success(event(id,"t809-unicode-"+action,text));
        String stored=jdbc.queryForObject("SELECT after_state FROM operation_logs WHERE target_id=?",String.class,task(id));
        assertThat(mapper.readTree(stored).path("reason").asText()).isEqualTo(text);
        absent("t809-long-"+action);absent("t809-long-emoji-"+action);
    }

    @ParameterizedTest
    @ValueSource(ints={0,0xD800,0xDC00})
    void rejectsTextThatCannotBePreservedInPostgres(int codeUnit) throws Exception {
        String raw=mapper.writer().with(JsonGenerator.Feature.ESCAPE_NON_ASCII)
                .writeValueAsString(Map.of("expectedVersion",0,"reason",String.valueOf((char)codeUnit)));
        error(request(path("INVALID"),raw,"t809-invalid-text","reviewer-test","REVIEWER"),400,"PARAM_VALIDATION_ERROR");
        absent("t809-invalid-text");
    }

    @Test
    void validatesIdentityOwnershipIdsAndIdempotencyHeaders() throws Exception {
        String input=body(0,"只读授权失败");
        error(request(path("INVALID"),input,"t809-auth",null,"REVIEWER"),401,"PERMISSION_DENIED");
        error(request(path("INVALID"),input,"t809-auth","reviewer-test","ADMIN"),403,"PERMISSION_DENIED");
        error(request(path("INVALID"),input,"t809-auth","reviewer-test",null),403,"PERMISSION_DENIED");
        error(request(path("INVALID"),input,"t809-auth","x".repeat(129),"REVIEWER"),400,"PARAM_VALIDATION_ERROR");
        for(String key:new String[]{null,"bad key","x".repeat(129)}) error(request(path("INVALID"),input,key,"reviewer-test","REVIEWER"),400,"PARAM_VALIDATION_ERROR");
        error(request("/api/tasks/task-lower/reworks/REWORK-T809-INVALID/resume",input,"t809-auth","reviewer-test","REVIEWER"),400,"PARAM_VALIDATION_ERROR");
        error(event("MISSING","t809-missing-task","无父任务"),404,"RESOURCE_NOT_FOUND");
        error(request("/api/tasks/"+task("INVALID")+"/reworks/REWORK-MISSING/resume",input,"t809-missing-rework","reviewer-test","REVIEWER"),404,"RESOURCE_NOT_FOUND");
        error(request("/api/tasks/TASK-003/reworks/"+rework("INVALID")+"/resume",input,"t809-owner","reviewer-test","REVIEWER"),409,"BUSINESS_CONFLICT");
        for(String key:List.of("t809-auth","t809-missing-task","t809-missing-rework","t809-owner")) absent(key);
    }

    @ParameterizedTest
    @ValueSource(strings={"block","fail"})
    void rejectsMissingLifecycleSourceStaleOrExhaustedVersion(String action) throws Exception {
        String label=action.toUpperCase(java.util.Locale.ROOT);
        String legacy="LEGACY-"+label;
        fixture(legacy,"COMPLETED",source(action),"PROCESSING",false);
        error(event(legacy,"t809-legacy-"+action,"不能补轮次"),409,"BUSINESS_CONFLICT");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM rework_lifecycles WHERE rework_task_id=?",Integer.class,rework(legacy))).isZero();
        String missing="SOURCE-"+label;
        fixture(missing,"COMPLETED",source(action),"PROCESSING",false);
        jdbc.update("UPDATE rework_tasks SET source_issue_id=NULL WHERE rework_task_id=?",rework(missing));
        error(event(missing,"t809-source-"+action,"缺来源"),409,"BUSINESS_CONFLICT");
        String stale="STALE-"+label;interrupted(stale,source(action));
        jdbc.update("UPDATE production_tasks SET version=2 WHERE task_id=?",task(stale));
        error(event(stale,"t809-stale-"+action,"旧版本"),409,"BUSINESS_CONFLICT");
        String exhausted="MAX-"+label;interrupted(exhausted,source(action));
        jdbc.update("UPDATE production_tasks SET version=9007199254740991 WHERE task_id=?",task(exhausted));
        error(request(path(exhausted),body(9007199254740991L,"版本已满"),"t809-max-"+action,"reviewer-test","REVIEWER"),409,"BUSINESS_CONFLICT");
        for(String prefix:List.of("legacy","source","stale","max")) absent("t809-"+prefix+"-"+action);
    }

    static Stream<Arguments> failureTargets() {
        return Stream.of("block","fail").flatMap(action -> Stream.of("operation_logs","rework_operation_receipts").map(table -> Arguments.of(action,table)));
    }

    @ParameterizedTest
    @MethodSource("failureTargets")
    void auditOrReceiptFailureRollsBackEverythingAndKeepsEvidence(String action,String table) throws Exception {
        String id="ROLL-"+action.toUpperCase(java.util.Locale.ROOT)+(table.equals("operation_logs")?"-AUDIT":"-RECEIPT");
        interrupted(id,source(action));materials(id);
        var before=state(id);var evidence=materialRows(id);String key="t809-rollback-"+id;
        jdbc.execute("CREATE FUNCTION t809_fail_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced T809 failure'; END $$");
        jdbc.execute("CREATE TRIGGER t809_fail_write BEFORE INSERT ON "+table+" FOR EACH ROW EXECUTE FUNCTION t809_fail_write()");
        try {
            error(event(id,key,"故障不能丢证据"),500,"INTERNAL_SERVER_ERROR");
            assertThat(state(id)).isEqualTo(before);assertThat(materialRows(id)).isEqualTo(evidence);absent(key);
        } finally {
            jdbc.execute("DROP TRIGGER t809_fail_write ON "+table);jdbc.execute("DROP FUNCTION t809_fail_write()");
        }
        success(event(id,key,"故障不能丢证据"));
        assertThat(materialRows(id)).isEqualTo(evidence);assertThat(auditCount(key)).isEqualTo(1);
    }

    @ParameterizedTest
    @ValueSource(strings={"block","fail"})
    void concurrentSameKeyReturnsOneReceiptAndOneVersionIncrement(String action) throws Exception {
        String id="SAME-"+action.toUpperCase(java.util.Locale.ROOT);interrupted(id,source(action));String key="t809-same-"+action;
        var results=concurrent(id,key,key);
        assertThat(success(results.get(0))).isEqualTo(success(results.get(1)));
        assertThat(state(id)).containsEntry("version",1L);assertThat(auditCount(key)).isEqualTo(1);
    }

    private List<ResponseEntity<JsonNode>> concurrent(String id,String ka,String kb) throws Exception {
        CountDownLatch ready=new CountDownLatch(2);CountDownLatch go=new CountDownLatch(1);
        try(var pool=Executors.newFixedThreadPool(2)) {
            var first=pool.submit(()->{ready.countDown();go.await();return event(id,ka,"并发人工恢复说明");});
            var second=pool.submit(()->{ready.countDown();go.await();return event(id,kb,"并发人工恢复说明");});
            assertThat(ready.await(10,TimeUnit.SECONDS)).isTrue();go.countDown();
            return List.of(first.get(30,TimeUnit.SECONDS),second.get(30,TimeUnit.SECONDS));
        }
    }

    private Map<String,Object> golden() {
        return jdbc.queryForMap("SELECT (SELECT status FROM production_tasks WHERE task_id='TASK-003') AS task_status,(SELECT version FROM production_tasks WHERE task_id='TASK-003') AS version,(SELECT status FROM quality_issues WHERE issue_id='ISSUE-001') AS issue_status,(SELECT status FROM review_records WHERE review_id='REVIEW-003') AS review_status,(SELECT status FROM delivery_records WHERE order_id='ORDER-003' ORDER BY delivery_id LIMIT 1) AS delivery_status");
    }
}
