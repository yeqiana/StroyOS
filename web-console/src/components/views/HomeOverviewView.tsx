import React, { useEffect, useMemo, useState } from 'react';
import { Button, Input, Pagination, Segmented, Table } from 'antd';
import { ArrowRight, CheckCircle2, ChevronRight, CircleAlert, Clapperboard, Clock3, Folder, Image as ImageIcon, Plus, RefreshCw, SlidersHorizontal } from 'lucide-react';
import type { Episode, NavigationTab, ProjectItem } from '../../types';
import { platformApi, type RuntimeStatusSummary, stageLabel } from '../../api/platformApi';
import { useLocalApprovedMedia, type ApprovedFrame } from '../../api/localApprovedMedia';

interface Props {
  episodes: Episode[];
  projects: ProjectItem[];
  onSelectEpisode: (episode: Episode) => void;
  onNewStory: () => void;
  onNavigate: (tab: NavigationTab) => void;
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

export const HomeOverviewView: React.FC<Props> = ({ episodes, projects, onSelectEpisode, onNewStory, onNavigate }) => {
  const { findEpisode } = useLocalApprovedMedia();
  // No generated placeholder image can pass this contract: the image is from the approved-only media catalog.
  const approvedFrames = (episode: Episode) => findEpisode(episode.title, episode.code)?.frames ?? [];
  const approvedCover = (episode: Episode) => approvedFrames(episode)[0]?.url ?? '';
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<'all' | 'unfinished' | 'approved'>('all');
  const [storyPage, setStoryPage] = useState(1);
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
  const otherApproved = approved.filter(episode => episode.id !== featured?.id).slice(0, 3);
  const featuredSequence = featured ? approvedFrames(featured) : [];
  const previewOffsets = featuredSequence.length >= 12 ? [4, 9, 14, 19] : [1, 2, 3, 4];
  const featuredPreviews = previewOffsets.map(index => featuredSequence[index]).filter((frame): frame is ApprovedFrame => Boolean(frame));
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
  const runtimeIsFixture = runtime.some(item => item.state_source === 'isolated-test');
  const runtimeIsLocalFile = runtime.some(item => item.state_source === 'local_workspace_episode_state_file');

  return <div id="storyos-home-overview" className="w-full min-w-0 space-y-4 pb-6 text-[var(--text-primary)]">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-3">
      <div>
        <h1 className="os-page-heading">工作台</h1>
        <p className="mt-1 text-[12px] text-[var(--text-secondary)]">从作品继续创作，查看已经完成的图片与下一段工作</p>
      </div>
      <Button type="primary" icon={<Plus size={16}/>} onClick={onNewStory}>新建故事</Button>
    </header>

    <section aria-label="项目概况" className="flex flex-wrap items-center gap-x-7 gap-y-2 border-b border-[var(--border-subtle)] pb-3 text-[12px]">
      {[
        { label: '作品', value: episodes.length },
        { label: '有批准图片', value: approved.length },
        { label: '未发布', value: unfinished.length },
        { label: '项目空间', value: projects.length }
      ].map(metric => <span key={metric.label} className="inline-flex items-baseline gap-2 text-[var(--text-secondary)]">
        <span>{metric.label}</span><strong className="text-[16px] font-semibold tabular-nums text-[var(--text-primary)]">{metric.value}</strong>
      </span>)}
      <span className="ml-auto text-[11px] text-[var(--text-tertiary)]">当前工作区记录 · 非实时生产状态</span>
    </section>

    <section aria-label="创作焦点" className="grid min-w-0 gap-px border-y border-[var(--border-subtle)] bg-[var(--border-subtle)] lg:grid-cols-[minmax(0,1.55fr)_minmax(290px,.85fr)]">
      <div className="min-w-0 bg-[var(--bg-app)] p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="os-section-heading">接着创作</h2>
          <span className="text-[11px] text-[var(--text-tertiary)]">{approved.length ? '优先展示有已批准图片的未发布作品' : '按工作区更新时间选择未发布作品'}</span>
        </div>
        {featured ? <div className="flex min-w-0 flex-col gap-4 sm:flex-row">
          <button type="button" onClick={() => onSelectEpisode(featured)}
            aria-label={`打开焦点作品 ${featured.title}`}
            className="group relative flex h-[204px] w-full shrink-0 items-center justify-center overflow-hidden rounded-[5px] border border-[var(--border-normal)] bg-[var(--bg-elevated)] sm:w-[160px]">
            {approvedCover(featured)
              ? <img src={approvedCover(featured)} alt={featured.title + '的已批准素材'} className="h-full w-full object-cover object-top transition-transform duration-150 group-hover:scale-[1.02]"/>
              : <span className="flex flex-col items-center gap-2 text-[11px] text-[var(--text-tertiary)]"><Clapperboard size={27}/>暂无已批准图片</span>}
            {approvedFrames(featured).length > 0 && <span className="absolute bottom-2 right-2 border border-[var(--border-normal)] bg-[var(--bg-workspace)] px-2 py-1 text-[11px] tabular-nums">{approvedFrames(featured).length} 张已批准</span>}
          </button>
          <div className="flex min-w-0 flex-1 flex-col justify-between gap-3 py-1">
            <div className="min-w-0">
              <p className="mb-2 text-[11px] text-[var(--text-tertiary)]">{featured.genre || '未分类'} · 更新 {readableDate(featured.updatedAt)}</p>
              <h3 className="line-clamp-2 text-[20px] font-semibold leading-7">
                <button type="button" onClick={() => onSelectEpisode(featured)} className="text-left hover:text-[var(--info)]">{featured.title}</button>
              </h3>
              <p className="mt-2 line-clamp-2 text-[12px] leading-5 text-[var(--text-secondary)]">{featured.logline || featured.synopsis || '打开这部作品继续查看分镜与已记录的制作证据。'}</p>
            </div>
            {featuredPreviews.length > 0 && <div aria-label="焦点作品已批准分镜预览" className="flex min-w-0 items-center gap-2 overflow-hidden py-1">
              <span className="shrink-0 text-[11px] text-[var(--text-tertiary)]">已批准分镜</span>
              {featuredPreviews.map(frame => <button key={frame.frame} type="button" onClick={() => onSelectEpisode(featured)} title={`查看作品中的 Frame ${String(frame.frame).padStart(2,'0')}`} aria-label={`打开作品查看 Frame ${String(frame.frame).padStart(2,'0')}`} className="relative h-[50px] w-10 shrink-0 overflow-hidden rounded-[4px] border border-[var(--border-normal)] bg-[var(--bg-elevated)] hover:border-[var(--info)]"><img src={frame.url} alt={`已批准 Frame ${frame.frame}`} className="h-full w-full object-cover object-top"/><span className="absolute bottom-0 right-0 bg-[var(--bg-workspace)] px-1 text-[9px] tabular-nums text-[var(--text-primary)]">{String(frame.frame).padStart(2,'0')}</span></button>)}
            </div>}
            <div className="space-y-2.5">
              <div className="flex flex-wrap items-center justify-between gap-3 text-[12px]"><span className="text-[var(--text-secondary)]">{STAGES[featured.currentStage] ?? featured.currentStage}</span><span className="tabular-nums">工作区 {featured.completedFrames} / {featured.totalFrames} 帧</span></div>
              <div className="h-1 overflow-hidden rounded-[2px] bg-[var(--border-normal)]" aria-label={`工作区帧进度 ${percentage(featured)}%`}><div className="h-full bg-[var(--info)]" style={{ width: `${percentage(featured)}%` }}/></div>
              <Button type="primary" icon={<ArrowRight size={15}/>} iconPlacement="end" onClick={() => onSelectEpisode(featured)}>继续制作</Button>
            </div>
          </div>
        </div> : <div className="flex min-h-[204px] items-center justify-center gap-3 text-[13px] text-[var(--text-secondary)]"><Folder size={20}/>工作区还没有故事，先创建一个新故事。</div>}
      </div>
      <aside aria-label="工作台关注事项与快捷入口" className="flex min-w-0 flex-col gap-3 bg-[var(--bg-app)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="os-section-heading">最近有图的作品</h2>
          <button type="button" onClick={() => onNavigate('episodes')} className="inline-flex items-center gap-1 text-[12px] text-[var(--info)] hover:text-[var(--text-primary)]">作品库 <ArrowRight size={13}/></button>
        </div>
        {otherApproved.length > 0 ? <div className="divide-y divide-[var(--border-subtle)]">
          {otherApproved.map(episode => <button key={episode.id} type="button" onClick={() => onSelectEpisode(episode)}
            aria-label={`打开近期素材 ${episode.title}`} className="group flex w-full min-w-0 items-center gap-3 py-2 text-left hover:bg-[var(--bg-hover)]">
            <span className="flex h-[54px] w-[46px] shrink-0 items-center justify-center overflow-hidden rounded-[4px] bg-[var(--bg-elevated)]">
              <img src={approvedCover(episode)} loading="lazy" alt="" className="h-full w-full object-cover object-top"/>
            </span>
            <span className="min-w-0 flex-1">
              <strong className="block truncate text-[13px] font-semibold group-hover:text-[var(--info)]">{episode.title}</strong>
              <span className="mt-1 block truncate text-[11px] text-[var(--text-tertiary)]">{STAGES[episode.currentStage] ?? episode.currentStage} · {approvedFrames(episode).length} 张已批准</span>
            </span>
            <ChevronRight size={15} className="shrink-0 text-[var(--text-tertiary)]"/>
          </button>)}
        </div> : <p className="py-3 text-[12px] leading-5 text-[var(--text-tertiary)]">{approved.length ? '当前仅有这一部作品具备可验证的批准素材。' : '工作区暂无可验证的已批准图片。'}</p>}
        <div className="mt-auto space-y-2 border-t border-[var(--border-subtle)] pt-3">
          <div className="flex items-center gap-2 text-[12px]">
            {attention.length ? <CircleAlert size={15} className="shrink-0 text-[var(--danger)]"/> : <CheckCircle2 size={15} className="shrink-0 text-[var(--text-tertiary)]"/>}
            <span className="text-[var(--text-secondary)]">{attention.length ? `${attention.length} 部作品在已载入记录中需要检查` : '已载入记录未发现明确阻塞或失败审核'}</span>
          </div>
          {attention.slice(0, 2).map(({ episode, blocked, failed }) => <button type="button" key={episode.id} onClick={() => onSelectEpisode(episode)} className="flex w-full items-center justify-between gap-2 text-left text-[12px] text-[var(--danger)]"><span className="truncate">{episode.title}</span><span className="shrink-0">{blocked} 阻塞 · {failed} 失败</span></button>)}
          <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1">
            <button type="button" onClick={() => onNavigate('production_monitor')} className="inline-flex items-center gap-1.5 py-1 text-[12px] text-[var(--text-secondary)] hover:text-[var(--info)]"><SlidersHorizontal size={14}/>生产监控</button>
            <button type="button" onClick={() => onNavigate('pipeline')} className="inline-flex items-center gap-1.5 py-1 text-[12px] text-[var(--text-secondary)] hover:text-[var(--info)]"><Clock3 size={14}/>工作流</button>
          </div>
        </div>
      </aside>
    </section>

    <section aria-label="工作台继续制作主列表" className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="os-section-heading">全部作品</h2><p className="mt-1 text-[11px] text-[var(--text-tertiary)]">按工作区更新时间排序 · 点击名称进入故事制作</p></div>
        <button type="button" onClick={() => onNavigate('episodes')} className="inline-flex items-center gap-1 text-[12px] text-[var(--info)] hover:text-[var(--text-primary)]">进入作品库 <ArrowRight size={14}/></button>
      </div>
      <div className="os-console-filterbar flex flex-wrap items-center gap-2 border-b border-[var(--border-subtle)] pb-2">
        <Segmented aria-label="首页作品范围" size="small" value={scope} onChange={value => {setScope(value as typeof scope);setStoryPage(1);}}
          options={[{label:'全部',value:'all'},{label:'未发布',value:'unfinished'},{label:'有批准图片',value:'approved'}]}/>
        <Input.Search aria-label="搜索作品" value={query} onChange={event => {setQuery(event.target.value);setStoryPage(1);}} placeholder="搜索作品名称 / 编号 / 类型" allowClear className="!w-[288px] max-w-full"/>
        <span className="ml-auto text-[11px] tabular-nums text-[var(--text-tertiary)]">筛选 {filtered.length} / {episodes.length} 部</span>
      </div>
      <Table<Episode> rowKey="id" size="small" className="storyos-home-episode-grid" dataSource={filtered} scroll={{x:800}}
        onRow={episode => ({onClick: () => onSelectEpisode(episode),className:'cursor-pointer'})}
        locale={{emptyText:'当前筛选条件下没有作品，清除条件后可查看全部记录。'}}
        columns={[
          {title:'作品',key:'title',render:(_,episode)=><div className="flex min-w-0 items-center gap-3"><span className="flex h-10 w-9 shrink-0 items-center justify-center overflow-hidden rounded-[4px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)]">{approvedCover(episode) ? <img loading="lazy" src={approvedCover(episode)} alt="" className="h-full w-full object-cover object-top"/> : <Clapperboard size={16} className="text-[var(--text-tertiary)]"/>}</span><div className="min-w-0"><button type="button" aria-label={`打开故事 ${episode.title}`} onClick={event=>{event.stopPropagation();onSelectEpisode(episode);}} className="block max-w-[36vw] truncate text-left text-[13px] font-semibold hover:text-[var(--info)]">{episode.title}</button><span className="block max-w-[36vw] truncate text-[11px] text-[var(--text-tertiary)]">{episode.code} · {episode.genre || '未分类'}</span></div></div>},
          {title:'制作阶段',key:'stage',width:155,render:(_,episode)=><span className="text-[12px] text-[var(--text-secondary)]">{STAGES[episode.currentStage] ?? episode.currentStage}</span>},
          {title:'工作区帧',key:'frames',width:150,render:(_,episode)=><span className="tabular-nums text-[12px]">{episode.completedFrames}<span className="text-[var(--text-tertiary)]"> / {episode.totalFrames}</span></span>},
          {title:'已批准图片',key:'approved',width:140,render:(_,episode)=><span className="inline-flex items-center gap-1.5 tabular-nums text-[12px] text-[var(--text-secondary)]"><ImageIcon size={13} className="text-[var(--text-tertiary)]"/>{approvedFrames(episode).length ? `${approvedFrames(episode).length} 张` : '—'}</span>},
          {title:'更新',key:'date',width:100,sorter:(a,b)=>timeValue(a.updatedAt)-timeValue(b.updatedAt),render:(_,episode)=><span className="tabular-nums text-[12px] text-[var(--text-tertiary)]">{readableDate(episode.updatedAt)}</span>},
          {title:'',key:'open',width:75,align:'right',render:(_,episode)=><button type="button" onClick={event=>{event.stopPropagation();onSelectEpisode(episode);}} className="inline-flex items-center gap-1 text-[12px] text-[var(--info)]">进入 <ArrowRight size={13}/></button>}
        ]}
        pagination={{current:Math.min(storyPage,Math.max(1,Math.ceil(filtered.length/storyPageSize))),pageSize:storyPageSize,total:filtered.length,
          showTotal:(count,range)=>`${range[0]}–${range[1]} / ${count} 部`,onChange:setStoryPage}}
      />
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
