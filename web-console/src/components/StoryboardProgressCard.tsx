import React, { useMemo, useState } from 'react';
import { Image as ImageIcon, PanelsTopLeft } from 'lucide-react';
import type { StoryboardBeat } from '../types';

interface StoryboardProgressCardProps {
  beats: StoryboardBeat[];
  totalFrames: number;
  completedFrames: number;
}
const STATUS_LABEL: Record<string, string> = { approved:'终审通过',in_review:'审核中',rendering:'制作中',queued:'待制作' };
export const StoryboardProgressCard: React.FC<StoryboardProgressCardProps> = ({beats,totalFrames,completedFrames}) => {
  const [selectedAct,setSelectedAct] = useState('ALL');
  const acts = useMemo(() => Array.from(new Set(beats.map(beat => beat.act).filter(Boolean))), [beats]);
  const filtered = selectedAct === 'ALL' ? beats : beats.filter(beat => beat.act === selectedAct);
  const progress = totalFrames > 0 ? Math.min(100,Math.round(completedFrames / totalFrames * 100)) : 0;
  return <section id="storyboard-progress-card" className="space-y-3 border-y border-[var(--border-subtle)] py-4 text-[var(--text-primary)]">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="flex items-center gap-2 text-[14px] font-semibold"><PanelsTopLeft size={16} strokeWidth={1.75}/> 分镜节拍</h3><p className="mt-1 text-[12px] text-[var(--text-tertiary)]">仅依据当前作品的分镜条目与帧进度，不推断正式门禁。</p></div>
      <div className="flex items-center gap-3 text-[12px] tabular-nums"><span>{completedFrames}/{totalFrames} 帧</span><div className="h-1.5 w-24 overflow-hidden rounded bg-[var(--border-normal)]"><div className="h-full bg-[var(--info)]" style={{width:progress+'%'}} /></div><span>{progress}%</span></div>
    </header>
    <div className="flex flex-wrap items-center gap-1.5">
      <button type="button" onClick={()=>setSelectedAct('ALL')} aria-pressed={selectedAct==='ALL'} className={'rounded-[5px] border px-3 py-1.5 text-[12px] '+(selectedAct==='ALL'?'border-[var(--info)] bg-[var(--bg-selected)]':'border-[var(--border-normal)] hover:bg-[var(--bg-hover)]')}>全部 · {beats.length}</button>
      {acts.map(act=><button key={act} type="button" onClick={()=>setSelectedAct(act)} aria-pressed={selectedAct===act} className={'rounded-[5px] border px-3 py-1.5 text-[12px] '+(selectedAct===act?'border-[var(--info)] bg-[var(--bg-selected)]':'border-[var(--border-normal)] hover:bg-[var(--bg-hover)]')}>{act} · {beats.filter(b=>b.act===act).length}</button>)}
    </div>
    <div className="divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)]">
      {!filtered.length && <p className="py-8 text-center text-[12px] text-[var(--text-tertiary)]">尚无对应分镜证据</p>}
      {filtered.map(beat=><div key={beat.id} className="flex min-w-0 flex-wrap items-center gap-3 py-3 sm:flex-nowrap">
        <div className="flex h-12 w-16 shrink-0 items-center justify-center overflow-hidden rounded-[4px] bg-[var(--bg-elevated)]">{beat.thumbnailUrl?<img loading="lazy" src={beat.thumbnailUrl} alt={beat.sceneName} className="h-full w-full object-cover"/>:<ImageIcon size={17} strokeWidth={1.75} className="text-[var(--text-tertiary)]"/>}</div>
        <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2 text-[13px]"><span className="font-mono text-[11px] text-[var(--text-tertiary)]">#{String(beat.beatIndex).padStart(2,'0')}</span><strong className="truncate font-semibold">{beat.sceneName}</strong><span className="text-[11px] text-[var(--text-tertiary)]">{beat.shotType}</span></div><p className="mt-1 truncate text-[12px] text-[var(--text-secondary)]">{beat.narration || '暂无分镜旁白'}</p></div>
        <span className="shrink-0 text-[12px] text-[var(--text-secondary)]">{STATUS_LABEL[beat.status] || beat.status || '状态未提供'}</span>
      </div>)}
    </div>
  </section>;
};
