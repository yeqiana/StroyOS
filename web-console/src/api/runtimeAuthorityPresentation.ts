import type { RuntimeAuthorityDomain, RuntimeAuthorityReport, RuntimeStatusDetail } from './platformApi';

/**
 * R35 reader results are hints, not dispatch capabilities. Keep cross-Episode,
 * local-file and malformed "verified" claims out of the console.
 */
export function usableRuntimeAuthority(
  value: RuntimeAuthorityReport | null,
  expectedEpisode: string,
  localEvidence: boolean,
): RuntimeAuthorityReport | null {
  if (!value || !expectedEpisode || value.episode_ref !== expectedEpisode
    || value.read_only !== true || value.production_authorization !== false
    || value.can_start !== false || value.can_retry !== false || value.can_publish !== false
    || value.model_calls !== 0 || value.global_image_capacity_policy !== 5) return null;
  if (localEvidence && value.scope !== 'LOCAL_READ_ONLY_EVIDENCE') return null;
  if (!localEvidence && !['AUTHORIZED_READ_ONLY', 'AUTHORITY_NOT_CONFIGURED'].includes(value.scope)) return null;
  if (!value.evidence || typeof value.evidence !== 'object') return null;

  const domains: RuntimeAuthorityDomain[] = ['task', 'attempt', 'worker', 'writer', 'capacity'];
  if (!domains.every(name => {
    const evidence = value.evidence[name];
    return evidence && evidence.read_only === true
      && ['UNAVAILABLE', 'READ_ONLY_VERIFIED', 'ADVISORY_ONLY'].includes(evidence.status)
      && (!localEvidence || evidence.status === 'UNAVAILABLE');
  })) return null;
  return value;
}

const sourceIds: Record<RuntimeAuthorityDomain, string> = {
  task: 'mysql_task_repository',
  attempt: 'mysql_generation_attempt_authority',
  worker: 'redis_worker_heartbeat',
  writer: 'runtime_driver_owner_fence',
  capacity: 'git_common_directory_os_permits',
};

/** Safe text-only presentation: never infer Worker online, retry or available permits. */
export function runtimeEvidenceRows(
  report: RuntimeAuthorityReport | null,
  detail: RuntimeStatusDetail | null,
  localEvidence: boolean,
): { key: string; label: string; children: string }[] {
  const executionStatus = !localEvidence ? String(detail?.execution_status || '').trim().toUpperCase() : '';
  const reportedExecution = executionStatus && !['UNKNOWN', '-', 'NO_STATE'].includes(executionStatus);
  const reportedHeartbeat = !localEvidence ? String(detail?.heartbeat?.health || '').trim() : '';
  const fallback: Record<RuntimeAuthorityDomain, string> = {
    task: reportedExecution ? `仅报告状态 ${executionStatus} · Task ID 与执行租约未验证` : '权威 Task ID / 执行租约未接入',
    attempt: 'MySQL Generation Attempt、预算和当前 fencing 未接入此只读详情',
    worker: reportedHeartbeat && reportedHeartbeat.toLowerCase() !== 'unknown'
      ? `接口报告 ${reportedHeartbeat} · Worker 身份/租约未核验`
      : 'Worker 身份与权威心跳未验证',
    writer: 'Episode Driver Owner / fencing 尚未核验',
    capacity: '同一仓库全局最多 5 张；当前持锁数未接入，不能由此推断剩余名额',
  };
  const labels: Record<RuntimeAuthorityDomain, string> = {
    task: 'Task', attempt: 'Attempt', worker: 'Worker', writer: 'Writer', capacity: '图片名额',
  };
  const names: RuntimeAuthorityDomain[] = ['task', 'attempt', 'worker', 'writer', 'capacity'];
  return names.map(name => {
    const proof = !localEvidence && report?.scope === 'AUTHORIZED_READ_ONLY' ? report.evidence[name] : null;
    const trusted = proof && proof.source === sourceIds[name] &&
      (name === 'capacity' ? proof.status === 'ADVISORY_ONLY' : proof.status === 'READ_ONLY_VERIFIED') &&
      !!proof.observed_at;
    if (!trusted) return { key: name, label: labels[name], children: fallback[name] };
    switch (name) {
      case 'task':
        return { key: name, label: labels[name], children: Number.isInteger(proof.task_count)
          ? `MySQL 只读 Task 证据 ${proof.task_count} 条 · 不代表可执行` : 'MySQL Task 来源已核验，执行租约仍需验证' };
      case 'attempt':
        return { key: name, label: labels[name], children: Number.isInteger(proof.attempt_count)
          ? `MySQL Generation Attempt 证据 ${proof.attempt_count} 条${proof.unresolved ? ' · 存在未决尝试' : ''} · 不授权重试`
          : 'MySQL Generation Attempt 来源已核验，预算和当前 fencing 仍需验证' };
      case 'worker':
        return { key: name, label: labels[name], children: proof.heartbeat_verified
          ? 'Redis Worker 心跳来源已核验 · 未证明执行租约或在线调度授权'
          : fallback.worker };
      case 'writer':
        return { key: name, label: labels[name], children: proof.owner_fence_verified
          ? 'Episode Driver Owner / fencing 来源已核验 · 不授权新的 Writer'
          : fallback.writer };
      case 'capacity': {
        const busy = proof.observed_busy, free = proof.observed_available;
        return { key: name, label: labels[name], children: typeof busy === 'number' && typeof free === 'number' &&
          Number.isInteger(busy) && Number.isInteger(free) && busy + free === 5
          ? `OS 锁瞬时观察 ${busy}/5 占用，${free} 空闲 · 非预约许可，不授权派发`
          : '全局 5 图规则已确认；容量快照未完整验证，不推断可用名额' };
      }
    }
  });
}
