import React, {useState} from 'react';
import {Button} from 'antd';
import {RefreshCw} from 'lucide-react';
import type {Episode} from '../../types';
import {stageLabel} from '../../api/platformApi';
import {matchCanonicalHistoricalEpisode, useCanonicalRuntimeCatalog} from '../../api/canonicalRuntimeCatalog';

interface Props {
  episodes: Episode[];
  onSelectHistorical: (ep:Episode)=>void;
  onOpenMonitor: (episodeRef:string)=>void;
  condensed?:boolean;
}

/** Runtime is the primary list; archived TS snapshots and browser drafts are not
 * quietly converted into Runtime Episodes and never override actual stages.
 */
export const CanonicalRuntimeDirectory:React.FC<Props>=({episodes,onSelectHistorical,onOpenMonitor,condensed=false})=>{
  const catalog=useCanonicalRuntimeCatalog();
  const [expanded,setExpanded]=useState(false);
  const entries=condensed&&!expanded?catalog.items.slice(0,5):catalog.items;
  const drafts=episodes.filter(ep=>/^ep-(home|proj)-/.test(ep.id)).length;
  return <section aria-label="正式Runtime作品目录" className="space-y-2 border-y border-[var(--border-subtle)] py-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h2 className="os-section-heading">正式作品 · Runtime 目录</h2>
        <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
          直接读取本机生产目录 · 已核验 {catalog.items.length}{catalog.total!==null?' / '+catalog.total:''} 部
          {catalog.status==='complete'?' · 本次读取完整':' · 来源未完整核验'}
          {drafts?' · 另有 '+drafts+' 个浏览器本地草稿':''}
        </p>
      </div>
      <Button size="small" onClick={catalog.refresh} icon={<RefreshCw size={13}/>} loading={catalog.status==='loading'}>刷新正式目录</Button>
    </div>
    {catalog.warning&&<p role="status" className="text-[11px] text-[var(--warning)]">{catalog.warning}</p>}
    {catalog.items.length ? <div className="grid min-w-0 grid-cols-1 gap-x-5 md:grid-cols-2 lg:grid-cols-3">
      {entries.map(item=>{
        const match=matchCanonicalHistoricalEpisode(item,episodes,catalog.items);
        return <div key={item.episode_ref} className="flex min-w-0 items-center justify-between gap-2 border-b border-[var(--border-subtle)] py-2">
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium text-[var(--text-primary)]">{item.title}</p>
            <p className="mt-1 truncate text-[11px] text-[var(--text-tertiary)]">
              {item.business_episode_id} · {stageLabel(item.production_stage||'NO_STATE')} · {match?'历史分镜已双重匹配':'历史分镜尚未可靠关联'}
            </p>
          </div>
          <Button size="small" type="link" onClick={()=>match?onSelectHistorical(match):onOpenMonitor(item.episode_ref||"")}>
            {match?'检视历史分镜':'查看真实监控'}
          </Button>
        </div>;
      })}
    </div> : <p className="py-3 text-[12px] text-[var(--text-tertiary)]">{catalog.status==='loading'?'正在读取正式 Runtime 作品…':'尚无已核验的正式作品，保留本地历史与草稿入口。'}</p>}
    {condensed&&catalog.items.length>5&&<Button type="link" size="small" onClick={()=>setExpanded(x=>!x)}>{expanded?'收起目录':'查看全部 '+catalog.items.length+' 部正式作品'}</Button>}
    <p className="text-[11px] text-[var(--text-tertiary)]">
      “检视历史分镜”只读取已匹配的历史证据；未匹配作品进入真实监控核对，不会创建虚假的制作任务。
    </p>
  </section>;
};
