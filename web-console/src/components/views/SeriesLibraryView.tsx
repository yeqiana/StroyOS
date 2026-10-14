import React, {useMemo, useState} from 'react';
import {Button, Checkbox, Drawer, Input, Pagination, Progress, Segmented, Select, Table} from 'antd';
import type {TableColumnsType} from 'antd';
import {ArrowUpRight, Eye, Image as ImageIcon, Images, List, Plus} from 'lucide-react';
import type {Episode,ProjectItem} from '../../types';
import {useLocalApprovedMedia} from '../../api/localApprovedMedia';
import {CanonicalRuntimeDirectory} from '../catalog/CanonicalRuntimeDirectory';
import {LocalDraftSafetyPanel} from '../catalog/LocalDraftSafetyPanel';

interface Props { episodes:Episode[]; activeEpisode:Episode; onSelectEpisode:(episode:Episode)=>void; onGoToWorkbench:()=>void; onGoToMonitor:(episodeRef:string)=>void; onNewStoryClick:()=>void; projects:ProjectItem[];onRestoreLocalDrafts:(json:string)=>void; }
const STAGES:Record<string,string> = {IDEA_LOCK:'创意锁定',STORYBOARD_LOCK:'分镜锁定',VISUAL_CALIBRATE:'视觉校准',PROD_APPROVED:'生产审核',READY_TO_PUBLISH:'待发布',PUBLISHED:'已发布',POST_MORTEM:'数据复盘'};
const readableTime=(value:string)=>{if(!value)return '未知';const d=new Date(value);return Number.isNaN(d.valueOf())?value:new Intl.DateTimeFormat('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(d);};
export const SeriesLibraryView: React.FC<Props> = ({episodes,activeEpisode,onSelectEpisode,onGoToWorkbench,onGoToMonitor,onNewStoryClick,projects,onRestoreLocalDrafts}) => {
  const {findEpisode}=useLocalApprovedMedia();
  const coverFor=(ep:Episode)=>findEpisode(ep.title,ep.code)?.frames[0]?.url || (ep.coverImage && !ep.coverImage.startsWith('data:image/svg+xml') ? ep.coverImage : '');
  const [query,setQuery]=useState('');
  const [stage,setStage]=useState('ALL');
  const [approvedOnly,setApprovedOnly]=useState(false);
  const [viewMode,setViewMode]=useState<'gallery'|'list'>('gallery');
  const [selectedEpisode,setSelectedEpisode]=useState<Episode|null>(null);
  const [page,setPage]=useState(1);
  const [pageSize,setPageSize]=useState(10);
  const rows=useMemo(()=>episodes.filter(ep=>(stage==='ALL'||ep.currentStage===stage)&&(!approvedOnly||Boolean(findEpisode(ep.title,ep.code)?.frames.length))&&`${ep.title} ${ep.code} ${ep.genre}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())),[episodes,stage,approvedOnly,query,findEpisode]);
  const publishedCount=episodes.filter(ep=>['PUBLISHED','POST_MORTEM'].includes(ep.currentStage)).length;
  const verifiedCount=episodes.filter(ep=>Boolean(findEpisode(ep.title,ep.code)?.frames.length)).length;
  const visiblePage=Math.min(page,Math.max(1,Math.ceil(rows.length/pageSize)));
  // Image-first presentation for creator browsing; keep the original stable order in list mode.
  const gallerySortedRows=[...rows].sort((a,b)=>Number(Boolean(findEpisode(b.title,b.code)?.frames.length))-Number(Boolean(findEpisode(a.title,a.code)?.frames.length)));
  const galleryItems=gallerySortedRows.slice((visiblePage-1)*pageSize,visiblePage*pageSize);
  const open=(ep:Episode)=>{onSelectEpisode(ep);setSelectedEpisode(null);onGoToWorkbench();};
  const columns:TableColumnsType<Episode>=[
    {title:'作品',dataIndex:'title',key:'title',ellipsis:true,sorter:(a,b)=>a.title.localeCompare(b.title,'zh-CN'),render:(_,ep)=><div className="flex min-w-0 items-center gap-3"><div className="flex h-[48px] w-10 shrink-0 items-center justify-center overflow-hidden rounded-[5px] border border-[var(--border-subtle)] bg-[var(--bg-surface)]">{coverFor(ep)?<img src={coverFor(ep)} alt="" loading="lazy" className="h-full w-full object-cover"/>:<ImageIcon size={16} strokeWidth={1.75} className="text-[var(--text-tertiary)]"/>}</div><div className="min-w-0"><Button type="link" size="small" onClick={()=>open(ep)} aria-label={`打开故事 ${ep.title}`} title="直接进入故事制作" className="!h-auto !p-0 !text-[14px] !font-semibold !text-[var(--text-primary)] hover:!text-[var(--info)]"><span className="block max-w-[35vw] truncate text-left">{ep.title}</span></Button><p className="mt-1 truncate text-[12px] text-[var(--text-tertiary)]">{ep.code} · {ep.genre||'未分类'}</p></div></div>},
    {title:'生产阶段',dataIndex:'currentStage',key:'stage',width:148,render:(value:string)=><span className="inline-flex items-center gap-2 text-[13px] text-[var(--text-secondary)]"><span className="h-1.5 w-1.5 rounded-full bg-[var(--text-tertiary)]" />{STAGES[value]||value}</span>},
    {title:'帧进度',key:'frames',width:158,render:(_,ep)=>{const percent=ep.totalFrames?Math.round(ep.completedFrames/ep.totalFrames*100):0;return <div className="max-w-[132px] text-[13px] tabular-nums"><span>{ep.completedFrames}<span className="text-[var(--text-tertiary)]"> / {ep.totalFrames}</span></span><Progress percent={Math.min(100,Math.max(0,percent))} showInfo={false} size="small" strokeColor="var(--info)" trailColor="var(--border-normal)" className="!my-0 !mt-1"/></div>;}},
    {title:'更新时间',dataIndex:'updatedAt',key:'updatedAt',width:148,ellipsis:true,sorter:(a,b)=>(Date.parse(a.updatedAt||'')||0)-(Date.parse(b.updatedAt||'')||0),render:(value:string)=><span title={value||''} className="text-[12px] tabular-nums text-[var(--text-secondary)]">{readableTime(value)}</span>},
    {title:'操作',key:'action',width:90,render:(_,ep)=><Button type="link" onClick={()=>setSelectedEpisode(ep)} size="small" icon={<Eye size={14} strokeWidth={1.75} aria-hidden="true"/>} aria-label={'预览作品 '+ep.title} className="!font-semibold">预览</Button>},
  ];
  return <section id="series-library-view" className="w-full min-w-0 space-y-3 pb-6 text-[var(--text-primary)]">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-3">
      <div><h1 className="os-page-heading">作品与项目</h1><p className="mt-1 text-[12px] text-[var(--text-secondary)]">作品素材库 · 图片优先，工作区状态与批准素材分开计数</p></div>
      <Button type="primary" icon={<Plus size={15}/>} onClick={onNewStoryClick}>新建故事</Button>
    </header>
    <LocalDraftSafetyPanel episodes={episodes} projects={projects} onRestore={onRestoreLocalDrafts}/>

    <CanonicalRuntimeDirectory episodes={episodes} onSelectHistorical={onSelectEpisode} onOpenMonitor={onGoToMonitor}/>

    <section aria-label="作品库概况" className="flex flex-wrap items-center gap-x-8 gap-y-2 border-b border-[var(--border-subtle)] py-1.5">
      {[{label:'已收录',count:episodes.length},{label:'工作区未发布',count:episodes.length-publishedCount},{label:'含已批准图片',count:verifiedCount}].map(metric=><div key={metric.label} className="flex items-baseline gap-2"><span className="text-[11px] text-[var(--text-tertiary)]">{metric.label}</span><strong className="text-[16px] font-semibold tabular-nums">{metric.count}</strong></div>)}
      <span className="ml-auto text-[11px] text-[var(--text-tertiary)]">数据范围：当前工作区 · 本机素材目录只读</span>
    </section>
    <div className="os-console-filterbar flex flex-wrap items-center gap-3 border-b border-[var(--border-subtle)] pb-3">
      <Input.Search aria-label="搜索故事标题、编号或类型" value={query} onChange={e=>{setQuery(e.target.value);setPage(1);}} placeholder="搜索作品 / 编号 / 类型" allowClear className="min-w-[220px] max-w-[360px] flex-1"/>
      <Select aria-label="筛选生产阶段" value={stage} onChange={v=>{setStage(v);setPage(1);}} className="w-[170px]" options={[{value:'ALL',label:'全部阶段'},...Object.entries(STAGES).map(([value,label])=>({value,label}))]}/>
      <Checkbox checked={approvedOnly} onChange={event=>{setApprovedOnly(event.target.checked);setPage(1);}}>只看有批准图片</Checkbox>
      <Segmented size="small" aria-label="作品显示方式" value={viewMode} onChange={value=>{setViewMode(value as 'gallery'|'list');setPage(1);setPageSize(value==='gallery'?15:10);}} options={[{value:'gallery',label:<span className="inline-flex items-center gap-1.5"><Images size={14} strokeWidth={1.75} aria-hidden="true"/>封面画廊</span>},{value:'list',label:<span className="inline-flex items-center gap-1.5"><List size={14} strokeWidth={1.75} aria-hidden="true"/>列表</span>}]}/>
      <span className="ml-auto text-[12px] tabular-nums text-[var(--text-tertiary)]">显示 {rows.length} / {episodes.length} 部</span>
    </div>
    {viewMode==='gallery'?<section aria-label="作品封面画廊" className="space-y-3">
      {galleryItems.length?<div className="space-y-4">
        {galleryItems.some(ep=>Boolean(findEpisode(ep.title,ep.code)?.frames.length))&&<section aria-label="已批准素材作品画廊" className="space-y-2"><div className="flex items-center justify-between gap-3"><h2 className="os-section-heading">已有图片的作品</h2><span className="text-[11px] text-[var(--text-tertiary)]">从本机已批准素材目录读取</span></div><div className="grid grid-cols-2 gap-3 sm:grid-cols-3 2xl:grid-cols-4">
        {galleryItems.filter(ep=>Boolean(findEpisode(ep.title,ep.code)?.frames.length)).map(ep=>{const media=findEpisode(ep.title,ep.code);const cover=coverFor(ep);return <button type="button" key={ep.id} onClick={()=>setSelectedEpisode(ep)} aria-label={'预览作品 '+ep.title} className="group min-w-0 overflow-hidden rounded-[6px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] text-left hover:border-[var(--info)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus)]">
          <div className="relative aspect-[4/3] overflow-hidden bg-[var(--bg-elevated)]">
            {cover&&<img src={cover} alt={ep.title+'的已批准素材封面'} loading="lazy" className="h-full w-full object-cover object-top transition-transform duration-150 group-hover:scale-[1.02]"/>}
            {media?.frames.length?<span className="absolute bottom-2 right-2 border border-[var(--border-normal)] bg-[var(--bg-workspace)] px-2 py-1 text-[11px] tabular-nums text-[var(--text-primary)]">已批准 {media.frames.length} 帧</span>:null}
          </div>
          <div className="space-y-1 px-3 py-2"><div className="flex items-center gap-2"><h3 className="min-w-0 flex-1 truncate text-[13px] font-semibold text-[var(--text-primary)]">{ep.title}</h3><span className="inline-flex shrink-0 items-center gap-1 text-[11px] text-[var(--text-tertiary)]"><Eye size={13} strokeWidth={1.75} aria-hidden="true"/>预览</span></div><p className="truncate text-[11px] text-[var(--text-tertiary)]">{ep.code} · {ep.genre||'未分类'}</p><div className="flex items-center justify-between gap-2 pt-1 text-[11px] text-[var(--text-secondary)]"><span>{STAGES[ep.currentStage]||ep.currentStage}</span><span className="tabular-nums">工作区 {ep.completedFrames}/{ep.totalFrames} 帧</span></div></div>
        </button>;})}
        </div></section>}
        {galleryItems.some(ep=>!findEpisode(ep.title,ep.code)?.frames.length)&&<section aria-label="无批准图片作品紧凑列表" className="space-y-2"><div className="flex items-center justify-between gap-3"><h2 className="os-section-heading">其他作品</h2><span className="text-[11px] text-[var(--text-tertiary)]">未找到可验证批准封面 · 保留作品入口</span></div><div className="divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)]">
          {galleryItems.filter(ep=>!findEpisode(ep.title,ep.code)?.frames.length).map(ep=><button key={ep.id} type="button" onClick={()=>setSelectedEpisode(ep)} aria-label={'预览作品 '+ep.title} className="grid w-full min-w-0 grid-cols-[minmax(0,1fr)_120px_115px] items-center gap-3 px-3 py-2 text-left text-[12px] hover:bg-[var(--bg-hover)] sm:grid-cols-[minmax(0,1fr)_170px_145px]"><span className="min-w-0"><strong className="block truncate text-[13px] font-medium text-[var(--text-primary)]">{ep.title}</strong><span className="block truncate text-[11px] text-[var(--text-tertiary)]">{ep.code} · {ep.genre||'未分类'}</span></span><span className="truncate text-[var(--text-secondary)]">{STAGES[ep.currentStage]||ep.currentStage}</span><span className="text-right tabular-nums text-[var(--text-secondary)]">工作区 {ep.completedFrames}/{ep.totalFrames} 帧</span></button>)}
        </div></section>}
      </div>:<p className="border border-dashed border-[var(--border-normal)] p-6 text-[13px] text-[var(--text-secondary)]">当前筛选条件下没有作品。</p>}
      <div className="flex justify-end"><Pagination size="small" current={visiblePage} pageSize={pageSize} total={rows.length} showSizeChanger pageSizeOptions={['10','15','30','60']} showTotal={(total,range)=>`${range[0]}–${range[1]} / ${total} 部`} onChange={(next,size)=>{setPage(next);setPageSize(size);}}/></div>
    </section>:<Table<Episode> rowKey="id" size="small" columns={columns} dataSource={rows} scroll={{x:820}} rowClassName={ep=>ep.id===activeEpisode.id?'storyos-ant-selected':''}
      pagination={{current:visiblePage,pageSize,total:rows.length,showSizeChanger:true,pageSizeOptions:['10','20','30','50'],showTotal:(total,range)=>`${range[0]}–${range[1]} / ${total} 条`,onChange:(next,size)=>{setPage(next);setPageSize(size);}}}
      locale={{emptyText:'暂无符合条件的作品，请修改筛选条件'}}/>}
    <Drawer open={selectedEpisode!==null} onClose={()=>setSelectedEpisode(null)} width="min(440px, 100vw)" destroyOnClose title="作品详情 · 只读预览" className="storyos-episode-preview-inspector">
      {selectedEpisode&&<section aria-label="作品预览详情" className="space-y-4">
        {coverFor(selectedEpisode)?<img src={coverFor(selectedEpisode)} alt={selectedEpisode.title+'的真实封面'} className="max-h-[240px] w-full object-contain bg-[var(--bg-surface)]"/>:<div className="flex items-center gap-2 border border-dashed border-[var(--border-normal)] p-4 text-[12px] text-[var(--text-tertiary)]"><ImageIcon size={18} strokeWidth={1.75}/>暂无可验证封面，仍可查看作品记录</div>}
        <div><h2 className="text-[17px] font-semibold">{selectedEpisode.title}</h2><p className="mt-1 text-[12px] text-[var(--text-secondary)]">{selectedEpisode.code} · {selectedEpisode.genre||'未分类'}</p></div>
        <dl className="divide-y divide-[var(--border-subtle)] text-[12px]">{[['阶段',STAGES[selectedEpisode.currentStage]||selectedEpisode.currentStage],['工作区帧进度',`${selectedEpisode.completedFrames} / ${selectedEpisode.totalFrames}`],['已批准素材',`${findEpisode(selectedEpisode.title,selectedEpisode.code)?.frames.length||0} 张（本机只读）`],['更新时间',readableTime(selectedEpisode.updatedAt)]].map(([label,value])=><div key={label} className="grid grid-cols-[100px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">{label}</dt><dd className="break-words">{value}</dd></div>)}</dl>
        <div><h3 className="text-[13px] font-semibold">故事简介</h3><p className="mt-2 whitespace-pre-wrap text-[12px] leading-6 text-[var(--text-secondary)]">{selectedEpisode.synopsis||'未提供剧情简介'}</p></div>
        <Button type="primary" block icon={<ArrowUpRight size={15} strokeWidth={1.75} aria-hidden="true"/>} onClick={()=>open(selectedEpisode)}>进入故事制作</Button>
        <p className="text-[11px] leading-5 text-[var(--text-tertiary)]">仅展示可验证的工作区记录。进入创作台不会触发生产、生成或审核写入。</p>
      </section>}
    </Drawer>
    <p className="border-t border-[var(--border-subtle)] pt-2 text-[11px] leading-5 text-[var(--text-tertiary)]">阶段与帧数来自工作区记录，已批准图片仅取自可验证的素材目录；正式生产与发布状态以受控 Runtime 为准。</p>
  </section>;
};