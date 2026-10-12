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

// GET /api/v1/runtime/status?episode=... -> data (detail 投影)
export interface RuntimeStatusDetail {
  schema_version?: number;
  observed_at?: string | null;
  episode?: string | null;
  production_stage?: string | null;
  execution_status?: string | null;
  blocking_reason?: string | null;
  current_action?: string | null;
  next_step?: string | null;
  image_progress?: ImageProgress;
  review_progress?: ReviewProgress;
  auto_recoverable?: boolean | null;
  needs_user?: boolean | null;
  heartbeat?: Heartbeat;
  dag?: DagState;
  consistency_warnings?: string[];
  source_states?: Record<string, unknown>;
  sources?: Record<string, RuntimeSourceRef>;
  episode_ref?: string | null;
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

// ================= Platform API 客户端 =================

export const platformApi = {
  // GET /healthz
  async health(): Promise<PlatformHealthResponse> {
    return platformRequest<PlatformHealthResponse>('/healthz', { timeoutMs: 5000 });
  },

  // GET /api/v1/runtime/statuses?limit&offset
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
