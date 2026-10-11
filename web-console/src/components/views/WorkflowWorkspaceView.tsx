import React, { useEffect, useRef, useState } from 'react';
import {Button, Input, Select, Steps, Table} from 'antd';
import { AlertCircle, RefreshCw, Search } from 'lucide-react';
import { platformApi, RuntimeStatusSummary, stageLabel } from '../../api/platformApi';
import { WorkflowDetailPanel } from './WorkflowDetailPanel';

const readableDate=(value?:string)=>{if(!value)return '未知';const date=new Date(value);return Number.isNaN(date.valueOf())?value:new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(date);};
const STAGE_ORDER = ['IDEA_LOCKED','STORYBOARD_LOCKED','VISUAL_CALIBRATED','PRODUCTION_PASSED','PUBLISH_READY','PUBLISHED','DATA_REVIEWED'];
export const WorkflowWorkspaceView: React.FC = () => {
  const [items,setItems] = useState<RuntimeStatusSummary[]>([]);
  const [loading,setLoading] = useState(true);
  const [error,setError] = useState<string | null>(null);
  const [reload,setReload] = useState(0);
  const [hasMore,setHasMore] = useState(false);
  const [loadingMore,setLoadingMore] = useState(false);
  const [total,setTotal] = useState<number | null>(null);
  const [filter,setFilter] = useState('ALL');
  const [keyword,setKeyword] = useState('');
  const [page,setPage]=useState(1);
  const [pageSize,setPageSize]=useState(20);
  const [selected,setSelected] = useState<RuntimeStatusSummary | null>(null);
  const generation = useRef(0);
  const pagingInFlight = useRef(false);
  const nextOffset = useRef(0);
  useEffect(() => {
    let active=true;
    const requestId = ++generation.current;
    pagingInFlight.current = false;
    nextOffset.current = 0;
    setLoading(true);
    platformApi.runtimeStatuses(100,0).then(data => {
      if(!active || requestId !== generation.current)return;
      setItems(data.items ?? []);
      nextOffset.current = (data.items ?? []).length;
      setHasMore(Boolean(data.has_more));
      setTotal(typeof data.total === 'number' ? data.total : null);
      setError(data.errors?.length ? '部分状态数据读取失败，以下仅展示成功返回的阶段投影。' : null);
    }).catch(() => {
      if(!active || requestId !== generation.current)return;
      setItems([]);
      setHasMore(false);
      setTotal(null);
      setError('无法连接 Platform API，暂不能读取生产阶段。');
    }).finally(() => {if(active && requestId === generation.current)setLoading(false)});
    return () => {active=false;generation.current += 1;pagingInFlight.current=false};
  },[reload]);
  const filtered=items.filter(x => {
    if (filter !== 'ALL' && x.production_stage !== filter) return false;
    const search = keyword.trim().toLocaleLowerCase();
    return !search || [x.title,x.episode_ref,x.episode_id].some(value=>String(value||'').toLocaleLowerCase().includes(search));
  });
  const loadNext = async () => {
    if (!hasMore || pagingInFlight.current || loading) return;
    const requestId = generation.current;
    const offset = nextOffset.current;
    pagingInFlight.current = true;
    setLoadingMore(true);
    try {
      const data = await platformApi.runtimeStatuses(100, offset);
      if (requestId !== generation.current) return;
      const page = Array.isArray(data.items) ? data.items : [];
      nextOffset.current = offset + page.length;
      setItems(current => {
        // 服务端数据可能跨页重复；按明确身份去重，不影响后续 offset 计算。
        const ids = new Set(current.map(x => x.episode_id || x.episode_ref).filter(Boolean));
        return [...current, ...page.filter(x => {
          const id = x.episode_id || x.episode_ref;
          if (!id || ids.has(id)) return false;
          ids.add(id);
          return true;
        })];
      });
      setHasMore(Boolean(data.has_more) && page.length > 0);
      if (typeof data.total === 'number') setTotal(data.total);
      if (data.errors?.length) setError('后续分页返回部分错误，列表可能不完整。');
    } catch {
      if (requestId === generation.current) setError('加载更多阶段记录失败，已保留此前成功读取的列表。可重试加载。');
    } finally {
      if (requestId === generation.current) {
        pagingInFlight.current = false;
        setLoadingMore(false);
      }
    }
  };
  return <div id="storyos-workflow-workspace" className="flex w-full min-w-0 flex-col gap-3 pb-5 text-[var(--text-primary)]">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-3">
      <div><h1 className="os-page-heading">生产流程</h1><p className="mt-1 text-[12px] text-[var(--text-secondary)]">七阶段进度分布与作品记录 · 只读阶段投影，不代表实际执行状态</p></div>
      <Button onClick={()=>setReload(v=>v+1)} disabled={loading} icon={<RefreshCw size={15}/>}>刷新</Button>
    </header>
    <nav aria-label="工作流阶段快速筛选" className="order-1 min-w-0 overflow-x-auto border-y border-[var(--border-subtle)]">
      <div className="flex min-w-[830px] items-stretch gap-px bg-[var(--border-subtle)]">
        {[{value:'ALL',label:'全部作品'},...STAGE_ORDER.map(value=>({value,label:stageLabel(value)}))].map(choice=>{
          const count=choice.value==='ALL'?items.length:items.filter(item=>item.production_stage===choice.value).length;
          return <button key={choice.value} type="button" aria-pressed={filter===choice.value} onClick={()=>{setFilter(choice.value);setPage(1);}} className={`flex min-h-[58px] flex-1 flex-col items-start justify-center gap-1 bg-[var(--bg-surface)] px-3 text-left hover:bg-[var(--bg-hover)] ${filter===choice.value?'shadow-[inset_0_-2px_0_var(--info)]':'text-[var(--text-secondary)]'}`}><span className="truncate text-[11px]">{choice.label}</span><span className="text-[17px] font-semibold tabular-nums text-[var(--text-primary)]">{count}</span></button>;
        })}
      </div>
    </nav>
    <details className="order-3 group border-t border-[var(--border-subtle)] pt-3" aria-label="七阶段流程">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 py-1 text-[13px] font-semibold text-[var(--text-primary)]">
        <span>标准七阶段 <span className="ml-2 text-[12px] font-normal text-[var(--text-tertiary)]">参考流程 · 非可点击执行步骤</span></span>
        <span className="text-[12px] font-normal text-[var(--info)] group-open:hidden">展开流程</span><span className="hidden text-[12px] font-normal text-[var(--info)] group-open:inline">收起流程</span>
      </summary>
      <div className="mt-3 overflow-x-auto"><div className="min-w-[890px] py-1.5"><Steps size="small" current={-1} responsive={false} items={STAGE_ORDER.map(stage=>({title:stageLabel(stage),status:'wait' as const}))}/></div></div>
      <p className="mt-2 text-[12px] text-[var(--text-secondary)]">仅表示阶段定义，不代表已有运行记录通过门禁。</p>
    </details>
    <section className="order-2 min-w-0 space-y-2" aria-label="工作流主数据列表">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-2"><div className="flex flex-wrap items-baseline gap-3"><h2 className="os-section-heading">作品阶段清单</h2><p className="text-[11px] text-[var(--text-tertiary)]">已载入 {items.length}{total!==null?' / '+total:''} 条 · 当前匹配 {filtered.length} 条{hasMore?' · 筛选只针对已读取数据':''}</p></div>
      <div className="os-console-filterbar flex flex-wrap items-center gap-2"><Input aria-label="搜索已载入作品" placeholder="搜索作品名称 / 标识" value={keyword} onChange={e=>{setKeyword(e.target.value);setPage(1);}} allowClear prefix={<Search size={14}/>} className="!w-[230px] max-w-full"/><Select aria-label="筛选阶段" value={filter} onChange={v=>{setFilter(v);setPage(1);}} className="w-[170px] shrink-0" options={[{value:'ALL',label:'全部阶段'},...STAGE_ORDER.map(value=>({value,label:stageLabel(value)}))]}/>{(keyword||filter!=='ALL')&&<Button size="small" aria-label="清除工作流筛选" onClick={()=>{setKeyword('');setFilter('ALL');setPage(1);}}>重置筛选</Button>}</div>
      </div>
      {error&&<p role="alert" className="flex items-center gap-2 border-l-2 border-[var(--warning)] py-2 pl-3 text-[12px] text-[var(--warning)]"><AlertCircle size={15}/>{error}</p>}
      <Table<RuntimeStatusSummary> size="small" rowKey={x=>x.episode_id||x.episode_ref||x.title||'unknown'}
        loading={loading} dataSource={filtered} scroll={{x:780}}
        onRow={record=>({onClick:()=>setSelected(record),className:'cursor-pointer'})}
        locale={{emptyText:'暂无可展示的阶段记录'}}
        columns={[
          {title:'作品',key:'title',sorter:(a,b)=>String(a.title||a.episode_ref||'').localeCompare(String(b.title||b.episode_ref||''),'zh-CN'),render:(_,x)=><div className="min-w-0"><div title={x.episode_ref||x.episode_id} className="truncate text-[13px] font-semibold text-[var(--text-primary)]">{x.title||x.episode_ref||x.episode_id||'未命名作品'}</div><span className="block truncate font-mono text-[10px] text-[var(--text-tertiary)]">{x.episode_ref||x.episode_id||'未提供作品标识'}</span></div>},
          {title:'生产阶段',dataIndex:'production_stage',key:'stage',width:150,render:(v:string)=><span className="inline-flex items-center gap-2 text-[13px] text-[var(--text-secondary)]"><span className="h-1.5 w-1.5 rounded-full bg-[var(--text-tertiary)]"/>{stageLabel(v||'NO_STATE')}</span>},
          {title:'数据来源',dataIndex:'state_source',key:'source',width:215,ellipsis:true,render:(v:string)=><span title={v||'未提供'} className="text-[12px] text-[var(--text-secondary)]">{v==='local_workspace_episode_state_file'?'本机状态文件 · 只读':v||'未提供'}</span>},
          {title:'更新时间',key:'updated',width:170,sorter:(a,b)=>String(a.updated_at||a.observed_at||'').localeCompare(String(b.updated_at||b.observed_at||'')),render:(_,x)=><span title={x.updated_at||x.observed_at||''} className="text-[12px] tabular-nums text-[var(--text-secondary)]">{readableDate(x.updated_at||x.observed_at)}</span>},
          {title:'操作',key:'action',width:90,render:(_,x)=><Button type="link" size="small" onClick={event=>{event.stopPropagation();setSelected(x);}} aria-label={'查看阶段详情：'+(x.title||x.episode_ref||x.episode_id)}>详情</Button>}
        ]}
        pagination={{current:Math.min(page,Math.max(1,Math.ceil(filtered.length/pageSize))),pageSize,total:filtered.length,showSizeChanger:true,pageSizeOptions:['10','20','30','50'],showTotal:(n,range)=>`${range[0]}–${range[1]} / 已载入 ${n}`,onChange:(v,s)=>{setPage(v);setPageSize(s);}}}/>
      {hasMore && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border-subtle)] pt-3 text-[12px] text-[var(--text-secondary)]"><span>继续加载的是下一批服务端记录，不等于翻页。</span><Button loading={loadingMore} disabled={loading||loadingMore} onClick={loadNext}>加载更多</Button></div>}
    </section>
    {selected&&<WorkflowDetailPanel selected={selected} onClose={()=>setSelected(null)}/>}
  </div>;
};
