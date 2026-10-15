import React from 'react';
import {Alert, Segmented, Tabs} from 'antd';
import {Bell, LockKeyhole, Palette, SlidersHorizontal, Type, UserRound} from 'lucide-react';
import {UserProfileSection} from './UserProfileSection';
import type {ThemeMode} from '../../types';
import type {FontPreference,PreferencePersistence} from '../../utils/fontPreference';
import type {MockAuthState,MockProfile} from '../../utils/mockAuth';

export type SettingsSection = 'appearance'|'profile'|'notifications'|'security'|'pipeline';

interface SettingsViewProps {
  mockSession?:MockAuthState;
  onOpenMockLogin?:()=>void;
  onSaveMockProfile?:(profile:MockProfile)=>MockAuthState['persistence'];
  onExpireMock?:()=>void;
  activeSection?: SettingsSection;
  onSectionChange?: (section:SettingsSection)=>void;
  unreadNotifications?:number;
  onOpenNotifications?:()=>void;
  currentTheme?: ThemeMode;
  onThemeChange?: (theme:ThemeMode)=>void;
  fontPreference?: FontPreference;
  fontPreferencePersistence?: PreferencePersistence;
  onFontPreferenceChange?: (font:FontPreference)=>void;
}
const fontNames:Record<FontPreference,string>={balanced:'均衡显示',chinese:'中文优先'};
const persistenceNames:Record<PreferencePersistence,string>={
  default:'当前为默认预设',
  saved:'已保存到本机浏览器',
  'session-only':'浏览器存储不可用，仅当前会话生效',
};

export const SettingsView:React.FC<SettingsViewProps>=({
  currentTheme='dark',onThemeChange,fontPreference='balanced',
  fontPreferencePersistence='default',onFontPreferenceChange,
  activeSection='appearance',onSectionChange,unreadNotifications=0,onOpenNotifications,
  mockSession={status:'guest',profile:null,persistence:'none'},onOpenMockLogin,onSaveMockProfile,onExpireMock
})=>{
  return <section id="codex-appearance-settings-view" className="w-full min-w-0 space-y-3 pb-6 text-[var(--text-primary)]">
    <header className="border-b border-[var(--border-subtle)] pb-3">
      <h1 className="os-page-heading">系统设置</h1>
    </header>
    <Tabs size="small" className="storyos-settings-tabs" activeKey={activeSection} onChange={key=>onSectionChange?.(key as SettingsSection)} items={[
      {key:'appearance',label:<span className="inline-flex items-center gap-1.5"><Palette size={14}/>外观设置</span>,
        children:<div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,.8fr)]" aria-label="外观设置双栏工作区">
          <div className="min-w-0 space-y-5">
            <section aria-label="界面主题设置" className="space-y-3 border-y border-[var(--border-subtle)] py-4">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <span className="text-[12px] font-medium">界面主题</span>
                <Segmented aria-label="界面主题" value={currentTheme} onChange={value=>onThemeChange?.(value as ThemeMode)}
                  options={[{value:'dark',label:'深色'},{value:'light',label:'浅色'},{value:'light-gradient',label:'浅色渐变'}]}/>
              </div>
            </section>
            <section aria-label="字体与排版设置" className="space-y-3 border-b border-[var(--border-subtle)] pb-4">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <span className="inline-flex items-center gap-2 text-[12px] font-medium"><Type size={15}/>字体与排版</span>
                <Segmented aria-label="字体偏好" value={fontPreference} onChange={value=>onFontPreferenceChange?.(value as FontPreference)}
                  options={[{value:'balanced',label:'均衡显示'},{value:'chinese',label:'中文优先'}]}/>
              </div>
              <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 text-[12px]">
                <span className="text-[var(--text-secondary)]">当前预设</span><strong className="font-medium">{fontNames[fontPreference]}</strong>
                <span className="text-[var(--text-secondary)]">英文字母与中文</span><span className="text-right">{fontPreference==='balanced'?'Inter / 系统中文后备':'系统中文优先'}</span>
                <span className="text-[var(--text-secondary)]">Run ID、日志与时间</span><span className="text-right font-mono">Mono · Tabular</span>
              </div>
              <p role="status" aria-live="polite" className={'text-[11px] '+(fontPreferencePersistence==='session-only'?'text-[var(--warning)]':'text-[var(--text-tertiary)]')}>{persistenceNames[fontPreferencePersistence]} · 仅影响此浏览器的界面，不涉及故事制作契约</p>
            </section>
            <div aria-label="外观配置生效范围" className="text-[12px] text-[var(--text-secondary)]">
              <p className="mt-2 leading-5">切换即生效；字体使用设备已有的系统字体，不下载专有字体文件。浏览器关闭后只有成功保存的偏好能自动恢复。</p>
            </div>
          </div>
          <aside className="min-w-0 border-t border-[var(--border-subtle)] pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0" aria-label="字体实时预览">
            <div className="storyos-font-sample mt-3 space-y-3 border-y border-[var(--border-subtle)] py-4">
              <p className="text-[18px] font-semibold">五十亩山地之后</p>
              <p className="text-[14px] font-semibold leading-5">Frame 08 · 人物画风一致性</p>
              <p className="text-[13px] leading-5 text-[var(--text-secondary)]">已批准图片与当前生产任务属于不同证据；审核时应明确标注来源、状态和执行回执。</p>
              <p className="text-[12px] leading-[18px] text-[var(--text-tertiary)]">阅读层级：标题 20px · 正文 13px · 元数据 12px</p>
              <p className="storyos-font-sample-number break-all text-[12px] leading-[18px] text-[var(--text-secondary)]">FRAME_08 · 2026-10-14 14:26 · 128/256</p>
            </div>
            <Alert className="mt-4 !rounded-[5px]" type="info" showIcon message="未提供的字体交由系统回退，不从竞品复制字体资源。"/>
          </aside>
        </div>},
      {key:'profile',label:<span className="inline-flex items-center gap-1.5"><UserRound size={14}/>个人资料</span>,
        children:<UserProfileSection session={mockSession} onLogin={onOpenMockLogin} onSave={onSaveMockProfile}/>},
      {key:'notifications',label:<span className="inline-flex items-center gap-1.5"><Bell size={14}/>通知与提醒</span>,
        children:<div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,.8fr)]" aria-label="通知设置工作区">
          <section className="min-w-0 space-y-4">
            <div className="border-y border-[var(--border-subtle)] py-4">
              <h2 className="os-section-heading">通知中心</h2>
              <p className="mt-1 text-[12px] text-[var(--text-secondary)]">当前会话未读通知 <strong className="font-mono font-medium text-[var(--text-primary)]">{unreadNotifications}</strong> 条 · 只代表已载入的前端会话，不代表服务端全部通知</p>
              <button type="button" onClick={onOpenNotifications} disabled={!onOpenNotifications} className="os-action mt-3" aria-label="打开通知中心">打开通知中心</button>
            </div>
            <Alert type="info" showIcon message="通知偏好尚无持久化接口" description="邮件、桌面推送和生产阻断提醒尚未接入授权偏好 API，因此不提供不会生效的开关，也不声明已订阅通知。"/>
          </section>
          <aside aria-label="通知范围说明" className="min-w-0 border-t border-[var(--border-subtle)] pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
            <p className="mt-3 text-[12px] leading-6 text-[var(--text-secondary)]">侧边栏铃铛和此处共用现有通知中心。通知条数不等于生产任务数，也不能证明后台监控或推送服务已经启动。</p>
          </aside>
        </div>},
      {key:'security',label:<span className="inline-flex items-center gap-1.5"><LockKeyhole size={14}/>账号与安全</span>,
        children:<div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,.8fr)]" aria-label="账号安全工作区">
          <section className="min-w-0 space-y-4">
            <h2 className="os-section-heading">账号安全</h2>
            <div aria-label="Mock 会话状态" className="space-y-2 border border-[var(--border-subtle)] p-3 text-[12px]">
              <p className="font-medium">演示身份：{mockSession.status==='mock'?'Mock 已进入':mockSession.status==='expired'?'Mock 会话已过期':'访客'}</p>
              <p className="text-[var(--text-secondary)]">这个状态只在浏览器演示界面有效，不能作为生产 API 或 Runtime 授权。</p>
              {mockSession.status==='mock'&&<button type="button" aria-label="模拟会话过期" onClick={onExpireMock} className="os-action">模拟会话过期</button>}
              {mockSession.status==='expired'&&<button type="button" aria-label="重新进入演示账号" onClick={onOpenMockLogin} className="os-action">重新进入演示账号</button>}
            </div>
            <Alert type="warning" showIcon message="尚未接入真实账号和会话权限"
              description="无法检索可信的登录会话、绑定设备、密码、多因素认证或访问令牌。此处不会显示模拟状态，也不提供没有权限的修改、登出或密钥操作。"/>
            <div className="divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)] text-[12px]" aria-label="安全能力列表">
              {([['账号登录态','未验证'],['多因素认证','未接入'],['设备与登录会话','未接入'],['访问密钥管理','无授权入口']] as const).map(([name,value])=>
                <div key={name} className="flex items-center justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">{name}</span><span className="text-[var(--text-tertiary)]">{value}</span></div>)}
            </div>
          </section>
          <aside aria-label="本机数据说明" className="min-w-0 border-t border-[var(--border-subtle)] pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0">
            <p className="mt-3 text-[12px] leading-6 text-[var(--text-secondary)]">外观及字体仅保存在当前浏览器，不构成已登录账号或跨设备同步。生产凭据、Token、数据库密码不能在此页面显示或导出。</p>
          </aside>
        </div>},
      {key:'pipeline',label:<span className="inline-flex items-center gap-1.5"><SlidersHorizontal size={14}/>生产管线</span>,
        children:<div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,.8fr)]" aria-label="生产配置双栏工作区">
          <section className="min-w-0 space-y-3">
            <p className="text-[12px] font-medium">Runtime 配置权限（只读）</p>
            <Alert type="warning" showIcon message="尚无已授权的生产配置读写接口" description="模型、画幅、批次、并发等参数必须由受控 StoryOS Runtime 提供权威数据；本页不会展示假配置值或模拟写入成功。"/>
            <div className="divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)] text-[12px]">
              <div className="flex flex-wrap justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">生图模型 / 质量 / 画幅</span><span>等待权威配置接口</span></div>
              <div className="flex flex-wrap justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">批次 / 并发限制</span><span>等待权威配置接口</span></div>
              <div className="flex flex-wrap justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">操作权限</span><span>当前页面只读</span></div>
            </div>
          </section>
          <aside className="min-w-0 border-t border-[var(--border-subtle)] pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0" aria-label="生产权限说明">
            <p className="mt-3 text-[12px] leading-6 text-[var(--text-secondary)]">本页是当前前端能力的说明，不代表 Runtime 已启动或配置可写。接通正式授权能力后，需根据后端返回的权限契约新增读写操作。</p>
          </aside>
        </div>}
    ]}/>
  </section>;
};
