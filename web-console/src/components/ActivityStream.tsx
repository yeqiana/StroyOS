import React, { useState } from 'react';
import {Button, Drawer, Pagination, Segmented, Select} from 'antd';
import { AlertCircle, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Clock3, Copy, ExternalLink, Image as ImageIcon, LayoutGrid, Images, ClipboardCheck, Link2, Pin, PinOff, ScanEye, ShieldAlert, SlidersHorizontal } from 'lucide-react';
import { Episode } from '../types';
import {useLocalApprovedMedia} from '../api/localApprovedMedia';
import {loadLocalReferenceDraft, saveLocalReferenceDraft, type LocalReferenceDraft} from '../utils/localReferenceDraft';
import {summarizeConsistency} from '../utils/consistencySummary';

interface ActivityStreamProps {
  activeEpisode: Episode;
  onGenerateBatch: () => void;
  isGeneratingBatch: boolean;
  onReviewAction: (frameId: string, action: 'pass' | 'inpaint' | 'reject') => void;
  onShowToast: (msg: string) => void;
}

const hasVerifiedPreview=(url?:string)=>Boolean(url && !url.startsWith('data:image/svg+xml') && !url.includes('/placeholder'));
const verdictColor: Record<string,string> = { PASS: 'text-[var(--success)]', WARN: 'text-[var(--warning)]', FAIL: 'text-[var(--danger)]' };
type FrameSelection = {frame:number;kind:'approved'|'batch'};
export const ActivityStream: React.FC<ActivityStreamProps> = ({ activeEpisode, onShowToast }) => {
  const copyBatchPrompt = async (prompt: string) => {
    try {
      await navigator.clipboard.writeText(prompt);
      onShowToast('已复制当前批次的历史 Prompt');
    } catch {
      onShowToast('复制失败，请在分镜详情中手动选择 Prompt');
    }
  };
  const [expanded, setExpanded] = useState(false);
  const [consistencyOpen,setConsistencyOpen]=useState(false);
  const [reviewPage, setReviewPage] = useState(1);
  const [reviewVerdict, setReviewVerdict] = useState<'ALL'|'PASS'|'WARN'|'FAIL'|'NEEDS_ATTENTION'>('ALL');
  const [canvasMode,setCanvasMode]=useState<'approved'|'batch'>('approved');
  const [selectedFrame,setSelectedFrame]=useState<FrameSelection|null>(null);
  const [pinnedFrame,setPinnedFrame]=useState<FrameSelection|null>(null);
  // Selected reference candidates are local UI drafts, not a production binding.
  const [referenceDraft,setReferenceDraft]=useState<LocalReferenceDraft>(()=>loadLocalReferenceDraft(activeEpisode.id));
  const quickNavRef=React.useRef<HTMLDivElement|null>(null);
  const {findEpisode}=useLocalApprovedMedia();
  const approved=findEpisode(activeEpisode.title,activeEpisode.code);
  const reviews = activeEpisode.frameReviews ?? [];
  const batch = activeEpisode.currentBatch;
  const warnings = reviews.filter(x => x.verdict !== 'PASS');
  const consistency=summarizeConsistency(reviews);
  const hasPreview=Boolean(batch?.items.some(item=>hasVerifiedPreview(item.imageUrl)));
  const hasApproved=Boolean(approved?.frames.length);
  const activeCanvasMode=hasApproved?canvasMode:'batch';
  const selectedApprovedFrame=selectedFrame?.kind==='approved'?approved?.frames.find(item=>item.frame===selectedFrame.frame):undefined;
  const selectedBatchFrame=selectedFrame?.kind==='batch'?batch?.items.find(item=>item.frameIndex===selectedFrame.frame):undefined;
  const selectedImageUrl=selectedApprovedFrame?.url||(hasVerifiedPreview(selectedBatchFrame?.imageUrl)?selectedBatchFrame?.imageUrl:undefined);
  const selectedReview=selectedFrame?reviews.find(review=>review.frameIndex===selectedFrame.frame):undefined;
  // A frame-number match is evidence of storyboard planning, never of image-reference binding.
  const selectedStoryboardBeat=selectedFrame?activeEpisode.storyboardBeats?.find(beat=>beat.beatIndex===selectedFrame.frame):undefined;
  const frameOrder=selectedFrame?.kind==='approved'?(approved?.frames.map(item=>item.frame)||[]):(batch?.items.map(item=>item.frameIndex)||[]);
  const orderedFrames=[...new Set(frameOrder)].sort((a,b)=>a-b);
  const framePosition=selectedFrame?orderedFrames.indexOf(selectedFrame.frame):-1;
  const previousFrame=framePosition>0?orderedFrames[framePosition-1]:null;
  const nextFrame=framePosition>=0&&framePosition<orderedFrames.length-1?orderedFrames[framePosition+1]:null;
  const attentionFrames=[...new Set(warnings.map(review=>review.frameIndex))].sort((a,b)=>a-b);
  const approvedNumbers=new Set((approved?.frames||[]).map(frame=>frame.frame));
  const batchNumbers=new Set((batch?.items||[]).map(frame=>frame.frameIndex));
  // Revalidate the exact approved image URL; never silently relink to a replaced asset.
  const verifiedLinks=Object.fromEntries(Object.entries(referenceDraft).filter(([target,link])=>
    Number(target)!==link.sourceFrame && (approvedNumbers.has(Number(target))||batchNumbers.has(Number(target))) && approved?.frames.some(source=>source.frame===link.sourceFrame&&source.url===link.sourceUrl)
  )) as LocalReferenceDraft;
  const linkedCount=Object.keys(verifiedLinks).length;
  const selectedReference=selectedFrame?verifiedLinks[selectedFrame.frame]:undefined;
  const selectedReferenceImage=selectedReference?approved?.frames.find(frame=>frame.frame===selectedReference.sourceFrame&&frame.url===selectedReference.sourceUrl):undefined;
  const setReferenceForFrame=(target:number,sourceFrame:number|null)=>{
    if(!Number.isInteger(target)||target<1||target>20)return;
    const next={...referenceDraft};
    if(sourceFrame===null)delete next[target];
    else {
      const source=approved?.frames.find(frame=>frame.frame===sourceFrame&&frame.frame!==target&&hasVerifiedPreview(frame.url));
      if(!source)return;
      next[target]={sourceFrame:source.frame,sourceUrl:source.url};
    }
    setReferenceDraft(next);
    if(!saveLocalReferenceDraft(activeEpisode.id,next))onShowToast('浏览器本地保存不可用，本页参考草稿仍可预览');
  };
  const jumpTo=(id:string)=>document.getElementById(id)?.scrollIntoView({block:'start',behavior:'smooth'});
  const openRecordedFrame=(frame:number)=>{
    if(!approvedNumbers.has(frame)&&!batchNumbers.has(frame))return;
    const kind=approvedNumbers.has(frame)?'approved':'batch';
    setCanvasMode(kind);
    setSelectedFrame({frame,kind});
  };
  const openReferenceTool=()=>{
    if(selectedFrame)return;
    const frame=approved?.frames[0]?.frame??batch?.items[0]?.frameIndex;
    if(frame!==undefined)openRecordedFrame(frame);
  };
  const nextAttention=selectedFrame&&attentionFrames.length?(attentionFrames.find(frame=>frame>selectedFrame.frame)||attentionFrames[0]):null;
  const pinnedImageUrl=pinnedFrame?.kind==='approved'?approved?.frames.find(item=>item.frame===pinnedFrame.frame)?.url:(pinnedFrame?.kind==='batch'?batch?.items.find(item=>item.frameIndex===pinnedFrame.frame)?.imageUrl:undefined);
  const validPinnedImageUrl=hasVerifiedPreview(pinnedImageUrl)?pinnedImageUrl:undefined;
  const comparing=Boolean(selectedFrame&&pinnedFrame&&validPinnedImageUrl&&selectedImageUrl&&selectedFrame.frame!==pinnedFrame.frame);
  React.useEffect(()=>{
    const strip=quickNavRef.current;
    if(!selectedFrame||!strip)return;
    const align=()=>{
      const current=strip.querySelector<HTMLElement>('[aria-current="true"]');
      if(!current||!strip.clientWidth)return;
      const a=strip.getBoundingClientRect(),b=current.getBoundingClientRect();
      strip.scrollTo({left:strip.scrollLeft+(b.left-a.left)-(strip.clientWidth-b.width)/2,behavior:'auto'});
    };
    align();
    const raf=requestAnimationFrame(align);
    // Inspector widens when compare mode is pinned; measure again during that layout change.
    const observer=new ResizeObserver(align);
    observer.observe(strip);
    return()=>{cancelAnimationFrame(raf);observer.disconnect();};
  },[selectedFrame?.frame,selectedFrame?.kind,pinnedFrame?.frame]);
  React.useEffect(()=>{
    if(!selectedFrame)return;
    const keyHandler=(event:KeyboardEvent)=>{
      if(event.altKey||event.ctrlKey||event.metaKey||event.shiftKey||event.defaultPrevented||event.target instanceof HTMLInputElement||event.target instanceof HTMLTextAreaElement)return;
      const target=event.target as HTMLElement|null;
      if(target instanceof Element && (target instanceof HTMLElement && target.isContentEditable || target.closest('select,[role="combobox"],[contenteditable="true"]')))return;
      const frame=event.key==='ArrowLeft'?previousFrame:event.key==='ArrowRight'?nextFrame:null;
      if(frame===null)return;
      event.preventDefault();
      setSelectedFrame({frame,kind:selectedFrame.kind});
    };
    document.addEventListener('keydown',keyHandler);
    return()=>document.removeEventListener('keydown',keyHandler);
  },[selectedFrame,previousFrame,nextFrame]);
  const filteredReviews=reviewVerdict==='ALL'?reviews:reviewVerdict==='NEEDS_ATTENTION'?warnings:reviews.filter(item=>item.verdict===reviewVerdict);
  const safeReviewPage=Math.min(reviewPage,Math.max(1,Math.ceil(filteredReviews.length/10)));
  const pageReviews=filteredReviews.slice((safeReviewPage-1)*10,safeReviewPage*10);
  return <section className="space-y-4 pb-6 text-[var(--text-primary)]">
    <header className="os-console-toolbar flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-[14px] font-semibold">制作与审核记录</h2><p className="mt-1 text-[12px] text-[var(--text-tertiary)]">素材与分镜优先 · 审核证据在右 · 本机工作区只读</p></div>
      <span className="text-[11px] text-[var(--text-tertiary)]">正式出图与返修需受控 Runtime 接口</span>
    </header>
    <nav aria-label="创作工具快捷导航" className="flex flex-wrap items-center gap-1 border-y border-[var(--border-subtle)] py-1 text-[12px]">
      {[
        {label:'帧定位',icon:LayoutGrid,target:'storyos-creator-frame-index'},
        {label:'素材画布',icon:Images,target:'storyos-creator-canvas'},
        {label:'审核记录',icon:ClipboardCheck,target:'storyos-creator-review'}
      ].map(tool=>{const Icon=tool.icon;return <button key={tool.target} type="button" onClick={()=>jumpTo(tool.target)} className="inline-flex h-8 items-center gap-1.5 rounded-[4px] px-2 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"><Icon size={14} strokeWidth={1.75} aria-hidden="true"/>{tool.label}</button>;})}
      <button type="button" aria-expanded={consistencyOpen} onClick={()=>{
        setConsistencyOpen(true);
        requestAnimationFrame(()=>jumpTo('storyos-creator-consistency'));
      }} className="inline-flex h-8 items-center gap-1.5 rounded-[4px] px-2 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"><ScanEye size={14} strokeWidth={1.75} aria-hidden="true"/>一致性检视</button>
      <button type="button" disabled={!hasApproved&&!batch?.items.length} onClick={openReferenceTool} className="inline-flex h-8 items-center gap-1.5 rounded-[4px] px-2 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] disabled:opacity-40"><Link2 size={14} strokeWidth={1.75} aria-hidden="true"/>参考关联{linkedCount>0&&<span className="tabular-nums text-[var(--text-tertiary)]">({linkedCount} 草稿)</span>}</button>
      <span className="ml-auto text-[11px] text-[var(--text-tertiary)]">仅创作视图 · 不执行生产</span>
    </nav>
    <section id="storyos-creator-frame-index" aria-label="20帧快速定位" className="space-y-2 border-y border-[var(--border-subtle)] py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="text-[12px] font-semibold">20 帧快速定位</h3>
          <span className="text-[11px] text-[var(--text-tertiary)]">有批准素材 {approvedNumbers.size} 帧 · 有批次记录 {batchNumbers.size} 帧 · 需检查 {attentionFrames.length} 帧</span>
        </div>
        <Button size="small" disabled={!attentionFrames.some(frame=>approvedNumbers.has(frame)||batchNumbers.has(frame))}
          onClick={()=>{const frame=attentionFrames.find(f=>approvedNumbers.has(f)||batchNumbers.has(f));if(frame)openRecordedFrame(frame);}}>
          定位首个待查帧
        </Button>
      </div>
      <div className="grid grid-cols-10 gap-1 sm:grid-cols-20" role="group" aria-label="逐帧索引">
        {Array.from({length:20},(_,i)=>i+1).map(frame=>{
          const review=reviews.find(item=>item.frameIndex===frame);
          const hasAsset=approvedNumbers.has(frame)||batchNumbers.has(frame);
          const selected=selectedFrame?.frame===frame;
          const color=selected?'border-[var(--info)] bg-[var(--bg-selected)] text-[var(--text-primary)]'
            :review?.verdict==='FAIL'?'border-[var(--danger)] text-[var(--danger)]'
            :review?.verdict==='WARN'?'border-[var(--warning)] text-[var(--warning)]'
            :'border-[var(--border-subtle)] text-[var(--text-secondary)]';
          return <button key={frame} type="button" disabled={!hasAsset} onClick={()=>openRecordedFrame(frame)}
            aria-label={'定位第 '+frame+' 帧'+(review?'，审核 '+review.verdict:'')+(approvedNumbers.has(frame)?'，有批准素材':'')}
            aria-pressed={selected}
            title={hasAsset?'第 '+frame+' 帧 · '+(review?.verdict||'无审核结论'):'第 '+frame+' 帧 · 未发现可检视帧证据'}
            className={'min-h-8 rounded-[4px] border text-[11px] tabular-nums transition-colors '+color+' '+(hasAsset?'hover:bg-[var(--bg-hover)]':'cursor-not-allowed opacity-35')}><span>{String(frame).padStart(2,'0')}</span>{verifiedLinks[frame]&&<span className="ml-0.5 text-[9px] text-[var(--info)]" aria-label="有本地参考草稿">↗</span>}</button>;
        })}
      </div>
      <p className="text-[11px] text-[var(--text-tertiary)]">可点击表示有可检视的批准图或批次帧；灰色表示无可检视帧证据。数字边框仅标记已有审核结论，不代表自动生成或通过。</p>
    </section>

    <section id="storyos-creator-consistency" aria-label="20帧一致性检视" className="border-y border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0"><h3 className="text-[12px] font-semibold">20 帧一致性线索</h3>
          <p className="mt-1 text-[11px] tabular-nums text-[var(--text-tertiary)]">已有审核记录 {consistency.reviewed}/20 帧 · 无审核记录 {consistency.unreviewed} 帧 · 待查 {consistency.alerts} 帧</p>
        </div>
        <button type="button" aria-controls="storyos-consistency-details" aria-expanded={consistencyOpen} aria-label={consistencyOpen?'收起一致性线索':'展开一致性线索'} onClick={()=>setConsistencyOpen(open=>!open)}
          className="inline-flex h-8 items-center gap-1 rounded-[4px] px-2 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]">{consistencyOpen?'收起':'展开'}{consistencyOpen?<ChevronDown size={14}/>:<ChevronRight size={14}/>}</button>
      </div>
      {consistencyOpen&&<div id="storyos-consistency-details" className="mt-3 space-y-3 text-[12px]">
        <p className="text-[11px] text-[var(--text-tertiary)]">仅按已有 WARN / FAIL 的审核问题标签归类，帮助定位人物、画风、场景问题；没有命中不代表一致性通过，不执行图像相似度计算。</p>
        {consistency.reviewed===0?<p role="status" className="py-2 text-[var(--text-secondary)]">暂无真实逐帧审核记录，无法判断角色、画风或场景是否一致。</p>:
          <div className="grid gap-2 lg:grid-cols-3">
            {consistency.categories.map(category=><div key={category.id} className="min-w-0 border-l-2 border-[var(--border-normal)] pl-3" aria-label={category.label+'审核标签'}>
              <div className="flex items-center justify-between gap-2"><h4 className="font-semibold">{category.label}</h4><span className="text-[11px] tabular-nums text-[var(--text-tertiary)]">{category.frames.length} 帧标签命中</span></div>
              <div className="mt-2 flex flex-wrap items-center gap-1">
                {category.frames.length?category.frames.map(frame=>(approvedNumbers.has(frame)||batchNumbers.has(frame))?
                  <button type="button" key={frame} aria-label={'从'+category.label+'定位 Frame '+frame} onClick={()=>openRecordedFrame(frame)} className="min-h-7 rounded-[4px] border border-[var(--border-subtle)] px-2 tabular-nums text-[11px] hover:border-[var(--info)]">F{String(frame).padStart(2,'0')}</button>
                  :<span key={frame} title="仅有审核记录，没有可检视图片或批次证据" className="rounded-[4px] border border-dashed border-[var(--border-subtle)] px-2 py-1 tabular-nums text-[11px] text-[var(--text-tertiary)]">F{String(frame).padStart(2,'0')} · 无图</span>)
                  :<span className="text-[11px] text-[var(--text-tertiary)]">未命中标签 · 未验证是否一致</span>}
              </div>
            </div>)}
          </div>}
        {!!consistency.unclassified.length&&<p className="text-[11px] text-[var(--text-secondary)]">另有 {consistency.unclassified.length} 帧 WARN / FAIL 无对应分类标签：{consistency.unclassified.map(frame=>'F'+String(frame).padStart(2,'0')).join('、')}。请查看原始审核意见。</p>}
      </div>}
    </section>

    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(330px,1fr)]" aria-label="当前批次与审核双栏工作区">
    <section id="storyos-creator-canvas" className="min-w-0 border border-[var(--border-subtle)] rounded-[6px] bg-[var(--bg-surface)]" aria-label="分镜与素材创作画布">
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 border-b border-[var(--border-subtle)]">
        <div><h3 className="text-[13px] font-semibold">分镜画布</h3><p className="mt-1 text-[11px] text-[var(--text-tertiary)]">{activeCanvasMode==='approved'?`已批准素材 · ${approved?.frames.length||0} 张`:(batch?.batchName || '暂无批次证据')}</p></div>
        <Segmented size="small" aria-label="分镜画布内容" value={activeCanvasMode} onChange={value=>{setCanvasMode(value as 'approved'|'batch');setSelectedFrame(null);setPinnedFrame(null);}} options={[{value:'batch',label:`当前批次 (${batch?.items.length||0})`},...(hasApproved?[{value:'approved',label:`已批准 (${approved?.frames.length||0})`}]:[])]}/>
      </div>
      {pinnedFrame&&<div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-subtle)] bg-[var(--bg-workspace)] px-3 py-2 text-[12px]" aria-label="分镜对照工具栏"><span className="flex items-center gap-2 text-[var(--text-secondary)]"><Pin size={13}/>固定对照 Frame {String(pinnedFrame.frame).padStart(2,'0')} · {validPinnedImageUrl?'可验证图片':'图片证据不可用'}</span><Button size="small" onClick={()=>setPinnedFrame(null)} icon={<PinOff size={13}/>}>清除对照</Button></div>}
      <div className="grid min-w-0 gap-0 lg:grid-cols-[176px_minmax(0,1fr)]">
        <aside className="border-b border-[var(--border-subtle)] px-3 py-3 lg:border-b-0 lg:border-r" aria-label="创作参数只读面板">
          <div className="flex items-center gap-2 text-[12px] font-semibold"><SlidersHorizontal size={14} className="text-[var(--text-secondary)]"/>创作参数</div>
          <dl className="mt-3 grid grid-cols-2 gap-3 text-[11px] lg:grid-cols-1">
            {[['图片模型',activeEpisode.runtimeRequest.imageModel],['画幅',activeEpisode.runtimeRequest.aspectRatio],['质量',activeEpisode.runtimeRequest.quality],['批次策略',activeEpisode.runtimeRequest.batchMode]].map(([label,value])=><div key={label} className="min-w-0"><dt className="text-[var(--text-tertiary)]">{label}</dt><dd className="mt-1 break-words text-[var(--text-primary)]">{value||'未提供'}</dd></div>)}
          </dl>
          <p className="mt-3 border-t border-[var(--border-subtle)] pt-2 text-[11px] leading-5 text-[var(--text-tertiary)]">参数来自工作区快照。当前不支持在此修改或发起正式生图。</p>
        </aside>
        <div className="min-w-0 p-3" aria-label="分镜视觉内容">
        {activeCanvasMode==='approved' && approved?.frames.length ? <>
          <p className="mb-3 text-[11px] text-[var(--text-tertiary)]">本机 media/approved · 已批准图片 · 点击分镜查看检视详情</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 2xl:grid-cols-4">
            {approved.frames.map(frame=><div key={frame.frame} className="group relative min-w-0"><button type="button" onClick={()=>setSelectedFrame({frame:frame.frame,kind:'approved'})} aria-label={'检视已批准 Frame '+frame.frame} aria-pressed={selectedFrame?.kind==='approved'&&selectedFrame.frame===frame.frame} className={`group min-w-0 overflow-hidden rounded-[5px] border bg-[var(--bg-elevated)] text-left hover:border-[var(--info)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus)] ${selectedFrame?.kind==='approved'&&selectedFrame.frame===frame.frame?'border-[var(--info)]':'border-[var(--border-subtle)]'}`}>
              <div className="aspect-[4/5] overflow-hidden"><img loading="lazy" src={frame.url} alt={'已批准 Frame '+frame.frame} className="h-full w-full object-cover"/></div>
              <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-[11px]"><span className="font-medium">Frame {String(frame.frame).padStart(2,'0')}</span><span className="text-[var(--text-tertiary)]">{pinnedFrame?.kind==='approved'&&pinnedFrame.frame===frame.frame?'对照固定':'已批准'}</span></div>
            </button>
            {hasVerifiedPreview(frame.url)&&<button type="button" aria-label={'固定已批准 Frame '+frame.frame+' 以对照'} title={'固定 Frame '+frame.frame+' 以对照'} onClick={()=>setPinnedFrame({frame:frame.frame,kind:'approved'})}
              className="absolute right-2 top-2 z-10 inline-flex min-h-8 items-center gap-1 rounded-[4px] border border-[var(--border-normal)] bg-[var(--bg-elevated)] px-2 text-[11px] text-[var(--text-primary)] opacity-100 hover:border-[var(--info)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus)] md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
              <Pin size={12}/>固定对照
            </button>}
            </div>)}
          </div>
        </> : <>
        {!batch?.items.length ? <div className="flex items-center gap-2 py-5 text-[13px] text-[var(--text-secondary)]"><ImageIcon size={18}/> 暂无可预览的批次帧，生成操作需使用已授权的 Runtime。</div> :
          <>
            {!hasPreview&&<p role="status" className="mb-3 flex items-center gap-2 text-[12px] text-[var(--text-secondary)]"><ImageIcon size={15} className="text-[var(--text-tertiary)]"/>本批次只记录了帧状态，尚无可验证的预览图片。下方不会用示意图冒充生成结果。</p>}
            {hasPreview ?
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 2xl:grid-cols-4">
                {batch.items.map(frame=><button type="button" key={frame.id} onClick={()=>setSelectedFrame({frame:frame.frameIndex,kind:'batch'})} aria-label={'检视批次 Frame '+frame.frameIndex} aria-pressed={selectedFrame?.kind==='batch'&&selectedFrame.frame===frame.frameIndex} className={`min-w-0 text-left hover:text-[var(--info)] ${selectedFrame?.kind==='batch'&&selectedFrame.frame===frame.frameIndex?'outline outline-2 outline-[var(--info)]':''}`}>
                  <div className="aspect-[4/5] overflow-hidden rounded-[5px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)]">
                    {hasVerifiedPreview(frame.imageUrl) ? <img loading="lazy" alt={'第 '+frame.frameIndex+' 帧'} src={frame.imageUrl} className="h-full w-full object-cover"/>:
                      <div className="flex h-full flex-col items-center justify-center gap-2 text-[var(--text-tertiary)]"><ImageIcon size={21}/><span className="text-[12px]">无可用预览</span></div>}
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-1 text-[12px]"><span className="font-medium">Frame {frame.frameIndex}</span><span className="truncate text-[var(--text-secondary)]">{frame.status}</span></div>
                </button>)}
              </div> :
              <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[6px] border border-[var(--border-subtle)] bg-[var(--border-subtle)] sm:grid-cols-4 xl:grid-cols-3 2xl:grid-cols-5">
                {batch.items.map(frame=><button type="button" key={frame.id} onClick={()=>setSelectedFrame({frame:frame.frameIndex,kind:'batch'})} aria-label={'检视批次 Frame '+frame.frameIndex} aria-pressed={selectedFrame?.kind==='batch'&&selectedFrame.frame===frame.frameIndex} className={`flex min-h-16 min-w-0 flex-col justify-between gap-1 px-3 py-2.5 text-left hover:bg-[var(--bg-hover)] ${selectedFrame?.kind==='batch'&&selectedFrame.frame===frame.frameIndex?'bg-[var(--bg-selected)] shadow-[inset_2px_0_0_var(--info)]':'bg-[var(--bg-surface)]'}`}>
                  <span className="text-[12px] font-semibold tabular-nums text-[var(--text-primary)]">{String(frame.frameIndex).padStart(2,'0')}</span>
                  <span title={frame.status} className="truncate text-[11px] text-[var(--text-secondary)]">{frame.status}</span>
                </button>)}
              </div>}
          </>}
        </>}
        </div>
      </div>
    </section>
    <section id="storyos-creator-review" className="min-w-0 border-t border-[var(--border-subtle)] pt-3 xl:border-t-0 xl:border-l xl:pl-4 xl:pt-0" aria-label="逐帧审核检视区">
      <div className="flex flex-wrap items-center justify-between gap-2"><div><h3 className="text-[14px] font-semibold">逐帧审核</h3><p className="mt-1 text-[12px] text-[var(--text-tertiary)]">已记录 {reviews.length} 项 · 需检查 {warnings.length} 项</p></div>
        <div className="flex items-center gap-2">{warnings.length ? <Button size="small" onClick={()=>{setExpanded(true);setReviewVerdict('NEEDS_ATTENTION');setReviewPage(1);}}>只看待查 ({warnings.length})</Button> : <span className="text-[11px] text-[var(--text-tertiary)]">暂无待查记录</span>}<button type="button" onClick={() => {setExpanded(!expanded);setReviewPage(1);setReviewVerdict('ALL');}} aria-expanded={expanded} className="flex items-center gap-1 text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">{expanded ? <ChevronDown size={15}/> : <ChevronRight size={15}/>} {expanded ? '收起' : '查看全部'}</button></div></div>
      {expanded && <div className="os-console-filterbar mt-3 flex flex-wrap items-center justify-between gap-2 border-y border-[var(--border-subtle)] py-2"><Select aria-label="筛选审核结论" value={reviewVerdict} onChange={value=>{setReviewVerdict(value);setReviewPage(1);}} style={{width:150}} options={[{value:"ALL",label:"全部审核结论"},{value:"NEEDS_ATTENTION",label:"待检查（WARN/FAIL）"},{value:"PASS",label:"通过 PASS"},{value:"WARN",label:"待查 WARN"},{value:"FAIL",label:"失败 FAIL"}]}/><span className="text-[12px] tabular-nums text-[var(--text-tertiary)]">已匹配 {filteredReviews.length} / {reviews.length} 项 · 已加载记录</span></div>}
      {filteredReviews.length === 0 ? <p className="mt-4 border border-dashed border-[var(--border-normal)] rounded-[6px] p-6 text-[13px] text-[var(--text-tertiary)]">{reviews.length?"当前筛选条件下无审核记录":"暂无审核记录。这里不会把未审核的帧标成通过。"}</p>
        : <div className="mt-3 divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)]">{(expanded ? pageReviews : reviews.slice(0,5)).map(review => <div key={review.frameId} className="flex min-w-0 flex-wrap items-start gap-3 py-2 sm:flex-nowrap">
          {review.verdict === 'PASS' ? <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-[var(--success)]"/> : review.verdict === 'FAIL' ? <ShieldAlert size={17} className="mt-0.5 shrink-0 text-[var(--danger)]"/> : <AlertCircle size={17} className="mt-0.5 shrink-0 text-[var(--warning)]"/>}
          <div className="flex-1 min-w-0"><div className="flex items-center gap-2 text-[13px]"><button type="button" aria-label={'检视审核 Frame '+review.frameIndex} onClick={()=>{const hasApprovedFrame=Boolean(approved?.frames.some(frame=>frame.frame===review.frameIndex));setCanvasMode(hasApprovedFrame?'approved':'batch');setSelectedFrame({frame:review.frameIndex,kind:hasApprovedFrame?'approved':'batch'});}} className="font-medium text-[var(--text-primary)] underline-offset-2 hover:text-[var(--info)] hover:underline">Frame {review.frameIndex} →</button><span className={`text-[11px] font-mono ${verdictColor[review.verdict]}`}>{review.verdict}</span></div><p className="mt-1 text-[12px] text-[var(--text-secondary)] break-words">{review.comment || review.issueTags?.join('、') || '暂无审核备注'}</p></div>
          <span className="text-[11px] text-[var(--text-tertiary)] flex items-center gap-1 shrink-0"><Clock3 size={12}/>{review.timestamp}</span>
        </div>)}</div>}
    </section>
    {expanded && filteredReviews.length>10 && <Pagination size="small" current={safeReviewPage} pageSize={10} total={filteredReviews.length} showTotal={(total,range)=>`${range[0]}–${range[1]} / 已载入 ${total} 项`} onChange={setReviewPage}/>}
    </div>
    <Drawer open={selectedFrame!==null} onClose={()=>setSelectedFrame(null)} title={selectedFrame?`Frame ${String(selectedFrame.frame).padStart(2,'0')} · 分镜检视`:'分镜检视'} width={pinnedFrame?'min(620px, 100vw)':'min(440px, 100vw)'} destroyOnClose className="storyos-creator-frame-inspector">
      {selectedFrame&&<section aria-label="创作分镜详情" className="space-y-3 text-[var(--text-primary)]">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border-subtle)] pb-3" aria-label="分镜导航">
          <div className="flex items-center gap-2">
            <Button size="small" aria-label="上一帧" icon={<ChevronLeft size={14}/>} disabled={previousFrame===null} onClick={()=>previousFrame!==null&&setSelectedFrame({frame:previousFrame,kind:selectedFrame.kind})}>上一帧</Button>
            <span className="min-w-12 text-center text-[12px] tabular-nums text-[var(--text-secondary)]">{framePosition>=0?`${framePosition+1} / ${orderedFrames.length}`:'无序列'}</span>
            <Button size="small" aria-label="下一帧" disabled={nextFrame===null} onClick={()=>nextFrame!==null&&setSelectedFrame({frame:nextFrame,kind:selectedFrame.kind})}>下一帧 <ChevronRight size={13}/></Button>
          </div>
          {pinnedFrame?<Button size="small" aria-label="取消固定对照帧" icon={<PinOff size={14}/>} onClick={()=>setPinnedFrame(null)}>结束对照</Button>:<Button size="small" aria-label="固定当前帧以对照" icon={<Pin size={14}/>} disabled={!selectedImageUrl} onClick={()=>setPinnedFrame(selectedFrame)}>固定对照</Button>}
        </div>
        <nav aria-label="分镜快速定位" className="min-w-0 space-y-2 border-b border-[var(--border-subtle)] pb-3">
          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]"><span className="text-[var(--text-tertiary)]">快速定位 · {orderedFrames.length} 帧已载入</span>{nextAttention!==null&&<Button size="small" aria-label="跳转下一待查帧" onClick={()=>{const kind=approved?.frames.some(frame=>frame.frame===nextAttention)?'approved':'batch';setCanvasMode(kind);setSelectedFrame({frame:nextAttention,kind});}}>下一待查 ({attentionFrames.length})</Button>}</div>
          <div ref={quickNavRef} className="flex min-w-0 gap-1.5 overflow-x-auto pb-1" role="group" aria-label="分镜序列缩略导航">
            {orderedFrames.map(frame=>{const url=selectedFrame.kind==='approved'?approved?.frames.find(item=>item.frame===frame)?.url:batch?.items.find(item=>item.frameIndex===frame)?.imageUrl;const actualUrl=hasVerifiedPreview(url)?url:undefined;const verdict=reviews.find(item=>item.frameIndex===frame)?.verdict;return <button key={frame} type="button" aria-label={'快速定位 Frame '+frame} aria-current={selectedFrame.frame===frame?'true':undefined} onClick={()=>setSelectedFrame({frame,kind:selectedFrame.kind})} className={`flex w-12 shrink-0 flex-col items-center gap-1 overflow-hidden border p-1 text-[11px] tabular-nums hover:border-[var(--info)] ${selectedFrame.frame===frame?'border-[var(--info)] bg-[var(--bg-selected)]':'border-[var(--border-subtle)] bg-[var(--bg-surface)]'}`} title={`Frame ${frame}${verdict?' · '+verdict:''}`}>
              {actualUrl?<span className="relative flex h-12 w-10 items-center justify-center bg-[var(--bg-workspace)] text-[var(--text-tertiary)]"><span aria-hidden="true">{String(frame).padStart(2,'0')}</span><img loading="lazy" src={actualUrl} alt="" onError={event=>{event.currentTarget.style.display='none';}} className="absolute inset-0 h-full w-full object-cover"/></span>:<span className="flex h-12 w-10 items-center justify-center bg-[var(--bg-workspace)] text-[var(--text-tertiary)]">{String(frame).padStart(2,'0')}</span>}
              <span className={verdict==='FAIL'?'text-[var(--danger)]':verdict==='WARN'?'text-[var(--warning)]':'text-[var(--text-secondary)]'}>{String(frame).padStart(2,'0')}</span>
            </button>;})}
          </div>
        </nav>
        <p className="text-[12px] text-[var(--text-secondary)]">{selectedFrame.kind==='approved'?'已批准素材 · 本机只读':'当前批次 · 工作区状态快照'} · 可使用左右方向键切换分镜</p>
        {comparing?<div className="grid grid-cols-2 gap-3" aria-label="双帧素材对照">
          <figure className="min-w-0"><figcaption className="mb-2 truncate text-[12px] font-medium">固定 Frame {String(pinnedFrame?.frame).padStart(2,'0')}</figcaption><img src={validPinnedImageUrl} alt={`用于对照的 Frame ${pinnedFrame?.frame} 已验证图片`} className="h-[280px] w-full bg-[var(--bg-workspace)] object-contain"/></figure>
          <figure className="min-w-0"><figcaption className="mb-2 truncate text-[12px] font-medium">当前 Frame {String(selectedFrame.frame).padStart(2,'0')}</figcaption><img src={selectedImageUrl} alt={`当前 Frame ${selectedFrame.frame} 已验证图片`} className="h-[280px] w-full bg-[var(--bg-workspace)] object-contain"/></figure>
        </div>:selectedImageUrl?<img src={selectedImageUrl} alt={`Frame ${selectedFrame.frame} 可验证的图片证据`} className="max-h-[55vh] w-full object-contain bg-[var(--bg-workspace)]"/>:<div className="flex items-center gap-2 border border-dashed border-[var(--border-normal)] p-4 text-[12px] text-[var(--text-secondary)]"><ImageIcon size={16}/>尚无可验证的 Frame 图片</div>}
        {pinnedFrame&&(!comparing)&&<p role="status" className="text-[11px] text-[var(--text-tertiary)]">{pinnedFrame.frame===selectedFrame.frame?'已固定当前帧。切换到其他有可信图片的分镜，即可并排对照。':'当前帧缺少可信图片，无法展示双图对照。'} </p>}
        <section aria-label="帧级参考素材草稿" className="space-y-2 border-y border-[var(--border-subtle)] py-3 text-[12px]">
          <div className="flex items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 font-semibold"><Link2 size={14} strokeWidth={1.75} aria-hidden="true"/>参考素材关联</h3>
            <span className="text-[11px] tabular-nums text-[var(--text-tertiary)]">本地草稿 {linkedCount} 帧</span>
          </div>
          <p className="text-[11px] leading-5 text-[var(--text-tertiary)]">仅建立浏览器内的拟参考关系，未提交生产；不代表此帧生成时实际使用了参考图。</p>
          {approved?.frames.length ? <>
            <Select aria-label={'为 Frame '+selectedFrame.frame+' 选择参考素材'} size="small" className="w-full" placeholder="选择同作品已批准图片作为参考"
              value={selectedReferenceImage?.frame} allowClear
              onChange={(sourceFrame:number|undefined)=>setReferenceForFrame(selectedFrame.frame,sourceFrame??null)}
              options={approved.frames.filter(source=>source.frame!==selectedFrame.frame).map(source=>({value:source.frame,label:'已批准 Frame '+String(source.frame).padStart(2,'0')}))}/>
            {selectedReferenceImage&&<div className="flex min-w-0 items-center gap-3 border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-2" aria-label="已选参考素材草稿">
              <img src={selectedReferenceImage.url} alt={'参考候选 Frame '+selectedReferenceImage.frame} className="h-16 w-12 shrink-0 object-cover" loading="lazy"/>
              <div className="min-w-0 flex-1"><p className="font-medium">Frame {String(selectedFrame.frame).padStart(2,'0')} ← Frame {String(selectedReferenceImage.frame).padStart(2,'0')}</p><p className="mt-1 text-[11px] text-[var(--text-tertiary)]">来源：本机已批准图片 · 仅拟引用</p></div>
              <Button size="small" aria-label={'移除 Frame '+selectedFrame.frame+' 的参考素材草稿'} onClick={()=>setReferenceForFrame(selectedFrame.frame,null)}>移除</Button>
            </div>}
            {pinnedFrame?.kind==='approved'&&pinnedFrame.frame!==selectedFrame.frame&&approved.frames.some(frame=>frame.frame===pinnedFrame.frame)&&
              <Button size="small" icon={<Pin size={13}/>} onClick={()=>setReferenceForFrame(selectedFrame.frame,pinnedFrame.frame)}>将固定 Frame {pinnedFrame.frame} 设为参考草稿</Button>}
            {approved.frames.length===1&&approved.frames[0].frame===selectedFrame.frame&&<p className="text-[11px] text-[var(--text-tertiary)]">没有其他可选的已批准帧。</p>}
          </>:<p className="text-[var(--text-tertiary)]">当前作品没有可验证的已批准图片，无法建立参考关联草稿。</p>}
        </section>
        <dl className="divide-y divide-[var(--border-subtle)] text-[12px]">
          <div className="grid grid-cols-[100px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">帧编号</dt><dd className="tabular-nums">{selectedFrame.frame}</dd></div>
          <div className="grid grid-cols-[100px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">证据状态</dt><dd>{selectedFrame.kind==='approved'?'approved':selectedBatchFrame?.status||'未提供'}</dd></div>
          {selectedReview&&<div className="grid grid-cols-[100px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">审核结论</dt><dd><span className={`font-medium ${verdictColor[selectedReview.verdict]}`}>{selectedReview.verdict}</span><p className="mt-1 whitespace-pre-wrap break-words leading-5 text-[var(--text-secondary)]">{selectedReview.comment||selectedReview.issueTags?.join('、')||'未记录审核备注'}</p></dd></div>}
          {selectedBatchFrame?.prompt&&<div className="grid grid-cols-[100px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">历史 Prompt</dt><dd className="min-w-0"><div className="mb-2 flex justify-end"><Button size="small" icon={<Copy size={12}/>} onClick={()=>void copyBatchPrompt(selectedBatchFrame.prompt)}>复制 Prompt</Button></div><p className="whitespace-pre-wrap break-words leading-5">{selectedBatchFrame.prompt}</p></dd></div>}
        </dl>
        <details aria-label="逐帧分镜快照" className="border-t border-[var(--border-subtle)] pt-3 text-[12px]">
          <summary className="cursor-pointer font-medium text-[var(--text-primary)]">Frame {String(selectedFrame.frame).padStart(2,'0')} · 分镜契约 {selectedStoryboardBeat?'有记录':'未提供'}</summary>
          {selectedStoryboardBeat?<dl className="mt-2 space-y-2 text-[var(--text-secondary)]">
            {selectedStoryboardBeat.sceneName&&<div><dt className="text-[var(--text-tertiary)]">场景</dt><dd className="break-words">{selectedStoryboardBeat.sceneName}</dd></div>}
            {selectedStoryboardBeat.shotType&&<div><dt className="text-[var(--text-tertiary)]">镜头</dt><dd className="break-words">{selectedStoryboardBeat.shotType}</dd></div>}
            {selectedStoryboardBeat.lighting&&<div><dt className="text-[var(--text-tertiary)]">光线</dt><dd className="break-words">{selectedStoryboardBeat.lighting}</dd></div>}
            {selectedStoryboardBeat.narration&&<div><dt className="text-[var(--text-tertiary)]">分镜描述</dt><dd className="whitespace-pre-wrap break-words">{selectedStoryboardBeat.narration}</dd></div>}
          </dl>:<p className="mt-2 text-[var(--text-tertiary)]">作品快照未提供与当前帧号匹配的分镜信息。</p>}
          <p className="mt-2 text-[11px] leading-5 text-[var(--text-tertiary)]">仅按作品快照的帧编号匹配，不代表参考素材已绑定或被实际用于生成。</p>
        </details>
        <details aria-label="作品级参考素材" className="border-y border-[var(--border-subtle)] py-3 text-[12px]">
          <summary className="cursor-pointer font-medium text-[var(--text-primary)]">作品参考 · {activeEpisode.characters.length} 人物 · {activeEpisode.visualLocks.length} 视觉锚点</summary>
          <p className="mt-2 text-[11px] leading-5 text-[var(--text-tertiary)]">仅展示当前作品快照中的参考信息；不代表素材已绑定此 Frame，也不构成正式生产授权。</p>
          {activeEpisode.characters.length>0&&<p className="mt-2 break-words text-[var(--text-secondary)]">人物：{activeEpisode.characters.map(character=>character.name).join('、')}</p>}
          {activeEpisode.visualLocks.length>0&&<p className="mt-2 break-words text-[var(--text-secondary)]">视觉锚点：{activeEpisode.visualLocks.map(lock=>lock.title).join('、')}</p>}
          {activeEpisode.characters.length===0&&activeEpisode.visualLocks.length===0&&<p className="mt-2 text-[var(--text-tertiary)]">当前快照未提供人物或视觉锚点。</p>}
        </details>
        {selectedImageUrl&&<a href={selectedImageUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 text-[12px] text-[var(--info)]">查看图片原始证据 <ExternalLink size={14}/></a>}
        <p className="border-t border-[var(--border-subtle)] pt-3 text-[11px] text-[var(--text-tertiary)]">本检视器只读。正式重绘、审核、生成与返修须由有权限的 Runtime 接口执行。</p>
      </section>}
    </Drawer>
  </section>;
};
