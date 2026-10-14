import React from 'react';
import {Alert, Segmented, Tabs} from 'antd';
import {Palette, ShieldCheck, SlidersHorizontal, Type} from 'lucide-react';
import type {ThemeMode} from '../../types';
import type {FontPreference,PreferencePersistence} from '../../utils/fontPreference';

interface SettingsViewProps {
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
  fontPreferencePersistence='default',onFontPreferenceChange
})=>{
  return <section id="codex-appearance-settings-view" className="w-full min-w-0 space-y-3 pb-6 text-[var(--text-primary)]">
    <header className="border-b border-[var(--border-subtle)] pb-3">
      <h1 className="os-page-heading">系统设置</h1>
      <p className="mt-1 text-[12px] text-[var(--text-secondary)]">外观与阅读偏好保存在本机；生产参数只呈现实际接入的权限</p>
    </header>
    <Tabs size="small" className="storyos-settings-tabs" defaultActiveKey="appearance" items={[
      {key:'appearance',label:<span className="inline-flex items-center gap-1.5"><Palette size={14}/>外观设置</span>,
        children:<div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,.8fr)]" aria-label="外观设置双栏工作区">
          <div className="min-w-0 space-y-5">
            <section aria-label="界面主题设置" className="space-y-3 border-y border-[var(--border-subtle)] py-4">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div><h2 className="os-section-heading">界面主题</h2><p className="mt-1 text-[12px] text-[var(--text-secondary)]">立即切换主题变量，不修改生产数据</p></div>
                <Segmented aria-label="界面主题" value={currentTheme} onChange={value=>onThemeChange?.(value as ThemeMode)}
                  options={[{value:'dark',label:'深色'},{value:'light',label:'浅色'},{value:'light-gradient',label:'浅色渐变'}]}/>
              </div>
              <p className="text-[11px] text-[var(--text-tertiary)]">当前：{currentTheme==='dark'?'深色':currentTheme==='light'?'浅色':'浅色渐变'} · 侧栏、表格、检视器复用统一色彩 Token</p>
            </section>
            <section aria-label="字体与排版设置" className="space-y-3 border-b border-[var(--border-subtle)] pb-4">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div><h2 className="os-section-heading flex items-center gap-2"><Type size={15}/>字体与排版</h2><p className="mt-1 text-[12px] text-[var(--text-secondary)]">调整系统字体候选顺序；保留已核定的字号、行高与数字等宽规则</p></div>
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
              <h2 className="os-section-heading">配置生效说明</h2>
              <p className="mt-2 leading-5">切换即生效；字体使用设备已有的系统字体，不下载专有字体文件。浏览器关闭后只有成功保存的偏好能自动恢复。</p>
            </div>
          </div>
          <aside className="min-w-0 border-t border-[var(--border-subtle)] pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0" aria-label="字体实时预览">
            <h2 className="os-section-heading">实时排版预览</h2>
            <div className="storyos-font-sample mt-3 space-y-3 border-y border-[var(--border-subtle)] py-4">
              <h3 className="os-page-heading">五十亩山地之后</h3>
              <p className="text-[14px] font-semibold leading-5">Frame 08 · 人物画风一致性</p>
              <p className="text-[13px] leading-5 text-[var(--text-secondary)]">已批准图片与当前生产任务属于不同证据；审核时应明确标注来源、状态和执行回执。</p>
              <p className="text-[12px] leading-[18px] text-[var(--text-tertiary)]">阅读层级：标题 20px · 正文 13px · 元数据 12px</p>
              <p className="storyos-font-sample-number break-all text-[12px] leading-[18px] text-[var(--text-secondary)]">FRAME_08 · 2026-10-14 14:26 · 128/256</p>
            </div>
            <Alert className="mt-4 !rounded-[5px]" type="info" showIcon message="未提供的字体交由系统回退，不从竞品复制字体资源。"/>
          </aside>
        </div>},
      {key:'pipeline',label:<span className="inline-flex items-center gap-1.5"><SlidersHorizontal size={14}/>生产管线</span>,
        children:<div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,.8fr)]" aria-label="生产配置双栏工作区">
          <section className="min-w-0 space-y-3">
            <h2 className="os-section-heading">Runtime 配置权限</h2>
            <Alert type="warning" showIcon message="尚无已授权的生产配置读写接口" description="模型、画幅、批次、并发等参数必须由受控 StoryOS Runtime 提供权威数据；本页不会展示假配置值或模拟写入成功。"/>
            <div className="divide-y divide-[var(--border-subtle)] border-y border-[var(--border-subtle)] text-[12px]">
              <div className="flex flex-wrap justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">生图模型 / 质量 / 画幅</span><span>等待权威配置接口</span></div>
              <div className="flex flex-wrap justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">批次 / 并发限制</span><span>等待权威配置接口</span></div>
              <div className="flex flex-wrap justify-between gap-3 py-3"><span className="text-[var(--text-secondary)]">操作权限</span><span>当前页面只读</span></div>
            </div>
          </section>
          <aside className="min-w-0 border-t border-[var(--border-subtle)] pt-4 lg:border-l lg:border-t-0 lg:pl-5 lg:pt-0" aria-label="生产权限说明">
            <h2 className="os-section-heading flex items-center gap-2"><ShieldCheck size={16}/>配置安全边界</h2>
            <p className="mt-3 text-[12px] leading-6 text-[var(--text-secondary)]">本页是当前前端能力的说明，不代表 Runtime 已启动或配置可写。接通正式授权能力后，需根据后端返回的权限契约新增读写操作。</p>
          </aside>
        </div>}
    ]}/>
  </section>;
};
