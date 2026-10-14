import React from 'react';
import {Alert} from 'antd';
import {ShieldCheck, UserRound} from 'lucide-react';

/** No authenticated identity endpoint exists in the current console.
 * Do not substitute local drafts, git username, OS user or fixture data. */
export const UserProfileSection:React.FC=()=>{
 return <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,.8fr)]" aria-label="用户资料工作区">
  <section aria-label="个人资料" className="min-w-0 space-y-4">
   <div className="flex flex-wrap items-center gap-4 border-y border-[var(--border-subtle)] py-4">
    <span aria-hidden="true" className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[6px] border border-[var(--border-normal)] bg-[var(--bg-elevated)] text-[var(--text-secondary)]"><UserRound size={24}/></span>
    <div className="min-w-0"><h2 className="os-section-heading">个人资料</h2>
     <p className="mt-1 text-[12px] text-[var(--text-secondary)]">账号尚未连接 · 当前无法验证登录身份</p>
    </div>
   </div>
   <Alert type="warning" showIcon message="未接入经过验证的账号身份"
    description="StoryOS 当前没有向本页提供账号认证与资料读写接口。不显示模拟头像、昵称、邮箱或会员状态，也不会将本机 Git 用户名当作登录账号。"/>
   <div className="border-y border-[var(--border-subtle)] divide-y divide-[var(--border-subtle)] text-[12px]" aria-label="账号资料字段">
    {([['头像','未获取'],['显示名称','未获取'],['账号标识','未获取'],['邮箱','未获取'],['账号来源','尚无已验证身份提供方']] as const).map(([name,value])=>
      <div key={name} className="flex min-w-0 flex-wrap items-start justify-between gap-x-4 gap-y-1 py-3">
        <span className="text-[var(--text-secondary)]">{name}</span><span className="break-all text-right text-[var(--text-tertiary)]">{value}</span>
      </div>)}
   </div>
  </section>
  <aside className="min-w-0 space-y-3 border-t border-[var(--border-subtle)] pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0" aria-label="资料权限说明">
   <h2 className="os-section-heading flex items-center gap-2"><ShieldCheck size={16}/>资料权限与同步</h2>
   <p className="text-[12px] leading-6 text-[var(--text-secondary)]">资料编辑、上传头像、修改邮箱、注销与登出都需要可信身份和服务端授权。当前仅提供状态说明，不显示无法执行的保存按钮。</p>
   <p className="border-l-2 border-[var(--info)] pl-3 text-[11px] leading-5 text-[var(--text-tertiary)]">本机字体、主题偏好属于浏览器级设置，与个人账号资料无关，也不会自动同步到其他设备。</p>
  </aside>
 </div>;
};
