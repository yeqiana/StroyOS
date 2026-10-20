import React, {useEffect, useMemo, useState} from 'react';
import {Button, Input, Modal, Table, Tooltip} from 'antd';
import {ArrowRight, FilePlus2, Pencil, RefreshCw, Search, Trash2} from 'lucide-react';
import type {Episode} from '../../types';
import {platformApi, stageLabel, type RuntimeStatusSummary} from '../../api/platformApi';
import {isManagedDraft, validateDraftProfile, type DraftProfile} from '../../api/localWorkCrud';

type ManagedRow = {key:string; kind:'runtime'|'draft'; title:string; code:string; updated:string; stage:string; draft?:Episode; official?:RuntimeStatusSummary};
interface Props {
  episodes: Episode[];
  onCreateDraft: (profile:DraftProfile)=>void;
  onUpdateDraft: (id:string, profile:DraftProfile)=>void;
  onDeleteDraft: (id:string)=>void;
  onSelectDraft: (episode:Episode)=>void;
  onOpenRuntimeEpisode: (ref:string)=>void;
}
const emptyProfile = ():DraftProfile=>({title:'',synopsis:'',genre:'未分类'});
export const ManagedWorksPanel:React.FC<Props>=({episodes,onCreateDraft,onUpdateDraft,onDeleteDraft,onSelectDraft,onOpenRuntimeEpisode})=>{
  const [official,setOfficial]=useState<RuntimeStatusSummary[]>([]);
  const [serverState,setServerState]=useState<'loading'|'ready'|'partial'|'offline'>('loading');
  const [warning,setWarning]=useState('');
  const [refreshKey,setRefreshKey]=useState(0);
  const [search,setSearch]=useState('');
  const [page,setPage]=useState(1);
  const [modal,setModal]=useState<{mode:'create'|'edit';id?:string}|null>(null);
  const [profile,setProfile]=useState<DraftProfile>(emptyProfile);
  const [formError,setFormError]=useState('');

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
        setWarning(result.has_more?'正式作品超过当前 100 条读取窗口；请到正式目录分页查看':
          result.errors?.length?'部分正式作品状态读取失败，请勿据此推断已删除':'');
      }catch{
        if(mounted){setServerState('offline');setWarning('MySQL 生产目录暂时不可访问，不能据此判断正式作品是否存在');setOfficial([]);}
      }
    };
    void read();
    return ()=>{mounted=false;};
  },[refreshKey]);

  const rows=useMemo<ManagedRow[]>(()=>{
    const canonical:ManagedRow[]=official.map(item=>({key:'official:'+item.episode_ref,kind:'runtime',
      title:item.title!,code:item.business_episode_id!,updated:item.updated_at||'',
      stage:stageLabel(item.production_stage||'NO_STATE'),official:item}));
    const local:ManagedRow[]=episodes.filter(isManagedDraft).map(ep=>({key:'draft:'+ep.id,kind:'draft',
      title:ep.title,code:ep.code,updated:ep.updatedAt,stage:'草稿（未进入生产）',draft:ep}));
    return [...local,...canonical].sort((a,b)=>(Date.parse(b.updated)||0)-(Date.parse(a.updated)||0));
  },[episodes,official]);
  const matches=rows.filter(item=>[item.title,item.code,item.stage,item.draft?.synopsis||''].join(' ').toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const selectedPage=Math.min(page,Math.max(1,Math.ceil(matches.length/10)));
  const beginCreate=()=>{setProfile(emptyProfile());setFormError('');setModal({mode:'create'});};
  const beginEdit=(ep:Episode)=>{setProfile({title:ep.title,synopsis:ep.synopsis||'',genre:ep.genre||'未分类'});setFormError('');setModal({mode:'edit',id:ep.id});};
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
      onOk:()=>{onDeleteDraft(ep.id);setPage(1);}
    });
  };
  return <section id="storyos-managed-works" aria-label="作品增删改查" className="min-w-0 space-y-3 border-t border-[var(--border-subtle)] pt-3">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="os-section-heading">作品管理</h2><p className="mt-1 text-[11px] text-[var(--text-secondary)]">正式作品查阅与监控 · 本机草稿新建、编辑、删除</p></div>
      <div className="flex items-center gap-2">
        <Button size="small" icon={<RefreshCw size={13}/>} onClick={()=>setRefreshKey(v=>v+1)}>刷新正式作品</Button>
        <Button size="small" type="primary" icon={<FilePlus2 size={13}/>} onClick={beginCreate}>新建作品</Button>
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-3">
      <Input prefix={<Search size={14}/>} value={search} onChange={event=>{setSearch(event.target.value);setPage(1);}} placeholder="搜索作品名称、编号、阶段" allowClear className="max-w-[350px]" aria-label="搜索正式作品与本机草稿"/>
      <span className="text-[11px] text-[var(--text-tertiary)]">正式 {official.length} 部 · 本机草稿 {episodes.filter(isManagedDraft).length} 部</span>
      {serverState==='loading'&&<span role="status" className="text-[11px] text-[var(--text-tertiary)]">正在读取正式目录…</span>}
    </div>
    {warning&&<p role="alert" className="text-[11px] text-[var(--warning)]">{warning}</p>}
    <Table<ManagedRow> rowKey="key" size="small" dataSource={matches} scroll={{x:760}}
      locale={{emptyText:serverState==='loading'?'正在读取作品…':'没有匹配的作品'}}
      columns={[
        {title:'作品',key:'title',render:(_,item)=><div className="min-w-0"><div className="truncate text-[13px] font-medium" title={item.title}>{item.title}</div><div className="text-[11px] text-[var(--text-tertiary)]">{item.code} · {item.kind==='runtime'?'正式 Runtime':'浏览器草稿'}</div></div>},
        {title:'状态',key:'stage',width:155,render:(_,item)=><span className="text-[12px] text-[var(--text-secondary)]">{item.stage}</span>},
        {title:'更新时间',key:'date',width:140,render:(_,item)=><span className="tabular-nums text-[11px] text-[var(--text-tertiary)]">{item.updated?item.updated.replace('T',' ').slice(0,16):'未知'}</span>},
        {title:'操作',key:'action',width:240,render:(_,item)=><div className="flex items-center gap-2 whitespace-nowrap">
          <Button type="link" size="small" onClick={()=>item.kind==='draft'?onSelectDraft(item.draft!):onOpenRuntimeEpisode(item.official!.episode_ref!)}>查看 <ArrowRight size={12}/></Button>
          {item.kind==='draft'?<>
            <Button size="small" icon={<Pencil size={12}/>} aria-label={'编辑草稿 '+item.title} onClick={()=>beginEdit(item.draft!)}>编辑</Button>
            <Button size="small" danger icon={<Trash2 size={12}/>} aria-label={'删除草稿 '+item.title} onClick={()=>confirmDelete(item.draft!)}>删除</Button>
          </>:<Tooltip title="正式作品关联 MySQL、生产锁与审核证据，必须经授权流程编辑或归档；此只读控制台不允许直接修改">
            <span className="text-[11px] text-[var(--text-tertiary)]">编辑/归档需授权</span>
          </Tooltip>}
        </div>},
      ]}
      pagination={{current:selectedPage,pageSize:10,total:matches.length,showSizeChanger:false,onChange:setPage,showTotal:n=>'共 '+n+' 部'}}
    />
    <p className="text-[11px] text-[var(--text-tertiary)]">新建操作保存为当前浏览器草稿，不会自动注册正式 Episode 或启动模型。正式作品的改名、归档和物理清理必须经生产控制面权限核验。</p>
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
