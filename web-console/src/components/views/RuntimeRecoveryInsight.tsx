import React from 'react';
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
  return <section aria-label="生产恢复安全诊断" className="border-t border-[var(--border-subtle)] pt-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="text-[12px] font-semibold text-[var(--text-primary)]">恢复安全诊断</h4>
      <span className="text-[11px] text-[var(--text-tertiary)]">只读建议 · 未授权执行</span>
    </div>
    <p data-recovery-code={diagnosis.code} className="mt-2 text-[12px] font-medium text-[var(--text-primary)]" role="status">{diagnosis.title}</p>
    <p className="mt-1 text-[11px] leading-5 text-[var(--text-secondary)]">{diagnosis.explanation}</p>
    <p className="mt-2 border-t border-[var(--border-subtle)] pt-2 text-[11px] text-[var(--text-tertiary)]">此处不提供启动、重试、跳过门禁或发布操作；正式恢复须由已授权 Runtime 重新确认权威状态与资源配额。</p>
  </section>;
};
