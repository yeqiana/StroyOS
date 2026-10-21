import { platformRequest } from './httpClient';

// ================= Platform API 真实契约类型 =================
// 字段以 platform/api/routes.py 的后端实现与 127.0.0.1:8080 实测响应为准。

// GET /api/v1/runtime/statuses -> data.items (summary 投影)
export interface RuntimeStatusSummary {
  schema_version: number;
  projection_level: string;
  episode_id: string;
  business_episode_id?: string | null;
  episode?: string | null;
  title?: string | null;
  episode_ref?: string | null;
  production_stage?: string | null;
  state_source?: string | null;
  updated_at?: string | null;
  observed_at?: string | null;
  writer_owner_status?: string | null;
}

export interface RuntimeStatusList {
  items: RuntimeStatusSummary[];
  count: number;
  total: number;
  stage_counts: Record<string, number>;
  limit: number;
  offset: number;
  has_more: boolean;
  errors: string[];
}

export interface RecordedFrameEvidence {
  frame: number;
  ledger_status: string | null;
  queue_status: string | null;
  recorded_attempt_entries: number | null;
  queue_attempts: number | null;
  approved_in_ledger: boolean;
  last_error_code: string | null;
  queue_history_count: number;
}
export interface RecordedCheckpointStep {
  step: string;
  status: string;
  attempt: number | null;
  finished_at: string | null;
}
export interface RecordedReviewEvidence {
  recorded_status: string | null;
  decision: string | null;
  passed: boolean | null;
  source: string;
}

// GET /api/v1/runtime/status?episode=... -> data (detail 投影)
/** SELECT-only observed database rows; never task-dispatch or Worker authority. */
export interface LocalMySqlMonitor {
  scope: 'MYSQL_EPISODE_READ_ONLY';
  read_only: true;
  available: boolean;
  reason: string | null;
  observed_at: string | null;
  database_identity_verified: boolean;
  read_only_grants_verified: boolean;
  records_limit_per_table: number;
  may_be_truncated: boolean;
  task_records: Array<{task_type: string | null; status: string | null; frame: number | null; attempt_no: number | null; updated_at: string | null}>;
  production_attempt_records: Array<{frame: number | null; attempt_no: number | null; kind: string | null; status: string | null; error_code: string | null; elapsed_ms: number | null; recorded_at: string | null}>;
  generation_attempt_records: Array<{frame: number | null; attempt_index: number | null; status: string | null; failure_class: string | null; dispatch_recorded_at: string | null; terminal_recorded_at: string | null}>;
  writer_owner_verified: false;
  worker_execution_verified: false;
  production_authorization: false;
}

export interface RecordedProductionProgress {
  scope: 'VERIFIED_EPISODE_RECORDED_PROGRESS';
  available: boolean;
  reason: string | null;
  read_only: true;
  verified_current_frame: null;
  verified_current_task: null;
  provider_call_verified: false;
  stalled_verified: false;
  execution_in_progress_verified: false;
  writer_producer_claim_fresh: boolean;
  recent_task: null | {
    task_type: string | null;
    recorded_status: string | null;
    frame: number | null;
    attempt_no: number | null;
    recorded_updated_at: string | null;
    age_seconds: number | null;
  };
  recent_frame: null | RecordedFrameAttemptSummary;
  frame_attempts: RecordedFrameAttemptSummary[];
  unresolved_generation_count: number;
  unresolved_generation_sample_only: true;
  may_be_truncated: boolean;
}
export interface RecordedFrameAttemptSummary {
  frame: number;
  last_attempt_no: number | null;
  last_recorded_status: string | null;
  last_kind: string | null;
  last_error_code: string | null;
  last_recorded_duration_ms: number | null;
  recorded_at: string | null;
  age_seconds: number | null;
}

export interface LocalProviderCallObservation {
  scope: 'CANONICAL_PROVIDER_CALL_WINDOW_READ_ONLY';
  read_only: true;
  status: 'UNKNOWN' | 'FRESH_PROVIDER_CALL_EVIDENCE';
  reason: string | null;
  verified_current_frames: number[];
  verified_current_image_attempts: Array<{
    frame: number;
    attempt_index: number;
    provider_call_age_seconds: number;
  }>;
  provider_call_verified: boolean;
  kernel_lock_verified: false;
  task_id_verified: false;
  stalled_verified: false;
  observed_at: string;
}

export interface RuntimeStatusDetail {
  story_excerpt?: string | null;
  story_excerpt_source?: 'local_story_draft' | null;
  schema_version?: number;
  observed_at?: string | null;
  episode?: string | null;
  production_stage?: string | null;
  execution_status?: string | null;
  blocking_reason?: string | null;
  /** Verified A15 story review and historical rc4 supersession, not a dispatch permit. */
  resume_admission?: {
    status: 'WAITING_EXPLICIT_START' | 'NOT_VERIFIED' | string;
    story_gate_verified?: boolean;
    read_only: true;
    production_authorization: false;
    image_entitlement_verified?: false;
  };
  story_review_authority?: {
    status: 'PASS_VERIFIED' | 'UNVERIFIED' | string;
    attempt?: number | null;
    read_only: true;
  };
  current_action?: string | null;
  next_step?: string | null;
  image_progress?: ImageProgress;
  monitoring_scope?: 'RECORDED_FILES_ONLY' | string;
  read_only?: boolean;
  frame_records?: RecordedFrameEvidence[];
  mysql_monitor?: LocalMySqlMonitor;
  recorded_production_progress?: RecordedProductionProgress;
  provider_call_observation?: LocalProviderCallObservation;
  writer_owner_observation?: {status: string; reason: string | null; read_only: true; fresh_seconds?: number | null; producer_process_verified?: boolean; kernel_lock_verified?: false; provider_inflight_verified?: false};
  queue_summary?: {recorded_items: number; status_counts: Record<string, number>; recorded_at?: string | null} | null;
  checkpoint_steps?: RecordedCheckpointStep[];
  review_records?: Record<string, RecordedReviewEvidence>;
  runner_record?: {recorded_status: string | null; last_heartbeat_recorded_at: string | null; verified_live: false} | null;
  recorded_sources?: Record<string,{source: string; recorded_at: string | null}>;
  source_errors?: string[];
  review_progress?: ReviewProgress;
  auto_recoverable?: boolean | null;
  needs_user?: boolean | null;
  heartbeat?: Heartbeat;
  dag?: DagState;
  consistency_warnings?: string[];
  source_states?: Record<string, unknown>;
  sources?: Record<string, RuntimeSourceRef>;
  episode_ref?: string | null;
  image_attempted_frames_observed?: number | null;
  image_attempt_source?: string | null;
  last_event_at?: string | null;
}

// R35: GET /api/v1/runtime/authority?episode=... — explicitly read-only.
// Verified evidence may be supplied only by an authorized backend reader;
// in local file mode every runtime domain is UNAVAILABLE.
export type RuntimeAuthorityDomain = 'task' | 'attempt' | 'worker' | 'writer' | 'capacity';
export interface RuntimeAuthorityEvidenceItem {
  status: 'UNAVAILABLE' | 'READ_ONLY_VERIFIED' | 'ADVISORY_ONLY';
  reason?: string;
  source?: string | null;
  observed_at?: string | null;
  read_only: boolean;
  task_count?: number;
  attempt_count?: number;
  unresolved?: boolean;
  unknown?: boolean;
  heartbeat_verified?: boolean;
  owner_fence_verified?: boolean;
  observed_busy?: number;
  observed_available?: number;
  advisory_snapshot_only?: boolean;
}
export interface RuntimeAuthorityReport {
  schema_version: number;
  episode_ref: string;
  scope: 'LOCAL_READ_ONLY_EVIDENCE' | 'AUTHORIZED_READ_ONLY' | 'AUTHORITY_NOT_CONFIGURED';
  stage_source?: string | null;
  read_only: boolean;
  production_authorization: false;
  can_start: false;
  can_retry: false;
  can_publish: false;
  model_calls: 0;
  global_image_capacity_policy: 5;
  evidence: Record<RuntimeAuthorityDomain, RuntimeAuthorityEvidenceItem>;
}

export interface ImageProgress {
  expected_frames?: number;
  generated_frames?: number;
  accepted_frames?: number;
  weak_pass_frames?: number;
  pending_review_frames?: number;
  pending_decision_frames?: number;
  technical_failed_frames?: number;
  queued_frames?: string[];
  running_frames?: string[];
}

export interface ReviewProgress {
  visual_lock_total?: number;
  visual_lock_accepted?: number;
  visual_lock_weak_pass?: number;
  visual_lock_failed?: number;
  content_review_pending?: number;
  content_decision_pending?: number;
}

export interface Heartbeat {
  at?: string | null;
  health?: string | null;
  runner_status?: string | null;
  host_loop?: string | null;
}

export interface DagState {
  status?: string | null;
  current_step?: string | null;
  attempt?: number | null;
  updated_at?: string | null;
}

export interface RuntimeSourceRef {
  path?: string;
  present?: boolean;
  source_kind?: string;
}

// GET /api/v1/runtime/events -> data.items
export interface RuntimeEventItem {
  event_id: string;
  event_type: string;
  aggregate_type?: string | null;
  aggregate_id?: string | null;
  episode_id?: string | null;
  occurred_at?: string | null;
  trace_id?: string | null;
  task_id?: string | null;
}

export interface RuntimeEventList {
  items: RuntimeEventItem[];
  count: number;
  total: number;
  limit: number;
  offset: number;
  has_more?: boolean;
  errors?: string[];
}

// GET /api/v1/traces -> data.items
export interface TraceSpanItem {
  span_id?: string;
  trace_id?: string;
  parent_span_id?: string | null;
  episode_id?: string | null;
  span_name?: string;
  category?: string;
  status?: string;
  start_time?: string | null;
  end_time?: string | null;
  elapsed_ms?: number | null;
  attributes?: string | null;
  create_time?: string | null;
  request_id?: string | null;
  task_id?: string | null;
  error_text?: string | null;
  operation?: string;
  started_at?: string | null;
  ended_at?: string | null;
  duration_ms?: number | null;
  error?: string | null;
}

export interface TraceList {
  items: TraceSpanItem[];
  count: number;
  total: number;
  limit: number;
  offset: number;
  has_more?: boolean;
  errors?: string[];
}

export interface MemorySearchResult {
  items: Array<Record<string, unknown>>;
  total?: number;
}

// ================= 前端展示归一化 =================

export const UNKNOWN = String.fromCharCode(45);

export interface RuntimeStatusRow {
  episode_ref: string;
  episode_id: string;
  title: string;
  production_stage: string;
  execution_status: string;
  current_action: string;
  image_progress: { accepted_frames: number; expected_frames: number };
  updated_at: string;
  state_source: string;
  heartbeat_health: string | null;
  blocking_reason: string | null;
  auto_recoverable: boolean | null;
  needs_user: boolean | null;
}

export interface PlatformHealthResponse {
  status: string;
}

/**
 * 把后端 summary 投影归一化为前端行。
 *
 * summary 端点只承载阶段事实（episode_ref / production_stage / state_source / updated_at），
 * 不含 execution_status / frames / heartbeat。这些字段一律显式置空而不是回退本地常量，
 * 需要真实值时由调用方再按 episode_ref 取 detail 投影补齐。
 */
export function normalizeRuntimeStatusSummary(row: RuntimeStatusSummary): RuntimeStatusRow {
  const ref = String(row.episode_ref || row.episode || row.title || row.business_episode_id || row.episode_id || '');
  const displayTitle = String(row.title || ref);
  return {
    episode_ref: ref,
    episode_id: String(row.episode_id || ''),
    title: displayTitle,
    production_stage: String(row.production_stage || 'NO_STATE'),
    execution_status: UNKNOWN,
    current_action: UNKNOWN,
    image_progress: { accepted_frames: 0, expected_frames: 0 },
    updated_at: String(row.updated_at || row.observed_at || ''),
    state_source: String(row.state_source || UNKNOWN),
    heartbeat_health: null,
    blocking_reason: null,
    auto_recoverable: null,
    needs_user: null,
  };
}

/** 用 detail 投影补齐 summary 不可达字段；detail 缺失时保持空，不编造默认值。 */
export function applyRuntimeStatusDetail(row: RuntimeStatusRow, detail: RuntimeStatusDetail | null): RuntimeStatusRow {
  if (!detail) return row;
  const image = detail.image_progress || {};
  return {
    ...row,
    production_stage: String(detail.production_stage || row.production_stage),
    execution_status: String(detail.execution_status || UNKNOWN),
    current_action: String(detail.current_action || detail.next_step || UNKNOWN),
    image_progress: {
      accepted_frames: Number(image.accepted_frames || 0),
      expected_frames: Number(image.expected_frames || 0),
    },
    heartbeat_health: detail.heartbeat && detail.heartbeat.health ? String(detail.heartbeat.health) : null,
    blocking_reason: detail.blocking_reason === undefined ? null : detail.blocking_reason,
    auto_recoverable: detail.auto_recoverable === undefined ? null : detail.auto_recoverable,
    needs_user: detail.needs_user === undefined ? null : detail.needs_user,
  };
}

/** 阶段名到中文标签；未知阶段原样返回，不臆造映射。 */
const STAGE_LABELS: Record<string, string> = {
  IDEA_LOCKED: '创意锁定',
  STORYBOARD_LOCKED: '分镜锁定',
  VISUAL_CALIBRATED: '视觉校准',
  PRODUCTION_PASSED: '生产通过',
  PUBLISH_READY: '待发布',
  PUBLISHED: '已发布',
  DATA_REVIEWED: '数据复盘',
  NO_STATE: '无状态',
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] || stage;
}

/** 后端 execution_status 到前端 StoryRunStatus 的映射；无对应语义时归 PENDING，不猜运行态。 */
export function mapExecutionStatus(executionStatus: string): 'RUNNING' | 'WAITING' | 'RETRYING' | 'BLOCKED' | 'FAILED' | 'COMPLETED' | 'CANCELLED' | 'PENDING' {
  switch (String(executionStatus || '').toUpperCase()) {
    case 'RUNNING':
    case 'RUN':
    case 'IN_PROGRESS':
      return 'RUNNING';
    case 'WAITING':
    case 'QUEUED':
      return 'WAITING';
    case 'RETRYING':
      return 'RETRYING';
    case 'BLOCKED':
      return 'BLOCKED';
    case 'FAILED':
      return 'FAILED';
    case 'COMPLETED':
    case 'COMPLETE':
      return 'COMPLETED';
    case 'CANCELLED':
      return 'CANCELLED';
    default:
      return 'PENDING';
  }
}

/** Global Redis heartbeat observations only: not Episode-specific Writer ownership. */
export interface LocalWorkerHeartbeatSnapshot {
  scope: 'LOCAL_REDIS_HEARTBEAT_OBSERVATION';
  read_only: true;
  observed_at: string;
  source: 'redis_storyos_worker_heartbeat';
  available: boolean;
  reason: string | null;
  record_count: number;
  fresh_heartbeats: number;
  stale_heartbeats: number;
  unverified_heartbeats: number;
  scan_complete: boolean;
  worker_execution_verified: false;
  writer_owner_verified: false;
  task_attempt_verified: false;
}

/** TaskStateManager stores status only, never proven live execution. */
export interface LocalTaskStateSnapshot {
  scope: 'LOCAL_REDIS_TASK_STATE_OBSERVATION';
  source: 'redis_storyos_task_state';
  read_only: true;
  observed_at: string;
  available: boolean;
  reason: string | null;
  scan_complete: boolean;
  record_count: number;
  unverified_count: number;
  running_claims: number;
  queued_claims: number;
  records: Array<{
    task_tag: string;
    recorded_status: string;
    episode_ref: null;
    frame: null;
    worker: null;
    updated_at: null;
    freshness_verified: false;
  }>;
  live_execution_verified: false;
  episode_binding_verified: false;
}

// ================= Platform API 客户端 =================

export const platformApi = {
  // GET /healthz
  async health(): Promise<PlatformHealthResponse> {
    return platformRequest<PlatformHealthResponse>('/healthz', { timeoutMs: 5000 });
  },

  // GET /api/v1/runtime/statuses?limit&offset
  async localTaskStates(): Promise<LocalTaskStateSnapshot> {
    return platformRequest<LocalTaskStateSnapshot>('/api/v1/local-monitor/tasks');
  },
  async localWorkerHeartbeats(): Promise<LocalWorkerHeartbeatSnapshot> {
    return platformRequest<LocalWorkerHeartbeatSnapshot>('/api/v1/local-monitor/workers');
  },
  async runtimeStatuses(limit = 20, offset = 0): Promise<RuntimeStatusList> {
    return platformRequest<RuntimeStatusList>(`/api/v1/runtime/statuses?limit=${limit}&offset=${offset}`);
  },

  // GET /api/v1/runtime/status?episode=...
  async runtimeStatus(episodeRef: string): Promise<RuntimeStatusDetail | null> {
    return platformRequest<RuntimeStatusDetail | null>('/api/v1/runtime/status?episode=' + encodeURIComponent(episodeRef));
  },

  // R35: opt-in read-only authority evidence; unavailable is a safe outcome.
  async runtimeAuthority(episodeRef: string, signal?: AbortSignal): Promise<RuntimeAuthorityReport> {
    return platformRequest<RuntimeAuthorityReport>('/api/v1/runtime/authority?episode=' + encodeURIComponent(episodeRef), { signal });
  },

  // GET /api/v1/runtime/events?limit&offset&episode_id
  async events(limit = 50, offset = 0, episodeId = ''): Promise<RuntimeEventList> {
    const suffix = episodeId ? '&episode_id=' + encodeURIComponent(episodeId) : '';
    return platformRequest<RuntimeEventList>(`/api/v1/runtime/events?limit=${limit}&offset=${offset}${suffix}`);
  },

  // GET /api/v1/executions/:id
  async execution(id: string): Promise<unknown> {
    return platformRequest('/api/v1/executions/' + encodeURIComponent(id));
  },

  // GET /api/v1/traces/:id
  async trace(id: string): Promise<unknown> {
    return platformRequest('/api/v1/traces/' + encodeURIComponent(id));
  },

  // GET /api/v1/traces?limit&offset&episode_id&trace_id
  async traces(limit = 20, offset = 0, episodeId = '', traceId = ''): Promise<TraceList> {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (episodeId) params.set('episode_id', episodeId);
    if (traceId) params.set('trace_id', traceId);
    return platformRequest<TraceList>(`/api/v1/traces?${params.toString()}`);
  },

  // POST /api/v1/memory/search
  async memory(query: string): Promise<MemorySearchResult> {
    return platformRequest<MemorySearchResult>('/api/v1/memory/search', { method: 'POST', body: { query } });
  },

  // GET /api/v1/agents (列表路由未在 PLATFORM_API_ROUTES 注册，调用方需处理不可用)
  async agents(): Promise<{ items: unknown[] }> {
    return platformRequest<{ items: unknown[] }>('/api/v1/agents');
  },
};

export default platformApi;
