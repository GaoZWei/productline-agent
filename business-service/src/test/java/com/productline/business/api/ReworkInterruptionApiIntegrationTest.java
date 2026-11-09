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

/** 独占schema中的真实HTTP异常登记，覆盖材料保留、并发及审计/回执故障回滚。 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.flyway.schemas=t808_rework_interrupt", "spring.flyway.default-schema=t808_rework_interrupt",
        "spring.datasource.hikari.schema=t808_rework_interrupt",
        "spring.jpa.properties.hibernate.default_schema=t808_rework_interrupt"
})
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ReworkInterruptionApiIntegrationTest extends PostgresIntegrationTestSupport {
    @Autowired private TestRestTemplate http;
    @Autowired private JdbcTemplate jdbc;
    @Autowired private ObjectMapper mapper;
    private Map<String,Object> goldenBefore;

    @BeforeAll
    void prepare() {
        goldenBefore = golden();
        jdbc.update("INSERT INTO production_orders VALUES ('ORDER-T808','DOM','QUALITY_CHECKING')");
        running("INVALID");
    }

    @AfterAll
    void cleanup() {
        try {
            assertThat(golden()).isEqualTo(goldenBefore);
        } finally {
            jdbc.execute("DROP SCHEMA t808_rework_interrupt CASCADE");
        }
    }

    private String task(String id) { return "TASK-T808-" + id; }
    private String rework(String id) { return "REWORK-T808-" + id; }
    private String issue(String id) { return "ISSUE-T808-" + id; }
    private String target(String action) { return action.equals("block") ? "BLOCKED" : "FAILED"; }
    private String operation(String action) { return action.equals("block") ? "BLOCK_REWORK" : "FAIL_REWORK"; }
    private String path(String action, String id) { return "/api/tasks/" + task(id) + "/reworks/" + rework(id) + "/" + action; }

    private void running(String id) { fixture(id,"COMPLETED","RUNNING","PROCESSING",true); }

    private void fixture(String id, String taskStatus, String reworkStatus, String issueStatus, boolean lifecycle) {
        jdbc.update("INSERT INTO production_tasks(task_id,order_id,status) VALUES (?,'ORDER-T808',?)",task(id),taskStatus);
        jdbc.update("INSERT INTO quality_issues VALUES (?,?,'COORDINATE_SYSTEM',?,'独立异常测试问题')",issue(id),task(id),issueStatus);
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
        headers.set("X-Trace-Id","trace-t808-event");
        if (key != null) headers.set("Idempotency-Key",key);
        if (actor != null) headers.set("X-User-Id",actor);
        if (role != null) headers.set("X-User-Role",role);
        return http.exchange(path,HttpMethod.POST,new HttpEntity<>(body,headers),JsonNode.class);
    }

    private ResponseEntity<JsonNode> event(String action, String id, String key, String reason) throws Exception {
        return request(path(action,id),body(0,reason),key,"reviewer-test","REVIEWER");
    }

    private JsonNode success(ResponseEntity<JsonNode> response, String action) {
        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getHeaders().getFirst("X-Trace-Id")).isEqualTo("trace-t808-event");
        JsonNode envelope = response.getBody();
        assertThat(envelope).isNotNull();
        assertThat(envelope.size()).isEqualTo(6);
        assertThat(envelope.path("success").asBoolean()).isTrue();
        assertThat(envelope.path("code").asText()).isEqualTo("SUCCESS");
        assertThat(envelope.path("retryable").asBoolean()).isFalse();
        assertThat(envelope.path("trace_id").asText()).isEqualTo("trace-t808-event");
        JsonNode data = envelope.path("data");
        assertThat(data.size()).isEqualTo(12);
        assertThat(data.path("operation").asText()).isEqualTo(operation(action));
        assertThat(data.path("operationId").asText()).matches("^OPERATION-[A-Z0-9-]+$");
        assertThat(data.path("status").asText()).isEqualTo(target(action));
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
        running(id);
        var before=state(id);
        String reason="  等待处理材料\n保留说明空白  ";
        String key="t808-success-"+action;
        JsonNode data=success(event(action,id,key,reason),action);
        assertThat(data.path("taskId").asText()).isEqualTo(task(id));
        assertThat(data.path("reworkTaskId").asText()).isEqualTo(rework(id));
        assertThat(data.path("roundNumber").asLong()).isEqualTo(1);
        assertThat(data.path("taskVersion").asLong()).isEqualTo(1);
        for (String field:List.of("previousReworkTaskId","processingRevision","inspectionId","reviewId")) {
            assertThat(data.has(field)).as(field).isTrue();
            assertThat(data.get(field).isNull()).as(field).isTrue();
        }
        assertThat(state(id)).containsEntry("task_status","COMPLETED").containsEntry("version",1L)
                .containsEntry("rework_status",target(action)).containsEntry("issue_status","PROCESSING")
                .containsEntry("reason",before.get("reason")).containsEntry("started_by",before.get("started_by"))
                .containsEntry("started_at",before.get("started_at"));
        var audit=jdbc.queryForMap("SELECT actor_user_id,idempotency_key_hash,before_state,after_state,target_type,target_id FROM operation_logs WHERE operation_id=?",data.path("operationId").asText());
        assertThat(audit).containsEntry("actor_user_id","reviewer-test").containsEntry("target_type","PRODUCTION_TASK").containsEntry("target_id",task(id));
        assertThat(audit.get("idempotency_key_hash").toString()).matches("[a-f0-9]{64}");
        assertThat(mapper.readTree(audit.get("after_state").toString()).path("reason").asText()).isEqualTo(reason);
        assertThat(mapper.readTree(audit.get("before_state").toString()).path("status").asText()).isEqualTo("RUNNING");
        assertThat(audit.get("before_state").toString()+audit.get("after_state").toString()).doesNotContain(key);
        assertThat(mapper.readTree(jdbc.queryForObject("SELECT response_data::text FROM rework_operation_receipts WHERE idempotency_key=?",String.class,key))).isEqualTo(data);
    }

    private void materials(String id) {
        for (int revision=1;revision<=2;revision++) {
            jdbc.update("INSERT INTO rework_processing_revisions VALUES (?,?,'成果-A','v2','原始处理说明','[\"report:结果\"]'::jsonb,'handler-test',TIMESTAMPTZ '2026-11-09 00:02:00+00')",rework(id),revision);
        }
        jdbc.update("INSERT INTO rework_inspections VALUES (?, ?,1,1,'PASSED','[{\"checkItem\":\"坐标系\",\"result\":\"PASSED\",\"comment\":\"旧检查通过\",\"evidenceReferences\":[\"report:旧检查\"]}]'::jsonb,'inspector-test',TIMESTAMPTZ '2026-11-09 00:03:00+00')","CHECK-T808-OLD-"+id,rework(id));
        jdbc.update("INSERT INTO rework_reviews(review_id,rework_task_id,processing_revision,inspection_id,review_sequence,status,review_comment,reviewed_by,reviewed_at) VALUES (?,?,1,?,1,'APPROVED','旧修订复核','reviewer-test',TIMESTAMPTZ '2026-11-09 00:04:00+00')","REVIEW-T808-OLD-"+id,rework(id),"CHECK-T808-OLD-"+id);
        jdbc.update("INSERT INTO rework_inspections VALUES (?, ?,2,2,'FAILED','[{\"checkItem\":\"坐标系\",\"result\":\"FAILED\",\"comment\":\"当前检查失败\",\"evidenceReferences\":[\"report:当前检查\"]}]'::jsonb,'inspector-test',TIMESTAMPTZ '2026-11-09 00:05:00+00')","CHECK-T808-NEW-"+id,rework(id));
    }

    private List<Map<String,Object>> materialRows(String id) {
        return Stream.of("rework_processing_revisions","rework_inspections","rework_reviews")
                .flatMap(table -> jdbc.queryForList("SELECT to_jsonb(x)::text AS record FROM "+table+" x WHERE rework_task_id=? ORDER BY to_jsonb(x)::text",rework(id)).stream()).toList();
    }

    @ParameterizedTest
    @ValueSource(strings={"block","fail"})
    void preservesAllEvidenceAndReturnsCurrentPointersRatherThanOldApproval(String action) throws Exception {
        String id="EVIDENCE-"+action.toUpperCase(java.util.Locale.ROOT);
        running(id);materials(id);
        var before=materialRows(id);
        JsonNode data=success(event(action,id,"t808-evidence-"+action,"人工登记异常"),action);
        assertThat(materialRows(id)).isEqualTo(before);
        assertThat(data.path("processingRevision").asLong()).isEqualTo(2);
        assertThat(data.path("inspectionId").asText()).isEqualTo("CHECK-T808-NEW-"+id);
        assertThat(data.path("reviewId").isNull()).isTrue();
        HttpHeaders headers=new HttpHeaders();headers.set("X-User-Id","reviewer-test");headers.set("X-User-Role","REVIEWER");
        var current=http.exchange("/api/tasks/"+task(id)+"/reworks/"+rework(id),HttpMethod.GET,new HttpEntity<>(headers),JsonNode.class);
        assertThat(current.getStatusCode().value()).isEqualTo(200);
        JsonNode detail=current.getBody().path("data");
        assertThat(detail.path("reworkTask").path("status").asText()).isEqualTo(target(action));
        assertThat(detail.path("reworkTask").path("reason").asText()).isEqualTo("原始创建原因");
        assertThat(detail.path("inspection").path("result").asText()).isEqualTo("FAILED");
        assertThat(detail.path("review").isNull()).isTrue();
    }

    static Stream<Arguments> invalidBodies() {
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
        return Stream.of("block","fail").flatMap(action -> bodies.stream().map(body -> Arguments.of(action,body)));
    }

    @ParameterizedTest
    @MethodSource("invalidBodies")
    void rejectsMissingReasonCoercionUnknownFieldsAndAmbiguousJson(String action,String body) {
        error(request(path(action,"INVALID"),body,"t808-invalid","reviewer-test","REVIEWER"),400,"PARAM_VALIDATION_ERROR");
        absent("t808-invalid");
        assertThat(state("INVALID")).containsEntry("version",0L).containsEntry("rework_status","RUNNING");
    }

    @ParameterizedTest
    @ValueSource(strings={"block","fail"})
    void enforcesUtf16LimitsAndPreservesNonBmpCharacters(String action) throws Exception {
        String id="UNICODE-"+action.toUpperCase(java.util.Locale.ROOT);
        running(id);
        error(event(action,id,"t808-long-"+action,"字".repeat(1001)),400,"PARAM_VALIDATION_ERROR");
        error(event(action,id,"t808-long-emoji-"+action,"🚀".repeat(501)),400,"PARAM_VALIDATION_ERROR");
        String text="🚀".repeat(500);
        success(event(action,id,"t808-unicode-"+action,text),action);
        String stored=jdbc.queryForObject("SELECT after_state FROM operation_logs WHERE target_id=?",String.class,task(id));
        assertThat(mapper.readTree(stored).path("reason").asText()).isEqualTo(text);
        absent("t808-long-"+action);absent("t808-long-emoji-"+action);
    }

    @ParameterizedTest
    @ValueSource(ints={0,0xD800,0xDC00})
    void rejectsTextThatCannotBePreservedInPostgres(int codeUnit) throws Exception {
        String raw=mapper.writer().with(JsonGenerator.Feature.ESCAPE_NON_ASCII)
                .writeValueAsString(Map.of("expectedVersion",0,"reason",String.valueOf((char)codeUnit)));
        error(request(path("block","INVALID"),raw,"t808-invalid-text","reviewer-test","REVIEWER"),400,"PARAM_VALIDATION_ERROR");
        absent("t808-invalid-text");
    }

    static Stream<Arguments> illegalStates() {
        return Stream.of("block","fail").flatMap(action -> Stream.of(
                new String[]{"PENDING","COMPLETED","PENDING","OPEN"},
                new String[]{"BLOCKED","COMPLETED","BLOCKED","PROCESSING"},
                new String[]{"FAILED","COMPLETED","FAILED","PROCESSING"},
                new String[]{"COMPLETED","COMPLETED","COMPLETED","RESOLVED"},
                new String[]{"ISSUEOPEN","COMPLETED","RUNNING","OPEN"},
                new String[]{"ISSUECLOSED","COMPLETED","RUNNING","CLOSED"},
                new String[]{"TASKRUNNING","RUNNING","RUNNING","PROCESSING"},
                new String[]{"TASKFAILED","FAILED","RUNNING","PROCESSING"})
                .map(values -> Arguments.of(action,values[0],values[1],values[2],values[3])));
    }

    @ParameterizedTest
    @MethodSource("illegalStates")
    void rejectsTerminalOrUnstartedStatesWithoutMutatingFacts(String action,String label,String ts,String rs,String qs) throws Exception {
        String id="STATE-"+action.toUpperCase(java.util.Locale.ROOT)+"-"+label;
        fixture(id,ts,rs,qs,true);
        var before=state(id);
        String key="t808-state-"+id;
        error(event(action,id,key,"非法状态不应登记"),409,"BUSINESS_CONFLICT");
        assertThat(state(id)).isEqualTo(before);absent(key);
    }

    @Test
    void validatesIdentityOwnershipIdsAndIdempotencyHeaders() throws Exception {
        String input=body(0,"只读授权失败");
        error(request(path("block","INVALID"),input,"t808-auth",null,"REVIEWER"),401,"PERMISSION_DENIED");
        error(request(path("fail","INVALID"),input,"t808-auth","reviewer-test","ADMIN"),403,"PERMISSION_DENIED");
        error(request(path("fail","INVALID"),input,"t808-auth","reviewer-test",null),403,"PERMISSION_DENIED");
        error(request(path("block","INVALID"),input,"t808-auth","x".repeat(129),"REVIEWER"),400,"PARAM_VALIDATION_ERROR");
        for(String key:new String[]{null,"bad key","x".repeat(129)}) error(request(path("block","INVALID"),input,key,"reviewer-test","REVIEWER"),400,"PARAM_VALIDATION_ERROR");
        error(request("/api/tasks/task-lower/reworks/REWORK-T808-INVALID/block",input,"t808-auth","reviewer-test","REVIEWER"),400,"PARAM_VALIDATION_ERROR");
        error(event("block","MISSING","t808-missing-task","无父任务"),404,"RESOURCE_NOT_FOUND");
        error(request("/api/tasks/"+task("INVALID")+"/reworks/REWORK-MISSING/fail",input,"t808-missing-rework","reviewer-test","REVIEWER"),404,"RESOURCE_NOT_FOUND");
        error(request("/api/tasks/TASK-003/reworks/"+rework("INVALID")+"/block",input,"t808-owner","reviewer-test","REVIEWER"),409,"BUSINESS_CONFLICT");
        for(String key:List.of("t808-auth","t808-missing-task","t808-missing-rework","t808-owner")) absent(key);
    }

    @ParameterizedTest
    @ValueSource(strings={"block","fail"})
    void rejectsMissingLifecycleSourceStaleOrExhaustedVersion(String action) throws Exception {
        String label=action.toUpperCase(java.util.Locale.ROOT);
        String legacy="LEGACY-"+label;
        fixture(legacy,"COMPLETED","RUNNING","PROCESSING",false);
        error(event(action,legacy,"t808-legacy-"+action,"不能补轮次"),409,"BUSINESS_CONFLICT");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM rework_lifecycles WHERE rework_task_id=?",Integer.class,rework(legacy))).isZero();
        String missing="SOURCE-"+label;
        fixture(missing,"COMPLETED","RUNNING","PROCESSING",false);
        jdbc.update("UPDATE rework_tasks SET source_issue_id=NULL WHERE rework_task_id=?",rework(missing));
        error(event(action,missing,"t808-source-"+action,"缺来源"),409,"BUSINESS_CONFLICT");
        String stale="STALE-"+label;running(stale);
        jdbc.update("UPDATE production_tasks SET version=2 WHERE task_id=?",task(stale));
        error(event(action,stale,"t808-stale-"+action,"旧版本"),409,"BUSINESS_CONFLICT");
        String exhausted="MAX-"+label;running(exhausted);
        jdbc.update("UPDATE production_tasks SET version=9007199254740991 WHERE task_id=?",task(exhausted));
        error(request(path(action,exhausted),body(9007199254740991L,"版本已满"),"t808-max-"+action,"reviewer-test","REVIEWER"),409,"BUSINESS_CONFLICT");
        for(String prefix:List.of("legacy","source","stale","max")) absent("t808-"+prefix+"-"+action);
    }

    @ParameterizedTest
    @ValueSource(strings={"block","fail"})
    void replayUsesOriginalReceiptAndBindsExactReasonUserTargetAndOperation(String action) throws Exception {
        String id="REPLAY-"+action.toUpperCase(java.util.Locale.ROOT);running(id);
        String key="t808-replay-"+action;
        String reason="  原因必须原样绑定  ";
        JsonNode original=success(event(action,id,key,reason),action);
        jdbc.update("UPDATE rework_tasks SET status='RUNNING' WHERE rework_task_id=?",rework(id));
        jdbc.update("UPDATE production_tasks SET version=2 WHERE task_id=?",task(id));
        assertThat(success(event(action,id,key,reason),action)).isEqualTo(original);
        error(event(action,id,key,reason.strip()),409,"BUSINESS_CONFLICT");
        error(request(path(action,id),body(0,reason),key,"other-user","REVIEWER"),409,"BUSINESS_CONFLICT");
        error(request(path(action,id),body(2,reason),key,"reviewer-test","REVIEWER"),409,"BUSINESS_CONFLICT");
        error(event(action.equals("block")?"fail":"block",id,key,reason),409,"BUSINESS_CONFLICT");
        error(event(action,"INVALID",key,reason),409,"BUSINESS_CONFLICT");
        error(request(path(action,id),body(0,reason),key,"reviewer-test","VIEWER"),403,"PERMISSION_DENIED");
        assertThat(state(id)).containsEntry("version",2L).containsEntry("rework_status","RUNNING");
        assertThat(auditCount(key)).isEqualTo(1);
        assertThat(keyCount("rework_operation_receipts",key)).isEqualTo(1);
    }

    static Stream<Arguments> failureTargets() {
        return Stream.of("block","fail").flatMap(action -> Stream.of("operation_logs","rework_operation_receipts").map(table -> Arguments.of(action,table)));
    }

    @ParameterizedTest
    @MethodSource("failureTargets")
    void auditOrReceiptFailureRollsBackEverythingAndKeepsEvidence(String action,String table) throws Exception {
        String id="ROLL-"+action.toUpperCase(java.util.Locale.ROOT)+(table.equals("operation_logs")?"-AUDIT":"-RECEIPT");
        running(id);materials(id);
        var before=state(id);var evidence=materialRows(id);String key="t808-rollback-"+id;
        jdbc.execute("CREATE FUNCTION t808_fail_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'forced T808 failure'; END $$");
        jdbc.execute("CREATE TRIGGER t808_fail_write BEFORE INSERT ON "+table+" FOR EACH ROW EXECUTE FUNCTION t808_fail_write()");
        try {
            error(event(action,id,key,"故障不能丢证据"),500,"INTERNAL_SERVER_ERROR");
            assertThat(state(id)).isEqualTo(before);assertThat(materialRows(id)).isEqualTo(evidence);absent(key);
        } finally {
            jdbc.execute("DROP TRIGGER t808_fail_write ON "+table);jdbc.execute("DROP FUNCTION t808_fail_write()");
        }
        success(event(action,id,key,"故障不能丢证据"),action);
        assertThat(materialRows(id)).isEqualTo(evidence);assertThat(auditCount(key)).isEqualTo(1);
    }

    @ParameterizedTest
    @ValueSource(strings={"block","fail"})
    void concurrentSameKeyReturnsOneReceiptAndOneVersionIncrement(String action) throws Exception {
        String id="SAME-"+action.toUpperCase(java.util.Locale.ROOT);running(id);String key="t808-same-"+action;
        var results=concurrent(id,action,key,action,key);
        assertThat(success(results.get(0),action)).isEqualTo(success(results.get(1),action));
        assertThat(state(id)).containsEntry("version",1L);assertThat(auditCount(key)).isEqualTo(1);
    }

    @ParameterizedTest
    @ValueSource(booleans={false,true})
    void concurrentBlockAndFailHaveOneWinnerAndNoPartialWrite(boolean sameKey) throws Exception {
        String id=sameKey?"RACE-SAME":"RACE-DIFFERENT";running(id);
        String first="t808-race-"+id;String second=sameKey?first:first+"-other";
        var results=concurrent(id,"block",first,"fail",second);
        assertThat(results.stream().map(r->r.getStatusCode().value()).toList()).containsExactlyInAnyOrder(200,409);
        int winner=results.get(0).getStatusCode().value()==200?0:1;
        JsonNode receipt=success(results.get(winner),winner==0?"block":"fail");
        error(results.get(1-winner),409,"BUSINESS_CONFLICT");
        assertThat(state(id)).containsEntry("version",1L).containsEntry("rework_status",receipt.path("status").asText()).containsEntry("issue_status","PROCESSING");
        assertThat(keyCount("rework_operation_receipts",first)+(sameKey?0:keyCount("rework_operation_receipts",second))).isEqualTo(1);
        if(!sameKey) absent(winner==0?second:first);
    }

    private List<ResponseEntity<JsonNode>> concurrent(String id,String a,String ka,String b,String kb) throws Exception {
        CountDownLatch ready=new CountDownLatch(2);CountDownLatch go=new CountDownLatch(1);
        try(var pool=Executors.newFixedThreadPool(2)) {
            var first=pool.submit(()->{ready.countDown();go.await();return event(a,id,ka,"并发异常原因");});
            var second=pool.submit(()->{ready.countDown();go.await();return event(b,id,kb,"并发异常原因");});
            assertThat(ready.await(10,TimeUnit.SECONDS)).isTrue();go.countDown();
            return List.of(first.get(30,TimeUnit.SECONDS),second.get(30,TimeUnit.SECONDS));
        }
    }

    private Map<String,Object> golden() {
        return jdbc.queryForMap("SELECT (SELECT status FROM production_tasks WHERE task_id='TASK-003') AS task_status,(SELECT version FROM production_tasks WHERE task_id='TASK-003') AS version,(SELECT status FROM quality_issues WHERE issue_id='ISSUE-001') AS issue_status,(SELECT status FROM review_records WHERE review_id='REVIEW-003') AS review_status,(SELECT status FROM delivery_records WHERE order_id='ORDER-003' ORDER BY delivery_id LIMIT 1) AS delivery_status");
    }
}
