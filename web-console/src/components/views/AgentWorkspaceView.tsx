import React, {useEffect,useState} from 'react';
import {Alert,Button,Drawer,Empty,Input,Select,Table} from 'antd';
import type {TableColumnsType} from 'antd';
import {RefreshCw,ShieldCheck} from 'lucide-react';
import {platformApi} from '../../api/platformApi';
import {MemorySearchPanel} from './MemorySearchPanel';
type AgentSummary={id:string;name:string;description:string;status:string;tools:string[]};
const asText=(v:unknown):string=>typeof v==='string'?v:'';
const asAgent=(value:unknown):AgentSummary|null=>{
 if(!value||typeof value!=='object')return null;
 const x=value as Record<string,unknown>;const id=asText(x.agent_id)||asText(x.id);
 const name=asText(x.name)||id;if(!name)return null;
 return {id:id||name,name,description:asText(x.description),status:asText(x.status),tools:Array.isArray(x.tools)?x.tools.filter((v):v is string=>typeof v==='string'):[]};
};
export const AgentWorkspaceView:React.FC=()=>{
 const [agents,setAgents]=useState<AgentSummary[]>([]);
 const [state,setState]=useState<'loading'|'available'|'error'>('loading');
 const [message,setMessage]=useState('');
 const [reload,setReload]=useState(0);
 const [keyword,setKeyword]=useState('');
 const [statusFilter,setStatusFilter]=useState('ALL');
 const [selected,setSelected]=useState<AgentSummary|null>(null);
 useEffect(()=>{let alive=true;setState('loading');platformApi.agents().then(response=>{if(!alive)return;setAgents((response.items??[]).map(asAgent).filter((a):a is AgentSummary=>a!==null));setMessage('');setState('available');}).catch(()=>{if(!alive)return;setAgents([]);setMessage('Agent Registry 列表 API 尚不可用，不能据此推断在线 Agent 或启停状态。');setState('error');});return()=>{alive=false};},[reload]);
 const statusChoices=[...new Set(agents.map(agent=>agent.status).filter(Boolean))];
 const filtered=agents.filter(agent=>(statusFilter==='ALL'||agent.status===statusFilter)&&[agent.name,agent.id,agent.description,...agent.tools].join(' ').toLocaleLowerCase().includes(keyword.trim().toLocaleLowerCase()));
 const columns:TableColumnsType<AgentSummary>=[
  {title:'Agent',dataIndex:'name',key:'name',render:(v:string,x)=><div className="min-w-0"><div className="truncate text-[14px] font-semibold">{v}</div><div className="mt-1 truncate font-mono text-[11px] text-[var(--text-tertiary)]">{x.id}</div></div>},
  {title:'描述',dataIndex:'description',key:'description',ellipsis:true,render:(v:string)=><span className="text-[13px] text-[var(--text-secondary)]">{v||'暂无描述'}</span>},
  {title:'已披露工具',dataIndex:'tools',key:'tools',width:235,ellipsis:true,render:(v:string[])=><span className="text-[12px] text-[var(--text-secondary)]">{v.length?v.join('、'):'未披露'}</span>},
  {title:'状态',dataIndex:'status',key:'status',width:120,render:(v:string)=><span className="text-[12px]">{v||'未提供'}</span>}
 ];
 return <div id="storyos-agent-workspace" className="w-full min-w-0 space-y-3 pb-6 text-[var(--text-primary)]">
  <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-3"><div><h1 className="os-page-heading">Agents</h1><p className="mt-1 text-[12px] text-[var(--text-secondary)]">Agent Registry 与 Memory 检索 · 仅展示可验证的已注册能力</p></div><Button icon={<RefreshCw size={15}/>} disabled={state==='loading'} onClick={()=>setReload(v=>v+1)}>刷新 Registry</Button></header>
  <section aria-label="Agent Registry 概况" className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-[var(--border-subtle)] py-2 text-[12px]">
    <div className="flex items-baseline gap-2"><span className="text-[var(--text-tertiary)]">Registry 已返回</span><strong className="text-[17px] tabular-nums">{state==='available'?agents.length:'—'}</strong></div>
    <div className="flex items-baseline gap-2"><span className="text-[var(--text-tertiary)]">已披露工具关联</span><strong className="text-[17px] tabular-nums">{state==='available'?agents.reduce((n,a)=>n+a.tools.length,0):'—'}</strong></div>
    <span className={`ml-auto text-[11px] ${state==='error'?'text-[var(--warning)]':'text-[var(--text-secondary)]'}`}>{state==='loading'?'正在读取 Registry…':state==='error'?'API 暂不可读取 · 非在线状态':'数据来自 Registry · 非 Agent 在线心跳'}</span>
  </section>
  {state==='error'&&<Alert showIcon type="warning" title="Registry 暂时不可读取" description={message} className="!rounded-[5px]"/>}
  <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,.85fr)]" aria-label="Agent Registry 与 Memory 双栏工作区">
    <section className="min-w-0 space-y-2" aria-label="Agent 注册列表">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-subtle)] pb-2"><h2 className="os-section-heading">Agent Registry</h2><span className="text-[11px] text-[var(--text-tertiary)]">匹配 {filtered.length} / 已载入 {agents.length} 条</span></div>
      <div className="os-console-filterbar flex flex-wrap items-center gap-2 py-1"><Input.Search aria-label="搜索 Agent Registry" value={keyword} onChange={event=>setKeyword(event.target.value)} placeholder="搜索名称 / 标识 / 工具" allowClear className="!w-[260px] max-w-full"/><Select aria-label="筛选 Agent 状态" value={statusFilter} onChange={setStatusFilter} className="!w-[162px]" options={[{value:'ALL',label:'全部注册状态'},...statusChoices.map(value=>({value,label:value}))]}/>{(keyword||statusFilter!=='ALL')&&<Button size="small" onClick={()=>{setKeyword('');setStatusFilter('ALL');}}>重置</Button>}</div>
      <Table<AgentSummary> rowKey="id" size="small" columns={columns} dataSource={filtered} loading={state==='loading'} scroll={{x:740}} onRow={agent=>({onClick:()=>setSelected(agent),className:'cursor-pointer'})} pagination={filtered.length>0?{pageSize:12,showSizeChanger:true,pageSizeOptions:['12','24','50'],showTotal:(n,range)=>`${range[0]}–${range[1]} / ${n} 条`}:false} locale={{emptyText:<div className="py-3"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={state==='error'?'Registry 接口不可读，不能据此判断没有 Agent':keyword||statusFilter!=='ALL'?'当前筛选无匹配的 Agent':'当前 Registry 未返回注册 Agent'}>{state==='error'&&<Button size="small" onClick={()=>setReload(v=>v+1)}>重试连接</Button>}</Empty></div>}}/>
    </section>
    <aside className="min-w-0 border-t border-[var(--border-subtle)] pt-3 xl:border-l xl:border-t-0 xl:pl-4 xl:pt-0" aria-label="Memory 检索工作区"><MemorySearchPanel/><p className="mt-4 border-t border-[var(--border-subtle)] pt-3 text-[11px] leading-5 text-[var(--text-tertiary)]">Memory 独立查询现有 API；不会将空返回视为系统没有记录，也不会改变 Agent 状态。</p></aside>
  </div>
  <footer className="flex items-start gap-2 border-t border-[var(--border-subtle)] pt-3 text-[11px] text-[var(--text-tertiary)]"><ShieldCheck size={15} className="shrink-0"/>本页只读。创建、启动、停止 Agent 需要独立授权的后端 API。</footer>
  {selected&&<Drawer open onClose={()=>setSelected(null)} width="min(440px, 100vw)" title="Agent 注册详情 · 只读" destroyOnClose className="storyos-agent-inspector"><section aria-label="Agent 注册详情" className="space-y-3"><div><h2 className="text-[15px] font-semibold">{selected.name}</h2><p className="mt-1 break-all font-mono text-[11px] text-[var(--text-tertiary)]">{selected.id}</p></div><dl className="divide-y divide-[var(--border-subtle)] text-[12px]"><div className="grid grid-cols-[85px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">注册状态</dt><dd>{selected.status||'未披露'}</dd></div><div className="grid grid-cols-[85px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">描述</dt><dd>{selected.description||'未提供'}</dd></div><div className="grid grid-cols-[85px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">已披露工具</dt><dd className="break-words">{selected.tools.join('、')||'未披露'}</dd></div></dl><p className="text-[11px] text-[var(--text-tertiary)]">Registry 返回记录不代表 Agent 在线运行，也不提供本页启停操作。</p></section></Drawer>}
 </div>;
};
