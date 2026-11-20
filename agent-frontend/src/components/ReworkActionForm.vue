<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  cancelReworkAction, confirmReworkAction, isPageReworkAction, previewReworkAction, readReworkRecovery,
  reconcileReworkAction, ReworkActionError, storeReworkRecovery,
  type PageReworkAction, type PageReworkCommand, type ReworkActionPreview,
} from "../api/reworkActionClient";
import { reworkActionLabels, type InspectionResult, type ReworkDetail, type ReworkReview } from "../types/rework";
import type { ReworkInspectionItem } from "../types/reworkApproval";
import ReworkRecord from "./ReworkRecord.vue";

const props = defineProps<{ orderId: string; detail: ReworkDetail }>();
const emit = defineEmits<{
  busy: [value: boolean]; written: [operationId: string, nextReworkId: string | null]; refresh: [];
}>();
const target = {
  order_id: props.orderId,
  task_id: props.detail.reworkTask.taskId,
  rework_task_id: props.detail.reworkTask.reworkTaskId,
};
const actions = computed(() => props.detail.allowedActions.filter(isPageReworkAction).filter(item => {
  if (item === "REGISTER_REWORK_INSPECTION") return props.detail.processing !== null;
  if (item === "SUBMIT_REWORK_REVIEW") {
    return props.detail.processing !== null && props.detail.inspection?.result === "PASSED";
  }
  if (item === "CREATE_NEXT_REWORK") {
    return props.detail.review?.status === "REJECTED" || props.detail.review?.status === "REWORK_REQUIRED";
  }
  return true;
}));
const action = ref<PageReworkAction>();
const reason = ref("");
const artifactId = ref("");
const artifactVersion = ref("");
const comment = ref("");
const evidence = ref("");
const reviewStatus = ref<ReworkReview["status"] | "">("");
const reviewComment = ref("");
const reviewLabels: Record<ReworkReview["status"], string> = {
  APPROVED: "通过",
  REJECTED: "驳回",
  REWORK_REQUIRED: "退回返工",
};
interface InspectionInput {
  id: number;
  checkItem: string;
  result: InspectionResult | "";
  comment: string;
  evidence: string;
}
let nextInspectionId = 0;
function newInspection(): InspectionInput {
  return { id: ++nextInspectionId, checkItem: "", result: "", comment: "", evidence: "" };
}
const inspections = ref([newInspection()]);
const pending = ref(false);
const recovery = ref(readReworkRecovery(target));
const uncertain = computed(() => recovery.value !== undefined);
const waitingForConfirmation = ref(false);
const failure = ref("");
const trace = ref<string>();
const preview = ref<ReworkActionPreview>();
const submitted = ref<PageReworkCommand>();
let active = true;
onBeforeUnmount(() => { active = false; });
watch(() => !!action.value || pending.value || uncertain.value, value => emit("busy", value), {
  flush: "sync", immediate: true,
});

const nonWhitespace = /[^\t\n\v\f\r\x1c-\x1f \u1680\u2000-\u2006\u2008-\u200a\u2028\u2029\u205f\u3000]/u;
const boundarySpace = /^[\t\n\v\f\r\x1c-\x1f \u1680\u2000-\u2006\u2008-\u200a\u2028\u2029\u205f\u3000]|[\t\n\v\f\r\x1c-\x1f \u1680\u2000-\u2006\u2008-\u200a\u2028\u2029\u205f\u3000]$/u;
const nonblank = (value: string, max: number) => nonWhitespace.test(value) && !value.includes("\0") && value.length <= max;
const identifier = (value: string, max: number) => nonblank(value, max) && !boundarySpace.test(value);
const refreshable = computed(() => [
  "APPROVAL_STALE", "APPROVAL_EXPIRED", "APPROVAL_CANCELLED", "BUSINESS_CONFLICT", "NOT_SUBMITTED",
].includes(failure.value));

function evidenceReferences(value: string): string[] | undefined {
  const references = value.split(/\r?\n/u);
  return references.length <= 20 && references.every(text => identifier(text, 1024))
    ? references : undefined;
}

function clear() {
  action.value = undefined;
  submitted.value = undefined;
  preview.value = undefined;
  reason.value = artifactId.value = artifactVersion.value = comment.value = evidence.value = "";
  reviewStatus.value = reviewComment.value = "";
  inspections.value = [newInspection()];
  failure.value = "";
  trace.value = undefined;
}

function showError(error: unknown) {
  failure.value = error instanceof ReworkActionError ? error.code : "REQUEST_FAILED";
  trace.value = error instanceof ReworkActionError ? error.traceId : undefined;
}

function commandForForm(): PageReworkCommand | undefined {
  const operation = action.value;
  if (!operation || !actions.value.includes(operation)) return;
  const { taskId, reworkTaskId } = props.detail.reworkTask;
  const target = { task_id: taskId, rework_task_id: reworkTaskId };
  if (operation === "START_REWORK") return { ...target, operation };
  if (operation === "REGISTER_REWORK_INSPECTION") {
    const items: ReworkInspectionItem[] = [];
    for (const item of inspections.value) {
      const references = evidenceReferences(item.evidence);
      if (!item.result || !nonblank(item.checkItem, 128) || !nonblank(item.comment, 1000) || !references) return;
      items.push({ checkItem: item.checkItem, result: item.result, comment: item.comment, evidenceReferences: references });
    }
    return { ...target, operation, items };
  }
  if (operation === "SUBMIT_REWORK_REVIEW") {
    if (!reviewStatus.value || !nonblank(reviewComment.value, 1000)) return;
    return { ...target, operation, status: reviewStatus.value, review_comment: reviewComment.value };
  }
  if (operation !== "REGISTER_REWORK_RESULT") {
    if (nonblank(reason.value, 1000)) return { ...target, operation, reason: reason.value };
    return;
  }
  const references = evidenceReferences(evidence.value);
  if (!identifier(artifactId.value, 256) || !identifier(artifactVersion.value, 128)
    || !nonblank(comment.value, 1000) || !references) return;
  return {
    ...target, operation, artifact: { artifactId: artifactId.value, artifactVersion: artifactVersion.value },
    processing_comment: comment.value, evidence_references: references,
  };
}

async function prepare() {
  if (pending.value || preview.value || uncertain.value) return;
  const command = commandForForm();
  if (!command) {
    failure.value = "请填写必填材料，并检查长度和证据引用格式。";
    return;
  }
  pending.value = true;
  failure.value = "";
  trace.value = undefined;
  try {
    const result = await previewReworkAction(props.orderId, props.detail, command);
    if (!active) {
      // 页面已离开，尽力取消未确认的草稿。
      await cancelReworkAction(result).catch(() => undefined);
      return;
    }
    submitted.value = command;
    preview.value = result;
  } catch (error) {
    if (active) showError(error);
  } finally {
    if (active) pending.value = false;
  }
}

async function confirm() {
  const current = preview.value;
  if (!current || pending.value || uncertain.value) return;
  pending.value = true;
  recovery.value = current;
  // 提交前记住原审批。切单或响应丢失后，只允许对原审批核对。
  storeReworkRecovery(target, current);
  failure.value = "";
  trace.value = undefined;
  try {
    const result = await confirmReworkAction(current);
    if (!active) return;
    if (result.outcome === "SUCCEEDED") {
      finishSuccess(result.operationId, result.nextReworkId);
    } else {
      failure.value = result.code ?? result.outcome;
    }
  } catch (error) {
    if (!active) return;
    showError(error);
    if (refreshable.value) {
      forgetRecovery();
      preview.value = undefined;
      submitted.value = undefined;
      action.value = undefined;
    }
  } finally {
    if (active) pending.value = false;
  }
}

function forgetRecovery() {
  storeReworkRecovery(target);
  recovery.value = undefined;
  waitingForConfirmation.value = false;
}

function finishSuccess(operationId: string, nextReworkId: string | null) {
  if (nextReworkId === target.rework_task_id) throw new ReworkActionError("RESPONSE_VALIDATION_ERROR");
  forgetRecovery();
  clear();
  emit("written", operationId, nextReworkId);
}

function finishWithoutSubmission() {
  forgetRecovery();
  clear();
  failure.value = "NOT_SUBMITTED";
}

async function reconcile() {
  const current = recovery.value;
  if (!current || pending.value) return;
  pending.value = true;
  waitingForConfirmation.value = false;
  failure.value = "";
  trace.value = undefined;
  try {
    const result = await reconcileReworkAction(current, target);
    if (!active) return;
    if (result.outcome === "SUCCEEDED") finishSuccess(result.operationId, result.nextReworkId);
    else if (result.outcome === "NOT_SUBMITTED") finishWithoutSubmission();
    else {
      waitingForConfirmation.value = result.outcome === "WAITING_CONFIRMATION";
      failure.value = "code" in result && result.code ? result.code : result.outcome;
    }
  } catch (error) {
    if (active) showError(error);
  } finally {
    if (active) pending.value = false;
  }
}

async function cancelUnconfirmed() {
  const current = recovery.value;
  if (!current || pending.value || !waitingForConfirmation.value) return;
  pending.value = true;
  waitingForConfirmation.value = false;
  try {
    await cancelReworkAction(current);
    if (active) finishWithoutSubmission();
  } catch (error) {
    if (!active) return;
    if (error instanceof ReworkActionError && error.code === "APPROVAL_EXPIRED") finishWithoutSubmission();
    else showError(error);
  } finally {
    if (active) pending.value = false;
  }
}

async function cancel() {
  const current = preview.value;
  if (pending.value || uncertain.value) return;
  if (!current) { clear(); return; }
  pending.value = true;
  failure.value = "";
  trace.value = undefined;
  try {
    await cancelReworkAction(current);
    if (active) clear();
  } catch (error) {
    if (active) showError(error);
  } finally {
    if (active) pending.value = false;
  }
}
</script>

<template>
  <section v-if="actions.length || recovery || failure" class="rework-action-form" aria-label="返工操作" :aria-busy="pending">
    <div v-if="!action && !uncertain && !refreshable" class="rework-detail-actions">
      <button v-for="item in actions" :key="item" type="button" :disabled="pending" @click="clear(); action = item">
        {{ reworkActionLabels[item] }}
      </button>
    </div>
    <form v-else-if="action && !preview && !uncertain" @submit.prevent="prepare">
      <h4>{{ reworkActionLabels[action] }}</h4>
      <fieldset :disabled="pending">
        <template v-if="action === 'REGISTER_REWORK_RESULT'">
          <label>成果标识<input v-model="artifactId" required maxlength="256" /></label>
          <label>成果版本<input v-model="artifactVersion" required maxlength="128" /></label>
          <label>处理说明<textarea v-model="comment" required maxlength="1000" rows="3" /></label>
          <label>证据引用（每行一条，最多 20 条）<textarea v-model="evidence" required rows="3" /></label>
        </template>
        <template v-else-if="action === 'REGISTER_REWORK_INSPECTION'">
          <p v-if="detail.processing">检查成果修订 {{ detail.processing.processingRevision }} · {{ detail.processing.artifact.artifactId }} · 版本 {{ detail.processing.artifact.artifactVersion }}</p>
          <fieldset v-for="(item, index) in inspections" :key="item.id" class="rework-check-item">
            <legend>检查项 {{ index + 1 }}</legend>
            <label>检查项名称<input v-model="item.checkItem" required maxlength="128" /></label>
            <label>检查结果
              <select v-model="item.result" required>
                <option disabled value="">请选择</option>
                <option value="PASSED">通过</option>
                <option value="FAILED">失败</option>
              </select>
            </label>
            <label>检查说明<textarea v-model="item.comment" required maxlength="1000" rows="2" /></label>
            <label>检查证据引用（每行一条）<textarea v-model="item.evidence" required rows="2" /></label>
            <button v-if="inspections.length > 1" type="button" @click="inspections.splice(index, 1)">
              移除此项
            </button>
          </fieldset>
          <button type="button" :disabled="inspections.length >= 50" @click="inspections.push(newInspection())">
            添加检查项
          </button>
        </template>
        <template v-else-if="action === 'SUBMIT_REWORK_REVIEW'">
          <p v-if="detail.processing && detail.inspection">
            复核成果修订 {{ detail.processing.processingRevision }} · 检查 {{ detail.inspection.inspectionId }}
          </p>
          <label>复核结论
            <select v-model="reviewStatus" required>
              <option disabled value="">请选择</option>
              <option v-for="(label, status) in reviewLabels" :key="status" :value="status">{{ label }}</option>
            </select>
          </label>
          <label>复核意见<textarea v-model="reviewComment" required maxlength="1000" rows="3" /></label>
        </template>
        <label v-else-if="action !== 'START_REWORK'">原因<textarea v-model="reason" required maxlength="1000" rows="3" /></label>
        <div class="rework-detail-actions">
          <button type="submit">预览操作</button>
          <button type="button" @click="cancel">取消填写</button>
        </div>
      </fieldset>
    </form>
    <section v-if="preview && submitted" aria-label="返工操作预览">
      <h4>确认{{ reworkActionLabels[submitted.operation] }}</h4>
      <p>{{ submitted.task_id }} · {{ submitted.rework_task_id }} · 第 {{ preview.roundNumber }} 轮 · 任务版本 {{ preview.taskVersion }}</p>
      <p>来源问题 {{ preview.issueId }}，有效期至 {{ new Date(preview.expiresAt).toLocaleString() }}</p>
      <p v-if="'reason' in submitted" class="original-text">{{ submitted.reason }}</p>
      <section v-if="preview.previousReview" aria-label="上一轮复核">
        <ReworkRecord kind="reviews" :record="preview.previousReview" />
        <p>本次独立审批用于创建新一轮待开始返工，上一轮证据与历史继续保留。</p>
      </section>
      <template v-if="submitted.operation === 'REGISTER_REWORK_RESULT'">
        <p>成果 {{ submitted.artifact.artifactId }} · 版本 {{ submitted.artifact.artifactVersion }}</p>
        <p class="original-text">{{ submitted.processing_comment }}</p>
        <ul><li v-for="(reference, index) in submitted.evidence_references" :key="index">{{ reference }}</li></ul>
      </template>
      <template v-if="submitted.operation === 'REGISTER_REWORK_INSPECTION' || submitted.operation === 'SUBMIT_REWORK_REVIEW'">
        <section v-if="preview.boundMaterials" aria-label="审批绑定的成果与证据">
          <h5>绑定成果与证据</h5>
          <ReworkRecord kind="results" :record="preview.boundMaterials.processing" />
          <ReworkRecord v-if="preview.boundMaterials.inspection"
            kind="inspections" :record="preview.boundMaterials.inspection" />
        </section>
        <template v-if="submitted.operation === 'REGISTER_REWORK_INSPECTION'">
          <h5>本次人工检查</h5>
          <ol>
            <li v-for="(item, index) in submitted.items" :key="index">
              <strong>{{ item.checkItem }} · {{ item.result === 'PASSED' ? '通过' : '失败' }}</strong>
              <p class="original-text">{{ item.comment }}</p>
              <ul><li v-for="(reference, refIndex) in item.evidenceReferences" :key="refIndex">{{ reference }}</li></ul>
            </li>
          </ol>
          <p v-if="preview.reworkStatusAfter === 'COMPLETED'">检查通过后本轮处理完成，问题仍需再次复核。</p>
          <p v-else>登记失败检查后，问题仍待处理。</p>
        </template>
        <template v-else-if="submitted.operation === 'SUBMIT_REWORK_REVIEW'">
          <p>本次复核结论：{{ reviewLabels[submitted.status] }}</p>
          <p class="original-text">{{ submitted.review_comment }}</p>
          <p v-if="preview.deliveryEffect === 'RECHECK_ONLY'">复核通过后仍需核查其他交付条件。</p>
          <p v-else>本次结论将重新打开来源问题，保留该轮检查和复核历史。</p>
        </template>
      </template>
      <p>Java 接受后的预期状态：返工 {{ preview.reworkStatusAfter }}，问题 {{ preview.issueStatusAfter }}。</p>
      <div v-if="!uncertain" class="rework-detail-actions">
        <button type="button" :disabled="pending" @click="confirm">确认并执行</button>
        <button type="button" :disabled="pending" @click="cancel">取消操作</button>
      </div>
    </section>
    <p v-if="pending" role="status">正在处理请求…</p>
    <div v-if="failure" role="alert">
      <p>{{ failure }}<small v-if="trace"> · Trace {{ trace }}</small></p>
      <p v-if="uncertain">执行结果待核对。审批编号 {{ recovery?.approvalId }}。</p>
      <p v-else-if="failure === 'NOT_SUBMITTED'">原审批已结束，未提交写入。</p>
      <button v-if="!uncertain && refreshable"
        type="button" :disabled="pending" @click="emit('refresh')">刷新后重新核对</button>
    </div>
    <section v-if="recovery" aria-label="原审批结果核对">
      <p v-if="!failure">待核对审批 {{ recovery.approvalId }}</p>
      <p v-if="waitingForConfirmation">尚未记录确认，可取消原待确认审批。</p>
      <div class="rework-detail-actions">
        <button type="button" :disabled="pending" @click="reconcile">核对原审批结果</button>
        <button v-if="waitingForConfirmation" type="button" :disabled="pending" @click="cancelUnconfirmed">
          取消原待确认审批
        </button>
      </div>
    </section>
  </section>
</template>
