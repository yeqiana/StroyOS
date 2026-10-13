import React, { useEffect, useState } from 'react';
import {Button,Drawer,Input,Select,Table} from 'antd';
import { platformApi, RuntimeStatusDetail, RuntimeStatusSummary, stageLabel } from '../../api/platformApi';
import type { RuntimeCoverage } from '../../api/runtimeCoverage';
import { RuntimeRecoveryInsight } from './RuntimeRecoveryInsight';
import { runtimeDetailMatchesEpisode, selectCurrentRuntimeDetail } from '../../api/runtimeRecoveryAssessment';

interface Props { items: RuntimeStatusSummary[]; coverage: RuntimeCoverage; hasMore: boolean; loadingMore: boolean; onLoadMore: () => void; dataState: 'loading' | 'ok' | 'partial' | 'offline'; lastSync: string | null; }
export const RuntimeAuthorityPanel: React.FC<Props> = ({ items, coverage, hasMore, loadingMore, onLoadMore, dataState, lastSync }) => {
  const [selected, setSelected] = useState<RuntimeStatusSummary | null>(null);
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
      <div className="flex flex-wrap items-baseline gap-3"><h2 className="os-section-heading">{items.some(item => item.state_source === 'local_workspace_episode_state_file') ? '本机作品状态文件记录' : '平台阶段证据'}</h2><span className="text-[11px] text-[var(--text-tertiary)]">只读 · 非实时 Runtime</span></div>
      <span className="shrink-0 text-[11px] text-[var(--text-tertiary)]">{lastSync ? '读取于 ' + lastSync : '未获取成功'}</span>
    </div>
    {items.length>0&&<nav aria-label="生产阶段快速筛选" className="flex min-w-0 flex-wrap items-stretch gap-px border-b border-[var(--border-subtle)] bg-[var(--border-subtle)]">
      {[{value:'ALL',label:'已载入',count:items.length},...stageChoices.map(value=>({value,label:stageLabel(value),count:items.filter(item=>item.production_stage===value).length}))].map(choice=><button key={choice.value} type="button" aria-pressed={stageFilter===choice.value} onClick={()=>{setStageFilter(choice.value);setPage(1);}} className={`flex min-h-12 flex-1 items-center justify-center gap-2 bg-[var(--bg-surface)] px-3 py-2 text-[12px] hover:bg-[var(--bg-hover)] ${stageFilter===choice.value?'shadow-[inset_0_-2px_0_var(--info)] text-[var(--text-primary)]':'text-[var(--text-secondary)]'}`}><span className="truncate">{choice.label}</span><strong className="tabular-nums text-[14px]">{choice.count}</strong></button>)}
    </nav>}
    {items.some(item => item.state_source === 'local_workspace_episode_state_file') && <p role="status" className="os-source-warning mx-4 my-2 px-3 py-1.5 text-[12px]">本机真实作品状态文件：只读磁盘记录，不是实时调度、Worker 心跳或 MySQL 权威状态。</p>}
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
        scroll={{x:820}}
        onRow={item=>({onClick:()=>setSelected(item),className:'cursor-pointer'})}
        locale={{emptyText:'接口已响应，但没有可显示的阶段摘要'}}
        columns={[
          {title:'作品',key:'title',render:(_,item)=><div className="min-w-0"><span title={item.title||item.episode_ref||item.episode_id} className="block max-w-[560px] truncate text-[13px] font-semibold text-[var(--text-primary)]">{item.title||item.episode_ref||item.episode_id||'未知作品'}</span><span className="block max-w-[560px] truncate font-mono text-[10px] text-[var(--text-tertiary)]">{item.episode_ref||item.episode_id||'未提供作品标识'}</span></div>},
          {title:'生产阶段',dataIndex:'production_stage',key:'stage',width:160,render:(value:string)=><span className="inline-flex items-center gap-2 text-[12px] text-[var(--text-secondary)]"><span className="h-1.5 w-1.5 rounded-full bg-[var(--text-tertiary)]"/>{stageLabel(value||'NO_STATE')}</span>},
          {title:'数据来源',dataIndex:'state_source',key:'source',width:190,render:(value:string)=><span title={value||'未提供'} className="text-[12px] text-[var(--text-tertiary)]">{value==='local_workspace_episode_state_file'?'本机文件 · 只读':value==='isolated-test'?'隔离测试':value||'未提供'}</span>},
          {title:'更新时间',key:'updated',width:144,render:(_,item)=><span className="tabular-nums text-[11px] text-[var(--text-tertiary)]">{item.updated_at||item.observed_at?String(item.updated_at||item.observed_at).replace('T',' ').slice(0,16):'未知'}</span>},
          {title:'',key:'action',width:90,align:'right',render:(_,item)=><Button type="link" aria-label={'查看权威阶段：'+(item.title||item.episode_ref||item.episode_id)} size="small" onClick={event=>{event.stopPropagation();setSelected(item);}}>详情</Button>}
        ]}
        pagination={{current:safePage,pageSize,total:filtered.length,showSizeChanger:true,pageSizeOptions:['12','20','50'],showTotal:n=>`本次匹配 ${n} 条`,onChange:(next,size)=>{setPage(next);setPageSize(size);}}}
      />
      {hasMore&&<div className="flex items-center justify-between border-t border-[var(--border-subtle)] px-4 py-3"><span className="text-[12px] text-[var(--text-tertiary)]">仍有服务端记录未加载</span><Button loading={loadingMore} onClick={onLoadMore}>从 Platform API 加载下一页</Button></div>}
    </>}
    {selected && <Drawer open title="阶段证据详情 · 只读" onClose={()=>setSelected(null)} width="min(850px, 100vw)" destroyOnClose className="storyos-authority-inspector"><section aria-label="生产监控阶段详情" className="space-y-4">
      <div className="min-w-0"><h3 className="text-[14px] font-semibold break-words">{selected.title || selected.episode_ref || selected.episode_id}</h3><p className="mt-1 text-[11px] text-[var(--text-tertiary)]">仅展示当前只读证据 · 未知执行状态不推断</p></div>
      {(detailState === 'loading' || (detailState === 'available' && !detailIsCurrent)) && <p role="status" className="text-[var(--text-secondary)]">正在读取扩展详情，下方摘要已可查看…</p>}
      {detailState === 'unavailable' && <p role="alert" className="text-[var(--warning)]">扩展详情接口不可用，以下保留已读取的阶段证据。</p>}
      <dl className="space-y-0">
        {[
          ['生产阶段', stageLabel(selected.production_stage || 'NO_STATE')],
          ['数据来源', selected.state_source === 'local_workspace_episode_state_file' ? '本机状态文件 · 只读' : text(selected.state_source)],
          ['更新时间', text(selected.updated_at || selected.observed_at)],
          ...(detailIsCurrent ? [
            ['执行状态', text(visibleDetail?.execution_status)],
            ['当前动作', text(visibleDetail?.current_action || visibleDetail?.next_step)],
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

      <RuntimeRecoveryInsight episodeRef={ref || ""} detail={visibleDetail} source={selected.state_source} detailLoaded={detailIsCurrent} />
    </section></Drawer>}
  </section>;
};
