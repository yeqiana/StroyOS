import React, { useEffect, useMemo, useState } from 'react';
import {Pagination} from 'antd';
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
          <p className="mb-1 text-[11px] font-semibold tracking-[.08em] text-[var(--text-tertiary)]">内容工作区</p>
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
          <div className="text-[23px] font-semibold leading-none tabular-nums text-[var(--text-primary)]">{m.value}</div><div className="min-w-0"><div className="os-stat-label">{m.label}</div><div className="hidden truncate text-[11px] text-[var(--text-tertiary)] sm:block">{m.note}</div></div>
        </div>)}
      </section>
      <div className="grid min-w-0 grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_300px] 2xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="min-w-0 space-y-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div><h2 className="os-section-heading">继续制作</h2><p className="mt-1 text-[12px] text-[var(--text-tertiary)]">工作区作品快照 · 新建草稿仅保存在本机</p></div>
            <button type="button" onClick={() => onNavigate('episodes')} className="flex items-center gap-1 text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">全部作品 <ArrowRight size={14}/></button>
          </div>
          <label className="relative block mb-2 max-w-[420px]"><Search size={15} aria-hidden="true" className="absolute left-3 top-2.5 text-[var(--text-tertiary)]"/><input aria-label="搜索作品" value={query} onChange={e => {setQuery(e.target.value);setStoryPage(1)}} placeholder="搜索故事或编号" className="h-9 w-full rounded-[5px] border border-[var(--border-normal)] bg-[var(--bg-surface)] pl-9 pr-3 text-[13px] outline-[#58A6FF] placeholder:text-[var(--text-tertiary)]"/></label>
          <div className="overflow-hidden border-y border-[var(--border-subtle)]">
            {filtered.length === 0 && <p className="py-10 text-center text-[13px] text-[var(--text-tertiary)]">没有符合条件的故事。可以清除搜索后继续查看。</p>}
            {filtered.slice((storyPage-1)*storyPageSize,storyPage*storyPageSize).map(ep => <button key={ep.id} type="button" onClick={() => onSelectEpisode(ep)}
              aria-label={`打开故事 ${ep.title}`} className="os-data-row group w-full min-w-0 flex items-center gap-4 px-4 py-2.5 border-b last:border-b-0 border-[var(--border-subtle)] text-left">
              <div className="flex h-12 w-10 shrink-0 items-center justify-center overflow-hidden rounded-[4px] border border-[var(--border-subtle)] bg-[var(--bg-surface)]">{coverFor(ep) ? <img alt="" loading="lazy" src={coverFor(ep)} className="h-full w-full object-cover" /> : <Folder size={16} className="text-[var(--text-tertiary)]" />}</div>
              <div className="min-w-0 flex-1"><div className="truncate text-[14px] font-semibold leading-5">{ep.title}</div><div className="mt-1 truncate text-[12px] text-[var(--text-secondary)]">{STAGES[ep.currentStage] ?? ep.currentStage} · {ep.completedFrames}/{ep.totalFrames} 帧</div></div>
              <div className="hidden sm:block w-24 shrink-0"><div className="h-1 rounded-full bg-[var(--border-normal)]"><div className="h-full rounded-full bg-[#58A6FF]" style={{width: `${percentage(ep)}%`}}/></div><div className="mt-1 text-right text-[11px] tabular-nums text-[var(--text-tertiary)]">{percentage(ep)}%</div></div>
              <ArrowRight size={15} className="shrink-0 text-[var(--text-tertiary)] group-hover:text-[var(--text-primary)]"/>
            </button>)}
          </div>
          {filtered.length>storyPageSize && <Pagination size="small" current={storyPage} pageSize={storyPageSize} total={filtered.length} onChange={setStoryPage} showTotal={total=>`共 ${total} 部作品`}/>}
        </section>
        <aside className="min-w-0 space-y-5 border-t border-[var(--border-subtle)] pt-4 xl:sticky xl:top-1 xl:border-l xl:border-t-0 xl:pl-5 xl:pt-1">
          <section className="space-y-2">
            <h2 className="os-section-heading flex items-center gap-2"><CircleAlert size={16} className={attention.length ? 'text-[var(--danger)]' : 'text-[var(--text-tertiary)]'}/> 需要关注</h2>
            {attention.length === 0
              ? <div className="flex items-start gap-2 pt-4 text-[12px] text-[var(--text-secondary)]"><CheckCircle2 size={16} className="text-[var(--success)] shrink-0"/> 当前已载入作品中没有明确阻塞的审核记录。此处不代表平台实时健康状态。</div>
              : <div className="mt-3 space-y-3">{attention.map(({ep,blocked,failed}) => <button key={ep.id} type="button" onClick={() => onSelectEpisode(ep)} className="w-full text-left border-b last:border-b-0 border-[var(--border-subtle)] pb-3 text-[12px]"><span className="block font-medium text-[var(--text-primary)] truncate">{ep.title}</span><span className="mt-1 block text-[var(--danger)]">{blocked} 项阻塞检查 · {failed} 帧审核失败</span></button>)}</div>}
          </section>
          <section className="space-y-2 border-t border-[var(--border-subtle)] pt-4">
            <h2 className="text-[14px] font-semibold mb-3">快捷入口</h2>
            <div className="space-y-1">
              {[{id:'production_monitor',label:'查看生产监控',icon:SlidersHorizontal},{id:'pipeline',label:'查看生产流程',icon:Clock3},{id:'episodes',label:'管理全部作品',icon:Folder}].map(item => { const Icon = item.icon; return <button type="button" key={item.id} onClick={() => onNavigate(item.id as NavigationTab)} className="flex items-center justify-between w-full py-2 text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"><span className="flex items-center gap-2"><Icon size={15}/>{item.label}</span><ArrowRight size={14}/></button>; })}
            </div>
          </section>
          <p className="text-[11px] leading-5 text-[var(--text-tertiary)]">显示的是工作区证据投影，不等同于实时 Worker、队列或生产执行状态。实时信息请以 Platform API 为准。</p>
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
