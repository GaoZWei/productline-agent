export type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;
export interface JsonObject {
  [key: string]: JsonValue;
}
// 事件类型定义
export type RunEventType =
  | "run_started"
  | "context_loaded"
  | "intent_detected"
  | "clarification_required"
  | "agent_action_selected"
  | "tool_started"
  | "tool_completed"
  | "retrieval_started"
  | "retrieval_completed"
  | "diagnosis_generated"
  | "approval_required"
  | "writeback_started"
  | "writeback_completed"
  | "run_completed"
  | "run_failed";
// 描述一条完整事件结构
export interface RunEvent {
  event_id: string; // SSE协议中的事件ID，重连时使用
  event_type: RunEventType; // 当前是什么事件
  stream_id: string; // 属于哪条浏览器事件流
  run_id: string | null; // 对应哪一次Agent运行
  sequence_number: number; // 流内严格递增序号
  occurred_at: string; // 事件发生时间
  trace_id: string; // 用于跨服务排查
  step_id: string | null; // 对应哪个持久化Step
  data: JsonObject; // 当前事件的安全摘要
}

export interface RunEventStreamErrorResponse {
  stream_id: string;
  trace_id: string;
  code: string;
  message: string;
}

export type RunEventConnectionStatus =
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed"
  | "failed";
// 连接状态定义
export interface RunEventConnectionState {
  status: RunEventConnectionStatus;
  reconnectAttempt: number;
}
