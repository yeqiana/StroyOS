import React, { useEffect, useMemo, useState } from 'react';
import { Button, Input, Pagination, Segmented, Table } from 'antd';
import CSSMotion from '@rc-component/motion';
import { ArrowRight, CheckCircle2, ChevronRight, CircleAlert, Clapperboard, Clock3, Image as ImageIcon, Plus, RefreshCw, SlidersHorizontal } from 'lucide-react';
import type { Episode, NavigationTab, ProjectItem } from '../../types';
import { platformApi, type RuntimeStatusSummary, stageLabel } from '../../api/platformApi';
import { reconcileRuntimeCatalog } from '../../api/runtimeCatalogReconciliation';
import { useLocalApprovedMedia } from '../../api/localApprovedMedia';
import { CanonicalRuntimeDirectory } from '../catalog/CanonicalRuntimeDirectory';

interface Props {
  episodes: Episode[];
  projects: ProjectItem[];
  onSelectEpisode: (episode: Episode) => void;
  onNewStory: () => void;
  onNavigate: (tab: NavigationTab) => void;
  onOpenRuntimeEpisode: (episodeRef:string)=>void;
}

const STAGES: Record<string, string> = {
  IDEA_LOCK: '创意阶段',
  STORYBOARD_LOCK: '分镜阶段',
  VISUAL_CALIBRATE: '视觉校准',
  PROD_APPROVED: '生产审核',
  READY_TO_PUBLISH: '准备发布',
  PUBLISHED: '已发布',
  POST_MORTEM: '数据复盘'
};
const isPublished = (episode: Episode) => ['PUBLISHED', 'POST_MORTEM'].includes(episode.currentStage);
const percentage = (episode: Episode) => episode.totalFrames > 0
  ? Math.min(100, Math.max(0, Math.round(episode.completedFrames / episode.totalFrames * 100))) : 0;
const timeValue = (raw?: string) => { const value = Date.parse(raw || ''); return Number.isFinite(value) ? value : 0; };
const readableDate = (raw?: string) => {
  const value = timeValue(raw);
  return value ? new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) : '未知';
};

export const HomeOverviewView: React.FC<Props> = ({ episodes, projects, onSelectEpisode, onNewStory, onNavigate, onOpenRuntimeEpisode }) => {
  const { findEpisode } = useLocalApprovedMedia();
  // No generated placeholder image can pass this contract: the image is from the approved-only media catalog.
  const approvedFrames = (episode: Episode) => findEpisode(episode.title, episode.code)?.frames ?? [];
  const approvedCover = (episode: Episode) => approvedFrames(episode)[0]?.url ?? '';
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<'all' | 'unfinished' | 'approved'>('all');
  const [storyPage, setStoryPage] = useState(1);
  const [viewMode, setViewMode] = useState<'list'|'gallery'>('list');
  const [hasChangedViewMode, setHasChangedViewMode] = useState(false);
  const [runtimePage, setRuntimePage] = useState(1);
  const storyPageSize = 10;
  const runtimePageSize = 10;

  const [runtime, setRuntime] = useState<RuntimeStatusSummary[]>([]);
  const [runtimeStatus, setRuntimeStatus] = useState<'loading' | 'available' | 'partial' | 'offline'>('loading');
  const [runtimeTotal, setRuntimeTotal] = useState<number | null>(null);
  const [runtimeRefresh, setRuntimeRefresh] = useState(0);
  const [fetchedAt, setFetchedAt] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setRuntimeStatus('loading');
    platformApi.runtimeStatuses(20, 0).then(data => {
      if (!active) return;
      setRuntime(data.items ?? []);
      setRuntimeTotal(Number.isFinite(data.total) ? data.total : null);
      setRuntimeStatus(data.errors?.length ? 'partial' : 'available');
      setFetchedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    }).catch(() => {
      if (!active) return;
      setRuntime([]); setRuntimeTotal(null); setRuntimeStatus('offline'); setFetchedAt(null);
    });
    return () => { active = false; };
  }, [runtimeRefresh]);

  const sorted = useMemo(() => [...episodes].sort((a, b) => timeValue(b.updatedAt) - timeValue(a.updatedAt)), [episodes]);
  const approved = sorted.filter(episode => approvedFrames(episode).length > 0);
  const unfinished = sorted.filter(episode => !isPublished(episode));
  const featured = approved.find(episode => !isPublished(episode)) ?? unfinished[0] ?? sorted[0];
  const recentApproved=approved.slice(0,4);
  const attention = useMemo(() => episodes.flatMap(episode => {
    const blocked = episode.preflightChecks?.filter(check => check.status === 'blocking') ?? [];
    const failed = episode.frameReviews?.filter(review => review.verdict === 'FAIL') ?? [];
    return blocked.length || failed.length ? [{ episode, blocked: blocked.length, failed: failed.length }] : [];
  }), [episodes]);

  const search = query.trim().toLocaleLowerCase();
  const filtered = sorted.filter(episode => {
    if (scope === 'unfinished' && isPublished(episode)) return false;
    if (scope === 'approved' && !approvedFrames(episode).length) return false;
    return !search || [episode.title, episode.code, episode.genre].some(value => String(value || '').toLocaleLowerCase().includes(search));
  });
  const safeStoryPage=Math.min(storyPage,Math.max(1,Math.ceil(filtered.length/storyPageSize)));
  const galleryPageItems=filtered.slice((safeStoryPage-1)*storyPageSize,safeStoryPage*storyPageSize);
  const reconciliation = reconcileRuntimeCatalog(episodes,runtime,runtimeTotal,runtimeStatus==='available');
  const runtimeIsFixture = runtime.some(item => item.state_source === 'isolated-test');
  const runtimeIsLocalFile = runtime.some(item => item.state_source === 'local_workspace_episode_state_file');

  return <div id="storyos-home-overview" className="w-full min-w-0 space-y-4 pb-6 text-[var(--text-primary)]">

    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-3">
      <div><h1 className="os-page-heading">工作台</h1><p className="mt-1 text-[12px] text-[var(--text-secondary)]">从真实作品继续创作 · 分镜、批准素材与生产阶段分开记录</p></div>
      <span className="text-[11px] text-[var(--text-tertiary)]">本机工作区只读证据 · 非在线执行状态</span>
    </header>

    <section aria-label="创作快捷入口" className="space-y-3">
      <div><h2 className="text-[22px] font-semibold leading-8 tracking-tight">今天想创作什么？</h2><p className="mt-1 text-[12px] text-[var(--text-secondary)]">从已有作品接着做，或去素材库查看批准图片；正式生图仍使用受控流程。</p></div>
      <div className="grid min-w-0 gap-px border-y border-[var(--border-subtle)] bg-[var(--border-subtle)] md:grid-cols-3" role="group" aria-label="三项核心创作操作">
        <div className="os-home-entry flex min-w-0 items-center gap-3 bg-[var(--bg-surface)] px-3 py-3">
          <span className="os-home-entry-icon flex h-9 w-9 shrink-0 items-center justify-center rounded-[4px] bg-[var(--bg-elevated)] text-[var(--info)]"><Plus size={18}/></span>
          <div className="min-w-0 flex-1"><p className="truncate text-[12px] font-medium">从新的故事开始</p><p className="mt-1 truncate text-[11px] text-[var(--text-tertiary)]">创建故事与制作计划</p></div>
          <Button type="primary" size="small" onClick={onNewStory}>新建故事</Button>
        </div>
        <div className="os-home-entry flex min-w-0 items-center gap-3 bg-[var(--bg-surface)] px-3 py-3">
          <span className="os-home-entry-icon flex h-9 w-9 shrink-0 items-center justify-center rounded-[4px] bg-[var(--bg-elevated)] text-[var(--text-secondary)]"><Clapperboard size={18}/></span>
          <div className="min-w-0 flex-1"><p className="truncate text-[12px] font-medium">接着制作</p><p className="mt-1 truncate text-[11px] text-[var(--text-tertiary)]">{featured?.title||'暂无作品'}</p></div>
          <Button size="small" disabled={!featured} onClick={()=>featured&&onSelectEpisode(featured)}>继续制作</Button>
        </div>
        <div className="os-home-entry flex min-w-0 items-center gap-3 bg-[var(--bg-surface)] px-3 py-3">
          <span className="os-home-entry-icon flex h-9 w-9 shrink-0 items-center justify-center rounded-[4px] bg-[var(--bg-elevated)] text-[var(--text-secondary)]"><ImageIcon size={18}/></span>
          <div className="min-w-0 flex-1"><p className="truncate text-[12px] font-medium">作品素材库</p><p className="mt-1 truncate text-[11px] text-[var(--text-tertiary)]">{approved.length} 部有已批准图片</p></div>
          <Button size="small" onClick={()=>onNavigate('episodes')}>查看素材 <ArrowRight size={13}/></Button>
        </div>
      </div>
    </section>

    <CanonicalRuntimeDirectory episodes={episodes} condensed onSelectHistorical={onSelectEpisode} onOpenMonitor={onOpenRuntimeEpisode}/>



    <section aria-label="最近创作画廊" className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="os-section-heading">最近创作</h2><p className="mt-1 text-[11px] text-[var(--text-tertiary)]">展示已有批准图片的作品 · 不模拟生成结果</p></div><button type="button" onClick={()=>onNavigate('episodes')} className="inline-flex items-center gap-1 text-[12px] text-[var(--info)]">查看全部作品 <ArrowRight size={14}/></button></div>
      {recentApproved.length>0?<div className={'grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3'+(recentApproved.length>=4?' xl:grid-cols-4':'')}>
        {recentApproved.map((episode,index)=><button type="button" key={episode.id} onClick={()=>onSelectEpisode(episode)} aria-label={'打开最近创作 '+episode.title}
          className="os-home-cover-card group min-w-0 overflow-hidden rounded-[5px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-left hover:border-[var(--info)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--info)]">
          <div className="relative h-[186px] overflow-hidden bg-[var(--bg-elevated)] sm:h-[224px]">
            <img src={approvedCover(episode)} loading={index===0?'eager':'lazy'} alt={episode.title+'的已批准真实图片'} className="os-home-cover-image h-full w-full object-cover object-top"/>
            <span className="absolute right-2 top-2 border border-[var(--border-normal)] bg-[var(--bg-workspace)] px-2 py-1 text-[11px] tabular-nums text-[var(--text-primary)]">{approvedFrames(episode).length} 张已批准</span>
          </div>
          <div className="space-y-2 px-3 py-2.5">
            <div className="flex min-w-0 items-center justify-between gap-2"><strong className="truncate text-[13px] font-semibold">{episode.title}</strong><ArrowRight size={14} className="shrink-0 text-[var(--text-tertiary)] group-hover:text-[var(--info)]"/></div>
            <div className="flex items-center justify-between gap-2 text-[11px] text-[var(--text-secondary)]"><span className="truncate">{STAGES[episode.currentStage]??episode.currentStage}</span><span className="shrink-0 tabular-nums">更新 {readableDate(episode.updatedAt)}</span></div>
            <div className="flex items-center justify-between gap-2 border-t border-[var(--border-subtle)] pt-2 text-[11px] text-[var(--text-tertiary)]"><span>工作区 {episode.completedFrames}/{episode.totalFrames} 帧</span><span className={episode.id===featured?.id?'text-[var(--info)]':'text-[var(--text-secondary)]'}>{episode.id===featured?.id?'推荐继续':'查看制作'}</span></div>
          </div>
        </button>)}
      </div>:<div className="flex flex-wrap items-center gap-3 border-y border-[var(--border-subtle)] py-4 text-[12px] text-[var(--text-secondary)]"><ImageIcon size={19}/>本机暂无可验证的已批准图片。{featured&&<button type="button" onClick={()=>onSelectEpisode(featured)} className="text-[var(--info)]">继续最近作品 <ArrowRight size={13} className="inline"/></button>}</div>}
      {recentApproved.length>0&&<p className="text-[11px] text-[var(--text-tertiary)]">已批准图片与工作区帧进度来自不同证据，图片存在不代表本次生成完成。</p>}
    </section>

    <section aria-label="项目概况" className="flex flex-wrap items-center gap-x-7 gap-y-2 border-y border-[var(--border-subtle)] py-2 text-[12px]">
      {[{label:'作品记录',value:episodes.length},{label:'有批准图片',value:approved.length},{label:'未发布',value:unfinished.length},{label:'项目空间',value:projects.length}].map(metric=><span key={metric.label} className="inline-flex items-baseline gap-2 text-[var(--text-secondary)]"><span>{metric.label}</span><strong className="text-[15px] font-semibold tabular-nums text-[var(--text-primary)]">{metric.value}</strong></span>)}
      <span className="ml-auto text-[11px] text-[var(--text-tertiary)]">以下数字为历史工作区快照，不等于正式 Runtime 目录总量</span>
    </section>

    <details aria-label="作品来源一致性对账" className="border-b border-[var(--border-subtle)] pb-2 text-[12px] text-[var(--text-secondary)]">
      <summary className="flex cursor-pointer flex-wrap items-center gap-2 py-1 marker:text-[var(--text-tertiary)]">
        <span className="font-medium text-[var(--text-primary)]">作品来源对账</span>
        <span>双重身份一致 {reconciliation.confirmed.length} / 已读取真实作品 {reconciliation.observed}</span>
        <span className="text-[var(--text-tertiary)]">{reconciliation.complete?'本次来源完整':'本次来源未完整核验'} · 点击查看差异</span>
      </summary>
      <div className="space-y-2 pl-4 pt-2">
        <p>只用作品编号与标题同时完全相同的唯一记录确认关联；本地草稿不算正式作品。不会凭相似名称补齐身份，也不更改 Runtime 状态。</p>
        <p>监控侧未匹配目录：{reconciliation.unmatched.length} · 快照侧未匹配目录：{reconciliation.snapshotOnly.length}。这些是两种目录来源的差异，不表示作品丢失或没有生产。</p>
        {reconciliation.unmatched.length>0&&<p className="break-words">监控侧待核对：{reconciliation.unmatched.map(ep=>ep.title+'（'+ep.business_episode_id+'）').join('、')}</p>}
        <Button size="small" onClick={()=>onNavigate('production_monitor')}>打开真实生产监控核对</Button>
      </div>
    </details>

    <section aria-label="工作台关注事项与快捷入口" className="flex min-w-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-3 text-[12px]">
      <div className="flex items-center gap-2 text-[var(--text-secondary)]">{attention.length?<CircleAlert size={15} className="shrink-0 text-[var(--danger)]"/>:<CheckCircle2 size={15} className="shrink-0 text-[var(--text-tertiary)]"/>}
        {attention.length?<span>已载入记录中 {attention.length} 部作品存在阻塞或失败审核 · <button type="button" onClick={()=>onSelectEpisode(attention[0].episode)} className="text-[var(--info)]">查看首项</button></span>:<span>已载入记录未发现明确的阻塞或失败审核</span>}
      </div>
      <div className="flex items-center gap-4"><button type="button" onClick={()=>onNavigate('production_monitor')} className="inline-flex items-center gap-1 text-[var(--text-secondary)] hover:text-[var(--info)]"><SlidersHorizontal size={14}/>生产监控</button><button type="button" onClick={()=>onNavigate('pipeline')} className="inline-flex items-center gap-1 text-[var(--text-secondary)] hover:text-[var(--info)]"><Clock3 size={14}/>工作流</button></div>
    </section>

    <section aria-label="工作台继续制作主列表" className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="os-section-heading">作品管理</h2><p className="mt-1 text-[11px] text-[var(--text-tertiary)]">检索、筛选、进入已有制作流程</p></div><span className="text-[11px] text-[var(--text-tertiary)]">匹配 {filtered.length} / {episodes.length} 部</span></div>
      <div className="os-console-filterbar flex min-w-0 flex-wrap items-center gap-2 border-b border-[var(--border-subtle)] pb-2">
        <Segmented aria-label="首页作品范围" size="small" value={scope} onChange={value=>{setScope(value as typeof scope);setStoryPage(1);}} options={[{label:'全部',value:'all'},{label:'未发布',value:'unfinished'},{label:'有批准图片',value:'approved'}]}/>
        <Input.Search aria-label="搜索作品" value={query} onChange={event=>{setQuery(event.target.value);setStoryPage(1);}} placeholder="搜索名称 / 编号 / 类型" allowClear className="!w-[260px] max-w-full"/>
        <Segmented aria-label="作品管理显示方式" size="small" className="ml-auto" value={viewMode} onChange={value=>{setHasChangedViewMode(true);setViewMode(value as 'list'|'gallery');setStoryPage(1);}} options={[{label:'列表',value:'list'},{label:'画廊',value:'gallery'}]}/>
      </div>
      {viewMode==='list'?<CSSMotion key="list" visible motionAppear={hasChangedViewMode} motionName="os-home-view" motionDeadline={220}>{({className,style},ref)=><div ref={ref} className={`os-home-mode-content ${className||''}`} style={style}><Table<Episode> rowKey="id" size="small" className="storyos-home-episode-grid" dataSource={filtered} scroll={{x:800}}
        onRow={episode=>({onClick:()=>onSelectEpisode(episode),className:'os-home-list-row cursor-pointer'})}
        locale={{emptyText:'没有符合条件的作品，可清除搜索后继续查看。'}}
        columns={[
          {title:'作品',key:'title',render:(_,episode)=><div className="flex min-w-0 items-center gap-3"><span className="flex h-10 w-9 shrink-0 items-center justify-center overflow-hidden rounded-[4px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)]">{approvedCover(episode)?<img loading="lazy" src={approvedCover(episode)} alt="" className="h-full w-full object-cover object-top"/>:<Clapperboard size={16} className="text-[var(--text-tertiary)]"/>}</span><div className="min-w-0"><button type="button" aria-label={'打开故事 '+episode.title} onClick={event=>{event.stopPropagation();onSelectEpisode(episode);}} className="block max-w-[36vw] truncate text-left text-[13px] font-semibold hover:text-[var(--info)]">{episode.title}</button><span className="block max-w-[36vw] truncate text-[11px] text-[var(--text-tertiary)]">{episode.code} · {episode.genre||'未分类'}</span></div></div>},
          {title:'制作阶段',key:'stage',width:155,render:(_,episode)=><span className="text-[12px] text-[var(--text-secondary)]">{STAGES[episode.currentStage]??episode.currentStage}</span>},
          {title:'工作区帧',key:'frames',width:150,render:(_,episode)=><div className="flex items-center gap-2 tabular-nums text-[12px]"><span>{episode.completedFrames}/{episode.totalFrames}</span><div className="h-1 w-12 overflow-hidden rounded-[2px] bg-[var(--border-normal)]"><div className="h-full bg-[var(--info)]" style={{width:percentage(episode)+'%'}}/></div></div>},
          {title:'已批准图片',key:'approved',width:135,render:(_,episode)=><span className="inline-flex items-center gap-1 text-[12px] tabular-nums text-[var(--text-secondary)]"><ImageIcon size={13}/>{approvedFrames(episode).length?approvedFrames(episode).length+' 张':'—'}</span>},
          {title:'更新',key:'date',width:95,sorter:(a,b)=>timeValue(a.updatedAt)-timeValue(b.updatedAt),render:(_,episode)=><span className="tabular-nums text-[12px] text-[var(--text-tertiary)]">{readableDate(episode.updatedAt)}</span>},
          {title:'',key:'action',width:75,align:'right',render:(_,episode)=><button type="button" onClick={event=>{event.stopPropagation();onSelectEpisode(episode);}} className="inline-flex items-center gap-1 text-[12px] text-[var(--info)]">进入 <ArrowRight size={13}/></button>}
        ]}
        pagination={{current:safeStoryPage,pageSize:storyPageSize,total:filtered.length,showTotal:(count,range)=>range[0]+'–'+range[1]+' / '+count+' 部',onChange:setStoryPage}}
      /></div>}</CSSMotion>:<CSSMotion key="gallery" visible motionAppear={hasChangedViewMode} motionName="os-home-view" motionDeadline={220}>{({className,style},ref)=><div ref={ref} className={`os-home-mode-content ${className||''}`} style={style}><div aria-label="工作台作品管理画廊" className="min-w-0 space-y-4">
        {galleryPageItems.some(ep=>Boolean(approvedCover(ep)))&&<section aria-label="作品管理有图画廊" className="space-y-2">
          <div className="flex items-center justify-between gap-2"><h3 className="os-section-heading">有批准图片的作品</h3><span className="text-[11px] text-[var(--text-tertiary)]">仅展示已验证素材</span></div>
          <div className={'grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 '+(galleryPageItems.filter(ep=>Boolean(approvedCover(ep))).length>=4?'lg:grid-cols-3 xl:grid-cols-4':'md:grid-cols-3')}>
            {galleryPageItems.filter(ep=>Boolean(approvedCover(ep))).map(ep=><button key={ep.id} type="button" onClick={()=>onSelectEpisode(ep)} aria-label={'管理作品 '+ep.title} className="os-home-cover-card group min-w-0 overflow-hidden rounded-[5px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-left hover:border-[var(--info)]">
              <div className="h-[180px] overflow-hidden bg-[var(--bg-elevated)]"><img src={approvedCover(ep)} loading="lazy" alt={ep.title+'的真实批准图片'} className="h-full w-full object-cover object-top"/></div>
              <div className="space-y-1.5 px-3 py-2"><strong className="block truncate text-[13px] font-semibold">{ep.title}</strong><div className="flex items-center justify-between gap-2 text-[11px] text-[var(--text-secondary)]"><span className="truncate">{STAGES[ep.currentStage]??ep.currentStage}</span><span className="shrink-0 tabular-nums">{approvedFrames(ep).length} 张已批准</span></div><p className="text-[11px] tabular-nums text-[var(--text-tertiary)]">工作区 {ep.completedFrames}/{ep.totalFrames} 帧</p></div>
            </button>)}
          </div>
        </section>}
        {galleryPageItems.some(ep=>!approvedCover(ep))&&<section aria-label="作品管理无图紧凑列表" className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="os-section-heading">其他作品</h3><span className="text-[11px] text-[var(--text-tertiary)]">尚无可验证的批准图片 · 仍可进入故事制作</span></div>
          <div className="divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)]">
            {galleryPageItems.filter(ep=>!approvedCover(ep)).map(ep=><button key={ep.id} type="button" onClick={()=>onSelectEpisode(ep)} aria-label={'管理作品 '+ep.title} className="os-home-compact-row grid w-full min-w-0 grid-cols-[minmax(0,1fr)_110px_85px] items-center gap-3 px-3 py-2 text-left text-[12px] hover:bg-[var(--bg-hover)] sm:grid-cols-[minmax(0,1fr)_165px_110px]">
              <span className="min-w-0"><strong className="block truncate text-[13px] font-semibold">{ep.title}</strong><span className="block truncate text-[11px] text-[var(--text-tertiary)]">{ep.code} · {ep.genre||'未分类'}</span></span><span className="truncate text-[var(--text-secondary)]">{STAGES[ep.currentStage]??ep.currentStage}</span><span className="text-right tabular-nums text-[var(--text-secondary)]">{ep.completedFrames}/{ep.totalFrames} 帧</span>
            </button>)}
          </div>
        </section>}
        {galleryPageItems.length===0&&<p className="border-y border-[var(--border-subtle)] py-7 text-center text-[12px] text-[var(--text-tertiary)]">当前筛选条件下没有匹配作品</p>}
        {filtered.length>storyPageSize&&<Pagination size="small" current={safeStoryPage} pageSize={storyPageSize} total={filtered.length} showTotal={(count,range)=>range[0]+'–'+range[1]+' / '+count+' 部'} onChange={setStoryPage}/>}
      </div></div>}</CSSMotion>}
    </section>

    <section aria-label="平台生产阶段摘要" className="min-w-0 border-t border-[var(--border-subtle)] pt-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="os-section-heading">阶段记录与来源</h2><p className="mt-1 text-[11px] text-[var(--text-tertiary)]">按需核对，只读证据不等同于在线 Worker、队列或心跳</p></div>
        <div className="flex items-center gap-3">
          {runtimeStatus !== 'loading' && runtimeStatus !== 'offline' && <span className="text-[11px] text-[var(--text-tertiary)]">{runtimeIsLocalFile ? '本机文件 · 只读' : 'Platform API · 只读'} · {runtime.length}{runtimeTotal !== null ? ` / ${runtimeTotal}` : ''} 条</span>}
          <Button size="small" icon={<RefreshCw size={13}/>} disabled={runtimeStatus === 'loading'} onClick={() => setRuntimeRefresh(value=>value+1)}>刷新</Button>
        </div>
      </div>
      {runtimeStatus === 'loading' ? <p role="status" className="mt-2 text-[12px] text-[var(--text-secondary)]">正在读取阶段记录…</p>
        : runtimeStatus === 'offline' ? <p role="alert" className="mt-2 text-[12px] text-[var(--warning)]">Platform API 未连接，当前无法验证平台阶段记录。</p>
        : <>
          {runtimeStatus === 'partial' && <p role="alert" className="mt-2 text-[12px] text-[var(--warning)]">接口报告部分错误，记录可能不完整。</p>}
          {runtimeIsFixture && <p role="status" className="mt-2 text-[12px] text-[var(--warning)]">当前为隔离测试数据，不能视为正式生产证据。</p>}
          {runtimeIsLocalFile && <p role="status" className="mt-2 text-[11px] text-[var(--text-tertiary)]">本机 episodes 下的 episode-state.json 磁盘快照 · 不代表在线 Runtime 或 MySQL 权威状态。</p>}
          <details className="group mt-2 border-y border-[var(--border-subtle)]">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 py-3 text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
              <span>展开完整阶段记录 <span className="ml-2 tabular-nums text-[11px] text-[var(--text-tertiary)]">已读取 {runtime.length} 条 · {fetchedAt || '未知时间'}</span></span>
              <span className="inline-flex items-center gap-1 text-[var(--info)]">展开 <ChevronRight size={14} className="group-open:rotate-90"/></span>
            </summary>
            <div className="divide-y divide-[var(--border-subtle)] border-t border-[var(--border-subtle)]">
              {runtime.slice((runtimePage-1)*runtimePageSize,runtimePage*runtimePageSize).map((item,index)=><div key={item.episode_id+':'+index} className="os-data-row flex min-h-10 items-center justify-between gap-4 px-3 py-2 text-[12px]"><span title={item.title||item.episode_ref||item.episode_id} className="truncate">{item.title||item.episode_ref||item.episode_id||'未命名作品'}</span><span className="shrink-0 text-[var(--text-secondary)]">{stageLabel(item.production_stage||'NO_STATE')}</span></div>)}
              {runtime.length===0&&<p className="px-3 py-4 text-[12px] text-[var(--text-tertiary)]">接口已返回，但无可展示的阶段记录。</p>}
            </div>
            {runtime.length>runtimePageSize&&<Pagination size="small" current={runtimePage} pageSize={runtimePageSize} total={runtime.length} onChange={setRuntimePage} showTotal={count=>`当前已载入 ${count} 条`}/>}
          </details>
          <button type="button" onClick={() => onNavigate('pipeline')} className="mt-3 inline-flex items-center gap-1 text-[12px] text-[var(--text-secondary)] hover:text-[var(--info)]">在工作流中查看 <ArrowRight size={13}/></button>
        </>}
    </section>
  </div>;
};
