import React, { useState } from 'react';
import {Pagination, Select} from 'antd';
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Clock3, Image as ImageIcon, ShieldAlert } from 'lucide-react';
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
export const ActivityStream: React.FC<ActivityStreamProps> = ({ activeEpisode }) => {
  const [expanded, setExpanded] = useState(false);
  const [reviewPage, setReviewPage] = useState(1);
  const [reviewVerdict, setReviewVerdict] = useState<'ALL'|'PASS'|'WARN'|'FAIL'>('ALL');
  const [showAllApproved,setShowAllApproved]=useState(false);
  const {findEpisode}=useLocalApprovedMedia();
  const approved=findEpisode(activeEpisode.title,activeEpisode.code);
  const reviews = activeEpisode.frameReviews ?? [];
  const batch = activeEpisode.currentBatch;
  const warnings = reviews.filter(x => x.verdict !== 'PASS');
  const hasPreview=Boolean(batch?.items.some(item=>hasVerifiedPreview(item.imageUrl)));
  const filteredReviews=reviewVerdict==='ALL'?reviews:reviews.filter(item=>item.verdict===reviewVerdict);
  const safeReviewPage=Math.min(reviewPage,Math.max(1,Math.ceil(filteredReviews.length/10)));
  const pageReviews=filteredReviews.slice((safeReviewPage-1)*10,safeReviewPage*10);
  return <section className="space-y-4 pb-6 text-[var(--text-primary)]">
    <header className="os-console-toolbar flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-[14px] font-semibold">制作与审核记录</h2><p className="mt-1 text-[12px] text-[var(--text-tertiary)]">来自当前作品的工作区证据，不代表实时执行日志。</p></div>
      <span className="text-[11px] text-[var(--text-tertiary)]">只读视图 · 写入接口未接入</span>
    </header>
    {approved?.frames.length ? <section className="space-y-3 border-y border-[var(--border-subtle)] py-4" aria-label="已批准作品素材">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><h3 className="os-section-heading">已批准作品素材 <span className="ml-1 text-[12px] font-normal text-[var(--text-secondary)]">{approved.frames.length} 张</span></h3>
          <p className="mt-1 text-[12px] text-[var(--text-tertiary)]">直接读取本地 media/approved · 只读展示；不代表本批次刚刚生成</p></div>
        {approved.frames.length>10&&<button type="button" aria-expanded={showAllApproved} onClick={()=>setShowAllApproved(v=>!v)} className="os-action">
          {showAllApproved?'收起图片':'查看全部图片'}
        </button>}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-10">
        {(showAllApproved?approved.frames:approved.frames.slice(0,10)).map(frame=><a key={frame.frame} href={frame.url} target="_blank" rel="noopener noreferrer" title={'查看已批准 Frame '+frame.frame} className="group min-w-0 overflow-hidden rounded-[5px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:border-[var(--info)]">
          <div className="aspect-[4/5] overflow-hidden bg-[var(--bg-elevated)]"><img loading="lazy" src={frame.url} alt={'已批准第 '+frame.frame+' 帧'} onError={event=>{event.currentTarget.style.display='none';}} className="h-full w-full object-cover transition-opacity group-hover:opacity-90"/></div>
          <div className="flex items-center justify-between px-2 py-1.5 text-[12px]"><span className="font-medium">Frame {String(frame.frame).padStart(2,'0')}</span><span className="text-[var(--text-tertiary)]">已批准</span></div>
        </a>)}
      </div>
    </section> : null}
    <div className="border border-[var(--border-subtle)] rounded-[6px] bg-[var(--bg-surface)]">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
        <div><p className="text-[13px] font-medium">当前批次</p><p className="mt-1 text-[12px] text-[var(--text-tertiary)]">{batch?.batchName || '暂无批次证据'}</p></div>
        <span className="text-[12px] text-[var(--text-secondary)]">{batch ? `${batch.items.length} 帧 · ${batch.status}` : '尚无数据'}</span>
      </div>
      <div className="px-4 py-3">
        {!batch?.items.length ? <div className="flex items-center gap-2 py-5 text-[13px] text-[var(--text-secondary)]"><ImageIcon size={18}/> 暂无可预览的批次帧，生成操作需使用已授权的 Runtime。</div> :
          <>
            {!hasPreview&&<p role="status" className="mb-3 flex items-center gap-2 text-[12px] text-[var(--text-secondary)]"><ImageIcon size={15} className="text-[var(--text-tertiary)]"/>本批次只记录了帧状态，尚无可验证的预览图片。下方不会用示意图冒充生成结果。</p>}
            {hasPreview ?
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6">
                {batch.items.map(frame=><div key={frame.id} className="min-w-0">
                  <div className="aspect-[4/5] overflow-hidden rounded-[5px] border border-[var(--border-subtle)] bg-[var(--bg-elevated)]">
                    {hasVerifiedPreview(frame.imageUrl) ? <img loading="lazy" alt={'第 '+frame.frameIndex+' 帧'} src={frame.imageUrl} className="h-full w-full object-cover"/>:
                      <div className="flex h-full flex-col items-center justify-center gap-2 text-[var(--text-tertiary)]"><ImageIcon size={21}/><span className="text-[12px]">无可用预览</span></div>}
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-1 text-[12px]"><span className="font-medium">Frame {frame.frameIndex}</span><span className="truncate text-[var(--text-secondary)]">{frame.status}</span></div>
                </div>)}
              </div> :
              <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[6px] border border-[var(--border-subtle)] bg-[var(--border-subtle)] sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-10">
                {batch.items.map(frame=><div key={frame.id} className="flex min-h-16 flex-col justify-between gap-1 bg-[var(--bg-surface)] px-3 py-2.5">
                  <span className="text-[12px] font-semibold tabular-nums text-[var(--text-primary)]">{String(frame.frameIndex).padStart(2,'0')}</span>
                  <span title={frame.status} className="truncate text-[11px] text-[var(--text-secondary)]">{frame.status}</span>
                </div>)}
              </div>}
          </>}
      </div>
    </div>
    <div className="border-t border-[var(--border-subtle)] pt-4">
      <div className="flex items-center justify-between"><div><h3 className="text-[14px] font-semibold">逐帧审核</h3><p className="mt-1 text-[12px] text-[var(--text-tertiary)]">已记录 {reviews.length} 项 · 需检查 {warnings.length} 项</p></div>
        <button type="button" onClick={() => {setExpanded(!expanded);setReviewPage(1);setReviewVerdict('ALL');}} aria-expanded={expanded} className="flex items-center gap-1 text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">{expanded ? <ChevronDown size={15}/> : <ChevronRight size={15}/>} {expanded ? '收起' : '查看全部'}</button></div>
      {expanded && <div className="os-console-filterbar mt-3 flex flex-wrap items-center justify-between gap-2 border-y border-[var(--border-subtle)] py-2"><Select aria-label="筛选审核结论" value={reviewVerdict} onChange={value=>{setReviewVerdict(value);setReviewPage(1);}} style={{width:150}} options={[{value:"ALL",label:"全部审核结论"},{value:"PASS",label:"通过 PASS"},{value:"WARN",label:"待查 WARN"},{value:"FAIL",label:"失败 FAIL"}]}/><span className="text-[12px] tabular-nums text-[var(--text-tertiary)]">已匹配 {filteredReviews.length} / {reviews.length} 项 · 已加载记录</span></div>}
      {filteredReviews.length === 0 ? <p className="mt-4 border border-dashed border-[var(--border-normal)] rounded-[6px] p-6 text-[13px] text-[var(--text-tertiary)]">{reviews.length?"当前筛选条件下无审核记录":"暂无审核记录。这里不会把未审核的帧标成通过。"}</p>
        : <div className="mt-3 divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)]">{(expanded ? pageReviews : reviews.slice(0,5)).map(review => <div key={review.frameId} className="flex min-w-0 flex-wrap items-start gap-3 py-3 sm:flex-nowrap">
          {review.verdict === 'PASS' ? <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-[var(--success)]"/> : review.verdict === 'FAIL' ? <ShieldAlert size={17} className="mt-0.5 shrink-0 text-[var(--danger)]"/> : <AlertCircle size={17} className="mt-0.5 shrink-0 text-[var(--warning)]"/>}
          <div className="flex-1 min-w-0"><div className="flex items-center gap-2 text-[13px]"><span className="font-medium">Frame {review.frameIndex}</span><span className={`text-[11px] font-mono ${verdictColor[review.verdict]}`}>{review.verdict}</span></div><p className="mt-1 text-[12px] text-[var(--text-secondary)] break-words">{review.comment || review.issueTags?.join('、') || '暂无审核备注'}</p></div>
          <span className="text-[11px] text-[var(--text-tertiary)] flex items-center gap-1 shrink-0"><Clock3 size={12}/>{review.timestamp}</span>
        </div>)}</div>}
    </div>
    {expanded && filteredReviews.length>10 && <Pagination size="small" current={safeReviewPage} pageSize={10} total={filteredReviews.length} showTotal={(total,range)=>`${range[0]}–${range[1]} / 已载入 ${total} 项`} onChange={setReviewPage}/>}
  </section>;
};
