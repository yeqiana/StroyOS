import React,{useEffect,useRef,useState} from 'react';
import {Bell, BookOpenText, ChevronDown, LogOut, Mountain, Settings, ShieldCheck, Sparkles, UserRound} from 'lucide-react';
import type {MockAuthState,MockAvatar} from '../utils/mockAuth';

export function MockAvatarIcon({avatar,size=17}:{avatar:MockAvatar|null;size?:number}){
  if(avatar==='mountain')return <Mountain size={size}/>;
  if(avatar==='spark')return <Sparkles size={size}/>;
  return <BookOpenText size={size}/>;
}
interface Props {
  session:MockAuthState;
  onLogin:()=>void;
  onLogout:()=>void;
  onProfile:()=>void;
  onSettings:()=>void;
  onSecurity:()=>void;
  onNotifications:()=>void;
}
export const AccountMenu:React.FC<Props>=({session,onLogin,onLogout,onProfile,onSettings,onSecurity,onNotifications})=>{
 const [open,setOpen]=useState(false);
 const anchor=useRef<HTMLDivElement>(null);
 const trigger=useRef<HTMLButtonElement>(null);
 const menu=useRef<HTMLDivElement>(null);
 const entries=()=>[...menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')??[]];
 const focusEntry=(index:number)=>{const items=entries();if(items.length)items[(index+items.length)%items.length].focus()};
 useEffect(()=>{
   if(!open)return;
   const onPointer=(ev:PointerEvent)=>{if(!anchor.current?.contains(ev.target as Node))setOpen(false)};
   const onKey=(ev:KeyboardEvent)=>{
     if(ev.key==='Escape'){ev.preventDefault();setOpen(false);trigger.current?.focus();return}
     if(ev.key==='Tab'){setOpen(false);return}
     if(!['ArrowDown','ArrowUp','Home','End'].includes(ev.key))return;
     const items=entries();
     if(!items.length)return;
     ev.preventDefault();
     const current=items.indexOf(document.activeElement as HTMLButtonElement);
     if(ev.key==='Home'){focusEntry(0);return}
     if(ev.key==='End'){focusEntry(items.length-1);return}
     const next=ev.key==='ArrowDown'?(current+1):(current<0?items.length-1:current-1);
     focusEntry(next);
   };
   document.addEventListener('pointerdown',onPointer);
   document.addEventListener('keydown',onKey);
   return()=>{document.removeEventListener('pointerdown',onPointer);document.removeEventListener('keydown',onKey)};
 },[open]);
 const changeOpen=(next:boolean,fromKeyboard=false)=>{
   setOpen(next);
   if(next&&fromKeyboard)requestAnimationFrame(()=>focusEntry(0));
 };
 const action=(callback:()=>void)=>()=>{setOpen(false);callback()};
 return <div ref={anchor} className="storyos-account-anchor relative" aria-label="Mock 账号入口">
   <button ref={trigger} type="button" aria-label="账号菜单" aria-haspopup="menu" aria-controls="storyos-account-menu" aria-expanded={open}
     onKeyDown={e=>{if(['ArrowDown','ArrowUp'].includes(e.key)&&!open){e.preventDefault();changeOpen(true,true)}}}
     onClick={()=>changeOpen(!open)} className="storyos-account-trigger flex min-h-11 w-full items-center gap-2 rounded-[6px] px-1.5 py-1.5 text-left transition-colors hover:bg-[var(--bg-hover)] focus-visible:outline-2 focus-visible:outline-[var(--focus)]">
     <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--border-normal)] bg-[var(--bg-surface)] text-[var(--text-primary)]">
       {session.status==='mock'?<MockAvatarIcon avatar={session.profile?.avatar??null}/>:<UserRound size={17}/>}
     </span>
     <span className="storyos-account-copy min-w-0 flex-1">
       <span className="block truncate text-[12px] font-semibold">{session.status==='mock'?session.profile?.displayName:'访客'}</span>
       <span className="block truncate text-[10px] text-[var(--text-tertiary)]">{session.status==='mock'?'Mock 演示账号':session.status==='expired'?'Mock 会话已过期':'未登录 · 可体验 Mock'}</span>
     </span>
     <ChevronDown size={13} className={'storyos-account-chevron text-[var(--text-tertiary)] transition-transform '+(open?'rotate-180':'')}/>
   </button>
   {open&&<div id="storyos-account-menu" ref={menu} role="menu" aria-label="账号操作" className="storyos-account-menu absolute bottom-full left-0 z-50 mb-2 w-full min-w-[206px] rounded-[7px] border border-[var(--border-normal)] bg-[var(--bg-elevated)] p-1.5 shadow-xl text-[12px]">
     <p className="px-2 py-2 text-[11px] text-[var(--text-tertiary)]">仅浏览器演示 · 不是生产授权</p>
     <button role="menuitem" type="button" onClick={action(onProfile)} aria-label="个人资料" className="flex w-full items-center gap-2 rounded-[4px] px-2 py-2 text-left hover:bg-[var(--bg-hover)] focus-visible:bg-[var(--bg-selected)]"><UserRound size={15}/>个人资料</button>
     <button role="menuitem" type="button" onClick={action(onSettings)} aria-label="系统设置（账号菜单）" className="flex w-full items-center gap-2 rounded-[4px] px-2 py-2 text-left hover:bg-[var(--bg-hover)] focus-visible:bg-[var(--bg-selected)]"><Settings size={15}/>系统设置</button>
     <button role="menuitem" type="button" onClick={action(onSecurity)} aria-label="账号与安全（账号菜单）" className="flex w-full items-center gap-2 rounded-[4px] px-2 py-2 text-left hover:bg-[var(--bg-hover)] focus-visible:bg-[var(--bg-selected)]"><ShieldCheck size={15}/>账号与安全</button>
     <button role="menuitem" type="button" onClick={action(onNotifications)} aria-label="通知中心（账号菜单）" className="flex w-full items-center gap-2 rounded-[4px] px-2 py-2 text-left hover:bg-[var(--bg-hover)] focus-visible:bg-[var(--bg-selected)]"><Bell size={15}/>通知中心</button>
     <div className="my-1 border-t border-[var(--border-subtle)]"/>
     {session.status==='mock'
       ?<button role="menuitem" type="button" onClick={action(onLogout)} aria-label="退出演示账号" className="flex w-full items-center gap-2 rounded-[4px] px-2 py-2 text-left text-[var(--danger)] hover:bg-[var(--bg-hover)] focus-visible:bg-[var(--bg-selected)]"><LogOut size={15}/>退出演示账号</button>
       :<button role="menuitem" type="button" onClick={action(onLogin)} aria-label="进入演示账号" className="flex w-full items-center gap-2 rounded-[4px] px-2 py-2 text-left hover:bg-[var(--bg-hover)] focus-visible:bg-[var(--bg-selected)]"><UserRound size={15}/>进入演示账号</button>}
   </div>}
 </div>;
};