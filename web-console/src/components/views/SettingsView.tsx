import React from 'react';
import {Alert, Segmented, Tabs} from 'antd';
import {Palette, ShieldCheck, SlidersHorizontal} from 'lucide-react';
import type {ThemeMode} from '../../types';

interface SettingsViewProps{
 currentTheme?:ThemeMode;
 onThemeChange?:(theme:ThemeMode)=>void;
}
export const SettingsView:React.FC<SettingsViewProps>=({currentTheme='dark',onThemeChange})=>{
 return <section id="codex-appearance-settings-view" className="w-full min-w-0 space-y-3 pb-6 text-[var(--text-primary)]">
  <header className="border-b border-[var(--border-subtle)] pb-3">
   <h1 className="os-page-heading">系统设置</h1>
   <p className="mt-1 text-[12px] text-[var(--text-secondary)]">界面偏好与生产权限 · 仅展示已接入、可验证的设置</p>
  </header>
  <Tabs size="small" className="storyos-settings-tabs" defaultActiveKey="appearance" items={[
   {key:'appearance',label:<span className="inline-flex items-center gap-1.5"><Palette size={14}/>外观设置</span>,
    children:<div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,.8fr)]" aria-label="外观设置双栏工作区">
     <section className="min-w-0 space-y-4">
       <div className="flex flex-wrap items-center justify-between gap-4 border-y border-[var(--border-subtle)] py-4"><div><h2 className="os-section-heading">界面主题</h2><p className="mt-1 text-[12px] text-[var(--text-secondary)]">即时应用于控制台已使用主题变量的区域</p></div><Segmented aria-label="界面主题" value={currentTheme} onChange={value=>onThemeChange?.(value as ThemeMode)} options={[{value:'dark',label:'深色'},{value:'light',label:'浅色'},{value:'light-gradient',label:'浅色渐变'}]}/></div>
       <div className="divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)] text-[12px]"><div className="flex flex-wrap items-center justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">当前主题</span><strong className="font-medium">{currentTheme==='dark'?'深色':currentTheme==='light'?'浅色':'浅色渐变'}</strong></div><div className="flex flex-wrap items-center justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">受影响界面</span><span>侧边栏、主表格、检视抽屉和分页组件</span></div><div className="flex flex-wrap items-center justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">偏好保存</span><span>浏览器本地设置</span></div></div>
     </section>
     <aside className="min-w-0 border-t border-[var(--border-subtle)] pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0" aria-label="外观配置生效说明"><h2 className="os-section-heading flex items-center gap-2"><ShieldCheck size={16}/>配置生效说明</h2><p className="mt-3 text-[12px] leading-6 text-[var(--text-secondary)]">切换主题会立即更新当前控制台，表格、分页与菜单复用现有主题契约，不创建新的主题配置或影响生产流程。</p><Alert className="mt-4 !rounded-[5px]" type="info" showIcon message="其他外观参数尚未接入可验证的持久化接口，因此暂不提供模拟开关。" /></aside>
    </div>},
   {key:'pipeline',label:<span className="inline-flex items-center gap-1.5"><SlidersHorizontal size={14}/>生产管线</span>,
    children:<div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,.8fr)]" aria-label="生产配置双栏工作区">
     <section className="min-w-0 space-y-3"><h2 className="os-section-heading">Runtime 配置权限</h2><Alert type="warning" showIcon message="尚无已授权的生产配置读写接口" description="模型、画幅、批次、并发等参数必须由受控 StoryOS Runtime 提供权威数据；本页不会展示假配置值或模拟写入成功。"/><div className="divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)] text-[12px]"><div className="flex flex-wrap justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">生图模型 / 质量 / 画幅</span><span>等待权威配置接口</span></div><div className="flex flex-wrap justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">批次 / 并发限制</span><span>等待权威配置接口</span></div><div className="flex flex-wrap justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">操作权限</span><span>当前页面只读</span></div></div></section>
     <aside className="min-w-0 border-t border-[var(--border-subtle)] pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0" aria-label="生产权限说明"><h2 className="os-section-heading flex items-center gap-2"><ShieldCheck size={16}/>配置安全边界</h2><p className="mt-3 text-[12px] leading-6 text-[var(--text-secondary)]">本页是当前前端能力的说明，不代表 Runtime 已启动或配置可写。接通正式授权能力后，需根据后端返回的权限契约新增读写操作。</p></aside>
    </div>}
  ]}/>
 </section>;
};
