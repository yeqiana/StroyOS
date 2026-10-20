import React, {useEffect, useMemo, useState} from 'react';
import {Button, Drawer, Input, Modal, Segmented, Select, Table, Tooltip} from 'antd';
import {ArrowDownUp, ArrowRight, Eye, FilePlus2, Image as ImageIcon, Images, List, Pencil, RefreshCw, Search, Trash2} from 'lucide-react';
import type {Episode} from '../../types';
import {platformApi, stageLabel, type RuntimeStatusDetail, type RuntimeStatusSummary} from '../../api/platformApi';
import {isManagedDraft, validateDraftProfile, type DraftProfile} from '../../api/localWorkCrud';
import {useLocalApprovedMedia} from '../../api/localApprovedMedia';
import {projectProductionProgress} from '../../api/productionProgress';
import {galleryPageCapacity, galleryColumns, sortWorks, type WorkSortKey, type WorkSortDirection} from '../../api/workCatalogSorting';

type ManagedRow = {key:string; kind:'runtime'|'draft'; title:string; code:string; updated:string; stage:string; statusRank:number|null; completionPercent:number|null; completionScope:'stage'|'frames'|null; draft?:Episode; official?:RuntimeStatusSummary};
interface Props {
  episodes: Episode[];
  onCreateDraft: (profile:DraftProfile)=>void;
  onUpdateDraft: (id:string, profile:DraftProfile)=>void;
  onDeleteDraft: (id:string)=>void;
  onSelectDraft: (episode:Episode)=>void;
  onOpenRuntimeEpisode: (ref:string)=>void;
}
const emptyProfile = ():DraftProfile=>({title:'',synopsis:'',genre:'未分类'});
const dateText=(text:string)=>text?text.replace('T',' ').slice(0,16):'未知';
export const ManagedWorksPanel:React.FC<Props>=({episodes,onCreateDraft,onUpdateDraft,onDeleteDraft,onSelectDraft,onOpenRuntimeEpisode})=>{
  const {findEpisode}=useLocalApprovedMedia();
  const [official,setOfficial]=useState<RuntimeStatusSummary[]>([]);
  const [serverState,setServerState]=useState<'loading'|'ready'|'partial'|'offline'>('loading');
  const [warning,setWarning]=useState('');
  const [refreshKey,setRefreshKey]=useState(0);
  const [search,setSearch]=useState('');
  const [scope,setScope]=useState<'all'|'runtime'|'draft'>('all');
  const [viewMode,setViewMode]=useState<'list'|'gallery'>('list');
  const [sortKey,setSortKey]=useState<WorkSortKey>('updated');
  const [sortDirection,setSortDirection]=useState<WorkSortDirection>('desc');
  const [galleryRows,setGalleryRows]=useState(3);
  const [viewportWidth,setViewportWidth]=useState(()=>typeof window!=='undefined'?window.innerWidth:1440);
  const [page,setPage]=useState(1);
  const [selectedKey,setSelectedKey]=useState<string|null>(null);
  const [detail,setDetail]=useState<RuntimeStatusDetail|null>(null);
  const [modal,setModal]=useState<{mode:'create'|'edit';id?:string}|null>(null);
  const [profile,setProfile]=useState<DraftProfile>(emptyProfile);
  const [formError,setFormError]=useState('');
  useEffect(()=>{const onResize=()=>setViewportWidth(window.innerWidth);onResize();window.addEventListener('resize',onResize);return ()=>window.removeEventListener('resize',onResize);},[]);

  useEffect(()=>{
    let mounted=true;
    const read=async()=>{
      try{
        const result=await platformApi.runtimeStatuses(100,0);
        if(!mounted)return;
        const seen=new Set<string>();
        const approved=(result.items||[]).filter(row=>{
          const id=row.episode_ref||'';
          if(!/^LOCAL_[a-f0-9]{24}$/.test(id)||!['mysql_episode_state_read_only','local_workspace_episode_state_file'].includes(row.state_source||'')
             ||!row.title||!row.business_episode_id||seen.has(id))return false;
          seen.add(id);return true;
        });
        setOfficial(approved);
        setServerState(result.errors?.length||result.has_more?'partial':'ready');
        setWarning(result.has_more?'正式作品超过当前 100 条读取窗口，请到 Runtime 目录分页查看':
          result.errors?.length?'部分正式作品状态读取失败，请勿据此推断已删除':'');
      }catch{
        if(mounted){setServerState('offline');setWarning('正式 Runtime 目录暂时不可访问，不能据此判断正式作品是否存在');setOfficial([]);}
      }
    };
    void read();
    return ()=>{mounted=false;};
  },[refreshKey]);

  const rows=useMemo<ManagedRow[]>(()=>{
    const canonical:ManagedRow[]=official.map(item=>{
      // Stage percent describes completed workflow milestones only, not images or elapsed time.
      const progress=projectProductionProgress(item);
      return {key:'official:'+item.episode_ref,kind:'runtime',title:item.title!,code:item.business_episode_id!,
        updated:item.updated_at||'',stage:stageLabel(item.production_stage||'NO_STATE'),
        statusRank:progress.completedSteps,completionPercent:progress.stagePercent,
        completionScope:progress.stagePercent===null?null:'stage',official:item};
    });
    const local:ManagedRow[]=episodes.filter(isManagedDraft).map(ep=>{
      const frames=Number.isInteger(ep.totalFrames)&&ep.totalFrames>0&&Number.isInteger(ep.completedFrames)&&ep.completedFrames>=0
        ?Math.round(Math.min(ep.completedFrames,ep.totalFrames)/ep.totalFrames*100):null;
      return {key:'draft:'+ep.id,kind:'draft',title:ep.title,code:ep.code,
        updated:ep.updatedAt,stage:'本机草稿 · 未启动生产',
        statusRank:0,completionPercent:frames,completionScope:frames===null?null:'frames',draft:ep};
    });
    return [...local,...canonical];
  },[episodes,official]);
  const matches=useMemo(()=>sortWorks(rows.filter(item=>(scope==='all'||scope===item.kind)&&
    [item.title,item.code,item.stage,item.draft?.synopsis||''].join(' ').toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())),
    sortKey,sortDirection),[rows,scope,search,sortKey,sortDirection]);
  // A gallery page always contains an integral number of complete grid rows.
  // The final page may be short because we never invent or duplicate Episodes.
  const itemsPerPage=viewMode==='gallery'?galleryPageCapacity(viewportWidth,galleryRows):10;
  const pages=Math.max(1,Math.ceil(matches.length/itemsPerPage));
  const selectedPage=Math.min(page,pages);
  const displayed=matches.slice((selectedPage-1)*itemsPerPage,selectedPage*itemsPerPage);
  const selected=rows.find(item=>item.key===selectedKey)||null;
  const coverFor=(item:ManagedRow)=>{
    if(item.kind!=='runtime'||!item.official?.episode_ref)return null;
    const found=findEpisode(item.title,item.code);
    return found?.episode_ref===item.official.episode_ref ? found.frames[0]?.url||null : null;
  };
  useEffect(()=>{
    let active=true;
    setDetail(null);
    const ref=selected?.official?.episode_ref;
    if(ref)void platformApi.runtimeStatus(ref).then(value=>{if(active && value.episode_ref===ref)setDetail(value);}).catch(()=>{});
    return ()=>{active=false;};
  },[selected?.official?.episode_ref]);
  const beginCreate=()=>{setProfile(emptyProfile());setFormError('');setModal({mode:'create'});};
  const beginEdit=(ep:Episode)=>{
    if(!isManagedDraft(ep))return;
    setProfile({title:ep.title,synopsis:ep.synopsis||'',genre:ep.genre||'未分类'});
    setFormError('');setModal({mode:'edit',id:ep.id});
  };
  const save=()=>{
    try{
      const validated=validateDraftProfile(profile);
      if(modal?.mode==='edit' && modal.id) onUpdateDraft(modal.id,validated);
      else if(modal?.mode==='create')onCreateDraft(validated);
      else return;
      setModal(null);setPage(1);
    }catch(error){setFormError(error instanceof Error?error.message:'保存失败');}
  };
  const confirmDelete=(ep:Episode)=>{
    if(!isManagedDraft(ep))return;
    Modal.confirm({title:'删除本机草稿？',content:<span>《{ep.title}》将从当前浏览器的草稿库中移除。<strong>此操作不能撤销</strong>，但不会删除 MySQL 正式作品、图片或生产记录。</span>,
      okText:'确认删除草稿',okButtonProps:{danger:true},cancelText:'取消',
      onOk:()=>{onDeleteDraft(ep.id);if(selectedKey==='draft:'+ep.id)setSelectedKey(null);setPage(1);}
    });
  };
  const open=(item:ManagedRow)=>setSelectedKey(item.key);
  const action=(item:ManagedRow)=>(
    <div className="flex flex-wrap items-center gap-1.5">
      <Button type="link" size="small" icon={<Eye size={12}/>} onClick={()=>open(item)} aria-label={'查看作品 '+item.title}>查看</Button>
      {item.kind==='draft'?<>
        <Button size="small" icon={<Pencil size={12}/>} aria-label={'编辑草稿 '+item.title} onClick={()=>beginEdit(item.draft!)}>编辑</Button>
        <Button size="small" danger icon={<Trash2 size={12}/>} aria-label={'删除草稿 '+item.title} onClick={()=>confirmDelete(item.draft!)}>删除</Button>
      </>:<Tooltip title="正式作品关联 MySQL、生产锁与审核证据；此监控实例只读，需通过独立授权流程才能编辑或归档">
        <span className="whitespace-nowrap text-[11px] text-[var(--text-tertiary)]">编辑/归档需授权</span>
      </Tooltip>}
    </div>
  );
  const cover=(item:ManagedRow,size:'small'|'large')=><div className={(size==='small'?'h-11 w-9':'h-[164px] w-full')+' flex shrink-0 items-center justify-center overflow-hidden rounded-[4px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)]'}>
    {coverFor(item)?<img src={coverFor(item)!} loading="lazy" alt={item.title+'的已批准图片'} className="h-full w-full object-cover object-top"/>:
      <div className="flex flex-col items-center gap-1 text-[var(--text-tertiary)]"><ImageIcon size={size==='small'?16:22}/>{size==='large'&&<span className="text-[11px]">暂无已批准封面</span>}</div>}
  </div>;
  return <section id="storyos-managed-works" aria-label="作品增删改查" className="min-w-0 space-y-3 border-t border-[var(--border-subtle)] pt-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="os-section-heading">作品列表</h2><p className="mt-1 text-[11px] text-[var(--text-secondary)]">统一检索正式作品与本机草稿，按来源开放可用操作</p></div>
      <div className="flex items-center gap-2">
        <Button size="small" icon={<RefreshCw size={13}/>} onClick={()=>setRefreshKey(v=>v+1)}>刷新正式作品</Button>
        <Button size="small" type="primary" icon={<FilePlus2 size={13}/>} onClick={beginCreate}>新建作品</Button>
      </div>
    </div>
    <div className="os-console-filterbar flex flex-wrap items-center gap-2 border-b border-[var(--border-subtle)] pb-2">
      <Input prefix={<Search size={14}/>} value={search} onChange={event=>{setSearch(event.target.value);setPage(1);}} placeholder="搜索作品名称、编号、阶段" allowClear className="min-w-[210px] max-w-[320px] flex-1" aria-label="搜索正式作品与本机草稿"/>
      <Segmented size="small" aria-label="作品来源" value={scope} onChange={v=>{setScope(v as typeof scope);setPage(1);}}
        options={[{label:'全部',value:'all'},{label:'正式作品',value:'runtime'},{label:'本机草稿',value:'draft'}]}/>
      <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-secondary)]">
        <span>排序</span>
        <Select size="small" aria-label="作品排序字段" value={sortKey} className="min-w-[112px]" onChange={v=>{setSortKey(v as WorkSortKey);setPage(1);}}
          options={[{value:'updated',label:'更新时间'},{value:'status',label:'生产阶段'},{value:'completion',label:'完成度'}]}/>
        <Button size="small" aria-label={sortDirection==='desc'?'降序排列':'升序排列'}
          title={sortDirection==='desc'?'当前降序 · 点击切换升序':'当前升序 · 点击切换降序'}
          icon={<ArrowDownUp size={14}/>} onClick={()=>{setSortDirection(v=>v==='asc'?'desc':'asc');setPage(1);}}>
          {sortDirection==='desc'?'降序':'升序'}
        </Button>
      </div>
      <Segmented size="small" aria-label="作品显示方式" value={viewMode} onChange={v=>{setViewMode(v as typeof viewMode);setPage(1);}}
        options={[{label:<span className="inline-flex items-center gap-1"><List size={13}/>列表</span>,value:'list'},
                  {label:<span className="inline-flex items-center gap-1"><Images size={13}/>画廊</span>,value:'gallery'}]}/>
      {viewMode==='gallery'&&<Select size="small" aria-label="画廊每页行数" value={galleryRows} onChange={v=>{setGalleryRows(v);setPage(1);}}
        className="min-w-[94px]" options={[{value:3,label:'每页 3 行'},{value:4,label:'每页 4 行'},{value:5,label:'每页 5 行'}]}/>}
    </div>
    <div className="flex flex-wrap items-center gap-4 text-[11px] text-[var(--text-tertiary)]">
      <span>正式 <strong className="text-[var(--text-primary)]">{official.length}</strong> 部</span>
      <span>本机草稿 <strong className="text-[var(--text-primary)]">{episodes.filter(isManagedDraft).length}</strong> 部</span>
      <span>匹配 <strong className="text-[var(--text-primary)]">{matches.length}</strong> 部</span>
      {viewMode==='gallery'&&<span>画廊 {galleryColumns(viewportWidth)} 列 × {galleryRows} 行 / 页，共 {itemsPerPage} 部容量</span>}
      {serverState==='loading'&&<span role="status">正在读取正式目录…</span>}
    </div>
    {warning&&<p role="alert" className="text-[11px] text-[var(--warning)]">{warning}</p>}
    {viewMode==='list'?<Table<ManagedRow> rowKey="key" size="small" dataSource={matches} scroll={{x:820}}
      locale={{emptyText:serverState==='loading'?'正在读取作品…':'没有匹配的作品'}}
      columns={[
        {title:'作品',key:'title',render:(_,item)=><div className="flex min-w-0 items-center gap-2.5">{cover(item,'small')}<div className="min-w-0"><button className="block max-w-[32vw] truncate text-left text-[13px] font-semibold hover:text-[var(--info)]" onClick={()=>open(item)} title={item.title}>{item.title}</button><span className="text-[11px] text-[var(--text-tertiary)]">{item.code} · {item.kind==='runtime'?'正式 Runtime':'浏览器草稿'}</span></div></div>},
        {title:'状态',key:'stage',width:165,render:(_,item)=><span className="text-[12px] text-[var(--text-secondary)]">{item.stage}</span>},
        {title:'完成度',key:'completion',width:148,render:(_,item)=><span className="text-[12px] tabular-nums text-[var(--text-secondary)]">{item.completionPercent===null?'待核验':item.completionPercent+'%'}<span className="ml-1 text-[10px] text-[var(--text-tertiary)]">{item.completionScope==='stage'?'阶段':item.completionScope==='frames'?'草稿帧':''}</span></span>},
        {title:'更新',key:'date',width:136,render:(_,item)=><span className="tabular-nums text-[11px] text-[var(--text-tertiary)]">{dateText(item.updated)}</span>},
        {title:'操作',key:'action',width:242,render:(_,item)=>action(item)}
      ]}
      pagination={{current:selectedPage,pageSize:itemsPerPage,total:matches.length,showSizeChanger:false,onChange:setPage,showTotal:n=>'共 '+n+' 部'}}
    />:<>
      <div aria-label="作品管理画廊" className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {displayed.map(item=><article key={item.key} className="min-w-0 overflow-hidden rounded-[5px] border border-[var(--border-subtle)] bg-[var(--bg-surface)]">
          {cover(item,'large')}
          <div className="space-y-2 px-3 py-2.5">
            <button type="button" title={item.title} onClick={()=>open(item)} className="block max-w-full truncate text-left text-[13px] font-semibold hover:text-[var(--info)]">{item.title}</button>
            <p className="truncate text-[11px] text-[var(--text-tertiary)]">{item.code} · {item.stage}</p>
            <p className="text-[11px] tabular-nums text-[var(--text-secondary)]">完成度 {item.completionPercent===null?'待核验':item.completionPercent+'%（'+(item.completionScope==='stage'?'生产阶段':'草稿帧')+'）'}</p>
            {action(item)}
          </div>
        </article>)}
      </div>
      {!matches.length&&<p className="py-7 text-center text-[12px] text-[var(--text-tertiary)]">没有匹配的作品</p>}
      <div className="flex justify-end"><Button size="small" disabled={selectedPage===1} onClick={()=>setPage(v=>v-1)}>上一页</Button><span className="px-3 py-1 text-[11px]">第 {selectedPage} / {pages} 页</span><Button size="small" disabled={selectedPage>=pages} onClick={()=>setPage(v=>v+1)}>下一页</Button></div>
    </>}
    <p className="text-[11px] text-[var(--text-tertiary)]">新建及编辑/删除只作用于当前浏览器草稿，不会启动生产或修改正式 Episode；正式作品的编辑、归档需生产写入授权和锁核验。</p>
    <Drawer open={Boolean(selected)} title="作品详情" width="min(440px, 100vw)" onClose={()=>setSelectedKey(null)} destroyOnClose>
      {selected&&<div className="space-y-3 text-[12px]">
        {cover(selected,'large')}
        <h3 className="break-words text-[16px] font-semibold">{selected.title}</h3>
        <p className="text-[var(--text-secondary)]">{selected.code} · {selected.kind==='runtime'?'MySQL 正式作品':'浏览器本机草稿'}</p>
        <p>生产阶段：{selected.stage}</p><p>完成度：{selected.completionPercent===null?'待核验':selected.completionPercent+'%（'+(selected.completionScope==='stage'?'生产阶段':'草稿帧')+'）'}</p><p>更新时间：{dateText(selected.updated)}</p>
        <div><h4 className="font-medium">故事简介</h4><p className="mt-1 whitespace-pre-wrap text-[var(--text-secondary)]">{selected.kind==='draft'
          ?selected.draft?.synopsis||'暂无简介'
          : detail?.story_excerpt||'未收录可核验的故事简介'}</p></div>
        {selected.kind==='runtime'?<Button type="primary" block onClick={()=>onOpenRuntimeEpisode(selected.official!.episode_ref!)}>进入生产监控 <ArrowRight size={13}/></Button>:
          <div className="flex gap-2"><Button type="primary" onClick={()=>onSelectDraft(selected.draft!)}>进入故事制作</Button><Button onClick={()=>beginEdit(selected.draft!)}>编辑</Button><Button danger onClick={()=>confirmDelete(selected.draft!)}>删除</Button></div>}
      </div>}
    </Drawer>
    <Modal open={modal!==null} title={modal?.mode==='edit'?'编辑本机草稿':'新建作品草稿'} onCancel={()=>setModal(null)} onOk={save} okText={modal?.mode==='edit'?'保存修改':'保存草稿'} cancelText="取消" destroyOnClose>
      <div className="space-y-3 py-2">
        <label className="block text-[12px]">作品名称 <Input autoFocus maxLength={100} value={profile.title} onChange={e=>setProfile(v=>({...v,title:e.target.value}))} placeholder="请输入作品名称" aria-label="草稿作品名称" className="mt-1"/></label>
        <label className="block text-[12px]">作品类型 <Input maxLength={40} value={profile.genre} onChange={e=>setProfile(v=>({...v,genre:e.target.value}))} aria-label="草稿作品类型" className="mt-1"/></label>
        <label className="block text-[12px]">剧情简介 <Input.TextArea maxLength={2000} showCount rows={4} value={profile.synopsis} onChange={e=>setProfile(v=>({...v,synopsis:e.target.value}))} placeholder="介绍故事的主要人物、冲突与悬念" aria-label="草稿剧情简介" className="mt-1"/></label>
        {formError&&<p role="alert" className="text-[12px] text-[var(--danger)]">{formError}</p>}
      </div>
    </Modal>
  </section>;
};
