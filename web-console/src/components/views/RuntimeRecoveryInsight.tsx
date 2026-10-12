import React, { useEffect, useState } from 'react';
import { Descriptions } from 'antd';
import type { RuntimeAuthorityReport, RuntimeStatusDetail } from '../../api/platformApi';
import { platformApi } from '../../api/platformApi';
import { assessRuntimeRecovery } from '../../api/runtimeRecoveryAssessment';
import { runtimeEvidenceRows, usableRuntimeAuthority } from '../../api/runtimeAuthorityPresentation';

interface Props {
  episodeRef: string;
  detail: RuntimeStatusDetail | null;
  source: string | null | undefined;
  detailLoaded: boolean;
}

/** Two inspect-only drawers share the identity-validated, fail-closed R35 evidence. */
export const RuntimeRecoveryInsight: React.FC<Props> = ({ episodeRef, detail, source, detailLoaded }) => {
  const diagnosis = assessRuntimeRecovery(detailLoaded ? detail : null, source);
  const localEvidence = source === 'local_workspace_episode_state_file' || source === 'isolated-test';
  const [authority, setAuthority] = useState<RuntimeAuthorityReport | null>(null);
  const [authorityState, setAuthorityState] = useState<'loading' | 'ready' | 'unavailable'>('loading');
  // An inspector can remain open for hours. Expire timestamp-based read-side
  // evidence locally rather than leaving an old "verified" badge on screen.
  // This does not poll the server or mutate runtime state.
  const [, refreshProofAge] = useState(0);
  useEffect(() => {
    const ticker = setInterval(() => refreshProofAge(value => value + 1), 15000);
    return () => clearInterval(ticker);
  }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setAuthority(null);
    setAuthorityState('loading');
    if (!episodeRef) {
      setAuthorityState('unavailable');
      return () => { active = false; controller.abort(); };
    }
    platformApi.runtimeAuthority(episodeRef, controller.signal).then(data => {
      if (!active) return;
      const checked = usableRuntimeAuthority(data, episodeRef, localEvidence);
      setAuthority(checked);
      setAuthorityState(checked ? 'ready' : 'unavailable');
    }).catch(() => {
      if (active) {
        setAuthority(null);
        setAuthorityState('unavailable');
      }
    });
    return () => { active = false; controller.abort(); };
  }, [episodeRef, localEvidence]);

  // Effects run after paint; never render a previously selected Episode's
  // authority report even for one frame during a Drawer selection change.
  const currentAuthority = usableRuntimeAuthority(authority, episodeRef, localEvidence);
  const currentState = authorityState === 'ready' && !currentAuthority ? 'unavailable' : authorityState;
  const evidenceRows = runtimeEvidenceRows(currentAuthority, detailLoaded ? detail : null, localEvidence);
  const verifiedSources = currentAuthority ? Object.values(currentAuthority.evidence).filter(
    item => item.status === 'READ_ONLY_VERIFIED' || item.status === 'ADVISORY_ONLY',
  ).length : 0;
  return <section aria-label="生产恢复安全诊断" className="border-t border-[var(--border-subtle)] pt-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="text-[12px] font-semibold text-[var(--text-primary)]">恢复安全诊断</h4>
      <span className="text-[11px] text-[var(--text-tertiary)]">只读建议 · 未授权执行</span>
    </div>
    <p data-recovery-code={diagnosis.code} className="mt-2 text-[12px] font-medium text-[var(--text-primary)]" role="status">{diagnosis.title}</p>
    <p className="mt-1 text-[11px] leading-5 text-[var(--text-secondary)]">{diagnosis.explanation}</p>
    <div className="mt-3 border-t border-[var(--border-subtle)] pt-3" aria-label="Task Attempt Worker 生产证据矩阵">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h5 className="text-[11px] font-semibold text-[var(--text-secondary)]">生产证据完整度</h5>
        <div className="flex items-center gap-2 text-[11px] text-[var(--text-tertiary)]">
          <span>R36 · TTL / fencing</span>
          <span data-r37-sample-consistency="non-atomic-readonly" title="双读只能核对采样期间的身份变化，不是原子事务或生产执行许可">R37 · 双读一致性</span>
          <span data-authority-verified-count={verifiedSources} title="来源核验通过仅代表只读观测，不代表启动、重试或图片名额许可" className="rounded-[4px] border border-[var(--border-normal)] px-1.5 py-0.5 tabular-nums">已核验 {verifiedSources}/5</span>
        </div>
      </div>
      {currentState === 'ready' && currentAuthority?.scope === 'LOCAL_READ_ONLY_EVIDENCE'
        ? <p data-authority-scope="LOCAL_READ_ONLY_EVIDENCE" role="status" className="mb-2 text-[11px] leading-5 text-[var(--text-tertiary)]">已通过只读接口核对当前 Episode；Task / Attempt / Worker / Writer 在线权威数据未授权接入，容量只显示全仓库五图规则。</p>
        : currentState === 'ready'
        ? <p data-authority-scope={currentAuthority?.scope} role="status" className="mb-2 text-[11px] leading-5 text-[var(--text-tertiary)]">权威证据接口已响应；仅显示当前 Episode 经来源与时间验证的只读结果，不能作为执行许可。</p>
        : currentState === 'unavailable'
        ? <p role="status" className="mb-2 text-[11px] text-[var(--text-tertiary)]">权威证据接口不可读取；保留未核验证据提示，不推断在线或可恢复。</p>
        : <p role="status" className="mb-2 text-[11px] text-[var(--text-tertiary)]">正在核查本 Episode 的只读权威证据…</p>}
      <Descriptions size="small" column={1} colon={false} items={evidenceRows} />
      <p className="mt-2 text-[11px] leading-5 text-[var(--text-tertiary)]" data-r37-evidence-expiry="120s">R37 证据采样非原子事务；Worker/Writer 接入时须双次核验，最多保留 120 秒的只读观测有效性，超时自动撤销已核验展示。</p>
    </div>
    <p className="mt-2 border-t border-[var(--border-subtle)] pt-2 text-[11px] text-[var(--text-tertiary)]">此处不提供启动、重试、跳过门禁或发布操作；正式恢复须由已授权 Runtime 重新确认权威状态与资源配额。</p>
  </section>;
};
