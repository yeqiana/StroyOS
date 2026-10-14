import React, { useMemo, useState } from 'react';
import { Activity, Bell, Bot, ChevronDown, ChevronRight, BookOpenText, FileClock, Folder, GitBranch, LayoutDashboard, Moon, Plus, Search, Settings, Sun, X, MoreHorizontal, UserRound } from 'lucide-react';
import { Episode, NavigationTab, ProjectItem } from '../types';
import { StoryOSMark } from './StoryOSMark';
const CompactProjectsDrawer = React.lazy(() => import('./CompactProjectsDrawer'));

interface SidebarProps {
  currentTab: NavigationTab;
  onSelectTab: (tab: NavigationTab) => void;
  activeEpisode: Episode;
  allEpisodes: Episode[];
  onSelectEpisode: (episode: Episode) => void;
  projects: ProjectItem[];
  onCreateProject: (name: string) => void;
  onRenameProject: (projectId: string, newName: string) => void;
  onDeleteProject: (projectId: string) => void;
  onCreateStoryInProject?: (projectId: string, title?: string) => void;
  onCreateStoryFromHome?: (title?: string) => void;
  recentStoryIds?: string[];
  onRemoveRecentStory?: (storyId: string) => void;
  onAssignStoryToProject?: (storyId: string, projectId: string) => void;
  onNewConversation?: () => void;
  onOpenSearch?: () => void;
  onOpenNotifications?: () => void;
  onOpenProfile?: () => void;
  unreadCount?: number;
  onToggleContextPanel?: () => void;
  contextPanelOpen?: boolean;
  currentTheme?: 'dark' | 'light' | 'light-gradient';
  onThemeChange?: (theme: 'dark' | 'light' | 'light-gradient') => void;
  onShowToast?: (msg: string) => void;
}

const nav = [
  { label: '工作台', id: 'overview', icon: LayoutDashboard },
  { label: '作品与项目', id: 'episodes', icon: Folder },
  { label: '故事制作', id: 'workbench', icon: BookOpenText },
  { label: '生产监控', id: 'production_monitor', icon: Activity },
  { label: '工作流', id: 'pipeline', icon: GitBranch },
  { label: 'Agents', id: 'agents', icon: Bot },
  { label: '审计日志', id: 'logs', icon: FileClock },
] as const;

export const Sidebar: React.FC<SidebarProps> = (props) => {
  const { currentTab, onSelectTab, activeEpisode, allEpisodes, onSelectEpisode, projects,
    onCreateProject, onRenameProject, onDeleteProject, onCreateStoryFromHome,
    onCreateStoryInProject, recentStoryIds = [], onOpenSearch, onOpenNotifications,
    unreadCount = 0, currentTheme = 'dark', onThemeChange } = props;
  const [expandedProject, setExpandedProject] = useState<string | null>(null);
  // Creator-first navigation: project tree remains available on demand, not permanently expanded.
  const [projectsOpen, setProjectsOpen] = useState(false);
  const [recentOpen, setRecentOpen] = useState(false);
  const [compactProjectsOpen,setCompactProjectsOpen]=useState(false);
  const [modal, setModal] = useState<'project' | 'story' | 'rename' | null>(null);
  const [projectForAction, setProjectForAction] = useState<ProjectItem | null>(null);
  const [draft, setDraft] = useState('');
  const [projectMenu, setProjectMenu] = useState<string | null>(null);

  const recents = useMemo(() => {
    const arranged = recentStoryIds.map(id => allEpisodes.find(ep => ep.id === id)).filter((ep): ep is Episode => !!ep);
    allEpisodes.forEach(ep => { if (!arranged.some(item => item.id === ep.id)) arranged.push(ep); });
    return arranged.slice(0, 8);
  }, [recentStoryIds, allEpisodes]);

  const openModal = (type: 'project' | 'story' | 'rename', project: ProjectItem | null = null) => {
    setProjectForAction(project);
    setDraft(type === 'rename' ? (project?.name ?? '') : '');
    setModal(type);
    setProjectMenu(null);
  };
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const name = draft.trim();
    if (!name) return;
    if (modal === 'project') onCreateProject(name);
    if (modal === 'rename' && projectForAction) onRenameProject(projectForAction.id, name);
    if (modal === 'story') {
      if (projectForAction) onCreateStoryInProject?.(projectForAction.id, name);
      else onCreateStoryFromHome?.(name);
    }
    setModal(null);
  };
  const pickStory = (ep: Episode) => { onSelectEpisode(ep); onSelectTab('workbench'); };

  return (
    <aside aria-label="主导航" className="storyos-sidebar flex h-full w-[224px] shrink-0 flex-col border-r border-[var(--border-subtle)] bg-[var(--bg-workspace)] text-[13px]">
      <div className="h-[52px] flex items-center justify-between px-3 border-b border-[var(--border-subtle)]">
        <button onClick={() => onSelectTab('overview')} className="text-left flex items-center gap-3 text-[var(--text-primary)] font-semibold tracking-tight" type="button" aria-label="返回 StoryOS 工作台">
          <StoryOSMark size={31}/>
          <span className="storyos-sidebar-brand text-[15px] leading-5">StoryOS</span>
        </button>
        <div className="storyos-sidebar-header-actions flex items-center gap-1">
          <button type="button" onClick={onOpenSearch} className="p-1.5 rounded-[4px] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)]" title="搜索 Ctrl+K" aria-label="搜索"><Search size={16}/></button>
          <button type="button" onClick={onOpenNotifications} className="relative p-1.5 rounded-[4px] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)]" title="通知" aria-label="通知"><Bell size={16}/>{unreadCount > 0 && <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-[var(--info)]" />}</button>
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto px-2.5 py-3 space-y-4">
        {currentTab !== 'overview' && <div className="storyos-sidebar-create px-1">
          <button type="button" onClick={() => openModal('story')} className="os-action os-action-primary w-full !h-9 text-[13px] font-semibold"><Plus size={16}/> 新建故事</button>
        </div>}
        <nav aria-label="主要页面" className="space-y-1"><p className="storyos-sidebar-section-label px-3 pb-2 os-eyebrow">内容制作</p>
          {nav.slice(0,3).map(item => {
            const Icon = item.icon;
            return <button key={item.id} type="button" onClick={() => onSelectTab(item.id)} aria-label={item.label} title={item.label} aria-current={currentTab === item.id ? 'page' : undefined}
              className={`relative w-full h-9 flex items-center gap-3 px-3 rounded-[6px] text-left transition-colors ${currentTab === item.id ? 'bg-[var(--bg-selected)] text-[var(--text-primary)] font-semibold shadow-[inset_2px_0_0_var(--info)]' : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]'}`}>
              <Icon size={16} strokeWidth={1.75} aria-hidden="true"/><span className="storyos-sidebar-nav-label">{item.label}</span>
            </button>;
          })}
          <div className="mx-2 my-3 border-t border-[var(--border-subtle)]" />
          <p className="storyos-sidebar-section-label px-3 pb-2 os-eyebrow">运行与管理</p>
          {nav.slice(3).map(item => {const Icon=item.icon;return <button key={item.id} type="button" onClick={()=>onSelectTab(item.id)} aria-label={item.label} title={item.label} aria-current={currentTab===item.id?'page':undefined} className={`relative flex h-9 w-full items-center gap-3 rounded-[6px] px-3 text-left transition-colors ${currentTab===item.id?'bg-[var(--bg-selected)] font-semibold text-[var(--text-primary)] shadow-[inset_2px_0_0_var(--info)]':'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]'}`}><Icon size={16} strokeWidth={1.75} aria-hidden="true"/><span className="storyos-sidebar-nav-label">{item.label}</span></button>})}
        </nav>
        <button type="button" className="storyos-compact-project-trigger" onClick={()=>setCompactProjectsOpen(true)} title="打开项目快捷面板" aria-label="打开项目快捷面板"><Folder size={19} aria-hidden="true"/></button>
        <section aria-label="项目列表" className="storyos-sidebar-projects pt-2 border-t border-[var(--border-subtle)]">
          <div className="flex items-center justify-between px-2 pb-2">
            <button type="button" aria-expanded={projectsOpen} onClick={() => setProjectsOpen(!projectsOpen)} className="flex items-center gap-1 text-[11px] font-semibold tracking-wide text-[var(--text-tertiary)] hover:text-[var(--text-primary)]">
              {projectsOpen ? <ChevronDown size={13}/> : <ChevronRight size={13}/>} 项目空间 <span className="font-normal">{projects.length}</span>
            </button>
            <button type="button" onClick={() => openModal('project')} aria-label="新建项目" title="新建项目" className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"><Plus size={15}/></button>
          </div>
          {projectsOpen && <div className="space-y-0.5">
            {projects.map(project => {
              const children = allEpisodes.filter(ep => project.episodeIds.includes(ep.id));
              return <div key={project.id}>
                <div className="group flex items-center gap-1 rounded-[5px] hover:bg-[var(--bg-hover)]">
                  <button type="button" onClick={() => setExpandedProject(expandedProject === project.id ? null : project.id)} className="flex flex-1 min-w-0 h-8 items-center gap-2 px-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)]" aria-expanded={expandedProject === project.id}>
                    {expandedProject === project.id ? <ChevronDown size={12}/> : <ChevronRight size={12}/>}
                    <Folder size={15} className="shrink-0 text-[var(--text-tertiary)]"/>
                    <span className="truncate">{project.name}</span><span className="ml-auto text-[11px] text-[var(--text-tertiary)]">{children.length}</span>
                  </button>
                  <button type="button" onClick={() => setProjectMenu(projectMenu === project.id ? null : project.id)} aria-label={`管理项目 ${project.name}`} className="px-1 text-[var(--text-tertiary)] opacity-60 focus:opacity-100 group-hover:opacity-100"><MoreHorizontal size={15}/></button>
                </div>
                {projectMenu === project.id && <div className="ml-3 mb-1 flex flex-wrap gap-2 px-2 py-2 text-[11px] border-l border-[var(--border-normal)]">
                  <button type="button" onClick={() => openModal('story', project)} className="text-[var(--info)]">新增故事</button>
                  <button type="button" onClick={() => openModal('rename', project)}>重命名</button>
                  <button type="button" onClick={() => { if(window.confirm(`删除项目「${project.name}」？`)) onDeleteProject(project.id); setProjectMenu(null); }} className="text-[var(--danger)]">删除</button>
                </div>}
                {expandedProject === project.id && <div className="ml-6 border-l border-[var(--border-subtle)] pl-2 space-y-0.5">
                  {children.length === 0 && <p className="px-2 py-1 text-[11px] text-[var(--text-tertiary)]">暂无故事</p>}
                  {children.map(ep => <button key={ep.id} type="button" onClick={() => pickStory(ep)} className={`w-full truncate text-left px-2 py-1.5 rounded-[4px] text-[12px] ${ep.id === activeEpisode.id ? 'text-[var(--text-primary)] bg-[var(--bg-selected)]' : 'text-[var(--text-tertiary)] hover:text-[var(--text-primary)]'}`}>{ep.title}</button>)}
                </div>}
              </div>;
            })}
          </div>}
        </section>
        <section className="storyos-sidebar-recent border-t border-[var(--border-subtle)] pt-3">
          <button type="button" onClick={() => setRecentOpen(!recentOpen)} className="w-full text-left px-2 text-[11px] font-semibold tracking-wide text-[var(--text-tertiary)] flex items-center gap-1">
            {recentOpen ? <ChevronDown size={13}/> : <ChevronRight size={13}/>} 最近作品
          </button>
          {recentOpen && <div className="mt-2 space-y-0.5">{recents.map(ep => <button key={ep.id} type="button" onClick={() => pickStory(ep)} className="block w-full truncate rounded-[4px] px-3 py-1.5 text-left text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]">{ep.title}</button>)}</div>}
        </section>
      </div>
      <div className="border-t border-[var(--border-subtle)] px-3 py-3 space-y-3">
        <div className="storyos-sidebar-theme flex items-center justify-between">
          <span className="text-[11px] text-[var(--text-tertiary)]">外观</span>
          <div className="flex rounded-[5px] border border-[var(--border-normal)] overflow-hidden">
            <button type="button" onClick={() => onThemeChange?.('dark')} className={`p-1.5 ${currentTheme === 'dark' ? 'bg-[var(--bg-selected)] text-[var(--text-primary)]' : 'text-[var(--text-tertiary)]'}`} title="深色"><Moon size={14}/></button>
            <button type="button" onClick={() => onThemeChange?.('light')} className={`p-1.5 ${currentTheme !== 'dark' ? 'bg-[var(--bg-selected)] text-[var(--text-primary)]' : 'text-[var(--text-tertiary)]'}`} title="浅色"><Sun size={14}/></button>
          </div>
        </div>
        <button type="button" onClick={() => onSelectTab('settings')} aria-label="系统设置" title="系统设置" className="h-8 w-full flex items-center gap-2 px-2 rounded-[5px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"><Settings size={15}/><span className="storyos-sidebar-settings-label">系统设置</span></button>
        <button type="button" onClick={props.onOpenProfile} aria-label="个人资料" title="个人资料" className="h-8 w-full flex items-center gap-2 px-2 rounded-[5px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"><UserRound size={15}/><span className="storyos-sidebar-settings-label">个人资料</span></button>
      </div>
      <React.Suspense fallback={null}>{compactProjectsOpen&&<CompactProjectsDrawer projects={projects} episodes={allEpisodes} onClose={()=>setCompactProjectsOpen(false)} onOpenLibrary={()=>onSelectTab('episodes')} onSelectEpisode={pickStory}/>}</React.Suspense>
      {modal && <div role="dialog" aria-modal="true" aria-label={modal === 'project' ? '新建项目' : modal === 'rename' ? '重命名项目' : '新建故事'} className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
        <form onSubmit={submit} className="w-full max-w-sm border border-[var(--border-normal)] rounded-[8px] p-5 bg-[var(--bg-elevated)] shadow-xl space-y-4">
          <div className="flex items-center justify-between text-[var(--text-primary)] font-semibold">
            <span>{modal === 'project' ? '新建项目' : modal === 'rename' ? '重命名项目' : '新建故事'}</span>
            <button type="button" onClick={() => setModal(null)} aria-label="关闭"><X size={17}/></button>
          </div>
          <label className="block text-[12px] text-[var(--text-secondary)]">{modal === 'project' || modal === 'rename' ? '项目名称' : '故事名称'}
            <input autoFocus required maxLength={100} value={draft} onChange={e => setDraft(e.target.value)} placeholder="输入名称" className="mt-2 w-full h-10 rounded-[5px] px-3 bg-[var(--bg-app)] border border-[var(--border-normal)] text-[var(--text-primary)] focus:outline-2 focus:outline-[var(--focus)]" />
          </label>
          <div className="flex items-center justify-end gap-2"><button type="button" onClick={() => setModal(null)} className="px-3 py-2 text-[var(--text-secondary)]">取消</button><button type="submit" className="rounded-[5px] px-4 py-2 bg-[var(--text-primary)] text-[var(--bg-app)] font-semibold">确认</button></div>
        </form>
      </div>}
    </aside>
  );
};
