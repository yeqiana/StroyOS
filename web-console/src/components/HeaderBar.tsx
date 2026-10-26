import React, { useState } from 'react';
import { ChevronDown, PanelRight } from 'lucide-react';
import { Episode, NavigationTab } from '../types';

interface HeaderBarProps {
  activeEpisode: Episode;
  allEpisodes: Episode[];
  onSelectEpisode: (episode: Episode) => void;
  onToggleContextPanel?: () => void;
  contextPanelOpen?: boolean;
  onConnectWorkspace?: () => void;
  onOpenSettings?: () => void;
  currentTab?: NavigationTab;
  runtimeStoryTitle?: string | null;
}
const PAGE_NAMES: Partial<Record<NavigationTab,string>> = {
  overview: '工作台', production_monitor: '生产监控', pipeline: '工作流',
  episodes: '作品与项目', agents: 'Agents', logs: '审计日志',
  settings: '系统设置', workbench: '故事制作'
};
export const HeaderBar: React.FC<HeaderBarProps> = ({ activeEpisode, allEpisodes, onSelectEpisode, onToggleContextPanel, contextPanelOpen, currentTab='overview', runtimeStoryTitle }) => {
  const [open,setOpen] = useState(false);
  const showEpisode = currentTab === 'workbench';
  return <header className="relative z-20 flex h-12 shrink-0 items-center justify-between gap-4 border-b border-[var(--border-subtle)] bg-[var(--bg-workspace)] px-5 text-[12px] text-[var(--text-secondary)]">
    <div className="flex items-center gap-2 min-w-0">
      <span className="hidden sm:inline font-medium text-[var(--text-tertiary)]">StoryOS</span>
      <span className="hidden sm:inline text-[var(--border-strong)]">/</span>
      {!showEpisode ? <span className="truncate text-[14px] font-semibold tracking-tight text-[var(--text-primary)]">{PAGE_NAMES[currentTab] || '工作区'}</span> :
        runtimeStoryTitle ? <span className="max-w-[320px] truncate text-[14px] font-semibold text-[var(--text-primary)]" title={runtimeStoryTitle}>{runtimeStoryTitle}</span> :
        <div className="relative min-w-0">
          <button type="button" onClick={()=>setOpen(!open)} aria-expanded={open} aria-label="选择故事" className="flex items-center gap-2 min-w-0 rounded-[4px] px-2 py-1 hover:bg-[var(--bg-hover)]">
            <span className="max-w-[260px] truncate font-semibold text-[var(--text-primary)]">{activeEpisode.title}</span><ChevronDown size={14}/>
          </button>
          {open && <div className="absolute left-0 top-full mt-2 z-40 min-w-[260px] max-h-[360px] overflow-y-auto border border-[var(--border-normal)] rounded-[6px] bg-[var(--bg-elevated)] p-1 shadow-lg">
            {allEpisodes.map(ep=><button key={ep.id} type="button" onClick={()=>{onSelectEpisode(ep);setOpen(false);}} className="block w-full truncate px-3 py-2 text-left text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]">{ep.title}</button>)}
          </div>}
        </div>}
      {showEpisode && !runtimeStoryTitle && <span className="hidden lg:block text-[11px] tabular-nums text-[var(--text-tertiary)]">{activeEpisode.completedFrames}/{activeEpisode.totalFrames} 帧</span>}
    </div>
    <div className="flex shrink-0 items-center gap-2">
      {import.meta.env.VITE_STORYOS_LOCAL_EVIDENCE_MODE === 'true' && <span role="status" data-testid="local-real-evidence-banner" title="本机真实作品状态文件；只读快照，非 MySQL 权威运行状态，不代表在线任务" className="inline-flex items-center gap-2 border-l-2 border-[var(--warning)] px-2 py-1 text-[11px] font-medium text-[var(--text-secondary)]"><span className="h-1.5 w-1.5 rounded-full bg-[var(--warning)]"/>本机文件 · 只读</span>}
      {showEpisode && !runtimeStoryTitle && <button type="button" onClick={onToggleContextPanel} title={contextPanelOpen?'收起详情':'打开详情'} aria-label="切换详情面板" className="p-1.5 text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] rounded-[4px]"><PanelRight size={16}/></button>}
    </div>
  </header>;
};
