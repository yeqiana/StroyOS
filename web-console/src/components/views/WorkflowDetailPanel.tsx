import React, { useEffect, useState } from 'react';
import { Drawer } from 'antd';
import { platformApi, RuntimeStatusDetail, RuntimeStatusSummary, stageLabel } from '../../api/platformApi';

interface Props { selected: RuntimeStatusSummary; onClose: () => void; }
export const WorkflowDetailPanel: React.FC<Props> = ({selected, onClose}) => {
  const [detail, setDetail] = useState<RuntimeStatusDetail | null>(null);
  const [status, setStatus] = useState<'loading'|'ready'|'failed'>('loading');
  const episode = selected.episode_ref || selected.episode || selected.business_episode_id || selected.episode_id;
  useEffect(() => {
    let active = true; setDetail(null); setStatus('loading');
    if (!episode) { setStatus('failed'); return; }
    platformApi.runtimeStatus(episode).then(data => {
      if(!active)return;
      setDetail(data);
      setStatus(data?'ready':'failed');
    }).catch(() => {if(active)setStatus('failed')});
    return () => {active=false};
  },[episode]);
  const value = (data: string | number | boolean | null | undefined) => data == null || data === '' ? '未提供' : String(data);
  return <Drawer open title="工作流阶段详情" onClose={onClose} width={440} destroyOnClose className="storyos-workflow-inspector"><section aria-label="工作流阶段详情" className="space-y-4">
    <div className="flex gap-3 items-start justify-between">
      <div className="min-w-0"><h3 className="os-section-heading break-words">{selected.title || episode}</h3><p className="text-[11px] text-[var(--text-tertiary)] mt-1">只读阶段详情 · 文件模式不代表在线运行状态</p></div>
    </div>
    {status === 'loading' ? <p role="status" className="text-[12px] text-[var(--text-secondary)]">正在获取阶段详情…</p> : status === 'failed' ? <p role="alert" className="text-[12px] text-[var(--warning)]">详情接口不可用；只保留摘要，不推测运行状态。</p> :
      <dl className="grid grid-cols-1 gap-0">
        {[
          ['正式阶段',stageLabel(detail?.production_stage || selected.production_stage || 'NO_STATE')],
          ['执行状态',value(detail?.execution_status)],
          ['当前动作',value(detail?.current_action)],
          ['下一步',value(detail?.next_step)],
          ['阻塞原因',value(detail?.blocking_reason)],
          ['需要人工',value(detail?.needs_user)],
          ['可自动恢复',value(detail?.auto_recoverable)],
          ['心跳状态',value(detail?.heartbeat?.health)],
          ['通过帧',value(detail?.image_progress?.accepted_frames)],
          ['目标帧',value(detail?.image_progress?.expected_frames)]
        ].map(([k,v]) => <div key={k} className="grid grid-cols-[100px_minmax(0,1fr)] items-start gap-3 border-b border-[var(--border-subtle)] py-3"><dt className="text-[11px] text-[var(--text-tertiary)]">{k}</dt><dd className="break-words text-[13px] font-medium text-[var(--text-primary)]">{v}</dd></div>)}
      </dl>
    }
  </section></Drawer>;
};
