import React,{useEffect,useState} from 'react';
import {Alert} from 'antd';
import {ShieldCheck,UserRound} from 'lucide-react';
import {MockAvatarIcon} from '../AccountMenu';
import type {MockAuthState,MockProfile,MockAvatar} from '../../utils/mockAuth';

interface Props{
  session?:MockAuthState;
  onLogin?:()=>void;
  onSave?:(profile:MockProfile)=>MockAuthState['persistence'];
}
const fallback:MockAuthState={status:'guest',profile:null,persistence:'none'};
const choices:{avatar:MockAvatar;title:string}[]=[
  {avatar:'book',title:'书本'},{avatar:'mountain',title:'山峰'},{avatar:'spark',title:'星光'},
];

/** Demo fields never represent verified email, token, identity or production authority. */
export const UserProfileSection:React.FC<Props>=({session=fallback,onLogin,onSave})=>{
  const [name,setName]=useState(session.profile?.displayName??'');
  const [avatar,setAvatar]=useState<MockAvatar>(session.profile?.avatar??'book');
  const [message,setMessage]=useState('');
  useEffect(()=>{setName(session.profile?.displayName??'');setAvatar(session.profile?.avatar??'book')},
    [session.status,session.profile?.displayName,session.profile?.avatar]);
  useEffect(()=>{setMessage('')},[session.status]);
  const submit=(e:React.FormEvent)=>{
    e.preventDefault();
    const trimmed=name.trim();
    if(!trimmed||trimmed.length>30||/[\u0000-\u001F\u007F]/.test(trimmed)){
      setMessage('昵称需为 1–30 个有效字符，不能包含控制字符');return;
    }
    const result=onSave?.({displayName:trimmed,avatar});
    setMessage(result==='saved'?'演示资料已保存到本机浏览器':result==='session-only'?'演示资料已更新，仅当前页面生效；浏览器存储不可用':'资料未保存');
  };
  return <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,.8fr)]" aria-label="用户资料工作区">
   <section aria-label="个人资料" className="min-w-0 space-y-4">
    <div className="flex flex-wrap items-center gap-4 border-y border-[var(--border-subtle)] py-4">
      <span aria-hidden="true" className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-[var(--border-normal)] bg-[var(--bg-selected)] text-[var(--text-primary)]">
        {session.status==='mock'?<MockAvatarIcon avatar={session.profile?.avatar??null} size={24}/>:<UserRound size={24}/>}
      </span>
      <div className="min-w-0"><h2 className="os-section-heading">个人资料</h2>
        <p className="mt-1 text-[12px] text-[var(--text-secondary)]">{session.status==='mock'?'演示资料 · Mock 模式':session.status==='expired'?'Mock 会话已过期':'账号尚未连接 · 当前无法验证登录身份'}</p>
      </div>
    </div>
    <Alert type="warning" showIcon message={session.status==='mock'?'Mock 演示资料不等于真实账号':'未接入经过验证的账号身份'}
      description="StoryOS 当前没有向本页提供账号认证与资料读写接口。以下演示资料仅用于 UI 体验，不是服务端身份，也不授予任何制作、审批或 Runtime 权限。"/>
    {session.status==='mock'&&session.profile
      ? <form aria-label="演示资料编辑" onSubmit={submit} className="space-y-4 border-y border-[var(--border-subtle)] py-4">
        <label className="block text-[12px] text-[var(--text-secondary)]">显示名称（仅 Mock）
          <input aria-label="演示昵称" type="text" maxLength={30} value={name} onChange={e=>setName(e.target.value)}
            className="mt-2 block h-9 w-full rounded-[5px] border border-[var(--border-normal)] bg-[var(--bg-workspace)] px-3 text-[13px] text-[var(--text-primary)]"/>
        </label>
        <fieldset className="space-y-2">
          <legend className="text-[12px] text-[var(--text-secondary)]">头像预设（仅 Mock）</legend>
          <div className="flex flex-wrap gap-2">
            {choices.map(c=><button type="button" key={c.avatar} aria-label={'选择'+c.title+'头像'} aria-pressed={avatar===c.avatar}
              onClick={()=>setAvatar(c.avatar)} className={'flex min-w-[83px] items-center justify-center gap-2 rounded-[5px] border px-2 py-2 text-[12px] '+(avatar===c.avatar?'border-[var(--info)] bg-[var(--bg-selected)]':'border-[var(--border-normal)] hover:bg-[var(--bg-hover)]')}>
              <MockAvatarIcon avatar={c.avatar}/>{c.title}</button>)}
          </div>
        </fieldset>
        <p className="text-[11px] text-[var(--text-tertiary)]">不收集手机号、邮箱、密码；不上传头像文件。</p>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p role="status" aria-live="polite" className={'text-[11px] '+(session.persistence==='session-only'?'text-[var(--warning)]':'text-[var(--text-tertiary)]')}>
            {message|| (session.persistence==='saved'?'Mock 会话存于此浏览器':'仅当前页面可用')}
          </p>
          <button type="submit" className="os-action os-action-primary">保存演示资料</button>
        </div>
      </form>
      : <div className="space-y-3">
          {session.status==='expired'&&<p role="status" className="text-[12px] text-[var(--warning)]">会话已模拟过期，请重新进入演示账号。</p>}
          <div className="border-y border-[var(--border-subtle)] divide-y divide-[var(--border-subtle)] text-[12px]" aria-label="账号资料字段">
            {([['头像','未获取'],['显示名称','未获取'],['账号标识','未获取'],['邮箱','未获取'],['账号来源','尚无已验证身份提供方']] as const).map(([key,val])=>
              <div key={key} className="flex flex-wrap justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">{key}</span><span className="text-[var(--text-tertiary)]">{val}</span></div>)}
          </div>
          <button type="button" onClick={onLogin} aria-label="进入演示账号（个人资料）" className="os-action os-action-primary">进入 Mock 演示账号</button>
        </div>}
   </section>
   <aside className="min-w-0 space-y-3 border-t border-[var(--border-subtle)] pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0" aria-label="资料权限说明">
     <h2 className="os-section-heading flex items-center gap-2"><ShieldCheck size={16}/>资料权限与同步</h2>
     <p className="text-[12px] leading-6 text-[var(--text-secondary)]">演示昵称和头像只用于本地 UI。真实邮箱、手机、绑定设备、注销与登出均需要未来的认证服务端授权。</p>
     <p className="border-l-2 border-[var(--info)] pl-3 text-[11px] leading-5 text-[var(--text-tertiary)]">本机字体与主题偏好独立保存，不会随 Mock 账号同步其他设备，也不会改变任何生产鉴权。</p>
   </aside>
  </div>;
};
