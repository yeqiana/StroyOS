import React, {useEffect, useMemo, useState} from 'react';
import {ArrowLeft, ArrowRight, Image as ImageIcon, RefreshCw} from 'lucide-react';
import {platformApi, stageLabel, type RuntimeStatusDetail, type RuntimeStatusSummary} from '../../api/platformApi';
import {PRODUCTION_MILESTONES, projectProductionProgress} from '../../api/productionProgress';
import {useLocalCandidateMedia} from '../../api/localCandidateMedia';
import {useLocalApprovedMedia} from '../../api/localApprovedMedia';

interface Props {
  episodeRef: string;
  onBack: () => void;
  onOpenMonitor: (ref: string) => void;
}
const validRef=(ref:string)=>/^LOCAL_[a-f0-9]{24}$/.test(ref);

/** Canonical Runtime story workspace: real evidence only, no simulated story editing. */
export const RuntimeStoryWorkbench: React.FC<Props> = ({episodeRef,onBack,onOpenMonitor}) => {
  const {findByRuntimeRef}=useLocalCandidateMedia();
  const {findEpisode}=useLocalApprovedMedia();
  const [summary,setSummary]=useState<RuntimeStatusSummary|null>(null);
  const [detail,setDetail]=useState<RuntimeStatusDetail|null>(null);
  const [status,setStatus]=useState<'loading'|'ready'|'error'>('loading');
  const [refreshKey,setRefreshKey]=useState(0);
  const [checkedAt,setCheckedAt]=useState('');

  useEffect(()=>{
    let active=true;
    let busy=false;
    setSummary(null);setDetail(null);setStatus('loading');
    const refresh=async()=>{
      if(!active||busy)return;
      busy=true;
      try {
        if(!validRef(episodeRef))throw Error('INVALID_EPISODE_REF');
        const list=await platformApi.runtimeStatuses(100,0);
        const matches=list.items.filter(item=>item.episode_ref===episodeRef &&
          item.state_source!=='isolated-test');
        if(matches.length!==1)throw Error('EPISODE_IDENTITY_NOT_UNIQUE');
        const row=matches[0];
        const evidence=await platformApi.runtimeStatus(episodeRef);
        // A canonical ref is the only cross-source join key. Never match by title.
        if(!evidence||evidence.episode_ref!==episodeRef ||
           evidence.business_episode_id!==row.business_episode_id ||
           evidence.title!==row.title)throw Error('EPISODE_DETAIL_IDENTITY_MISMATCH');
        if(!active)return;
        setSummary(row);setDetail(evidence);setStatus('ready');
        setCheckedAt(new Date().toLocaleTimeString('zh-CN',{hour12:false}));
      }catch{
        if(active){setStatus('error');setSummary(null);setDetail(null);}
      }finally{busy=false;}
    };
    void refresh();
    const timer=window.setInterval(()=>{if(document.visibilityState!=='hidden')void refresh();},15000);
    return ()=>{active=false;window.clearInterval(timer);};
  },[episodeRef,refreshKey]);

  const candidate=findByRuntimeRef(episodeRef);
  const approved=summary?findEpisode(summary.title,summary.business_episode_id):undefined;
  const confirmedApproved=approved?.episode_ref===episodeRef?approved:undefined;
  const progress=useMemo(()=>summary?projectProductionProgress(summary,detail):null,[summary,detail]);
  const images=confirmedApproved?.frames??[];
  const lastCandidate=candidate?.preview;
  return <section id="storyos-runtime-story-workbench" aria-label="故事制作详情" data-episode-ref={episodeRef} className="min-w-0 space-y-5 pb-8">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-3">
      <div className="min-w-0">
        <button type="button" className="mb-2 inline-flex items-center gap-1 text-[12px] text-[var(--text-secondary)] hover:text-[var(--info)]" onClick={onBack}><ArrowLeft size={14}/> 返回工作台</button>
        <h1 className="os-page-heading">故事制作详情</h1>
        <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">正式生产作品 · 工作区证据只读 · 未确认的内容不推断为已完成</p>
      </div>
      <div className="flex gap-2">
        <button type="button" className="inline-flex items-center gap-1 rounded-[4px] border border-[var(--border-normal)] px-3 py-1.5 text-[12px]" onClick={()=>setRefreshKey(x=>x+1)}><RefreshCw size={13}/> 刷新</button>
        <button type="button" className="inline-flex items-center gap-1 rounded-[4px] border border-[var(--border-normal)] px-3 py-1.5 text-[12px] text-[var(--info)]" onClick={()=>onOpenMonitor(episodeRef)}>生产监控 <ArrowRight size={13}/></button>
      </div>
    </header>
    {status==='loading' ? <p role="status">正在核验作品身份和制作记录…</p> :
      status==='error'||!summary||!detail ? <div role="alert" className="space-y-2 text-[12px] text-[var(--warning)]"><p>作品制作记录读取失败或身份无法核验，没有使用同名作品的历史快照替代。</p><button type="button" className="underline" onClick={()=>setRefreshKey(x=>x+1)}>重新读取</button></div> :
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0"><h2 className="text-[22px] font-semibold">{summary.title}</h2><p className="mt-1 text-[12px] text-[var(--text-tertiary)]">{summary.business_episode_id||'业务编号待核验'} · {stageLabel(summary.production_stage||'NO_STATE')} · {summary.state_source==='mysql_episode_state_read_only'?'MySQL 权威阶段':'本机历史文件阶段'}</p></div>
        <span className="text-[11px] text-[var(--text-tertiary)]">同步 {checkedAt||'未知'}</span>
      </div>
      <section aria-label="故事内容" className="space-y-2">
        <h3 className="os-section-heading">故事内容</h3>
        <p className="whitespace-pre-wrap text-[13px] leading-7 text-[var(--text-secondary)]">{detail.story_excerpt?.trim()||'尚无可核验的故事简介，不能用其他作品文案替代。'}</p>
        <p className="text-[11px] text-[var(--text-tertiary)]">{detail.story_excerpt?'来源：本机故事草稿（非发布审核文本）':'完整剧本暂未通过只读接口开放'}</p>
      </section>
      <section aria-label="制作阶段" className="space-y-3 border-t border-[var(--border-subtle)] pt-4">
        <div className="flex items-center justify-between gap-2"><h3 className="os-section-heading">制作流程</h3><span className="text-[12px] tabular-nums">{progress?.completedSteps!==null && progress?.completedSteps!==undefined ? progress.completedSteps+' / '+PRODUCTION_MILESTONES.length+' 阶段 · '+progress.stagePercent+'%' : '阶段待核验'}</span></div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">{PRODUCTION_MILESTONES.map((step,index)=><div key={step} className="min-w-0 border-t border-[var(--border-normal)] pt-2 text-[11px]"><span className={progress?.completedSteps!==null && progress?.completedSteps!==undefined && index<progress.completedSteps?'text-[var(--info)]':'text-[var(--text-tertiary)]'}>{index+1}. {step}</span><p className="mt-1 text-[10px] text-[var(--text-tertiary)]">{progress?.completedSteps!==null && progress?.completedSteps!==undefined && index<progress.completedSteps?'阶段通过':'尚未确认通过'}</p></div>)}</div>
        <p className="text-[12px] text-[var(--text-secondary)]">最近记录节点：{detail.current_action||'待核验'} · 执行状态：{progress?.stateLabel||'未核验'} · {progress?.evidenceLabel||'执行证据未读取'}</p>
        {progress?.blockedReason && <p role="alert" className="text-[12px] text-[var(--danger)]">阻断原因：{progress.blockedReason}</p>}
      </section>
      <section aria-label="故事分镜素材" className="space-y-3 border-t border-[var(--border-subtle)] pt-4">
        <div><h3 className="os-section-heading">分镜与图片素材</h3><p className="mt-1 text-[11px] text-[var(--text-tertiary)]">已批准素材与未审核候选图严格区分；候选文件数量不等于成功帧数。</p></div>
        {lastCandidate&&<div className="flex flex-wrap gap-4"><img src={lastCandidate.url} alt={'第'+lastCandidate.frame+'帧生成候选预览，未经审核'} className="max-h-[310px] max-w-full rounded-[4px] object-contain sm:max-w-[245px]"/><div className="space-y-2 text-[12px]"><p className="font-medium">最近生成候选 · 待审核</p><p>第 {lastCandidate.frame} 帧 · 检测到 {candidate?.candidate_count} 个候选文件</p><p className="text-[var(--text-tertiary)]">该图片不代表生产通过，也不具备发布资格。</p></div></div>}
        {images.length>0&&<div><p className="mb-2 text-[12px]">已批准素材：{images.length} 帧</p><div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-8">{images.map(frame=><div key={frame.frame} className="min-w-0"><img className="aspect-[4/5] w-full object-cover" loading="lazy" alt={'已批准第'+frame.frame+'帧'} src={frame.url}/><span className="text-[10px] text-[var(--text-tertiary)]">Frame {frame.frame}</span></div>)}</div></div>}
        {!lastCandidate&&!images.length&&<div className="flex items-center gap-2 text-[12px] text-[var(--text-tertiary)]"><ImageIcon size={18}/>本机尚无符合安全读取规则的真实候选图或批准素材</div>}
      </section>
    </>}
  </section>;
};
