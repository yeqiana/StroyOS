import React, { useEffect, useRef, useState } from 'react';
import { recordedTraceCoverage } from '../../api/recordedTraceCoverage';
import {Button,Drawer,Input,Select,Table} from 'antd';
import { platformApi, RuntimeStatusDetail, RuntimeStatusSummary, stageLabel } from '../../api/platformApi';
import type { RuntimeCoverage } from '../../api/runtimeCoverage';
import { RuntimeRecoveryInsight } from './RuntimeRecoveryInsight';
import { runtimeDetailMatchesEpisode, selectCurrentRuntimeDetail } from '../../api/runtimeRecoveryAssessment';

const readOnlyAge = (seconds: number | null | undefined): string => {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return "无法核验";
  if (seconds < 60) return "不足 1 分钟";
  if (seconds < 3600) return Math.floor(seconds / 60) + " 分钟前";
  if (seconds < 86400) return Math.floor(seconds / 3600) + " 小时前";
  return Math.floor(seconds / 86400) + " 天前";
};

interface Props { items: RuntimeStatusSummary[]; coverage: RuntimeCoverage; hasMore: boolean; loadingMore: boolean; onLoadMore: () => void; dataState: 'loading' | 'ok' | 'partial' | 'offline'; lastSync: string | null; focusEpisodeRef?:string|null; }
export const RuntimeAuthorityPanel: React.FC<Props> = ({ items, coverage, hasMore, loadingMore, onLoadMore, dataState, lastSync, focusEpisodeRef }) => {
  const [selected, setSelected] = useState<RuntimeStatusSummary | null>(null);
  // Keep the open drawer bound to the latest row, using exact Episode identity.
  const currentSelected = selected ? items.find(item =>
    selected.episode_ref ? item.episode_ref === selected.episode_ref
      : selected.episode_id ? item.episode_id === selected.episode_id
      : selected.business_episode_id ? item.business_episode_id === selected.business_episode_id
      : Boolean(selected.episode && item.episode === selected.episode)
  ) ?? null : null;
  useEffect(() => {
    if (selected && dataState !== 'loading' && (dataState === 'offline' || !currentSelected)) setSelected(null);
  }, [dataState, selected, currentSelected]);
  const openedFocus = useRef<string|null>(null);
  useEffect(()=>{
    if(!focusEpisodeRef||!/^LOCAL_[a-f0-9]{24}$/.test(focusEpisodeRef)||openedFocus.current===focusEpisodeRef)return;
    const target=items.find(item=>item.episode_ref===focusEpisodeRef);
    if(target){openedFocus.current=focusEpisodeRef;setSelected(target);}
  },[focusEpisodeRef,items]);
  const [page,setPage]=useState(1);
  const [stageFilter,setStageFilter]=useState('ALL');
  const [keyword,setKeyword]=useState('');
  const [pageSize,setPageSize]=useState(12);
  const stageChoices=Array.from(new Set(items.map(item=>item.production_stage).filter((stage):stage is string=>Boolean(stage))));
  const filtered=items.filter(item=>{
    if(stageFilter!=='ALL'&&item.production_stage!==stageFilter)return false;
    const needle=keyword.trim().toLocaleLowerCase();
    return !needle||[item.title,item.episode_ref,item.episode_id,item.business_episode_id].some(value=>String(value||'').toLocaleLowerCase().includes(needle));
  });
  const safePage=Math.min(page,Math.max(1,Math.ceil(filtered.length/pageSize)));
  const [detail, setDetail] = useState<RuntimeStatusDetail | null>(null);
  const [detailState, setDetailState] = useState<'loading' | 'available' | 'unavailable'>('loading');
  const ref = selected?.episode_ref || selected?.episode || selected?.business_episode_id || selected?.episode_id;
  useEffect(() => {
    if (!ref) { setDetail(null); return; }
    let active = true;
    let reading = false;
    setDetailState('loading');
    setDetail(null);
    const refreshDetail = async () => {
      if (!active || reading) return;
      reading = true;
      try {
        const response = await platformApi.runtimeStatus(ref);
        if (!active) return;
        const matched = runtimeDetailMatchesEpisode(ref, response);
        setDetail(matched ? response : null);
        setDetailState(matched ? 'available' : 'unavailable');
      } catch {
        if (active) { setDetail(null); setDetailState('unavailable'); }
      } finally {
        reading = false;
      }
    };
    void refreshDetail();
    // Poll only the selected read-only detail; never invoke a mutating endpoint.
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') void refreshDetail();
    }, 10_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [ref]);
  // Identity guard runs at render-time, before the effect clears prior selection.
  // Never flash another Episode's asynchronous details in a newly selected drawer.
  const visibleDetail = detailState === 'available' && ref ? selectCurrentRuntimeDetail(ref, detail) : null;
  const detailIsCurrent = visibleDetail !== null;
  const text = (value?: string | number | boolean | null) => value === null || value === undefined || value === '' ? '未提供' : String(value);
  return <section aria-label="只读状态记录及数据来源" className="min-w-0 overflow-hidden border-y border-[var(--border-subtle)] text-[12px] text-[var(--text-primary)]">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-3 py-2">
      <div className="flex flex-wrap items-baseline gap-3"><h2 className="os-section-heading">{items.some(item => item.state_source === 'mysql_episode_state_read_only') ? '生产阶段 · MySQL 权威只读' : '本机作品状态记录'}</h2><span className="text-[11px] text-[var(--text-tertiary)]">每 10 秒刷新详情 · 不派发生产</span></div>
      <span className="shrink-0 text-[11px] text-[var(--text-tertiary)]">{lastSync ? '读取于 ' + lastSync : '未获取成功'}</span>
    </div>
    {items.length>0&&<nav aria-label="生产阶段快速筛选" className="flex min-w-0 flex-wrap items-stretch gap-px border-b border-[var(--border-subtle)] bg-[var(--border-subtle)]">
      {[{value:'ALL',label:'已载入',count:items.length},...stageChoices.map(value=>({value,label:stageLabel(value),count:items.filter(item=>item.production_stage===value).length}))].map(choice=><button key={choice.value} type="button" aria-pressed={stageFilter===choice.value} onClick={()=>{setStageFilter(choice.value);setPage(1);}} className={`flex min-h-12 flex-1 items-center justify-center gap-2 bg-[var(--bg-surface)] px-3 py-2 text-[12px] hover:bg-[var(--bg-hover)] ${stageFilter===choice.value?'shadow-[inset_0_-2px_0_var(--info)] text-[var(--text-primary)]':'text-[var(--text-secondary)]'}`}><span className="truncate">{choice.label}</span><strong className="tabular-nums text-[14px]">{choice.count}</strong></button>)}
    </nav>}
    {items.some(item => item.state_source === 'local_workspace_episode_state_file') && <p role="status" className="os-source-warning mx-4 my-2 px-3 py-1.5 text-[12px]">本机真实作品状态文件：只读磁盘记录，不是实时调度、Worker 心跳或 MySQL 权威状态。</p>}
    {items.some(item => item.state_source === 'local_episode_directory_unverified') && <p role="status" className="os-source-warning mx-4 my-2 px-3 py-1.5 text-[12px]">部分新作品只有目录证据：可发现作品，但 MySQL 权威阶段尚未取得，只显示 UNKNOWN，不能用来判断生产已停或已完成。</p>}
    {items.some(item => item.state_source === 'mysql_episode_state_read_only') && <p role="status" className="mx-4 my-2 text-[12px] text-[var(--text-secondary)]">MySQL 专用 SELECT-only 账号提供权威阶段；当前节点来自只读日志，Writer 来自心跳快照，不等同于 Provider 活动证明。</p>}
    {items.some(item => item.state_source === 'isolated-test') && <p role="status" className="px-4 py-2 text-[var(--warning)] font-medium">本机隔离测试数据：仅用于验证 HTTP 接口与界面，不代表任何正式作品阶段。</p>}
    {dataState === 'loading' ? <p role="status" className="px-4 py-5 text-[var(--text-secondary)]">正在读取平台阶段…</p>
    : dataState === 'offline' ? <p role="alert" className="px-4 py-5 text-[var(--warning)]">无法连接 Platform API；本区不展示历史数据冒充在线状态。</p>
    : <>
      {dataState === 'partial' && <p role="alert" className="px-4 pt-3 text-[var(--warning)]">接口报告部分失败，阶段列表可能不完整。</p>}
      <div className="os-console-filterbar flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-3 py-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2"><Input.Search aria-label="搜索生产阶段作品" value={keyword} onChange={event=>{setKeyword(event.target.value);setPage(1);}} allowClear placeholder="搜索作品名称 / 编号" className="!w-[300px] max-w-full"/><Select aria-label="筛选权威阶段" className="!w-[176px]" value={stageFilter} onChange={value=>{setStageFilter(value);setPage(1);}} options={[{value:'ALL',label:'全部阶段'},...stageChoices.map(value=>({value,label:stageLabel(value)}))]}/>{(keyword||stageFilter!=='ALL')&&<Button size="small" onClick={()=>{setKeyword('');setStageFilter('ALL');setPage(1);}}>重置</Button>}</div>
        <span className="text-[11px] text-[var(--text-tertiary)]">匹配 {filtered.length} / 已读 {coverage.loaded}{coverage.total!==null?` / ${coverage.total}`:''}{coverage.incomplete?' · 仅筛选已加载':''}{items.length>100?' · 多页时暂停轮询':''}</span>
      </div>
      {coverage.warning && <p role="status" className="px-4 pb-3 text-[11px] text-[var(--warning)]">{coverage.warning}</p>}
      <Table<RuntimeStatusSummary>
        size="small"
        rowKey={item=>item.episode_id||item.episode_ref||item.title||'unknown'}
        dataSource={filtered}
        className="storyos-authority-grid"
        scroll={{x:800}}
        onRow={item=>({onClick:()=>setSelected(item),className:'cursor-pointer'})}
        locale={{emptyText:'接口已响应，但没有可显示的阶段摘要'}}
        columns={[
          {title:'作品',key:'title',width:280,render:(_,item)=><div className="min-w-0"><span title={item.title||item.episode_ref||item.episode_id} className="block max-w-[560px] truncate text-[13px] font-semibold text-[var(--text-primary)]">{item.title||item.episode_ref||item.episode_id||'未知作品'}</span><span className="block max-w-[560px] truncate font-mono text-[10px] text-[var(--text-tertiary)]">{item.episode_ref||item.episode_id||'未提供作品标识'}</span></div>},
          {title:'生产阶段',dataIndex:'production_stage',key:'stage',width:140,render:(value:string)=><span className="inline-flex items-center gap-2 text-[12px] text-[var(--text-secondary)]"><span className="h-1.5 w-1.5 rounded-full bg-[var(--text-tertiary)]"/>{stageLabel(value||'NO_STATE')}</span>},
          {title:'Driver持锁报告',key:'writer',width:160,responsive:['lg'],render:(_,item)=><span className="text-[11px] text-[var(--text-secondary)]">{item.writer_owner_status==='FRESH_PRODUCER_LOCK_CLAIM'?'持锁心跳新鲜（自报）':'未核验'}</span>},
          {title:'数据来源',dataIndex:'state_source',key:'source',width:190,responsive:['lg'],render:(value:string)=><span title={value||'未提供'} className="text-[12px] text-[var(--text-tertiary)]">{value==='mysql_episode_state_read_only'?'MySQL 阶段 · 只读':value==='local_episode_directory_unverified'?'目录 · 待核验':value==='local_workspace_episode_state_file'?'本机文件 · 只读':value==='isolated-test'?'隔离测试':value||'未提供'}</span>},
          {title:'更新时间',key:'updated',width:144,responsive:['lg'],render:(_,item)=><span className="tabular-nums text-[11px] text-[var(--text-tertiary)]">{item.updated_at||item.observed_at?String(item.updated_at||item.observed_at).replace('T',' ').slice(0,16):'未知'}</span>},
          {title:'',key:'action',width:88,fixed:'right',align:'right',render:(_,item)=><Button type="link" aria-label={'查看权威阶段：'+(item.title||item.episode_ref||item.episode_id)} size="small" onClick={event=>{event.stopPropagation();setSelected(item);}}>详情</Button>}
        ]}
        pagination={{current:safePage,pageSize,total:filtered.length,showSizeChanger:true,pageSizeOptions:['12','20','50'],showTotal:n=>`本次匹配 ${n} 条`,onChange:(next,size)=>{setPage(next);setPageSize(size);}}}
      />
      {hasMore&&<div className="flex items-center justify-between border-t border-[var(--border-subtle)] px-4 py-3"><span className="text-[12px] text-[var(--text-tertiary)]">仍有服务端记录未加载</span><Button loading={loadingMore} onClick={onLoadMore}>从 Platform API 加载下一页</Button></div>}
    </>}
    {currentSelected && dataState !== 'offline' && <Drawer open title="阶段证据详情 · 只读" onClose={()=>setSelected(null)} width="min(850px, 100vw)" destroyOnClose className="storyos-authority-inspector"><section aria-label="生产监控阶段详情" className="space-y-4">
      <div className="min-w-0">
  <h3 className="text-[14px] font-semibold break-words">{currentSelected.title || currentSelected.episode_ref || currentSelected.episode_id}</h3>
  <p aria-label="本次生产判断" role="status" className="mt-2 text-[12px] font-medium text-[var(--text-primary)]">{detailIsCurrent && visibleDetail?.provider_call_observation?.provider_call_verified ? "已核验图片调用窗口 · 不代表整集持续运行" : "当前执行：尚未核验"}</p>
  <p className="mt-1 text-[11px] text-[var(--text-secondary)]">下一步：查看下方恢复安全诊断；正式操作须由已授权 Runtime 核对。</p>
</div>
      {(detailState === 'loading' || (detailState === 'available' && !detailIsCurrent)) && <p role="status" className="text-[var(--text-secondary)]">正在读取扩展详情，下方摘要已可查看…</p>}
      {detailState === 'unavailable' && <p role="alert" className="text-[var(--warning)]">扩展详情接口不可用，以下保留已读取的阶段证据。</p>}
      <dl className="space-y-0">
        {[
          ['生产阶段', stageLabel(currentSelected.production_stage || 'NO_STATE')],
          ['数据来源', currentSelected.state_source === 'mysql_episode_state_read_only' ? 'MySQL 阶段权威 · SELECT-only' : currentSelected.state_source === 'local_workspace_episode_state_file' ? '本机状态文件 · 只读' : text(currentSelected.state_source)],
          ['证据原始更新时间', text(currentSelected.updated_at || currentSelected.observed_at)],
          ...(detailIsCurrent ? [
            ['执行记录状态（不等于在线）', text(visibleDetail?.execution_status)],
            ['最近记录节点', text(visibleDetail?.current_action || visibleDetail?.next_step)],
            ['节点证据时间', text(visibleDetail?.last_event_at)],
            ['有 Attempt 的帧数（非成功张数）', text(visibleDetail?.image_attempted_frames_observed)],
            ['阻塞原因', text(visibleDetail?.blocking_reason)],
            ['需要人工', text(visibleDetail?.needs_user)],
            ['心跳健康', text(visibleDetail?.heartbeat?.health)],
            ['已接受帧', text(visibleDetail?.image_progress?.accepted_frames)],
            ['总目标帧', text(visibleDetail?.image_progress?.expected_frames)]
          ] : [])
        ].map(([key, value]) => <div key={key} className="grid grid-cols-[100px_minmax(0,1fr)] items-start gap-3 border-b border-[var(--border-subtle)] py-3"><dt className="text-[11px] text-[var(--text-tertiary)]">{key}</dt><dd className="break-words text-[12px] text-[var(--text-primary)]">{value}</dd></div>)}
      </dl>
      {detailIsCurrent && visibleDetail?.monitoring_scope === 'RECORDED_FILES_ONLY' && (
        <section aria-label="真实生产记录明细" className="space-y-4 border-t border-[var(--border-subtle)] pt-4">
          <p className="text-xs text-[var(--text-secondary)]">
            真实磁盘生产记录 · 每次打开重新读取。仅显示已落盘证据；未验证 Writer/Worker 在线状态，不开放重试。
          </p>
          <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--text-secondary)]">
            <span>队列历史：{visibleDetail.queue_summary?.recorded_items ?? '暂无'}</span>
            <span>账本批准记录：{visibleDetail.image_progress?.accepted_frames ?? '暂无'} / {visibleDetail.image_progress?.expected_frames ?? '未知目标'}</span>
            <span>保存时 Runner：{visibleDetail.runner_record?.recorded_status || '未记录'}（在线未确认）</span>
          </div>
          {visibleDetail.queue_summary && (
            <div className="flex flex-wrap gap-2 text-[11px] text-[var(--text-tertiary)]">
              {Object.entries(visibleDetail.queue_summary.status_counts).map(([code, count]) =>
                <span key={code} className="rounded border border-[var(--border-subtle)] px-2 py-1">{code}: {count}</span>
              )}
            </div>
          )}
          <div className="space-y-2">
            <h4 className="font-medium">逐帧制作记录（账本与队列）</h4>
            {visibleDetail.frame_records?.length ? (
              <Table
                size="small"
                rowKey="frame"
                dataSource={visibleDetail.frame_records}
                pagination={false}
                scroll={{x:640,y:340}}
                columns={[
                  {title:'帧',dataIndex:'frame',width:52,render:(n:number)=><span className="font-mono">{String(n).padStart(2,'0')}</span>},
                  {title:'账本状态',dataIndex:'ledger_status',width:110,render:(v:string|null)=>v||'未记录'},
                  {title:'队列记录',dataIndex:'queue_status',width:110,render:(v:string|null)=>v||'未记录'},
                  {title:'账本历史条目',dataIndex:'recorded_attempt_entries',width:100,render:(v:number|null)=>v??'未知'},
                  {title:'队列历史数',dataIndex:'queue_history_count',width:100},
                  {title:'错误代码',dataIndex:'last_error_code',width:150,render:(v:string|null)=><span className="break-all">{v||'未记录'}</span>}
                ]}
              />
            ):<p className="text-xs text-[var(--text-tertiary)]">当前没有可核验的逐帧队列或账本记录，不代表尚未生产。</p>}
            <p className="text-[11px] text-[var(--text-tertiary)]">队列可能包含已替换的旧任务；账本批准记录不等于文件仍存在或质量审核已经完成；账本历史条目数也不等于真实模型调用次数。</p>
          </div>
          <div className="space-y-2">
            <h4 className="font-medium">最近运行步骤</h4>
            {visibleDetail.checkpoint_steps?.length ? (
              <ul className="max-h-[190px] space-y-1 overflow-y-auto text-xs">
                {visibleDetail.checkpoint_steps.map((item,i)=><li key={item.step + '-' + i} className="flex justify-between gap-2 border-b border-[var(--border-subtle)] py-1">
                  <span className="min-w-0 truncate">{item.step} · {item.status}</span>
                  <span className="shrink-0 text-[var(--text-tertiary)]">尝试 {item.attempt??'未知'}</span>
                </li>)}
              </ul>
            ):<p className="text-xs text-[var(--text-tertiary)]">未发现步骤 Checkpoint。</p>}
          </div>
          <div className="space-y-2">
            <h4 className="font-medium">审核证据</h4>
            {visibleDetail.review_records && Object.keys(visibleDetail.review_records).length ? (
              <ul className="space-y-1 text-xs">
                {Object.entries(visibleDetail.review_records).map(([name,item])=><li key={name} className="flex justify-between gap-3 border-b border-[var(--border-subtle)] py-1">
                  <span>{({story_review:'故事审核',frame_review:'画面审核',release_review:'发布审核',visual_lock:'视觉锁定'} as Record<string,string>)[name]||name}</span>
                  <span className="text-[var(--text-secondary)]">{item.decision||item.recorded_status||(item.passed===null?'未记录':item.passed?'记录通过':'记录未通过')}</span>
                </li>)}
              </ul>
            ):<p className="text-xs text-[var(--text-tertiary)]">没有可读取的审核结果文件。</p>}
          </div>
          {Boolean(visibleDetail.source_errors?.length) && (
            <p role="alert" className="text-xs text-[var(--warning)]">有 {visibleDetail.source_errors?.length} 份生产证据读取失败，当前明细不完整。</p>
          )}
        </section>
      )}

      {detailIsCurrent && visibleDetail?.writer_owner_observation && (
        <section aria-label="Driver持锁心跳只读观测" className="space-y-2 border-t border-[var(--border-subtle)] pt-4">
          <h4 className="font-medium">Driver 持锁心跳</h4>
          {visibleDetail.writer_owner_observation.status === 'FRESH_PRODUCER_LOCK_CLAIM'
            ? <p role="status" className="text-xs text-[var(--text-secondary)]">
                原生产 Driver 报告近期持有单机 Writer 锁；进程身份和心跳均已核验。
                上次心跳约 {visibleDetail.writer_owner_observation.fresh_seconds ?? '未知'} 秒前。
              </p>
            : <p role="status" className="text-xs text-[var(--text-tertiary)]">
                尚无可核验的持锁 Driver 报告（{visibleDetail.writer_owner_observation.reason || 'UNKNOWN'}）。
                可能尚未制作、运行中的旧版 Driver 未生成新证据，或进程已结束。
              </p>}
          <p className="text-[11px] text-[var(--text-tertiary)]">
            仅展示已成功取得锁的 Driver 自报心跳；不检测或争抢生产 OS 锁。
            该观察不等于内核锁此刻仍持有，也不证明有生图 Provider 正在调用。
          </p>
        </section>
      )}

      {detailIsCurrent && visibleDetail?.provider_call_observation && (
        <section aria-label="当前Provider调用只读核验证据" className="space-y-2 border-t border-[var(--border-subtle)] pt-4">
          <h4 className="font-medium">当前图片生成调用 · 可信执行窗口</h4>
          {visibleDetail.provider_call_observation.provider_call_verified ? <>
            <p role="status" className="text-xs text-[var(--text-secondary)]">
              近期观测到原生 Gateway 已进入 Provider 调用，且 Driver 进程身份、执行周期与 MySQL Generation Attempt 派发记录一致。
              观测帧：{visibleDetail.provider_call_observation.verified_current_frames.map(n => '第 '+n+' 帧').join('、')}。
            </p>
            <Table size="small" pagination={false} rowKey={item=>item.frame+'-'+item.attempt_index}
              dataSource={visibleDetail.provider_call_observation.verified_current_image_attempts}
              columns={[
                {title:'调用帧',dataIndex:'frame',render:(v:number)=>'第 '+v+' 帧'},
                {title:'Attempt',dataIndex:'attempt_index'},
                {title:'进入调用以来',dataIndex:'provider_call_age_seconds',render:(v:number)=>v+' 秒'}
              ]}/>
            <p className="text-xs text-[var(--text-tertiary)]">
              该信息是有时效的执行窗口采样，不保证页面显示瞬间调用仍在持续。
            </p>
          </> : (
            <p role="status" className="text-xs text-[var(--text-tertiary)]">
              当前没有能同时通过 Driver 执行周期、Provider 进程调用窗口和 MySQL 派发记录核验的生图任务
              （{visibleDetail.provider_call_observation.reason || 'UNKNOWN'}）。
            </p>
          )}
          <p className="text-[11px] text-[var(--text-tertiary)]">
            Task ID 和是否卡死仍未核验；不以数据库旧 RUNNING、DISPATCH_COMMITTED 或进程 PID 单独推断在线。
            不检测、争抢 OS 锁，也不触发重试。
          </p>
        </section>
      )}

      {detailIsCurrent && visibleDetail?.mysql_monitor && (() => {
        const chain=recordedTraceCoverage(visibleDetail);
        return <section aria-label="执行证据链覆盖情况" className="space-y-2 border-t border-[var(--border-subtle)] pt-4">
          <h4 className="text-[13px] font-semibold">执行证据链 · 当前可追溯程度</h4>
          {!chain.verified ? <p role="status" className="text-[12px] text-[var(--text-tertiary)]">MySQL 只读身份或权限未核验，无法列出可信的任务与尝试记录。</p> : <>
            <div className="flex flex-wrap gap-x-5 gap-y-2 text-[12px] text-[var(--text-secondary)]">
              <span>Task 记录 {chain.taskCount}</span>
              <span>Production Attempt 样本 {chain.productionAttemptCount}</span>
              <span>Generation Attempt 样本 {chain.generationAttemptCount}</span>
              {chain.unresolvedCount>0&&<span className="text-[var(--warning)]">OUTCOME_UNKNOWN 样本 {chain.unresolvedCount}</span>}
            </div>
            <p role="status" className="text-[12px] text-[var(--text-tertiary)]">
              三类记录当前仅按作品分别查询。尚无经权威外键核验的 Task → Generation Attempt → Trace → 图片关联，
              不可据此定位一次模型请求的全部执行步骤，也不能将查询样本数量当作全量数据。
            </p>
          </>}
        </section>;
      })()}

      {detailIsCurrent && visibleDetail?.recorded_production_progress && (
        <section aria-label="真实制作进度只读关联" className="space-y-3 border-t border-[var(--border-subtle)] pt-4">
          <h4 className="font-medium">制作进度 · Task / 逐帧记录关联</h4>
          {!visibleDetail.recorded_production_progress.available ? (
            <p role="status" className="text-xs text-[var(--text-tertiary)]">
              MySQL 身份或只读授权未验证，无法关联任务与制作帧；不将记录缺失解释为没有生产。
            </p>
          ) : <>
            <p className="text-xs text-[var(--text-secondary)]">
              以下是这部作品数据库中保存的最近记录，不是当前模型执行快照。
              持锁 Driver 报告：{visibleDetail.recorded_production_progress.writer_producer_claim_fresh ? '新鲜（仅进程自报）' : '未核验'}。
            </p>
            <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-[var(--text-secondary)]">
              <span>最近保存的 Task：{visibleDetail.recorded_production_progress.recent_task
                ? (visibleDetail.recorded_production_progress.recent_task.task_type || '类型未知') + ' / ' + (visibleDetail.recorded_production_progress.recent_task.recorded_status || '状态未知')
                : '无匹配记录'}</span>
              <span>Task 距上次更新：{readOnlyAge(visibleDetail.recorded_production_progress.recent_task?.age_seconds)}</span>
              <span>最近记录的生图帧：{visibleDetail.recorded_production_progress.recent_frame
                ? '第 ' + visibleDetail.recorded_production_progress.recent_frame.frame + ' 帧'
                : '无匹配记录'}</span>
              <span>帧记录距今：{readOnlyAge(visibleDetail.recorded_production_progress.recent_frame?.age_seconds)}</span>
            </div>
            <p role="status" className="text-xs text-[var(--text-secondary)]">
              当前执行 Task / 正在生成帧 / Provider 调用：<strong>均未核验</strong>；
              是否卡住：<strong>无法判定</strong>，不能仅凭历史 CURRENT、RUNNING 或较早更新时间下结论。
            </p>
            {visibleDetail.recorded_production_progress.unresolved_generation_count > 0 && (
              <p role="status" className="text-xs text-[var(--warning)]">
                最近的 Generation Attempt 样本内有 {visibleDetail.recorded_production_progress.unresolved_generation_count} 条 OUTCOME_UNKNOWN；
                仅提示人工核对，不自动补发或重试。
              </p>
            )}
            <h5 className="text-xs font-medium">各帧最近一条 Production Attempt</h5>
            <Table size="small" pagination={false} rowKey={item=>item.frame}
              scroll={{x:620,y:220}}
              dataSource={visibleDetail.recorded_production_progress.frame_attempts}
              locale={{emptyText:'该作品目前没有可匹配的逐帧 Attempt'}}
              columns={[
                {title:'帧',dataIndex:'frame',width:90,render:(v:number)=>'第 '+v+' 帧'},
                {title:'最近序号',dataIndex:'last_attempt_no',width:80,render:(v:number|null)=>v??'—'},
                {title:'保存的结果',dataIndex:'last_recorded_status',render:(v:string|null)=>v||'未知'},
                {title:'历史耗时',dataIndex:'last_recorded_duration_ms',width:98,render:(v:number|null)=>v===null?'未知':(v/1000).toFixed(1)+' 秒'},
                {title:'距记录时间',dataIndex:'age_seconds',width:112,render:(v:number|null)=>readOnlyAge(v)}
              ]}/>
            <p className="text-[11px] text-[var(--text-tertiary)]">
              MySQL 每类最多读取最近 60 条；本表只展示样本中涉及的帧，可能遗漏更早记录。
              历史耗时是已记录 Attempt 的用时，不是当前任务已运行多久。
            </p>
          </>}
        </section>
      )}

      {detailIsCurrent && visibleDetail?.mysql_monitor && (
        <section aria-label="MySQL真实生产任务只读监控" className="space-y-3 border-t border-[var(--border-subtle)] pt-4">
          <h4 className="font-medium">MySQL Task / Attempt 只读证据</h4>
          {!visibleDetail.mysql_monitor.available ? (
            <p role="status" className="text-xs text-[var(--text-tertiary)]">
              专用 MySQL 只读连接尚未证实：{visibleDetail.mysql_monitor.reason === 'READ_ONLY_MYSQL_NOT_ENABLED'
                ? '未授权开启'
                : visibleDetail.mysql_monitor.reason === 'DEDICATED_SELECT_ONLY_ACCOUNT_NOT_CONFIGURED'
                  ? '未配置专用 SELECT 账号'
                  : visibleDetail.mysql_monitor.reason === 'EPISODE_IDENTITY_MISMATCH'
                    ? '作品身份未匹配，已禁止查询'
                    : visibleDetail.mysql_monitor.reason === 'SELECT_ONLY_GRANTS_NOT_VERIFIED'
                      ? '账号最小权限未核实'
                      : '数据源不可用或身份未核验'}。以下不假设数据库里没有任务。
            </p>
          ) : <>
            <p className="text-xs text-[var(--text-secondary)]">
              数据库身份与只读事务已核验 · 每类最多 {visibleDetail.mysql_monitor.records_limit_per_table} 条记录 · 不保证完整历史。
              <span className="ml-2 text-[var(--warning)]">数据库显示 RUNNING 也不是 Worker 在线证明。</span>
            </p>
            <div className="flex flex-wrap gap-4 text-xs text-[var(--text-secondary)]">
              <span>Task 记录 {visibleDetail.mysql_monitor.task_records.length}</span>
              <span>Production Attempt {visibleDetail.mysql_monitor.production_attempt_records.length}</span>
              <span>Generation Attempt {visibleDetail.mysql_monitor.generation_attempt_records.length}</span>
            </div>
            <h5 className="text-xs font-medium">最近 Task</h5>
            <Table size="small" pagination={false} rowKey={(_,i)=>String(i)} scroll={{x:550,y:225}}
              dataSource={visibleDetail.mysql_monitor.task_records}
              locale={{emptyText:'已授权查询，但当前作品无匹配 Task 记录'}}
              columns={[
                {title:'任务类型',dataIndex:'task_type',render:(v:string|null)=>v||'未知'},
                {title:'帧',dataIndex:'frame',width:52,render:(v:number|null)=>v??'—'},
                {title:'保存的状态',dataIndex:'status',render:(v:string|null)=>v||'未知'},
                {title:'尝试编号',dataIndex:'attempt_no',width:90,render:(v:number|null)=>v??'—'}
              ]}/>
            <h5 className="text-xs font-medium">逐帧生产 Attempt</h5>
            <Table size="small" pagination={false} rowKey={(_,i)=>String(i)} scroll={{x:620,y:225}}
              dataSource={visibleDetail.mysql_monitor.production_attempt_records}
              locale={{emptyText:'没有匹配的逐帧生产 Attempt 记录'}}
              columns={[
                {title:'帧',dataIndex:'frame',width:52,render:(v:number|null)=>v??'—'},
                {title:'序号',dataIndex:'attempt_no',width:62,render:(v:number|null)=>v??'—'},
                {title:'类型',dataIndex:'kind',render:(v:string|null)=>v||'—'},
                {title:'结果',dataIndex:'status',render:(v:string|null)=>v||'—'},
                {title:'错误码',dataIndex:'error_code',render:(v:string|null)=>v||'未记录'},
                {title:'耗时(ms)',dataIndex:'elapsed_ms',width:98,render:(v:number|null)=>v??'—'}
              ]}/>
            <h5 className="text-xs font-medium">真实调度 Generation Attempt</h5>
            <Table size="small" pagination={false} rowKey={(_,i)=>String(i)} scroll={{x:590,y:225}}
              dataSource={visibleDetail.mysql_monitor.generation_attempt_records}
              locale={{emptyText:'没有匹配的真实 Generation Attempt 记录'}}
              columns={[
                {title:'帧',dataIndex:'frame',width:52,render:(v:number|null)=>v??'—'},
                {title:'序号',dataIndex:'attempt_index',width:68,render:(v:number|null)=>v??'—'},
                {title:'记录状态',dataIndex:'status',render:(v:string|null)=>v||'—'},
                {title:'失败类别',dataIndex:'failure_class',render:(v:string|null)=>v||'未记录'}
              ]}/>
          </>}
          <p className="text-[11px] text-[var(--text-tertiary)]">
            Writer 执行权：未验证。不会通过探测或占用生产 OS 文件锁来判断 Writer 是否在线。
          </p>
        </section>
      )}

      <RuntimeRecoveryInsight episodeRef={ref || ""} detail={visibleDetail} source={currentSelected.state_source} detailLoaded={detailIsCurrent} />
    </section></Drawer>}
  </section>;
};
