import type { JsonValue, RunEvent } from "../types/runEvents";

export type RunTimelineKind =
  | "run"
  | "context"
  | "router"
  | "agent"
  | "tool"
  | "rag"
  | "diagnosis"
  | "approval"
  | "writeback";
export type RunTimelineStatus =
  | "running"
  | "succeeded"
  | "failed"
  | "waiting"
  | "degraded"
  | "info";

export interface RunTimelineItem {
  key: string;
  kind: RunTimelineKind;
  label: string;
  detail: string | null;
  status: RunTimelineStatus;
  startedAt: string;
  completedAt: string | null;
  durationMs: number | null;
  errorCode: string | null;
  sourceName: string | null;
}

const TOOL_LABELS: Record<string, string> = {
  load_order: "查询订单详情",
  load_tasks: "查询关联任务",
  load_progress: "查询生产进度",
  load_quality: "查询质检问题",
  load_review: "查询复核结果",
  load_delivery: "查询交付状态",
};
// 时间事件线归并函数
export function buildRunTimeline(events: readonly RunEvent[]): RunTimelineItem[] {
  const ordered = [...new Map(events.map((event) => [event.sequence_number, event])).values()].sort(
    (left, right) => left.sequence_number - right.sequence_number,
  );
  const items: RunTimelineItem[] = [];
  const byKey = new Map<string, RunTimelineItem>();

  const add = (item: RunTimelineItem) => {
    items.push(item);
    byKey.set(item.key, item);
    return item;
  };
  const instant = (
    event: RunEvent,
    kind: RunTimelineKind,
    label: string,
    detail: string | null,
    status: RunTimelineStatus = "succeeded",
  ) =>
    add({
      key: `${kind}:${event.event_id}`,
      kind,
      label,
      detail,
      status,
      startedAt: event.occurred_at,
      completedAt: status === "running" || status === "waiting" ? null : event.occurred_at,
      durationMs: status === "running" || status === "waiting" ? null : 0,
      errorCode: null,
      sourceName: null,
    });

  for (const event of ordered) {
    switch (event.event_type) {
      case "run_started":
        add({
          key: runKey(event),
          kind: "run",
          label: "执行订单诊断",
          detail: text(event.data.session_id)
            ? `会话 ${text(event.data.session_id)}`
            : null,
          status: "running",
          startedAt: event.occurred_at,
          completedAt: null,
          durationMs: null,
          errorCode: null,
          sourceName: null,
        });
        break;
      case "context_loaded":
        instant(
          event,
          "context",
          "加载页面与会话上下文",
          joinDetail([text(event.data.order_id), text(event.data.current_page)]),
        );
        break;
      case "intent_detected":
        instant(
          event,
          "router",
          "识别用户意图",
          joinDetail([
            text(event.data.intent),
            number(event.data.confidence) === null
              ? null
              : `置信度 ${Math.round(number(event.data.confidence)! * 100)}%`,
          ]),
        );
        break;
      case "clarification_required":
        instant(
          event,
          "router",
          "等待补充信息",
          stringList(event.data.missing_fields).join("、") || null,
          "waiting",
        );
        break;
      case "agent_action_selected":
        instant(
          event,
          "agent",
          "Agent选择下一步动作",
          joinDetail([text(event.data.action), text(event.data.tool_name)]),
          "info",
        );
        break;
      case "tool_started": {
        const stepName = text(event.data.step_name);
        const key = toolKey(event, stepName);
        add({
          key,
          kind: "tool",
          label: toolLabel(stepName),
          detail: stepName,
          status: "running",
          startedAt: event.occurred_at,
          completedAt: null,
          durationMs: null,
          errorCode: null,
          sourceName: stepName,
        });
        break;
      }
      case "tool_completed": {
        const stepName = text(event.data.step_name);
        const key = toolKey(event, stepName);
        const item = byKey.get(key) ??
          add({
            key,
            kind: "tool",
            label: toolLabel(stepName),
            detail: stepName,
            status: "running",
            startedAt: event.occurred_at,
            completedAt: null,
            durationMs: null,
            errorCode: null,
            sourceName: stepName,
          });
        complete(
          item,
          event,
          text(event.data.status) === "FAILED" ? "failed" : "succeeded",
          text(event.data.error_code),
        );
        break;
      }
      case "retrieval_started":
        add({
          key: `rag:${event.event_id}`,
          kind: "rag",
          label: "检索现行规范",
          detail: joinDetail([
            text(event.data.permission_scope),
            text(event.data.effective_at),
          ]),
          status: "running",
          startedAt: event.occurred_at,
          completedAt: null,
          durationMs: null,
          errorCode: null,
          sourceName: "retrieval",
        });
        break;
      case "retrieval_completed": {
        const item = findLast(items, (candidate) => candidate.kind === "rag" && candidate.status === "running") ??
          add({
            key: `rag:${event.event_id}`,
            kind: "rag",
            label: "检索现行规范",
            detail: null,
            status: "running",
            startedAt: event.occurred_at,
            completedAt: null,
            durationMs: null,
            errorCode: null,
            sourceName: "retrieval",
          });
        const retrieved = number(event.data.retrieved_count);
        const selected = number(event.data.selected_count);
        const degraded = event.data.rerank_degraded === true;
        item.detail = joinDetail([
          retrieved === null || selected === null
            ? null
            : `召回 ${retrieved} 条，保留 ${selected} 条`,
          degraded ? "重排已降级" : null,
        ]);
        complete(item, event, degraded ? "degraded" : "succeeded", degraded ? "RERANK_DEGRADED" : null);
        break;
      }
      case "diagnosis_generated":
        instant(
          event,
          "diagnosis",
          "生成诊断结论",
          joinDetail([
            text(event.data.blocking_stage),
            countDetail(event.data.root_cause_count, "个根因"),
            countDetail(event.data.evidence_count, "条证据"),
          ]),
        );
        break;
      case "approval_required":
        add({
          key: approvalKey(event),
          kind: "approval",
          label: "等待人工确认",
          detail: joinDetail([text(event.data.target_id), text(event.data.approval_id)]),
          status: "waiting",
          startedAt: event.occurred_at,
          completedAt: null,
          durationMs: null,
          errorCode: null,
          sourceName: text(event.data.approval_id),
        });
        break;
      case "writeback_started": {
        const approval = byKey.get(approvalKey(event));
        if (approval?.status === "waiting") complete(approval, event, "succeeded", null);
        add({
          key: writebackKey(event),
          kind: "writeback",
          label: writebackLabel(text(event.data.tool_name)),
          detail: text(event.data.target_id),
          status: "running",
          startedAt: event.occurred_at,
          completedAt: null,
          durationMs: null,
          errorCode: null,
          sourceName: text(event.data.tool_name),
        });
        break;
      }
      case "writeback_completed": {
        const key = writebackKey(event);
        const item = byKey.get(key) ??
          add({
            key,
            kind: "writeback",
            label: "写回业务系统",
            detail: null,
            status: "running",
            startedAt: event.occurred_at,
            completedAt: null,
            durationMs: null,
            errorCode: null,
            sourceName: null,
          });
        const succeeded = text(event.data.status) === "SUCCEEDED";
        complete(item, event, succeeded ? "succeeded" : "failed", text(event.data.error_code));
        break;
      }
      case "run_completed": {
        const item = byKey.get(runKey(event));
        if (item) complete(item, event, "succeeded", null);
        break;
      }
      case "run_failed": {
        const errorCode = text(event.data.error_code) ?? "RUN_FAILED";
        const run = byKey.get(runKey(event)) ??
          add({
            key: runKey(event),
            kind: "run",
            label: "执行订单诊断",
            detail: text(event.data.error_step),
            status: "running",
            startedAt: event.occurred_at,
            completedAt: null,
            durationMs: null,
            errorCode: null,
            sourceName: null,
          });
        complete(run, event, "failed", errorCode);
        const errorStep = text(event.data.error_step);
        const active =
          findLast(
            items,
            (candidate) =>
              candidate.status === "running" &&
              candidate.kind !== "run" &&
              (!errorStep || candidate.sourceName === errorStep),
          ) ??
          findLast(
            items,
            (candidate) => candidate.status === "running" && candidate.kind !== "run",
          );
        if (active) complete(active, event, "failed", errorCode);
        break;
      }
    }
  }
  return items;
}

function complete(
  item: RunTimelineItem,
  event: RunEvent,
  status: "succeeded" | "failed" | "degraded",
  errorCode: string | null,
) {
  item.status = status;
  item.completedAt = event.occurred_at;
  item.durationMs = duration(item.startedAt, event.occurred_at);
  item.errorCode = errorCode;
}

function runKey(event: RunEvent) {
  return `run:${event.run_id ?? event.stream_id}`;
}

function toolKey(event: RunEvent, stepName: string | null) {
  return `tool:${event.step_id ?? stepName ?? event.event_id}`;
}

function approvalKey(event: RunEvent) {
  return `approval:${text(event.data.approval_id) ?? event.event_id}`;
}

function writebackKey(event: RunEvent) {
  return `writeback:${text(event.data.approval_id) ?? event.event_id}`;
}

function toolLabel(stepName: string | null) {
  return stepName ? (TOOL_LABELS[stepName] ?? `执行 ${stepName}`) : "执行只读Tool";
}

function writebackLabel(toolName: string | null) {
  if (toolName === "write_review_result") return "写回复核结果";
  if (toolName === "create_rework_task") return "创建返工任务";
  return "写回业务系统";
}

function duration(start: string, end: string) {
  return Math.max(0, Date.parse(end) - Date.parse(start));
}

function text(value: JsonValue | undefined): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function number(value: JsonValue | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringList(value: JsonValue | undefined): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function countDetail(value: JsonValue | undefined, suffix: string) {
  const resolved = number(value);
  return resolved === null ? null : `${resolved} ${suffix}`;
}

function joinDetail(parts: Array<string | null>) {
  const values = parts.filter((item): item is string => Boolean(item));
  return values.length ? values.join(" · ") : null;
}

function findLast<T>(values: T[], predicate: (value: T) => boolean): T | undefined {
  for (let index = values.length - 1; index >= 0; index -= 1) {
    const value = values[index];
    if (value !== undefined && predicate(value)) return value;
  }
  return undefined;
}
