import React,{useEffect,useRef} from 'react';
import {UserRound,X} from 'lucide-react';

export const MockLoginDialog:React.FC<{onCancel:()=>void;onConfirm:()=>void}>=({onCancel,onConfirm})=>{
 const submit=useRef<HTMLButtonElement>(null);
 useEffect(()=>{submit.current?.focus();const onKey=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.preventDefault();onCancel()}};document.addEventListener('keydown',onKey);return()=>document.removeEventListener('keydown',onKey)},[onCancel]);
 return <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/70 p-4" onMouseDown={e=>{if(e.target===e.currentTarget)onCancel()}}>
  <section role="dialog" aria-modal="true" aria-labelledby="mock-login-title" aria-describedby="mock-login-explainer"
    className="w-full max-w-[380px] space-y-4 rounded-[9px] border border-[var(--border-normal)] bg-[var(--bg-elevated)] p-5 text-[var(--text-primary)] shadow-xl">
    <header className="flex items-start justify-between gap-3"><div><h2 id="mock-login-title" className="text-[17px] font-semibold">进入 StoryOS 演示账号</h2><p className="mt-1 text-[11px] text-[var(--warning)]">Mock 认证 · 非真实登录</p></div>
      <button type="button" aria-label="关闭演示登录" onClick={onCancel} className="rounded-[4px] p-1 hover:bg-[var(--bg-hover)]"><X size={18}/></button>
    </header>
    <p id="mock-login-explainer" className="text-[12px] leading-6 text-[var(--text-secondary)]">无需手机号和密码。演示账号只用于体验头像、资料编辑及设置交互，不能获得生图、审批、Runtime 或数据库操作权限。</p>
    <div className="flex items-center gap-3 rounded-[5px] border border-[var(--border-subtle)] bg-[var(--bg-workspace)] p-3">
      <UserRound size={22}/><div><strong className="text-[13px]">演示用户</strong><p className="text-[11px] text-[var(--text-tertiary)]">资料仅保存于当前浏览器</p></div>
    </div>
    <div className="flex justify-end gap-2"><button type="button" className="os-action" onClick={onCancel}>取消</button><button ref={submit} type="button" aria-label="确认进入演示账号" onClick={onConfirm} className="os-action os-action-primary">进入演示账号</button></div>
  </section>
 </div>;
};
