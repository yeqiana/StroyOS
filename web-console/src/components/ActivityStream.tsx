import React, { useState } from 'react';
import {Button, Drawer, Pagination, Segmented, Select} from 'antd';
import { AlertCircle, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Clock3, ExternalLink, Image as ImageIcon, Pin, PinOff, ShieldAlert, SlidersHorizontal } from 'lucide-react';
import { Episode } from '../types';
import {useLocalApprovedMedia} from '../api/localApprovedMedia';

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
export const ActivityStream: React.FC<ActivityStreamProps> = ({ activeEpisode }) => {
  const [expanded, setExpanded] = useState(false);
  const [reviewPage, setReviewPage] = useState(1);
  const [reviewVerdict, setReviewVerdict] = useState<'ALL'|'PASS'|'WARN'|'FAIL'|'NEEDS_ATTENTION'>('ALL');
  const [canvasMode,setCanvasMode]=useState<'approved'|'batch'>('approved');
  const [selectedFrame,setSelectedFrame]=useState<FrameSelection|null>(null);
  const [pinnedFrame,setPinnedFrame]=useState<FrameSelection|null>(null);
  const quickNavRef=React.useRef<HTMLDivElement|null>(null);
  const {findEpisode}=useLocalApprovedMedia();
  const approved=findEpisode(activeEpisode.title,activeEpisode.code);
  const reviews = activeEpisode.frameReviews ?? [];
  const batch = activeEpisode.currentBatch;
  const warnings = reviews.filter(x => x.verdict !== 'PASS');
  const hasPreview=Boolean(batch?.items.some(item=>hasVerifiedPreview(item.imageUrl)));
  const hasApproved=Boolean(approved?.frames.length);
  const activeCanvasMode=hasApproved?canvasMode:'batch';
  const selectedApprovedFrame=selectedFrame?.kind==='approved'?approved?.frames.find(item=>item.frame===selectedFrame.frame):undefined;
  const selectedBatchFrame=selectedFrame?.kind==='batch'?batch?.items.find(item=>item.frameIndex===selectedFrame.frame):undefined;
  const selectedImageUrl=selectedApprovedFrame?.url||(hasVerifiedPreview(selectedBatchFrame?.imageUrl)?selectedBatchFrame?.imageUrl:undefined);
  const selectedReview=selectedFrame?reviews.find(review=>review.frameIndex===selectedFrame.frame):undefined;
  const frameOrder=selectedFrame?.kind==='approved'?(approved?.frames.map(item=>item.frame)||[]):(batch?.items.map(item=>item.frameIndex)||[]);
  const orderedFrames=[...new Set(frameOrder)].sort((a,b)=>a-b);
  const framePosition=selectedFrame?orderedFrames.indexOf(selectedFrame.frame):-1;
  const previousFrame=framePosition>0?orderedFrames[framePosition-1]:null;
  const nextFrame=framePosition>=0&&framePosition<orderedFrames.length-1?orderedFrames[framePosition+1]:null;
  const attentionFrames=[...new Set(warnings.map(review=>review.frameIndex))].sort((a,b)=>a-b);
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
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(330px,1fr)]" aria-label="当前批次与审核双栏工作区">
    <section className="min-w-0 border border-[var(--border-subtle)] rounded-[6px] bg-[var(--bg-surface)]" aria-label="分镜与素材创作画布">
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
            {approved.frames.map(frame=><button type="button" key={frame.frame} onClick={()=>setSelectedFrame({frame:frame.frame,kind:'approved'})} aria-label={'检视已批准 Frame '+frame.frame} aria-pressed={selectedFrame?.kind==='approved'&&selectedFrame.frame===frame.frame} className={`group min-w-0 overflow-hidden rounded-[5px] border bg-[var(--bg-elevated)] text-left hover:border-[var(--info)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--focus)] ${selectedFrame?.kind==='approved'&&selectedFrame.frame===frame.frame?'border-[var(--info)]':'border-[var(--border-subtle)]'}`}>
              <div className="aspect-[4/5] overflow-hidden"><img loading="lazy" src={frame.url} alt={'已批准 Frame '+frame.frame} className="h-full w-full object-cover"/></div>
              <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-[11px]"><span className="font-medium">Frame {String(frame.frame).padStart(2,'0')}</span><span className="text-[var(--text-tertiary)]">{pinnedFrame?.kind==='approved'&&pinnedFrame.frame===frame.frame?'对照固定':'已批准'}</span></div>
            </button>)}
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
    <section className="min-w-0 border-t border-[var(--border-subtle)] pt-3 xl:border-t-0 xl:border-l xl:pl-4 xl:pt-0" aria-label="逐帧审核检视区">
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
        <dl className="divide-y divide-[var(--border-subtle)] text-[12px]">
          <div className="grid grid-cols-[100px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">帧编号</dt><dd className="tabular-nums">{selectedFrame.frame}</dd></div>
          <div className="grid grid-cols-[100px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">证据状态</dt><dd>{selectedFrame.kind==='approved'?'approved':selectedBatchFrame?.status||'未提供'}</dd></div>
          {selectedReview&&<div className="grid grid-cols-[100px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">审核结论</dt><dd><span className={`font-medium ${verdictColor[selectedReview.verdict]}`}>{selectedReview.verdict}</span><p className="mt-1 whitespace-pre-wrap break-words leading-5 text-[var(--text-secondary)]">{selectedReview.comment||selectedReview.issueTags?.join('、')||'未记录审核备注'}</p></dd></div>}
          {selectedBatchFrame?.prompt&&<div className="grid grid-cols-[100px_minmax(0,1fr)] gap-3 py-3"><dt className="text-[var(--text-tertiary)]">历史 Prompt</dt><dd className="whitespace-pre-wrap break-words leading-5">{selectedBatchFrame.prompt}</dd></div>}
        </dl>
        {selectedImageUrl&&<a href={selectedImageUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 text-[12px] text-[var(--info)]">查看图片原始证据 <ExternalLink size={14}/></a>}
        <p className="border-t border-[var(--border-subtle)] pt-3 text-[11px] text-[var(--text-tertiary)]">本检视器只读。正式重绘、审核、生成与返修须由有权限的 Runtime 接口执行。</p>
      </section>}
    </Drawer>
  </section>;
};
