import React, { useState, useEffect, useRef } from 'react';
import {Button,Checkbox,Input,Pagination,Progress,Table,Select,Segmented} from 'antd';
import {
  Play,
  Pause,
  RotateCcw,
  Search,
  Filter,
  RefreshCw,
  Maximize2,
  Bell,
  User,
  CheckCircle2,
  AlertCircle,
  Clock,
  MoreHorizontal,
  ArrowRight,
  Flame,
  Cpu,
  Database,
  Layers,
  X,
  ChevronRight,
  ExternalLink,
  ShieldAlert,
  SlidersHorizontal,
  Check,
  Zap
} from 'lucide-react';
import { StoryRunItem, FrameDetailItem, StoryRunStatus, StoryRunStage } from '../../types';
import { platformApi } from '../../api/platformApi';
import { REAL_STORY_RUNS } from '../../data/storyosRunSnapshots';
import { isHistoricalRunIndex, loadHistoricalRunDetail } from '../../data/storyosRunLoader';
import { STORY_OS_PLATFORM_MANIFEST } from '../../data/storyosManifestSnapshot';
import { StoryRunDetailView } from './StoryRunDetailView';
import { RuntimeAuthorityPanel } from './RuntimeAuthorityPanel';
import { ExclusiveReadGate } from '../../api/exclusiveReadGate';
import { summarizeRuntimeCoverage } from '../../api/runtimeCoverage';
import type { RuntimeStatusSummary, LocalWorkerHeartbeatSnapshot, LocalTaskStateSnapshot } from '../../api/platformApi';
import { mergeRuntimeStatusSummaries } from '../../api/runtimeSummaryMerge';

interface ProductionMonitorViewProps {
  onSelectStoryRun?: (run: StoryRunItem) => void;
  onShowToast: (msg: string) => void;
  focusEpisodeRef?:string|null;
}

export const ProductionMonitorView: React.FC<ProductionMonitorViewProps> = ({
  onSelectStoryRun,
  onShowToast,
  focusEpisodeRef,
}) => {
  // 历史运行快照，仅用于展示，不代表当前实时运行状态
  const [runs, setRuns] = useState<StoryRunItem[]>(REAL_STORY_RUNS);
  const [runtimeRows, setRuntimeRows] = useState<RuntimeStatusSummary[]>([]);
  const runtimeRowsRef = useRef<RuntimeStatusSummary[]>([]);
  const runtimeOffsetRef = useRef(0);
  const [runtimeHasMore, setRuntimeHasMore] = useState(false);
  const [runtimeLoadingMore, setRuntimeLoadingMore] = useState(false);
  const [runtimeCoverage, setRuntimeCoverage] = useState(summarizeRuntimeCoverage(0, null, false));

  // 过滤状态
  const [searchKeyword, setSearchKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [stageFilter, setStageFilter] = useState<string>('all');
  const [onlyException, setOnlyException] = useState(false);
  const [primaryView,setPrimaryView] = useState<'stages'|'history'>('stages');
  const [page,setPage] = useState(1);
  const [pageSize,setPageSize] = useState(10);
  useEffect(()=>setPage(1),[searchKeyword,statusFilter,stageFilter,onlyException]);

  // 自动刷新机制 (仅增量刷新数据，不触发整页 reload)
  const [refreshInterval, setRefreshInterval] = useState<number>(15);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [apiState, setApiState] = useState<'loading' | 'ok' | 'partial' | 'offline'>('loading');
  const [lastSync, setLastSync] = useState<string | null>(null);
  const requestGate = useRef(new ExclusiveReadGate());
  const [apiWarning, setApiWarning] = useState<string | null>(null);

  // Redis heartbeat is a separate, global, read-only observation. Never merge
  // it into an Episode's Writer, Task, Attempt, or generation state.
  const [workerSnapshot, setWorkerSnapshot] = useState<LocalWorkerHeartbeatSnapshot | null>(null);
  useEffect(() => {
    let active = true;
    let reading = false;
    const refresh = async () => {
      if (!active || reading) return;
      reading = true;
      try {
        const next = await platformApi.localWorkerHeartbeats();
        if (active) setWorkerSnapshot(next);
      } catch {
        // Never retain old green numbers as if the source were still reachable.
        if (active) setWorkerSnapshot(null);
      } finally { reading = false; }
    };
    void refresh();
    const timer = refreshInterval > 0 ? window.setInterval(() => {
      if (document.visibilityState !== 'hidden') void refresh();
    }, refreshInterval * 1000) : null;
    return () => { active = false; if (timer !== null) window.clearInterval(timer); };
  }, [refreshInterval]);

  // Separate read-only TaskStateManager scan. A RUNNING key is not a live Attempt.
  const [taskSnapshot, setTaskSnapshot] = useState<LocalTaskStateSnapshot | null>(null);
  useEffect(() => {
    let active = true;
    let reading = false;
    const refresh = async () => {
      if (!active || reading) return;
      reading = true;
      try {
        const next = await platformApi.localTaskStates();
        if (active) setTaskSnapshot(next);
      } catch {
        if (active) setTaskSnapshot(null);
      } finally { reading = false; }
    };
    void refresh();
    const timer = refreshInterval > 0 ? window.setInterval(() => {
      if (document.visibilityState !== 'hidden') void refresh();
    }, refreshInterval * 1000) : null;
    return () => { active = false; if (timer !== null) window.clearInterval(timer); };
  }, [refreshInterval]);

  // 选中的 Story Run 详情视图
  const [selectedRunForDetail, setSelectedRunForDetail] = useState<StoryRunItem | null>(null);
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);
  const [runLoadError, setRunLoadError] = useState<string | null>(null);
  const runLoadGeneration = useRef(0);
  const selectRun = async (run: StoryRunItem) => {
    if (!isHistoricalRunIndex(run)) { setSelectedRunForDetail(run);return; }
    const generation = ++runLoadGeneration.current;
    setPendingRunId(run.id);setRunLoadError(null);
    try {
      const detail = await loadHistoricalRunDetail(run.id);
      if (generation !== runLoadGeneration.current) return;
      if (detail.id !== run.id) throw new Error('Run 详情身份不匹配');
      setRuns(previous => previous.map(entry => entry.id === run.id ? detail : entry));
      setSelectedRunForDetail(detail);
    } catch(error) {
      if (generation === runLoadGeneration.current) setRunLoadError(error instanceof Error?error.message:'历史 Run 加载失败');
    } finally {if (generation === runLoadGeneration.current) setPendingRunId(null);}
  };

  // 从真实平台接口同步 canonical stage 投影；丰富的帧/证据详情继续来自工作区生成投影。
  const loadLatestStatuses = async (isManual = false) => {
    // 用户展开多页时暂停后台首屏轮询，以免 15 秒后把已加载的下一页静默清空。
    // 手动刷新明确恢复到第一页，并重新读取最新摘要。
    if (!isManual && runtimeOffsetRef.current > 100) return;
    // 同一页面只允许一个阶段查询在途；旧请求不能覆盖刷新后的数据。
    const generation = requestGate.current.begin();
    if (generation === null) {
      if (isManual) onShowToast('正在读取阶段摘要，请稍候');
      return;
    }
    try {
      setIsRefreshing(true);
      const data = await platformApi.runtimeStatuses(100, 0);
      if (!requestGate.current.isCurrent(generation)) return;
      setApiState(data.errors?.length ? 'partial' : 'ok');
      setApiWarning(data.errors?.length ? 'Platform API 返回部分错误，请勿据此推断未返回的故事状态。' : null);
      setLastSync(new Date().toLocaleTimeString('zh-CN',{hour12:false}));
      // 不将平台阶段数据按标题合并进历史 Story Run；两种证据各自独立展示。
      runtimeRowsRef.current = data.items ?? [];
      runtimeOffsetRef.current = (data.items ?? []).length;
      setRuntimeRows(runtimeRowsRef.current);
      setRuntimeHasMore(Boolean(data.has_more));
      setRuntimeCoverage(summarizeRuntimeCoverage(runtimeRowsRef.current.length, data.total, Boolean(data.has_more), data.errors ?? []));
      if (isManual) {
        onShowToast(data.errors?.length ? '接口仅部分返回；未覆盖工作区快照' : '已读取最新阶段摘要，其他指标仍为工作区快照');
      }
    } catch (err) {
      if (!requestGate.current.isCurrent(generation)) return;
      console.error('Failed to fetch runtime statuses:', err);
      setApiState('offline');
      runtimeRowsRef.current = [];
      runtimeOffsetRef.current = 0;
      setRuntimeRows([]);
      setRuntimeHasMore(false);
      setRuntimeCoverage(summarizeRuntimeCoverage(0, null, false));
      setApiWarning('无法连接 Platform API。以下运行记录仅为本地工作区快照，不代表当前在线执行状态。');
      if (isManual) onShowToast('同步失败：无法连接 Platform API');
    } finally {
      if (requestGate.current.finish(generation)) setIsRefreshing(false);
    }
  };

  // 只读分页。复用同一代际锁，确保手动刷新、轮询、下一页互不覆盖。
  const loadNextRuntimePage = async () => {
    if (!runtimeHasMore) return;
    const generation = requestGate.current.begin();
    if (generation === null) return;
    const offset = runtimeOffsetRef.current;
    setRuntimeLoadingMore(true);
    try {
      const data = await platformApi.runtimeStatuses(100, offset);
      if (!requestGate.current.isCurrent(generation)) return;
      const page = data.items ?? [];
      const next = mergeRuntimeStatusSummaries(runtimeRowsRef.current, page);
      runtimeRowsRef.current = next;
      runtimeOffsetRef.current = offset + page.length;
      const hasMore = Boolean(data.has_more) && page.length > 0;
      setRuntimeHasMore(hasMore);
      setRuntimeRows(next);
      setRuntimeCoverage(summarizeRuntimeCoverage(next.length, data.total, hasMore, data.errors ?? []));
      setApiState(data.errors?.length ? 'partial' : 'ok');
      if (data.errors?.length) onShowToast('下一页返回部分错误，阶段记录可能不完整');
    } catch {
      if (requestGate.current.isCurrent(generation)) {
        // Preserve loaded rows, but never continue to label partial evidence as complete.
        setApiState('partial');
        setApiWarning('下一页阶段摘要读取失败，已保留当前记录；完整范围尚未核验。');
        onShowToast('下一页读取失败，已保留成功加载的记录');
      }
    } finally {
      if (requestGate.current.finish(generation)) setRuntimeLoadingMore(false);
    }
  };

  useEffect(() => {
    loadLatestStatuses();
    return () => {
      // 组件卸载/StrictMode 重新挂载时废弃当前结果，不更新已卸载页面。
      requestGate.current.invalidate();
    };
  }, []);

  // 自动刷新不会和手动刷新并发，也不会在卸载后覆盖较新请求
  useEffect(() => {
    if (refreshInterval <= 0) return;
    const interval = setInterval(() => {
      if (document.visibilityState !== 'hidden') void loadLatestStatuses();
    }, refreshInterval * 1000);
    return () => clearInterval(interval);
  }, [refreshInterval]);

  // 仅显示现有证据快照可证实的数量；不推测 Worker、GPU 或平台健康度。
  const metrics = {
    queueWaiting: runs.filter(r => r.status === 'WAITING').length,
  };

  // 筛选逻辑
  const filteredRuns = runs.filter((run) => {
    if (searchKeyword) {
      const kw = searchKeyword.toLowerCase();
      const matchName = run.storyName.toLowerCase().includes(kw);
      const matchRunId = run.runId.toLowerCase().includes(kw);
      if (!matchName && !matchRunId) return false;
    }
    if (statusFilter !== 'all' && run.status !== statusFilter) {
      return false;
    }
    if (stageFilter !== 'all' && run.currentStage !== stageFilter) {
      return false;
    }
    if (onlyException) {
      if (!['BLOCKED', 'FAILED', 'RETRYING'].includes(run.status) && run.exceptionType !== 'manual' && run.exceptionType !== 'auto_retry') {
        return false;
      }
    }
    return true;
  });

  const safePage=Math.min(page,Math.max(1,Math.ceil(filteredRuns.length/pageSize)));
  const pagedRuns=filteredRuns.slice((safePage-1)*pageSize,safePage*pageSize);

  // 本端没有已验证的暂停/恢复/重试写入契约；严禁前端自改 status 并声称成功。
  const handleResetFilter = () => {
    setSearchKeyword('');
    setStatusFilter('all');
    setStageFilter('all');
    setOnlyException(false);
    onShowToast('筛选条件已重置');
  };

  // Queue 积压判定规则：0–20 正常, 21–50 轻度积压, 51–100 中度积压, >100 严重积压
  const getQueueSeverity = (count: number) => {
    if (count <= 20) return { label: '正常', color: 'text-[var(--success)]', bg: 'bg-[var(--success)]/10' };
    if (count <= 50) return { label: '轻度积压', color: 'text-[var(--warning)]', bg: 'bg-[var(--warning)]/10' };
    if (count <= 100) return { label: '中度积压', color: 'text-[var(--warning)]', bg: 'bg-[var(--warning)]/10' };
    return { label: '严重积压', color: 'text-[var(--danger)]', bg: 'bg-[var(--danger)]/10' };
  };

  // 本地快照的相对心跳文本并非在线探活结果，不可根据旧秒数显示实时健康。
  const getHeartbeatStatus = (_seconds: number) => ({ color: 'text-[var(--text-tertiary)]', dot: 'bg-[var(--text-tertiary)]', label: '历史快照（未验证当前心跳）' });

  // 如果点击查看了某个具体的 Story Run，无缝展示高阶独立全量详情页（尸解仙排障与流水线）
  if (selectedRunForDetail) {
    return (
      <StoryRunDetailView
        run={selectedRunForDetail}
        onBack={() => setSelectedRunForDetail(null)}
        onShowToast={onShowToast}
        onUpdateRun={(updated) => {
          setRuns((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
          setSelectedRunForDetail(updated);
        }}
      />
    );
  }

  // 状态与颜色辅助函数 (严格遵守 UI Baseline v1: dot 6px, gap 6px, font 12px / 500, 克制无浓艳背景)
  const getStatusBadge = (run: StoryRunItem) => {
    switch (run.status) {
      case 'RUNNING':
        return (
          <span className="inline-flex items-center gap-1.5 text-xs font-mono font-medium text-[var(--info)]">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--info)]" />
            <span>记录时运行中</span>
          </span>
        );
      case 'WAITING':
        return (
          <span className="inline-flex items-center gap-1.5 text-xs font-mono font-medium text-[var(--warning)]">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--warning)]" />
            <span>{run.waitingReason ? `记录时排队（${run.waitingReason}）` : '记录时排队'}</span>
          </span>
        );
      case 'RETRYING':
        return (
          <span className="inline-flex items-center gap-1.5 text-xs font-mono font-medium text-[var(--warning)]">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--warning)]" />
            <span>记录时重试中</span>
          </span>
        );
      case 'BLOCKED':
        return (
          <span className="inline-flex items-center gap-1.5 text-xs font-mono font-semibold text-[var(--danger)]">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--danger)]" />
            <span>记录时阻塞</span>
          </span>
        );
      case 'FAILED':
        return (
          <span className="inline-flex items-center gap-1.5 text-xs font-mono font-medium text-[var(--danger)]">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--danger)]" />
            <span>记录时失败</span>
          </span>
        );
      case 'COMPLETED':
        return (
          <span className="inline-flex items-center gap-1.5 text-xs font-mono font-medium text-[var(--success)]">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--success)]" />
            <span>记录时运行结束</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 text-xs font-mono text-[var(--text-tertiary)]">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--text-disabled)]" />
            <span>记录时未开始</span>
          </span>
        );
    }
  };

  const getStageBadge = (stage: StoryRunStage, label: string) => {
    return (
      <span className="inline-flex items-center rounded-[7px] border border-[var(--border-normal)] bg-[var(--bg-elevated)] px-2.5 py-1 text-[11px] font-medium text-[var(--text-secondary)] whitespace-nowrap">
        {label}
      </span>
    );
  };

  return (
    <div id="storyos-production-monitor-view" className="w-full min-w-0 space-y-3 pb-5 font-sans text-[var(--text-primary)]">
      {/* 顶部标题与控制栏 (UI Baseline v1: 弱装饰、扁平、简洁) */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-3">
        <div className="flex flex-col items-start gap-1">
          <h1 className="os-page-heading">
            生产监控
          </h1><p className="mt-1 text-[12px] text-[var(--text-secondary)]">查看作品阶段与历史记录 · 只读</p>
        </div>

        <div className="flex items-center gap-2 text-xs">
          {/* 自动刷新下拉切换 */}
          <div className="flex items-center gap-1.5 h-9 px-2 rounded-[5px] border border-[var(--border-subtle)] text-[var(--text-secondary)]">
            <span className={`w-1.5 h-1.5 rounded-full ${isRefreshing?'bg-[var(--info)]':apiState==='ok'?'bg-[var(--text-tertiary)]':'bg-[var(--warning)]'}`} />
            <span className="text-[var(--text-tertiary)]">读取间隔:</span>
            <Select aria-label="刷新间隔" size="small" variant="borderless" className="!min-w-[66px]" value={refreshInterval} onChange={setRefreshInterval} options={[{value:5,label:'5 秒'},{value:10,label:'10 秒'},{value:15,label:'15 秒'},{value:30,label:'30 秒'},{value:0,label:'关闭'}]} />
          </div>

          <button
            type="button"
            onClick={() => loadLatestStatuses(true)}
            className="h-9 w-9 flex items-center justify-center rounded-[4px] bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-elevated)] transition-colors cursor-pointer"
            title="手动刷新阶段证据"
            aria-label="手动刷新阶段证据"
          >
            <RefreshCw className={`w-3 h-3 ${isRefreshing ? 'animate-spin text-[var(--text-primary)]' : ''}`} />
          </button>
        </div>
      </div>

      <div aria-label="当前生产执行证据" role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-[var(--border-subtle)] pb-3 text-[12px]">
        <strong className="font-medium text-[var(--text-primary)]">当前执行：尚未核验</strong>
                <span aria-label="Redis 观测摘要" className="text-[var(--text-secondary)]">
          Redis Task：{taskSnapshot?.available ? String(taskSnapshot.record_count) + " 条（自报运行 " + taskSnapshot.running_claims + "）" : "不可用"} · Worker 心跳：{workerSnapshot?.available ? String(workerSnapshot.record_count) + " 条（时间/TTL 新鲜 " + workerSnapshot.fresh_heartbeats + "）" : "不可用"}；仅为只读记录，不等于实时生图。
        </span>
      </div>
      <div className="os-console-toolbar flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] py-1 pb-3" aria-label="生产监控主工作区切换">
        <Segmented aria-label="生产监控视图" value={primaryView} onChange={value=>setPrimaryView(value as 'stages'|'history')}
          options={[{value:'stages',label:`阶段证据 (${runtimeCoverage.loaded})`},{value:'history',label:`历史 Run (${runs.length})`}]}/>
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-[var(--text-tertiary)]"><span>{primaryView==='stages'?'Platform API 只读阶段 · 本机文件非实时':'历史 Run 快照 · 非实时 Worker 视图'}</span><span className="tabular-nums">{primaryView==='stages'?`已读取 ${runtimeCoverage.loaded} 条`:`${runs.length} 个历史实例`}</span></div>
      </div>
      {primaryView==='stages' ? <section aria-label="阶段证据主视图" className="min-w-0 space-y-3">
        {apiState !== 'ok' && <div role="status" className="flex flex-wrap items-center justify-between gap-2 border-l-2 border-[var(--warning)] px-3 py-2 text-[12px] text-[var(--text-secondary)]"><span>{apiState === 'loading' ? '正在读取 Platform API 阶段摘要…' : apiWarning}</span><span className="shrink-0 text-[var(--text-tertiary)]">{lastSync ? `最近获取 ${lastSync}` : '未获得有效在线证据'}</span></div>}
        <RuntimeAuthorityPanel focusEpisodeRef={focusEpisodeRef} items={runtimeRows} coverage={runtimeCoverage} hasMore={runtimeHasMore} loadingMore={runtimeLoadingMore} onLoadMore={loadNextRuntimePage} dataState={apiState} lastSync={lastSync}/>
        <details aria-label="Redis 只读技术证据" className="border-t border-[var(--border-subtle)] pt-2 text-[12px] text-[var(--text-secondary)]">
          <summary className="cursor-pointer py-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)]">Redis 技术观测 · 仅供核对，不证明正在生产</summary>
          <div className="space-y-2 pt-2">
        <section aria-label="Redis Worker 心跳只读观测" className="flex flex-wrap items-center gap-x-5 gap-y-2 border border-[var(--border-subtle)] px-3 py-2 text-[12px] text-[var(--text-secondary)]">
          <strong className="font-medium text-[var(--text-primary)]">Redis 心跳观测</strong>
          {!workerSnapshot || !workerSnapshot.available ? (
            <span role="status">只读来源未接通 · Worker 在线状态未知</span>
          ) : (
            <>
              <span>采集记录 {workerSnapshot.record_count}</span>
              <span>时间与 TTL 均新鲜 {workerSnapshot.fresh_heartbeats}</span>
              <span className={workerSnapshot.stale_heartbeats > 0 ? 'text-[var(--warning)]' : ''}>心跳过期 {workerSnapshot.stale_heartbeats}</span>
              <span>无法核验 {workerSnapshot.unverified_heartbeats}</span>
              {!workerSnapshot.scan_complete && <span className="text-[var(--warning)]">仅部分扫描结果</span>}
            </>
          )}
          <span className="text-[11px] text-[var(--text-tertiary)]">
            仅核对 Redis TTL、记录时间和身份；不等于 Worker 仍运行，更不代表当前作品有执行权。
          </span>
        </section>

        <section aria-label="Redis Task 状态只读观测" className="space-y-2 border border-[var(--border-subtle)] px-3 py-2 text-[12px] text-[var(--text-secondary)]">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <strong className="font-medium text-[var(--text-primary)]">Redis Task 记录</strong>
            {!taskSnapshot || !taskSnapshot.available ? (
              <span role="status">只读任务来源未接通 · 无法判断是否有任务在执行</span>
            ) : (
              <>
                <span>已扫描 {taskSnapshot.record_count}</span>
                <span className="text-[var(--text-tertiary)]">采集于 {taskSnapshot.observed_at ? new Date(taskSnapshot.observed_at).toLocaleString("zh-CN") : "未提供"}</span>
                <span>自报运行 {taskSnapshot.running_claims}</span>
                <span>自报排队 {taskSnapshot.queued_claims}</span>
                <span>{taskSnapshot.unverified_count ? `无法核验 ${taskSnapshot.unverified_count}` : '状态格式已核对（非执行核验）'}</span>
                {!taskSnapshot.scan_complete && <span className="text-[var(--warning)]">扫描不完整</span>}
              </>
            )}
          </div>
          <p className="text-[11px] leading-5 text-[var(--text-tertiary)]">
            Redis TaskStateManager 仅有 Task ID 与状态；不含作品、帧号、Worker、更新时间或有效执行租约。自报 RUNNING 不等于正在生产。
          </p>
          {taskSnapshot?.available && taskSnapshot.record_count === 0 && taskSnapshot.scan_complete &&
            <p role="status" className="text-[11px] text-[var(--text-secondary)]">当前未发现此命名空间的 Task 状态记录；不能据此断言所有生产队列为空。</p>}
          {taskSnapshot?.available && taskSnapshot.records.length > 0 &&
            <div className="max-h-[220px] overflow-auto border-t border-[var(--border-subtle)] pt-1" aria-label="Redis Task 状态记录列表">
              {taskSnapshot.records.map(item => (
                <div key={item.task_tag} className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-subtle)] px-1 py-1.5 text-[11px]">
                  <span className="font-mono text-[var(--text-secondary)]">Task #{item.task_tag}</span>
                  <span className="font-medium text-[var(--text-primary)]">{item.recorded_status}（历史状态，未核验时效）</span>
                  <span className="text-[var(--text-tertiary)]">作品／帧／Worker：无关联证据</span>
                </div>
              ))}
              {taskSnapshot.record_count > taskSnapshot.records.length && <p className="py-2 text-[var(--text-tertiary)]">只展示前 {taskSnapshot.records.length} 条；其余不在此处加载</p>}
            </div>}
        </section>
          </div>
        </details>
      </section> : <section aria-label="历史 Run 主视图" className="min-w-0 space-y-3">
      <p className="text-[12px] text-[var(--text-secondary)]">历史 Run 是保存时的记录；运行中、排队和完成仅指当时的 Run，不代表当前正在生产或整部作品完成。</p>
      {/* ======================= 1. Operational Status Bar ======================= */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-2 py-2.5 text-xs">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] text-[var(--text-tertiary)]">全部</span>
            <span className="text-[15px] font-semibold text-[var(--text-primary)]">{runs.length}</span>
          </div>

          <div className="w-[1px] h-3.5 bg-[var(--border-subtle)]" />

          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] text-[var(--text-tertiary)] flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--info)]" />
              <span>记录时运行</span>
            </span>
            <span className="text-[15px] font-semibold text-[var(--info)]">
              {runs.filter(r => r.status === 'RUNNING').length}
            </span>
          </div>

          <div className="w-[1px] h-3.5 bg-[var(--border-subtle)]" />

          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] text-[var(--text-tertiary)] flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--warning)]" />
              <span>记录时等待</span>
            </span>
            <span className="text-[15px] font-semibold text-[var(--warning)]">
              {runs.filter(r => r.status === 'WAITING').length}
            </span>
          </div>

          <div className="w-[1px] h-3.5 bg-[var(--border-subtle)]" />

          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] text-[var(--text-tertiary)] flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--warning)]" />
              <span>记录时重试</span>
            </span>
            <span className="text-[15px] font-semibold text-[var(--warning)]">
              {runs.filter(r => r.status === 'RETRYING').length}
            </span>
          </div>

          <div className="w-[1px] h-3.5 bg-[var(--border-subtle)]" />

          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] text-[var(--danger)] font-medium flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--danger)]" />
              <span>记录时阻塞</span>
            </span>
            <span className="text-[15px] font-semibold text-[var(--danger)]">
              {runs.filter(r => r.status === 'BLOCKED').length}
            </span>
          </div>

          <div className="w-[1px] h-3.5 bg-[var(--border-subtle)]" />

          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] text-[var(--text-tertiary)] flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--success)]" />
              <span>记录时结束</span>
            </span>
            <span className="text-[15px] font-semibold text-[var(--text-primary)]">
              {runs.filter(r => r.status === 'COMPLETED').length}
            </span>
          </div>
        </div>


      </div>

      {/* ======================= 2. Toolbar ======================= */}
      <div className="os-console-filterbar flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-2 py-2 text-xs">
        <div className="flex flex-1 flex-wrap items-center gap-2 min-w-[260px]">
          {/* 搜索输入框 */}
          <Input
            aria-label="搜索剧集或任务 ID"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            placeholder="搜索剧集 / 任务 ID..."
            prefix={<Search size={14} />}
            className="!w-[260px] max-w-full"
            allowClear
          />

          {/* 状态下拉筛选 */}
          <div className="flex items-center gap-1.5">
            <Select aria-label="按历史状态筛选" value={statusFilter} onChange={setStatusFilter} className="w-[152px]" options={[{value:'all',label:'全部记录状态'},{value:'RUNNING',label:'记录时运行'},{value:'WAITING',label:'记录时排队'},{value:'RETRYING',label:'记录时重试'},{value:'BLOCKED',label:'记录时阻塞'},{value:'COMPLETED',label:'记录时结束'}]} />
          </div>

          {/* 阶段下拉筛选 */}
          <div className="flex items-center gap-1.5">
            <Select aria-label="按阶段筛选" value={stageFilter} onChange={setStageFilter} className="w-[158px]" options={[{"value":"all","label":"全部阶段"},{"value":"CREATE","label":"创意"},{"value":"STORYBOARD","label":"分镜"},{"value":"VISUAL_LOCK","label":"视觉锁定"},{"value":"PRODUCTION","label":"生产"},{"value":"PUBLISH","label":"发布"},{"value":"COMPLETED","label":"已完成"}]} />
          </div>

          {/* 只看异常复选框 */}
          <Checkbox checked={onlyException} onChange={e => setOnlyException(e.target.checked)}><span className="inline-flex items-center gap-1 text-xs text-[var(--text-secondary)]"><ShieldAlert size={14} className="text-[var(--warning)]" />只看异常</span></Checkbox>
        </div>

        {/* 查询与重置按钮 */}
        <div className="flex items-center gap-2 font-mono">
          <Button size="small" onClick={handleResetFilter}>重置</Button>
        </div>
      </div>

      {/* ======================= 3. Data Table (Core: Header 36px, Row 44px, Cell X 12px, Cell Y 8px) ======================= */}
      <div className="overflow-hidden rounded-[6px] border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
        <div className="flex min-h-10 items-center justify-between border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 text-[13px]">
          <div className="flex items-center gap-2 text-[var(--text-secondary)] font-medium">
            <span>历史 Run 列表</span>
            <span className="text-[var(--text-tertiary)] text-[12px]">({filteredRuns.length} 个实例)</span>
            {pendingRunId && <span role="status" className="text-[11px] text-[var(--text-secondary)]">正在按需读取历史 Run 详情…</span>}
            {runLoadError && <span role="alert" className="text-[11px] text-[var(--warning)]">历史详情读取失败：{runLoadError}；请重新点击记录重试。</span>}
          </div>
        </div>

        <Table<StoryRunItem>
          rowKey="id"
          size="small"
          className="storyos-monitor-grid"
          scroll={{x:900}}
          dataSource={pagedRuns}
          onRow={run=>({onClick:()=>void selectRun(run),className:'cursor-pointer'})}
          pagination={false}
          locale={{emptyText:'暂无符合筛选条件的历史运行记录'}}
          columns={[

            {title:'作品',dataIndex:'storyName',key:'name',width:240,render:(value:string)=><span title={value} className="block max-w-[240px] truncate text-[13px] font-semibold text-[var(--text-primary)]">{value}</span>},

            {title:'状态',key:'status',width:162,render:(_,run)=>getStatusBadge(run)},
            {title:'记录时图片进度',key:'progress',width:126,render:(_,run)=><span className="flex items-center gap-2 text-[12px] tabular-nums"><Progress size="small" percent={run.progressPercent} strokeColor={run.status==='BLOCKED'?'var(--danger)':'var(--info)'} trailColor="var(--border-normal)" showInfo={false} className="!m-0 !w-16"/>{run.progressPercent}%</span>},


            {title:'异常摘要',key:'exception',width:160,ellipsis:true,render:(_,run)=>run.exceptionSummary==='-'?<span className="text-[var(--text-disabled)]">—</span>:<span title={run.exceptionSummary} className="text-[12px] font-medium text-[var(--danger)]">{run.exceptionSummary}</span>},
            {title:'操作',key:'action',width:100,fixed:'right',align:'right',render:(_,run)=><Button type="link" size="small" onClick={e=>{e.stopPropagation();void selectRun(run);}}>查看详情</Button>}
          ]}
        />
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border-subtle)] px-3 py-3"><span className="text-[11px] text-[var(--text-tertiary)]">历史快照 · 匹配 {filteredRuns.length} 条</span><Pagination size="small" current={safePage} pageSize={pageSize} total={filteredRuns.length} showSizeChanger pageSizeOptions={["10","20","50","100"]} showTotal={n=>`共 ${n} 条`} onChange={(p,s)=>{setPage(p);setPageSize(s);}} /></div>
      </div>
      </section>}

      {/* 极简详情抽屉 (不繁琐、无冗余AI堆砌) */}
      {selectedRunForDetail && (
        <div className="fixed inset-y-0 right-0 z-50 w-80 bg-[var(--bg-workspace)] border-l border-[var(--border-subtle)] shadow-2xl p-4 flex flex-col justify-between animate-in slide-in-from-right duration-150">
          <div className="space-y-4">
            {/* 顶栏 */}
            <div className="flex items-center justify-between pb-3 border-b border-[var(--border-subtle)]">
              <div>
                <span className="text-[10px] font-mono text-[var(--text-tertiary)]">实例详情 · {selectedRunForDetail.runId}</span>
                <h3 className="text-sm font-semibold text-[var(--text-primary)] mt-0.5">{selectedRunForDetail.storyName}</h3>
              </div>
              <button
                type="button"
                onClick={() => setSelectedRunForDetail(null)}
                className="p-1 rounded hover:bg-[#1A1F26] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* 核心指标列表 */}
            <div className="space-y-2.5 text-xs font-mono">
              <div className="flex items-center justify-between p-2 rounded bg-[#14171D] border border-[var(--border-subtle)]">
                <span className="text-[var(--text-tertiary)]">生产阶段</span>
                <span>{getStageBadge(selectedRunForDetail.currentStage, selectedRunForDetail.stageLabel)}</span>
              </div>

              <div className="flex items-center justify-between p-2 rounded bg-[#14171D] border border-[var(--border-subtle)]">
                <span className="text-[var(--text-tertiary)]">当前状态</span>
                <span>{getStatusBadge(selectedRunForDetail)}</span>
              </div>

              <div className="p-2 rounded bg-[#14171D] border border-[var(--border-subtle)] space-y-1.5">
                <div className="flex items-center justify-between text-[var(--text-tertiary)]">
                  <span>分镜进度</span>
                  <span className="text-[var(--text-primary)] font-semibold">{selectedRunForDetail.completedFrames} / {selectedRunForDetail.totalFrames} 帧 ({selectedRunForDetail.progressPercent}%)</span>
                </div>
                <div className="w-full h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                  <div
                    className={`h-full rounded-full ${selectedRunForDetail.progressPercent === 100 ? 'bg-[var(--success)]' : 'bg-[#58A6FF]'}`}
                    style={{ width: `${selectedRunForDetail.progressPercent}%` }}
                  />
                </div>
              </div>

              <div className="flex items-center justify-between p-2 rounded bg-[#14171D] border border-[var(--border-subtle)]">
                <span className="text-[var(--text-tertiary)]">累计耗时</span>
                <span className="text-[var(--text-primary)]">{selectedRunForDetail.duration}</span>
              </div>

              <div className="flex items-center justify-between p-2 rounded bg-[#14171D] border border-[var(--border-subtle)]">
                <span className="text-[var(--text-tertiary)]">心跳上报</span>
                <span className="text-[var(--text-secondary)]">{selectedRunForDetail.lastHeartbeatAgo}</span>
              </div>

              {selectedRunForDetail.exceptionSummary !== '-' && (
                <div className="p-2.5 rounded bg-red-500/10 border border-red-500/20 text-red-400">
                  <div className="font-semibold mb-1 flex items-center gap-1">
                    <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                    <span>异常摘要</span>
                  </div>
                  <p className="text-[11px] leading-relaxed">{selectedRunForDetail.exceptionSummary}</p>
                </div>
              )}
            </div>
          </div>

          {/* 底部操作 */}
          <div className="pt-3 border-t border-[var(--border-subtle)] flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setSelectedRunForDetail(null)}
              className="px-3 py-1.5 rounded bg-[var(--bg-elevated)] border border-[#2D333D] text-xs font-mono text-[var(--text-secondary)] hover:text-[var(--text-primary)] cursor-pointer"
            >
              关闭
            </button>
            <button
              type="button"
              onClick={() => {
                if (onSelectStoryRun) {
                  onSelectStoryRun(selectedRunForDetail);
                }
                setSelectedRunForDetail(null);
                onShowToast(`已进入《${selectedRunForDetail.storyName}》工作台`);
              }}
              className="px-3 py-1.5 rounded bg-white text-black hover:bg-zinc-200 text-xs font-semibold cursor-pointer flex items-center gap-1"
            >
              <span>进入工作台</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
