import React, { useEffect, useMemo, useState } from 'react';
import { Button, Progress } from 'antd';
import { Activity, AlertTriangle, ArrowRight, Check, Circle, Image as ImageIcon, RefreshCw } from 'lucide-react';
import { platformApi, type RuntimeStatusDetail, type RuntimeStatusSummary, stageLabel } from '../../api/platformApi';
import { PRODUCTION_MILESTONES, projectProductionProgress } from '../../api/productionProgress';
import { useLocalApprovedMedia } from '../../api/localApprovedMedia';
import { useLocalCandidateMedia } from '../../api/localCandidateMedia';
import { matchCanonicalHistoricalEpisode } from '../../api/canonicalRuntimeCatalog';
import type { Episode } from '../../types';

interface Props {
  episodes: Episode[];
  onOpenEpisode: (episodeRef: string) => void;
}

interface ObservedEpisode {
  summary: RuntimeStatusSummary;
  detail: RuntimeStatusDetail | null;
  detailLoaded: boolean;
}

const timeNumber = (item: RuntimeStatusSummary) => {
  const time = Date.parse(item.updated_at || item.observed_at || '');
  return Number.isFinite(time) ? time : 0;
};
const stateOrder: Record<string, number> = {
  verified_generating: 0,
  blocked: 1,
  waiting_start: 2,
  historical_block: 3,
  recorded_activity: 4,
  unverified: 5,
  completed: 6,
};

function ProductionProgressCard({ entry, onOpenEpisode, thumbnailUrl, thumbnailIsCandidate, synopsis, synopsisSource }: {
  entry: ObservedEpisode;
  onOpenEpisode: Props['onOpenEpisode'];
  thumbnailUrl?: string;
  thumbnailIsCandidate?: boolean;
  synopsis: string | null;
  synopsisSource: string | null;
}) {
  const { summary, detail, detailLoaded } = entry;
  const ref = summary.episode_ref || summary.episode_id || '';
  const progress = projectProductionProgress(summary, detail);
  const hasStage = progress.completedSteps !== null;
  const hasDetail = detailLoaded && Boolean(detail);
  const reason = progress.blockedReason === 'STEP_BLOCKED' ? '当前节点被生产门禁阻断，请进入详情查看原始日志与恢复条件' : progress.blockedReason;

  return <article className="min-w-0 rounded-[6px] border border-[var(--border-normal)] bg-[var(--bg-surface)] px-4 py-3.5" aria-label={'生产进度 '+(summary.title || ref)}>
    <div className="flex flex-wrap items-start gap-3">
      <div className="relative flex h-[100px] w-[76px] shrink-0 items-center justify-center overflow-hidden rounded-[4px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)] sm:h-[112px] sm:w-[84px]">
        {thumbnailUrl
          ? <img src={thumbnailUrl} loading="lazy" alt={(summary.title || '作品') + (thumbnailIsCandidate ? '的未审核候选图片预览' : '的已批准图片缩略图')} className="h-full w-full object-cover object-top"/>
          : <div className="flex flex-col items-center gap-1 text-[var(--text-tertiary)]"><ImageIcon size={20} strokeWidth={1.4}/><span className="text-center text-[10px] leading-4">暂无已批准图片</span></div>}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="min-w-0 max-w-full truncate text-[14px] font-semibold text-[var(--text-primary)]" title={summary.title || ref}>{summary.title || ref || '未命名作品'}</h3>
          <span className={'shrink-0 rounded-[3px] border px-2 py-0.5 text-[11px] '+(
            progress.state === 'blocked' ? 'border-[var(--danger)] text-[var(--danger)]' :
            progress.state === 'verified_generating' ? 'border-[var(--info)] text-[var(--info)]' :
            'border-[var(--border-normal)] text-[var(--text-secondary)]'
          )}>{!hasDetail && !detailLoaded ? '执行详情未核验' : progress.stateLabel}</span>
        </div>
        <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
          {stageLabel(summary.production_stage || 'NO_STATE')} · {summary.state_source === 'mysql_episode_state_read_only' ? 'MySQL 权威阶段' : '本地只读来源'}
          {progress.action ? (progress.state === 'historical_block' || progress.state === 'waiting_start' ? ' · 历史节点 ' : ' · 最近节点 ') + progress.action : ''}
        </p>
        <p className="mt-2 line-clamp-2 text-[12px] leading-[1.65] text-[var(--text-secondary)]" title={synopsis || undefined}>{synopsis || '暂无可核验的剧情简介'}</p>
        <p className="mt-1 text-[10px] text-[var(--text-tertiary)]">{synopsisSource || '简介未收录'}{thumbnailUrl ? (thumbnailIsCandidate ? ' · 未审核生成候选图（非发布成品）' : ' · 封面为已批准素材') : ''}</p>
      </div>
      <Button size="small" className="!shrink-0" onClick={() => ref && onOpenEpisode(ref)} disabled={!ref}>监控详情 <ArrowRight size={13}/></Button>
    </div>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
      <span className="text-[11px] font-medium text-[var(--text-secondary)]">生产流程 · 阶段完成率</span>
      <span className="text-[12px] font-semibold tabular-nums text-[var(--text-primary)]">{hasStage ? progress.completedSteps+' / '+PRODUCTION_MILESTONES.length+' 阶段 · '+progress.stagePercent+'%' : '阶段进度待核验'}</span>
    </div>
    {hasStage ? <Progress percent={progress.stagePercent ?? 0} size="small" showInfo={false} strokeColor="var(--info)" trailColor="var(--border-normal)" className="!mb-0 !mt-1" aria-label="已完成阶段比例"/> :
      <div className="mt-2 h-1.5 rounded-full bg-[var(--border-subtle)]" aria-label="暂无可计算的阶段进度"/>}
    <ol className="mt-3 grid min-w-0 grid-cols-7 gap-1" aria-label="七阶段真实生产流程图">
      {PRODUCTION_MILESTONES.map((name, index) => {
        const passed = hasStage && index < (progress.completedSteps as number);
        const current = index === progress.activeIndex && !passed;
        const blocked = current && progress.state === 'blocked';
        return <li key={name} className="min-w-0 text-center">
          <div className="flex items-center">
            <span aria-hidden="true" className={'h-px min-w-0 flex-1 '+(index===0 ? 'bg-transparent' : hasStage && index <= (progress.completedSteps as number) ? 'bg-[var(--info)]' : 'bg-[var(--border-normal)]')}/>
            <span className={'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[10px] '+(
              passed ? 'border-[var(--info)] bg-[var(--info)] text-white' :
              blocked ? 'border-[var(--danger)] text-[var(--danger)]' :
              current ? 'border-[var(--info)] text-[var(--info)]' :
              'border-[var(--border-normal)] text-[var(--text-tertiary)]'
            )}>{passed ? <Check size={13}/> : blocked ? <AlertTriangle size={12}/> : current ? <Activity size={12}/> : <Circle size={9}/>}</span>
            <span aria-hidden="true" className={'h-px min-w-0 flex-1 '+(index===PRODUCTION_MILESTONES.length-1 ? 'bg-transparent' : hasStage && index < (progress.completedSteps as number) ? 'bg-[var(--info)]' : 'bg-[var(--border-normal)]')}/>
          </div>
          <span title={name} className={'mt-1 block break-words text-[10px] leading-[1.3] '+(
            passed ? 'text-[var(--text-primary)]' : current ? blocked ? 'font-semibold text-[var(--danger)]' : 'font-semibold text-[var(--info)]' : 'text-[var(--text-tertiary)]'
          )}>{name}</span>
          <span className="mt-0.5 block text-[9px] text-[var(--text-tertiary)]">{passed ? '完成' : current ? blocked ? '阻断' : '最近节点' : '待推进'}</span>
        </li>;
      })}
    </ol>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border-subtle)] pt-2 text-[11px] text-[var(--text-secondary)]">
      <span>{hasDetail ? progress.evidenceLabel : '节点详情未读取 · 不能推断在线状态'}</span>
      {progress.framePercent !== null && <span className="font-medium tabular-nums">已接受图片 {progress.acceptedFrames}/{progress.expectedFrames} · {progress.framePercent}%</span>}
      {progress.framePercent === null && <span>已接受图片：暂无可验证总量</span>}
    </div>
    {progress.state === 'blocked' && reason && <p role="status" className="mt-2 flex gap-1.5 text-[11px] text-[var(--danger)]"><AlertTriangle size={13} className="mt-0.5 shrink-0"/><span className="break-words">阻断：{reason}</span></p>}
  </article>;
}

export const LiveProductionBoard: React.FC<Props> = ({ episodes, onOpenEpisode }) => {
  const { findEpisode } = useLocalApprovedMedia();
  const { findByRuntimeRef } = useLocalCandidateMedia();
  const [entries, setEntries] = useState<ObservedEpisode[]>([]);
  const [status, setStatus] = useState<'loading'|'ready'|'partial'|'offline'>('loading');
  const [total, setTotal] = useState<number | null>(null);
  const [lastChecked, setLastChecked] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let active = true;
    let busy = false;
    const load = async () => {
      if (!active || busy) return;
      busy = true;
      try {
        const listing = await platformApi.runtimeStatuses(100, 0);
        if (!active) return;
        const sorted = [...(listing.items || [])].sort((a,b)=>timeNumber(b)-timeNumber(a));
        // Read at most 10 most-recent details; list rows without details remain explicitly unverified.
        const sampled = await Promise.all(sorted.slice(0,10).map(async summary => {
          const ref = summary.episode_ref || summary.episode_id;
          if (!ref) return { summary, detail: null, detailLoaded: false };
          try { return { summary, detail: await platformApi.runtimeStatus(ref), detailLoaded: true }; }
          catch { return { summary, detail: null, detailLoaded: false }; }
        }));
        if (!active) return;
        const byRef = new Map(sampled.map(item=>[item.summary.episode_ref || item.summary.episode_id, item]));
        setEntries(sorted.map(summary=>byRef.get(summary.episode_ref || summary.episode_id) || {summary, detail:null, detailLoaded:false}));
        setTotal(Number.isFinite(listing.total) ? listing.total : null);
        setStatus(listing.errors?.length || listing.has_more ? 'partial' : 'ready');
        setLastChecked(new Date().toLocaleTimeString('zh-CN',{hour12:false}));
      } catch {
        if (active) { setStatus('offline');setEntries([]);setTotal(null);setLastChecked(null); }
      } finally { busy = false; }
    };
    void load();
    const handle = window.setInterval(() => { if (document.visibilityState !== 'hidden') void load(); },15000);
    return () => { active = false; window.clearInterval(handle); };
  }, [refreshKey]);

  const ranked = useMemo(()=>[...entries].sort((a,b)=>{
    const diff = stateOrder[projectProductionProgress(a.summary,a.detail).state] - stateOrder[projectProductionProgress(b.summary,b.detail).state];
    return diff || timeNumber(b.summary)-timeNumber(a.summary);
  }),[entries]);
  const verifiedCount = ranked.filter(x=>projectProductionProgress(x.summary,x.detail).state==='verified_generating').length;
  const blockedCount = ranked.filter(x=>projectProductionProgress(x.summary,x.detail).state==='blocked').length;
  const visible = expanded ? ranked : ranked.slice(0,4);

  return <section aria-label="生产作品进度与实时流程" className="min-w-0 space-y-3">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h2 className="text-[16px] font-semibold text-[var(--text-primary)]">生产进度</h2>
        <p className="mt-1 text-[11px] text-[var(--text-secondary)]">作品、当前节点、流程和阻断集中显示 · 15 秒只读刷新</p>
      </div>
      <div className="flex items-center gap-3 text-[11px] text-[var(--text-tertiary)]">
        <span>{lastChecked ? '同步 '+lastChecked : '正在连接'}</span>
        <Button size="small" icon={<RefreshCw size={13}/>} onClick={()=>setRefreshKey(v=>v+1)} aria-label="刷新生产进度">刷新</Button>
      </div>
    </header>
    {status === 'offline' ? <p role="alert" className="border border-[var(--border-normal)] p-4 text-[12px] text-[var(--warning)]">监控服务未连接，无法核验作品当前进度；不会显示历史快照冒充在线。</p> :
      status === 'loading' ? <p role="status" className="border border-[var(--border-normal)] p-4 text-[12px] text-[var(--text-secondary)]">读取 MySQL 阶段与本地节点证据中…</p> :
      <>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-y border-[var(--border-subtle)] py-2 text-[12px] text-[var(--text-secondary)]">
          <span>作品 <strong className="tabular-nums text-[var(--text-primary)]">{entries.length}{total!==null && total!==entries.length?' / '+total:''}</strong></span>
          <span>已核实出图中 <strong className="tabular-nums text-[var(--text-primary)]">{verifiedCount}</strong></span>
          <span>已记录阻断 <strong className={blockedCount?'tabular-nums text-[var(--danger)]':'tabular-nums text-[var(--text-primary)]'}>{blockedCount}</strong></span>
          {status==='partial' && <span className="text-[var(--warning)]">部分来源不可用 · 仅显示已载入记录</span>}
          <span className="ml-auto text-[11px] text-[var(--text-tertiary)]">阶段百分比 ≠ 时间或生图完成率</span>
        </div>
        {visible.length ? <div className="grid min-w-0 gap-3 xl:grid-cols-2">
          {visible.map(entry => {
            const row = entry.summary;
            const historical = matchCanonicalHistoricalEpisode(row, episodes, entries.map(item => item.summary));
            const fromDraft = entry.detail?.story_excerpt?.trim();
            const fromHistory = historical?.synopsis?.trim() || historical?.logline?.trim();
            const synopsis = fromDraft || fromHistory || null;
            const synopsisSource = fromDraft ? '工作区故事草稿 · 未经发布审核' : fromHistory ? '已匹配的历史作品简介' : null;
            const approved = row.title && row.business_episode_id
              ? findEpisode(row.title, row.business_episode_id) : undefined;
            const candidate = findByRuntimeRef(row.episode_ref || row.episode_id);
            const thumbnailIsCandidate = Boolean(candidate?.preview.url);
            const thumbnailUrl = candidate?.preview.url ||
              (approved?.episode_ref === row.episode_ref ? approved.frames[0]?.url : undefined);
            return <ProductionProgressCard key={row.episode_ref || row.episode_id} entry={entry} onOpenEpisode={onOpenEpisode}
              thumbnailUrl={thumbnailUrl} thumbnailIsCandidate={thumbnailIsCandidate}
              synopsis={synopsis} synopsisSource={synopsisSource}/>;
          })}
        </div> : <p className="p-4 text-[12px] text-[var(--text-secondary)]">尚未找到可以展示的生产作品。</p>}
        {ranked.length > 4 && <button type="button" className="flex w-full items-center justify-center gap-1 border-b border-[var(--border-subtle)] py-2 text-[12px] text-[var(--info)] hover:bg-[var(--bg-hover)]" onClick={()=>setExpanded(value=>!value)}>
          {expanded?'收起作品':'查看全部 '+ranked.length+' 部作品'} <ArrowRight size={13}/>
        </button>}
        <p className="text-[11px] text-[var(--text-tertiary)]">完成阶段仅按权威状态计算；最近节点与阻断来自执行记录。只核查最近 10 部详情，其余详情点击进入监控；无可信 Writer/Provider 证据时不标记“正在生产”。</p>
      </>}
  </section>;
};
