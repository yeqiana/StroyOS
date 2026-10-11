import React, { useEffect, useMemo, useState } from 'react';
import {Input, Pagination, Table} from 'antd';
import { ArrowRight, CheckCircle2, CircleAlert, Clock3, Folder, Plus, RefreshCw, Search, SlidersHorizontal } from 'lucide-react';
import { Episode, NavigationTab, ProjectItem } from '../../types';
import { platformApi, RuntimeStatusSummary, stageLabel } from '../../api/platformApi';
import { isHistoricalEpisodeIndex } from '../../data/storyosEpisodeLoader';
import {useLocalApprovedMedia} from '../../api/localApprovedMedia';

interface Props {
  episodes: Episode[];
  projects: ProjectItem[];
  onSelectEpisode: (episode: Episode) => void;
  onNewStory: () => void;
  onNavigate: (tab: NavigationTab) => void;
}
const STAGES: Record<string, string> = {
  IDEA_LOCK: '创意阶段', STORYBOARD_LOCK: '分镜阶段', VISUAL_CALIBRATE: '视觉校准',
  PROD_APPROVED: '生产审核', READY_TO_PUBLISH: '准备发布', PUBLISHED: '已发布', POST_MORTEM: '数据复盘'
};
const percentage = (ep: Episode) => ep.totalFrames > 0 ? Math.min(100, Math.round(ep.completedFrames / ep.totalFrames * 100)) : 0;

export const HomeOverviewView: React.FC<Props> = ({ episodes, projects, onSelectEpisode, onNewStory, onNavigate }) => {
  const {findEpisode}=useLocalApprovedMedia();
  const coverFor=(ep:Episode)=>findEpisode(ep.title,ep.code)?.frames[0]?.url || (ep.coverImage && !ep.coverImage.startsWith('data:image/svg+xml') ? ep.coverImage : '');
  const [query, setQuery] = useState('');
  const [storyPage,setStoryPage] = useState(1);
  const [runtimePage,setRuntimePage] = useState(1);
  const storyPageSize=10;
  const runtimePageSize=10;
  const [runtime, setRuntime] = useState<RuntimeStatusSummary[]>([]);
  const [runtimeStatus, setRuntimeStatus] = useState<'loading' | 'available' | 'partial' | 'offline'>('loading');
  const [runtimeTotal, setRuntimeTotal] = useState<number | null>(null);
  const [runtimeRefresh, setRuntimeRefresh] = useState(0);
  const [fetchedAt, setFetchedAt] = useState<string | null>(null);
  useEffect(() => {
    let mounted = true;
    setRuntimeStatus('loading');
    platformApi.runtimeStatuses(20, 0).then(data => {
      if (!mounted) return;
      setRuntime(data.items ?? []);
      setRuntimeTotal(Number.isFinite(data.total) ? data.total : null);
      setRuntimeStatus(data.errors?.length ? 'partial' : 'available');
      setFetchedAt(new Date().toLocaleTimeString('zh-CN', {hour12:false}));
    }).catch(() => {
      if (!mounted) return;
      setRuntime([]); setRuntimeTotal(null); setRuntimeStatus('offline'); setFetchedAt(null);
    });
    return () => { mounted = false; };
  }, [runtimeRefresh]);

  const unloadedCount = episodes.filter(isHistoricalEpisodeIndex).length;
  const attention = useMemo(() => episodes.flatMap(ep => {
    const blocked = ep.preflightChecks?.filter(item => item.status === 'blocking') ?? [];
    const failed = ep.frameReviews?.filter(item => item.verdict === 'FAIL') ?? [];
    return (blocked.length || failed.length) ? [{ ep, blocked: blocked.length, failed: failed.length }] : [];
  }), [episodes]);
  const runtimeIsFixture = runtime.some(item => item.state_source === 'isolated-test');
  const runtimeIsLocalFile = runtime.some(item => item.state_source === 'local_workspace_episode_state_file');
  const published = episodes.filter(ep => ['PUBLISHED', 'POST_MORTEM'].includes(ep.currentStage)).length;
  const pending = episodes.length - published;
  const filtered = episodes.filter(ep => (ep.title + ' ' + ep.code + ' ' + ep.genre).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  return (
    <div id="storyos-home-overview" className="w-full min-w-0 space-y-4 pb-6 text-[var(--text-primary)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-3">
        <div>
          <h1 className="os-page-heading">工作台</h1>
          <p className="mt-1 text-[13px] leading-5 text-[var(--text-secondary)]">正在制作的故事与已记录的生产状态</p>
        </div>
        <button type="button" onClick={onNewStory} className="os-action os-action-primary !h-9 text-[13px]"><Plus size={16}/> 新建故事</button>
      </header>
      <section aria-label="项目概况" className="grid grid-cols-3 gap-px border-y border-[var(--border-subtle)] bg-[var(--border-subtle)]">
        {[
          { label: '项目', value: projects.length, note: '当前工作区' },
          { label: '故事', value: episodes.length, note: '已收录' },
          { label: '待继续', value: pending, note: '尚未发布' }
        ].map((m) => <div key={m.label} className="flex min-w-0 items-center gap-3 bg-[var(--bg-app)] px-4 py-2.5 sm:gap-4">
          <div className="text-[18px] font-semibold leading-none tabular-nums text-[var(--text-primary)]">{m.value}</div><div className="min-w-0"><div className="os-stat-label">{m.label}</div><div className="hidden truncate text-[11px] text-[var(--text-tertiary)] sm:block">{m.note}</div></div>
        </div>)}
      </section>
      <div className="flex min-w-0 flex-col gap-4">
        <section className="order-2 min-w-0 space-y-3" aria-label="工作台继续制作主列表">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-2">
            <div><h2 className="os-section-heading">继续制作</h2><p className="mt-1 text-[12px] text-[var(--text-tertiary)]">工作区作品快照 · 新建草稿仅保存在本机</p></div>
            <div className="flex items-center gap-3"><span className="text-[11px] tabular-nums text-[var(--text-tertiary)]">工作区 {filtered.length} / {episodes.length} 部</span><button type="button" onClick={() => onNavigate('episodes')} className="flex items-center gap-1 text-[12px] text-[var(--info)] hover:text-[var(--text-primary)]">全部作品 <ArrowRight size={14}/></button></div>
          </div>
          <div className="os-console-filterbar flex flex-wrap items-center gap-2">
            <Input.Search aria-label="搜索作品" placeholder="搜索故事标题、编号或类型" value={query} onChange={e=>{setQuery(e.target.value);setStoryPage(1);}} allowClear className="!w-[310px] max-w-full"/>
            <span className="ml-auto text-[11px] text-[var(--text-tertiary)]">点击作品进入故事制作 · 已载入工作区数据</span>
          </div>
          <Table<Episode> size="small" rowKey="id" dataSource={filtered} scroll={{x:760}} className="storyos-home-episode-grid"
            onRow={ep=>({onClick:()=>onSelectEpisode(ep),className:'cursor-pointer'})}
            locale={{emptyText:'没有符合条件的故事，可清除筛选后继续查看。'}}
            columns={[
              {title:'作品',key:'title',render:(_,ep)=><div className="flex min-w-0 items-center gap-3"><div className="flex h-12 w-10 shrink-0 items-center justify-center overflow-hidden rounded-[4px] border border-[var(--border-subtle)] bg-[var(--bg-surface)]">{coverFor(ep)?<img alt="" loading="lazy" src={coverFor(ep)} className="h-full w-full object-cover"/>:<Folder size={16} className="text-[var(--text-tertiary)]"/>}</div><div className="min-w-0"><button type="button" onClick={event=>{event.stopPropagation();onSelectEpisode(ep);}} aria-label={`打开故事 ${ep.title}`} className="block max-w-[38vw] truncate text-left text-[13px] font-semibold hover:text-[var(--info)]">{ep.title}</button><span className="block truncate text-[11px] text-[var(--text-tertiary)]">{ep.code} · {ep.genre||'未分类'}</span></div></div>},
              {title:'工作区阶段',key:'stage',width:168,render:(_,ep)=><span className="text-[12px] text-[var(--text-secondary)]">{STAGES[ep.currentStage]??ep.currentStage}</span>},
              {title:'帧进度',key:'progress',width:180,render:(_,ep)=><div className="flex items-center gap-3 text-[12px] tabular-nums"><span className="shrink-0">{ep.completedFrames}/{ep.totalFrames}</span><div className="h-1 w-20 overflow-hidden rounded-[2px] bg-[var(--border-normal)]"><div className="h-full bg-[var(--info)]" style={{width:`${percentage(ep)}%`}}/></div><span className="text-[var(--text-tertiary)]">{percentage(ep)}%</span></div>},
              {title:'最近更新',key:'updated',width:165,sorter:(a,b)=>String(a.updatedAt||'').localeCompare(String(b.updatedAt||'')),render:(_,ep)=><span className="text-[11px] tabular-nums text-[var(--text-tertiary)]">{ep.updatedAt?new Date(ep.updatedAt).toLocaleDateString('zh-CN'):'未知'}</span>},
              {title:'',key:'action',width:90,align:'right',render:(_,ep)=><button type="button" onClick={event=>{event.stopPropagation();onSelectEpisode(ep);}} className="inline-flex items-center gap-1 text-[12px] text-[var(--info)]">打开 <ArrowRight size={13}/></button>}
            ]}
            pagination={{current:Math.min(storyPage,Math.max(1,Math.ceil(filtered.length/storyPageSize))),pageSize:storyPageSize,total:filtered.length,showTotal:(n,range)=>`${range[0]}–${range[1]} / ${n} 部`,onChange:setStoryPage}}
          />
        </section>
        <aside className="order-1 grid min-w-0 gap-x-6 gap-y-2 border-b border-[var(--border-subtle)] pb-3 md:grid-cols-[minmax(0,1fr)_minmax(280px,.9fr)]" aria-label="工作台关注事项与快捷入口">
          <section className="space-y-2">
            <h2 className="os-section-heading flex items-center gap-2"><CircleAlert size={16} className={attention.length ? 'text-[var(--danger)]' : 'text-[var(--text-tertiary)]'}/> 需要关注</h2>
            {attention.length === 0
              ? <div className="flex items-start gap-2 pt-4 text-[12px] text-[var(--text-secondary)]"><CheckCircle2 size={16} className="text-[var(--success)] shrink-0"/> 当前已载入作品中没有明确阻塞的审核记录。此处不代表平台实时健康状态。</div>
              : <div className="mt-3 space-y-3">{attention.map(({ep,blocked,failed}) => <button key={ep.id} type="button" onClick={() => onSelectEpisode(ep)} className="w-full text-left border-b last:border-b-0 border-[var(--border-subtle)] pb-3 text-[12px]"><span className="block font-medium text-[var(--text-primary)] truncate">{ep.title}</span><span className="mt-1 block text-[var(--danger)]">{blocked} 项阻塞检查 · {failed} 帧审核失败</span></button>)}</div>}
          </section>
          <section className="space-y-2 md:border-l md:border-[var(--border-subtle)] md:pl-5">
            <h2 className="os-section-heading">快捷入口</h2>
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
              {[{id:'production_monitor',label:'查看生产监控',icon:SlidersHorizontal},{id:'pipeline',label:'查看生产流程',icon:Clock3},{id:'episodes',label:'管理全部作品',icon:Folder}].map(item => { const Icon = item.icon; return <button type="button" key={item.id} onClick={() => onNavigate(item.id as NavigationTab)} className="inline-flex items-center gap-2 py-1.5 text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"><span className="flex items-center gap-2"><Icon size={15}/>{item.label}</span><ArrowRight size={14}/></button>; })}
            </div>
          </section>
          <p className="text-[11px] leading-5 text-[var(--text-tertiary)] md:col-span-2">工作区证据投影 · 非实时 Worker、队列或生产执行状态；正式执行信息请以 Platform API 为准。</p>
        </aside>
      </div>
      <section aria-label="平台生产阶段摘要" className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="os-section-heading">{runtimeIsLocalFile ? '生产阶段记录' : '平台生产阶段'}</h2><p className="mt-1 text-[12px] leading-5 text-[var(--text-secondary)]">需要核对时展开完整明细 · 不包含在线 Worker、队列或心跳。</p></div>
          <button type="button" onClick={() => setRuntimeRefresh(v => v + 1)} disabled={runtimeStatus === 'loading'} className="os-action disabled:opacity-50"><RefreshCw size={14}/> 刷新</button>
        </div>
        {runtimeStatus === 'loading' ? <p role="status" className="text-[12px] text-[var(--text-secondary)]">正在读取权威阶段摘要…</p> : runtimeStatus === 'offline' ? <p role="alert" className="text-[12px] text-[var(--warning)]">Platform API 未连接。下方仅展示本地工作区快照。</p> : <>
          {runtimeStatus === 'partial' && <p role="alert" className="text-[12px] text-[var(--warning)]">接口报告部分错误，以下记录可能不完整。</p>}
          {runtimeIsFixture && <p role="status" className="text-[12px] font-medium text-[var(--warning)]">当前来自隔离内存样例 API，仅用于本地联调，不是正式生产数据。</p>}
          {runtimeIsLocalFile && <p role="status" className="os-source-warning px-3 py-2 text-[12px] leading-5">来自本机 episodes 下真实的 episode-state.json；只读磁盘快照，不是在线 Runtime 或 MySQL 权威状态。</p>}
          <p className="text-[12px] text-[var(--text-secondary)]">已载入 {runtime.length}{runtimeTotal !== null ? ' / ' + runtimeTotal : ''} 条 · 读取时间 {fetchedAt || '未知'} · 不代表全部实时运行状态</p>
          <details className="group border-y border-[var(--border-subtle)]"><summary className="cursor-pointer py-3 text-[13px] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]">展开完整阶段记录 <span className="ml-2 text-[12px] text-[var(--text-tertiary)]">已载入 {runtime.length} 条</span></summary><div className="divide-y divide-[var(--border-subtle)] border-t border-[var(--border-subtle)]">{runtime.slice((runtimePage-1)*runtimePageSize,runtimePage*runtimePageSize).map((item, i) => <div key={item.episode_id + ':' + i} className="os-data-row flex min-h-[42px] items-center justify-between gap-4 px-4 py-2 text-[13px]"><span className="truncate" title={item.title || item.episode_ref || item.episode_id}>{item.title || item.episode_ref || item.episode_id || '未命名作品'}</span><span className="shrink-0 border-l border-[var(--border-normal)] pl-3 text-[12px] text-[var(--text-secondary)]">{stageLabel(item.production_stage || 'NO_STATE')}</span></div>)}</div>
          {runtime.length>runtimePageSize && <Pagination size="small" current={runtimePage} pageSize={runtimePageSize} total={runtime.length} onChange={setRuntimePage} showTotal={total=>`当前已载入 ${total} 条`} />}
          {runtime.length === 0 && <p className="text-[12px] text-[var(--text-tertiary)]">接口已响应，但没有阶段记录。</p>}
          </details>
          <button type="button" onClick={() => onNavigate('pipeline')} className="flex items-center gap-1 text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">查看完整工作流 <ArrowRight size={14}/></button>
        </>}
      </section>
    </div>
  );
};
