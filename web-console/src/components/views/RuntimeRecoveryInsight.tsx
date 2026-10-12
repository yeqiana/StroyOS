import React from 'react';
import { Descriptions } from 'antd';
import type { RuntimeStatusDetail } from '../../api/platformApi';
import { assessRuntimeRecovery } from '../../api/runtimeRecoveryAssessment';

interface Props {
  detail: RuntimeStatusDetail | null;
  source: string | null | undefined;
  detailLoaded: boolean;
}

/** Read-only, fail-closed production recovery triage shared by monitor and workflow inspectors. */
export const RuntimeRecoveryInsight: React.FC<Props> = ({ detail, source, detailLoaded }) => {
  const diagnosis = assessRuntimeRecovery(detailLoaded ? detail : null, source);
  const localEvidence = source === 'local_workspace_episode_state_file' || source === 'isolated-test';
  const executionStatus = !localEvidence && detailLoaded ? String(detail?.execution_status || '').trim().toUpperCase() : '';
  const reportedExecution = executionStatus && !['UNKNOWN', '-', 'NO_STATE'].includes(executionStatus);
  const reportedHeartbeat = !localEvidence && detailLoaded ? String(detail?.heartbeat?.health || '').trim() : '';
  const evidenceRows = [
    { key: 'task', label: 'Task', children: reportedExecution ? `仅报告状态 ${executionStatus} · Task ID 与执行租约未验证` : '权威 Task ID / 执行租约未接入' },
    { key: 'attempt', label: 'Attempt', children: 'MySQL Generation Attempt、预算和当前 fencing 未接入此只读详情' },
    { key: 'worker', label: 'Worker', children: reportedHeartbeat && reportedHeartbeat.toLowerCase() !== 'unknown' ? `接口报告 ${reportedHeartbeat} · Worker 身份/租约未核验` : 'Worker 身份与权威心跳未验证' },
    { key: 'owner', label: 'Writer', children: 'Episode Driver Owner / fencing 尚未核验' },
    { key: 'capacity', label: '图片名额', children: '同一仓库全局最多 5 张；当前持锁数未接入，不能由此推断剩余名额' },
  ];
  return <section aria-label="生产恢复安全诊断" className="border-t border-[var(--border-subtle)] pt-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="text-[12px] font-semibold text-[var(--text-primary)]">恢复安全诊断</h4>
      <span className="text-[11px] text-[var(--text-tertiary)]">只读建议 · 未授权执行</span>
    </div>
    <p data-recovery-code={diagnosis.code} className="mt-2 text-[12px] font-medium text-[var(--text-primary)]" role="status">{diagnosis.title}</p>
    <p className="mt-1 text-[11px] leading-5 text-[var(--text-secondary)]">{diagnosis.explanation}</p>
    <div className="mt-3 border-t border-[var(--border-subtle)] pt-3" aria-label="Task Attempt Worker 生产证据矩阵">
      <h5 className="mb-2 text-[11px] font-semibold text-[var(--text-secondary)]">生产证据完整度</h5>
      <Descriptions size="small" column={1} colon={false} items={evidenceRows} />
    </div>
    <p className="mt-2 border-t border-[var(--border-subtle)] pt-2 text-[11px] text-[var(--text-tertiary)]">此处不提供启动、重试、跳过门禁或发布操作；正式恢复须由已授权 Runtime 重新确认权威状态与资源配额。</p>
  </section>;
};
