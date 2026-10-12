import React from 'react';
import { AlertTriangle, ArrowRight, CircleDot, FilePenLine, ShieldAlert } from 'lucide-react';
import type { Episode } from '../types';

interface Props { episode: Episode; onOpenWorkflow: () => void; }

const isLocalDraft = (episode: Episode) => /^ep-(home|proj)-/.test(episode.id);
export const StoryNextAction: React.FC<Props> = ({ episode, onOpenWorkflow }) => {
  const failed = (episode.frameReviews || []).filter(item => item.verdict === 'FAIL');
  const warned = (episode.frameReviews || []).filter(item => item.verdict === 'WARN');
  const blocked = (episode.preflightChecks || []).filter(item => item.status === 'blocking');
  const pending = (episode.preflightChecks || []).filter(item => item.status === 'pending');
  const draft = isLocalDraft(episode);

  let title = '继续查看生产阶段';
  let detail = '根据工作区快照查看已完成的工作。是否可以进入下一阶段，必须由 Runtime 的正式门禁决定。';
  let kind: 'draft' | 'blocking' | 'warning' | 'neutral' = 'neutral';
  if (draft) {
    title = '先完善本地故事草稿';
    detail = '这部故事尚未提交正式 Runtime。请先补齐剧情、角色与分镜，正式生产需要受控创建/执行接口。';
    kind = 'draft';
  } else if (blocked.length || failed.length) {
    title = '先处理已记录的审核阻塞';
    detail = blocked.length + ' 项预检阻塞、' + failed.length + ' 帧审核失败。先核对对应证据，禁止直接跳过门禁或将其标记为通过。';
    kind = 'blocking';
  } else if (warned.length || pending.length) {
    title = '检查待确认的审核记录';
    detail = warned.length + ' 帧审核警告、' + pending.length + ' 项待完成预检。工作区记录不等于最终审核通过。';
    kind = 'warning';
  } else if (!episode.storyboardBeats?.length) {
    title = '缺少已记录的分镜内容';
    detail = '当前工作区没有可见分镜证据。请核对故事资产与正式分镜合同。';
  } else if (!episode.frameReviews?.length) {
    title = '尚无可见的逐帧审核记录';
    detail = '可以查看当前分镜与批次记录，但不能把无审核记录视为已通过。';
  }
  // The CTA navigates to read-only workflow evidence; it never starts recovery.
  const actionLabel = kind === 'blocking' ? '查看阻塞阶段' : kind === 'warning' ? '查看待确认阶段' : kind === 'draft' ? '查看制作流程' : '查看阶段';
  const Icon = kind === 'blocking' ? ShieldAlert : kind === 'warning' ? AlertTriangle : kind === 'draft' ? FilePenLine : CircleDot;
  return <section aria-labelledby="story-next-action-title" className="flex flex-wrap items-start justify-between gap-3 border-l-2 border-[var(--border-strong)] bg-[var(--bg-surface)] px-4 py-2.5 text-[var(--text-primary)]">
    <div className="flex items-start gap-3 min-w-0 flex-1">
      <Icon size={18} className={'mt-0.5 shrink-0 ' + (kind === 'blocking' ? 'text-[var(--danger)]' : kind === 'warning' ? 'text-[var(--warning)]' : 'text-[var(--text-secondary)]')} />
      <div className="space-y-1 min-w-0">
        <h2 id="story-next-action-title" className="text-[14px] font-semibold">{title}</h2>
        <p className="text-[12px] leading-5 text-[var(--text-secondary)]">{detail}</p>

      </div>
    </div>
    <button type="button" onClick={onOpenWorkflow} title="仅查看流程，不执行重试或修改审核状态" aria-label={actionLabel} className="flex shrink-0 items-center gap-1.5 text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">{actionLabel} <ArrowRight size={14}/></button>
  </section>;
};
