import React,{useEffect,useRef} from 'react';
import {BookOpenText,CheckCircle2,Layers3,ShieldCheck,UserRound,X} from 'lucide-react';

export const MockLoginDialog:React.FC<{onCancel:()=>void;onConfirm:()=>void}>=({onCancel,onConfirm})=>{
 const box=useRef<HTMLElement>(null);
 const confirmRef=useRef<HTMLButtonElement>(null);
 const onCancelRef=useRef(onCancel);
 onCancelRef.current=onCancel;
 useEffect(()=>{
   const focusBack=document.querySelector<HTMLButtonElement>('button[aria-label="账号菜单"]');
   confirmRef.current?.focus();
   const onKey=(e:KeyboardEvent)=>{
     if(e.key==='Escape'){e.preventDefault();onCancelRef.current();return}
     if(e.key!=='Tab')return;
     const items=[...box.current?.querySelectorAll<HTMLButtonElement>('button:not([disabled])')??[]];
     if(!items.length){e.preventDefault();return}
     const first=items[0],last=items[items.length-1];
     if(e.shiftKey&&(document.activeElement===first||!box.current?.contains(document.activeElement))){e.preventDefault();last.focus()}
     else if(!e.shiftKey&&(document.activeElement===last||!box.current?.contains(document.activeElement))){e.preventDefault();first.focus()}
   };
   document.addEventListener('keydown',onKey);
   return()=>{document.removeEventListener('keydown',onKey);focusBack?.focus()};
 },[]);
 return <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/75 p-3 sm:p-6" onMouseDown={e=>{if(e.target===e.currentTarget)onCancel()}}>
   <section ref={box} role="dialog" aria-modal="true" aria-labelledby="mock-login-title" aria-describedby="mock-login-explainer"
     className="grid w-full max-w-[980px] max-h-[min(90vh,680px)] min-h-[330px] overflow-y-auto rounded-[12px] border border-[var(--border-normal)] bg-[var(--bg-elevated)] shadow-2xl md:min-h-[520px] md:grid-cols-[minmax(0,1.15fr)_minmax(345px,.85fr)]">
     <div aria-label="StoryOS 原创故事视觉预览" className="relative hidden flex-col justify-between overflow-hidden bg-[#122139] px-8 py-9 text-white md:flex">
       <div aria-hidden="true" className="pointer-events-none absolute inset-0" style={{background:'radial-gradient(ellipse at 76% 27%, rgba(249,170,94,.45), transparent 33%), radial-gradient(ellipse at 19% 78%,rgba(85,119,169,.44),transparent 43%),linear-gradient(145deg,#182f46,#1b2434 60%,#101923)'}}/>
       <div className="relative flex items-center gap-2 text-[15px] font-semibold"><BookOpenText size={20}/>StoryOS <span className="ml-1 text-[10px] font-normal uppercase tracking-[.16em] text-white/65">Creative Workspace</span></div>
       <div className="relative space-y-6">
         <div className="flex gap-2 text-white/75"><span className="h-[2px] w-9 bg-white/90"/><span className="h-[2px] w-5 bg-white/30"/><span className="h-[2px] w-5 bg-white/30"/></div>
         <h3 className="max-w-[380px] text-[30px] font-semibold leading-[1.35] tracking-tight">从一个故事想法<br/>到完整的图文作品。</h3>
         <p className="max-w-[365px] text-[13px] leading-6 text-white/75">编排故事、检查人物一致性、逐帧检视制作结果。这里展示的是 StoryOS 自有工作流概念，而非竞品的视觉素材。</p>
         <div className="grid grid-cols-3 gap-3 text-[11px]">
           <div className="rounded-[8px] border border-white/20 bg-white/10 p-3 backdrop-blur-sm"><BookOpenText className="mb-3" size={18}/>故事</div>
           <div className="rounded-[8px] border border-white/20 bg-white/10 p-3 backdrop-blur-sm"><Layers3 className="mb-3" size={18}/>分镜</div>
           <div className="rounded-[8px] border border-white/20 bg-white/10 p-3 backdrop-blur-sm"><CheckCircle2 className="mb-3" size={18}/>审核</div>
         </div>
       </div>
       <p className="relative text-[11px] tracking-wide text-white/60">StoryOS · 图文创作工作台 · 原创示意</p>
     </div>
     <div className="flex min-w-0 flex-col justify-between gap-5 p-5 sm:p-8 md:p-9">
       <div className="space-y-5">
         <header className="flex items-start justify-between gap-3">
           <div className="space-y-2">
             <div className="flex items-center gap-1.5 text-[12px] font-semibold"><BookOpenText size={17}/>StoryOS</div>
             <h2 id="mock-login-title" className="text-[22px] font-semibold leading-8">欢迎体验 StoryOS</h2>
             <p className="text-[12px] text-[var(--warning)]">Mock 认证 · 非真实登录</p>
           </div>
           <button type="button" aria-label="关闭演示登录" onClick={onCancel} className="rounded-[5px] p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] focus-visible:outline-2 focus-visible:outline-[var(--focus)]"><X size={19}/></button>
         </header>
         <p id="mock-login-explainer" className="text-[12px] leading-6 text-[var(--text-secondary)]">无需手机号和密码。演示账号只用于体验头像、资料编辑及设置交互，不能获得生图、审批、Runtime 或数据库操作权限。</p>
         <div className="flex items-center gap-3 rounded-[8px] border border-[var(--border-normal)] bg-[var(--bg-workspace)] p-3.5">
           <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[var(--bg-selected)]"><UserRound size={23}/></span>
           <div><strong className="block text-[13px]">演示用户</strong><p className="mt-1 text-[11px] text-[var(--text-tertiary)]">资料仅保存于当前浏览器</p></div>
         </div>
       </div>
       <div className="space-y-4">
         <p className="flex items-center gap-2 text-[11px] leading-5 text-[var(--text-tertiary)]"><ShieldCheck size={16} className="shrink-0"/>仅用于交互演示，不产生任何身份凭证或生产权限</p>
         <button ref={confirmRef} type="button" aria-label="确认进入演示账号" onClick={onConfirm} className="os-action os-action-primary !h-10 w-full !rounded-[6px] text-[13px]">进入演示账号</button>
         <button type="button" className="os-action w-full !rounded-[6px]" onClick={onCancel}>取消</button>
       </div>
     </div>
   </section>
 </div>;
};