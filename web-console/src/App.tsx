import React, { useState, useEffect, useRef, Suspense } from 'react';
import { Sidebar } from './components/Sidebar';
import { HeaderBar } from './components/HeaderBar';
import { StatusFlowBanner } from './components/StatusFlowBanner';
import { StoryNextAction } from './components/StoryNextAction';
import { ProductionMetricsPanel } from './components/ProductionMetricsPanel';
import { CommandDock } from './components/CommandDock';
import { ContextPanel } from './components/ContextPanel';

// Views
const ActivityStream = React.lazy(() => import('./components/ActivityStream').then(m => ({ default: m.ActivityStream })));
const ProductionMonitorView = React.lazy(() => import('./components/views/ProductionMonitorView').then(m => ({ default: m.ProductionMonitorView })));
const HomeOverviewView = React.lazy(() => import('./components/views/HomeOverviewView').then(m=>({default:m.HomeOverviewView})));
const AntdSurface = React.lazy(() => import('./components/AntdSurface'));
const WorkflowWorkspaceView = React.lazy(() => import('./components/views/WorkflowWorkspaceView').then(m => ({ default: m.WorkflowWorkspaceView })));
const AgentWorkspaceView = React.lazy(() => import('./components/views/AgentWorkspaceView').then(m => ({ default: m.AgentWorkspaceView })));
const SeriesLibraryView = React.lazy(() => import('./components/views/SeriesLibraryView').then(m => ({ default: m.SeriesLibraryView })));
const RuntimeLogsView = React.lazy(() => import('./components/views/RuntimeLogsView').then(m => ({ default: m.RuntimeLogsView })));
const SettingsView = React.lazy(() => import('./components/views/SettingsView').then(m => ({ default: m.SettingsView })));

import { REAL_EPISODES } from './data/storyosEpisodeSnapshots';
import { isHistoricalEpisodeIndex, loadHistoricalEpisodeDetail } from './data/storyosEpisodeLoader';
import { platformApi } from './api/platformApi';
import { Episode, NavigationTab, ProductionStage, ThemeMode, ProjectItem } from './types';

const STORY_PLACEHOLDER_IMAGE = 'data:image/svg+xml;charset=UTF-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%20800%201000%22%3E%3Crect%20width%3D%22800%22%20height%3D%221000%22%20fill%3D%22%23e4e4e7%22%2F%3E%3Cpath%20d%3D%22M160%20720%20340%20500l120%20140%2090-110%20110%20190H160Z%22%20fill%3D%22%23a1a1aa%22%2F%3E%3Ccircle%20cx%3D%22300%22%20cy%3D%22330%22%20r%3D%2270%22%20fill%3D%22%23a1a1aa%22%2F%3E%3C%2Fsvg%3E';
import { Search, X, CheckCircle2, AlertCircle, Bell, Clock, ChevronDown } from 'lucide-react';

const DEFAULT_PROJECTS: ProjectItem[] = [
  {
    id: 'proj-aigc-dali',
    name: 'aigc-dali-cat',
    description: 'AIGC 视觉模型与工作流项目',
    createdAt: '2026-09-01',
    episodeIds: ['ep-10-01', 'ep-10-02'],
  },
  {
    id: 'proj-storyos',
    name: 'story OS',
    description: 'StoryOS 短剧核心生产与调度中枢',
    createdAt: '2026-09-07',
    episodeIds: ['ep-10-B01', 'ep-09-04', 'ep-09-05'],
  },
  {
    id: 'proj-urban',
    name: '《都市怪谈》系列',
    description: '都市情感与心理悬疑短剧矩阵',
    createdAt: '2026-08-20',
    episodeIds: ['ep-10-01', 'ep-10-02', 'ep-10-B01'],
  },
  {
    id: 'proj-relic',
    name: '《旧物惊魂》系列',
    description: '三十年旧物回响与微缩空间怪谈',
    createdAt: '2026-08-25',
    episodeIds: ['ep-09-04', 'ep-09-05', 'ep-11-01', 'ep-11-01-RE'],
  },
];

export default function App() {
  const [episodes, setEpisodes] = useState<Episode[]>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('storyos_local_story_drafts_v1') || '[]');
      if (!Array.isArray(saved)) return REAL_EPISODES;
      const drafts = saved.filter((value: unknown): value is Episode => {
        if (!value || typeof value !== 'object') return false;
        const record = value as Partial<Episode>;
        return typeof record.id === 'string' && /^ep-(home|proj)-/.test(record.id)
          && typeof record.title === 'string' && Array.isArray(record.frameReviews)
          && Array.isArray(record.preflightChecks) && Boolean(record.runtimeRequest);
      });
      return [...drafts, ...REAL_EPISODES];
    } catch { return REAL_EPISODES; }
  });
  useEffect(() => {
    try { localStorage.setItem('storyos_local_story_drafts_v1', JSON.stringify(episodes.filter(ep => /^ep-(home|proj)-/.test(ep.id)))); } catch { /* restricted local storage */ }
  }, [episodes]);
  const [activeEpisode, setActiveEpisode] = useState<Episode>(REAL_EPISODES[0]);
  const [currentTab, setCurrentTab] = useState<NavigationTab>('overview');
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailRetry, setDetailRetry] = useState(0);
  const detailGeneration = useRef(0);
  // 目录索引不包含真实审核/分镜证据，进入制作台才按 Episode 身份加载详情。
  useEffect(() => {
    if (currentTab !== 'workbench' || !isHistoricalEpisodeIndex(activeEpisode)) {
      setDetailError(null);
      return;
    }
    const episodeId = activeEpisode.id;
    const generation = ++detailGeneration.current;
    setDetailError(null);
    loadHistoricalEpisodeDetail(episodeId).then(detail => {
      if (detailGeneration.current !== generation) return;
      if (detail.id !== episodeId) throw new Error('作品详情与目录身份不一致');
      setEpisodes(previous => previous.map(ep => ep.id === episodeId ? detail : ep));
      setActiveEpisode(previous => previous.id === episodeId ? detail : previous);
    }).catch(error => {
      if (detailGeneration.current === generation) setDetailError(error instanceof Error ? error.message : '历史证据未能加载');
    });
    return () => { ++detailGeneration.current; };
  }, [currentTab, activeEpisode.id, activeEpisode.runtimeRequest.sourceBadge, detailRetry]);
  const [isGeneratingBatch] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  // Prioritise the creator canvas; the evidence rail stays one click away.
  const [contextPanelOpen, setContextPanelOpen] = useState(false);

  // 项目管理状态 (系列即项目，项目下包含具体作品)
  const [projects, setProjects] = useState<ProjectItem[]>(() => {
    try {
      const saved = localStorage.getItem('storyos_projects');
      if (saved) return JSON.parse(saved);
    } catch {}
    return DEFAULT_PROJECTS;
  });

  const saveProjects = (newProjects: ProjectItem[]) => {
    setProjects(newProjects);
    try {
      localStorage.setItem('storyos_projects', JSON.stringify(newProjects));
    } catch {}
  };

  // 项目同级的“最近故事”状态管理 (主页自建故事与最近活跃故事)
  const [recentStoryIds, setRecentStoryIds] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem('storyos_recent_story_ids');
      if (saved) return JSON.parse(saved);
    } catch {}
    return ['ep-10-01', 'ep-10-02', 'ep-10-B01'];
  });

  const saveRecentStories = (newIds: string[]) => {
    setRecentStoryIds(newIds);
    try {
      localStorage.setItem('storyos_recent_story_ids', JSON.stringify(newIds));
    } catch {}
  };

  const handleCreateProject = (name: string) => {
    const newProj: ProjectItem = {
      id: `proj-${Date.now()}`,
      name,
      createdAt: new Date().toISOString().split('T')[0],
      episodeIds: [],
    };
    saveProjects([newProj, ...projects]);
    showToast(`已成功创建项目: ${name}`);
  };

  const handleRenameProject = (projectId: string, newName: string) => {
    const updated = projects.map(p => p.id === projectId ? { ...p, name: newName } : p);
    saveProjects(updated);
    showToast(`项目名称已修改为: ${newName}`);
  };

  const handleDeleteProject = (projectId: string) => {
    const target = projects.find(p => p.id === projectId);
    if (!target) return;
    if (projects.length <= 1) {
      showToast('至少保留一个项目');
      return;
    }
    const updated = projects.filter(p => p.id !== projectId);
    saveProjects(updated);
    showToast(`已删除项目: ${target.name}`);
  };

  // 基础故事结构构建器
  const buildNewEpisode = (id: string, title: string, projectId?: string, initialSynopsis?: string): Episode => {
    return {
      id,
      code: 'LOCAL-' + id.slice(-8),
      title,
      projectId,
      synopsis: initialSynopsis || title + ' · 本地草稿，尚未提交生产 Runtime。',
      logline: '尚未设置故事梗概',
      genre: '未分类',
      targetAudience: '未设置',
      totalFrames: 0,
      completedFrames: 0,
      currentStage: 'IDEA_LOCK',
      stageProgressPercent: 0,
      coverImage: STORY_PLACEHOLDER_IMAGE,
      updatedAt: '刚刚',
      runtimeRequest: {
        imageModel: 'gpt-image-2',
        quality: 'high',
        aspectRatio: '4:5 1080×1350',
        batchMode: '5 帧逻辑批次',
        maxConcurrentImages: 3,
        executionLayer: 'StoryOS Engine',
        sourceBadge: '待连接工作区',
      },
      characters: [],
      visualLocks: [],
      storyboardBeats: [],
      currentBatch: {
        batchId: 'batch-01',
        batchNumber: 1,
        batchName: '未建立生产批次（本地草稿）',
        targetFrames: '未分配',
        totalImages: 0,
        createdAt: '未创建',
        status: 'processing',
        items: [],
      },
      frameReviews: [],
      preflightChecks: [],
      performance: Object.fromEntries((['6h','24h','48h','7d'] as const).map(timeframe => [timeframe, { timeframe, label:'无统计记录', completionRate:'—', completionDelta:'—', views:'—', viewsDelta:'—', shareVelocity:'—', retentionSpikeBeat:'—', retentionDropBeat:'—', viralityIndex:'—', audienceSentiment:'—', trendData:[] }])) as Episode['performance'],
    };
  };

  // 1. 在项目上新建的故事，自动归入该项目
  const handleCreateStoryInProject = (projectId: string, title?: string) => {
    const targetProject = projects.find(p => p.id === projectId);
    const storyTitle = title || `新剧目 · ${targetProject?.name || '项目'} #${(targetProject?.episodeIds.length || 0) + 1}`;
    const newEpId = `ep-proj-${Date.now()}`;
    const newEpisode = buildNewEpisode(newEpId, storyTitle, projectId);

    setEpisodes(prev => [newEpisode, ...prev]);
    const updatedProjects = projects.map(p =>
      p.id === projectId
        ? { ...p, episodeIds: [newEpId, ...p.episodeIds] }
        : p
    );
    saveProjects(updatedProjects);
    setActiveEpisode(newEpisode);
    setCurrentTab('workbench');
    showToast('已在本机项目中保存故事草稿，尚未提交生产 Runtime');
  };

  // 2. 如果是从主页自己建的故事，自动归入项目同级的“最近故事”中
  const handleCreateStoryFromHome = (title?: string) => {
    const count = recentStoryIds.length + 1;
    const storyTitle = title || `主页独立故事 #${count}`;
    const newEpId = `ep-home-${Date.now()}`;
    // 从主页自建，不归入任何特定项目
    const newEpisode = buildNewEpisode(newEpId, storyTitle, undefined);

    setEpisodes(prev => [newEpisode, ...prev]);
    // 自动归入项目同级的“最近故事”中，排在首位
    const nextRecent = [newEpId, ...recentStoryIds.filter(id => id !== newEpId)];
    saveRecentStories(nextRecent);
    setActiveEpisode(newEpisode);
    setCurrentTab('workbench');
    showToast('已在本机保存故事草稿，尚未提交生产 Runtime');
  };

  // 从最近故事移除
  const handleRemoveRecentStory = (storyId: string) => {
    const nextRecent = recentStoryIds.filter(id => id !== storyId);
    saveRecentStories(nextRecent);
  };

  // 主题模式: dark | light | light-gradient
  const [currentTheme, setCurrentTheme] = useState<ThemeMode>('dark');

  const handleThemeChange = (mode: ThemeMode) => {
    setCurrentTheme(mode);
    document.documentElement.classList.remove('theme-dark', 'theme-light', 'theme-light-gradient');
    document.documentElement.classList.add(`theme-${mode}`);
    try {
      localStorage.setItem('storyos_theme', mode);
    } catch {
      // ignore
    }
    showToast(`已切换为${mode === 'dark' ? '深色' : mode === 'light' ? '浅色' : '浅色渐变'}主题`);
  };

  useEffect(() => {
    try {
      const savedTheme = localStorage.getItem('storyos_theme') as ThemeMode | null;
      if (savedTheme && ['dark', 'light', 'light-gradient'].includes(savedTheme)) {
        setCurrentTheme(savedTheme);
        document.documentElement.classList.remove('theme-dark', 'theme-light', 'theme-light-gradient');
        document.documentElement.classList.add(`theme-${savedTheme}`);
      } else {
        document.documentElement.classList.add('theme-dark');
      }
    } catch {
      document.documentElement.classList.add('theme-dark');
    }
  }, []);

  // Search and Notifications Modals
  const [searchModalOpen, setSearchModalOpen] = useState(false);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [notifications, setNotifications] = useState<{ id: string; title: string; desc: string; time: string; unread: boolean }[]>([]);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 2500);
  };

  // Keyboard shortcut Ctrl/Cmd + K for quick search & Escape to dismiss
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchModalOpen(prev => !prev);
      } else if (e.key === 'Escape') {
        setSearchModalOpen(false);
        setNotificationsOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // 生产阶段和生成/审查权威属于 Platform Runtime，Web Console 暂无写入 API。
  // 这些入口必须明确说明只读，绝不在本地伪造成功或推进 canonical stage。
  const handleStageChange = (_newStage: ProductionStage) => {
    showToast('当前仅可查看阶段。请在受控 StoryOS Runtime 完成状态流转。');
  };
  const handleQuickGenerateNextBatch = () => {
    showToast('尚未接入受控图片调度 API，未发起生成。');
  };
  const handleCommandSubmit = (_commandText: string) => {
    showToast('当前仅支持工作区查看，命令未提交至生产 Runtime。');
  };
  const handleReviewAction = (_frameId: string, _action: 'pass' | 'inpaint' | 'reject') => {
    showToast('该操作需要审核权威接口，当前未执行任何审核变更。');
  };

  const searchResults = episodes.filter(ep =>
    ep.title.toLowerCase().includes(searchKeyword.toLowerCase()) ||
    ep.code.toLowerCase().includes(searchKeyword.toLowerCase()) ||
    ep.synopsis.toLowerCase().includes(searchKeyword.toLowerCase())
  );

  return (
    <div id="storyos-workspace-root" className="flex h-dvh w-full min-w-0 overflow-hidden bg-[var(--bg-app)] text-[var(--text-primary)] font-sans antialiased select-text">
      {import.meta.env.VITE_STORYOS_FIXTURE_MODE === 'true' && (
        <div role="status" data-testid="local-fixture-banner" className="fixed bottom-3 left-1/2 -translate-x-1/2 z-50 pointer-events-none border border-[var(--warning)] bg-[var(--bg-elevated)] px-4 py-2 rounded-[5px] shadow-lg text-[12px] text-[var(--text-primary)]">
          本机隔离测试模式 · Platform API 仅使用内存样例数据 · 非真实生产状态
        </div>
      )}
      {/* 1. 纯黑底白字极简左侧边栏 */}
      <Sidebar
        currentTab={currentTab}
        onSelectTab={(tab) => setCurrentTab(tab)}
        activeEpisode={activeEpisode}
        allEpisodes={episodes}
        onSelectEpisode={(ep) => setActiveEpisode(ep)}
        projects={projects}
        onCreateProject={handleCreateProject}
        onRenameProject={handleRenameProject}
        onDeleteProject={handleDeleteProject}
        onCreateStoryInProject={handleCreateStoryInProject}
        onCreateStoryFromHome={handleCreateStoryFromHome}
        recentStoryIds={recentStoryIds}
        onRemoveRecentStory={handleRemoveRecentStory}
        onNewConversation={() => {
          handleCreateStoryFromHome();
        }}
        onOpenSearch={() => setSearchModalOpen(true)}
        onOpenNotifications={() => setNotificationsOpen(true)}
        unreadCount={notifications.filter(n => n.unread).length}
        onToggleContextPanel={() => setContextPanelOpen(!contextPanelOpen)}
        contextPanelOpen={contextPanelOpen}
        currentTheme={currentTheme}
        onThemeChange={handleThemeChange}
        onShowToast={showToast}
      />

      {/* 2. 中间主工作台 */}
      <div className="flex-1 flex flex-col h-screen overflow-hidden relative min-w-0 bg-[var(--bg-app)]">
        {/* 顶部极简标题栏 */}
        <HeaderBar
          activeEpisode={activeEpisode}
          allEpisodes={episodes}
          onSelectEpisode={(ep) => setActiveEpisode(ep)}
          onToggleContextPanel={() => setContextPanelOpen(!contextPanelOpen)}
          contextPanelOpen={contextPanelOpen}
          currentTab={currentTab}
          onOpenSettings={() => setCurrentTab('settings')}
        />

        {/* 消息与活动主轴 (日志视图占满屏幕全屏铺开) */}
        <main className={`min-h-0 min-w-0 flex-1 ${currentTab === 'logs' ? 'p-0 overflow-hidden' : 'overflow-y-auto px-4 py-4 lg:px-5 xl:py-5 2xl:px-6'} relative scrollbar-thin scrollbar-thumb-[var(--border-normal)] bg-[var(--bg-app)]`}>
          {/* 轻量 Toast */}
          {toastMessage && (
            <div className="fixed top-12 right-6 z-50 bg-[var(--bg-elevated)] text-[var(--text-primary)] px-3.5 py-1.5 rounded-[6px] text-xs font-medium flex items-center gap-2 shadow-lg border border-[var(--border-normal)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#58A6FF]" />
              <span>{toastMessage}</span>
            </div>
          )}

          <Suspense fallback={<div role="status" className="py-10 text-center text-[13px] text-[var(--text-secondary)]">正在载入工作区…</div>}>
          {currentTab === 'overview' && <AntdSurface><HomeOverviewView episodes={episodes} projects={projects} onSelectEpisode={(ep) => { setActiveEpisode(ep); setCurrentTab('workbench'); }} onNewStory={() => handleCreateStoryFromHome()} onNavigate={setCurrentTab} /></AntdSurface>}

          {/* 生产监控台主控页 (StoryOS 生产监控台 V1.0 - Dense Operations Console) */}
          {currentTab === 'production_monitor' && (
            <div className="w-full">
              <AntdSurface><ProductionMonitorView
                onShowToast={showToast}
                onSelectStoryRun={(run) => {
                  const matchEp = episodes.find(e => e.title === run.storyName);
                  if (matchEp) {
                    setActiveEpisode(matchEp);
                  }
                }}
              /></AntdSurface>
            </div>
          )}

          {/* canonical 阶段只读检视，不可前端直接推进 */}
          {currentTab === 'pipeline' && <AntdSurface><WorkflowWorkspaceView /></AntdSurface>}
          {currentTab === 'agents' && <AntdSurface><AgentWorkspaceView /></AntdSurface>}

          {/* 剧集库视图 */}
          {currentTab === 'episodes' && (
            <div className="w-full">
              <AntdSurface><SeriesLibraryView
                episodes={episodes}
                activeEpisode={activeEpisode}
                onSelectEpisode={(ep) => {
                  setActiveEpisode(ep);
                  setCurrentTab('workbench');
                }}
                onGoToWorkbench={() => setCurrentTab('workbench')}
                onNewStoryClick={() => handleCreateStoryFromHome()}
              /></AntdSurface>
            </div>
          )}

          {/* 运行日志审计视图 (占满屏幕，全屏展示) */}
          {currentTab === 'logs' && (
            <div className="w-full h-full flex flex-col overflow-hidden">
              <AntdSurface><RuntimeLogsView /></AntdSurface>
            </div>
          )}

          {/* 系统设置视图 */}
          {currentTab === 'settings' && (
            <div className="w-full min-w-0">
              <AntdSurface><SettingsView
                currentTheme={currentTheme}
                onThemeChange={handleThemeChange}
              /></AntdSurface>
            </div>
          )}

          {/* 核心工作流：呼吸感单主轴 */}
          {currentTab === 'workbench' && (
            <div className="w-full min-w-0 space-y-4 pb-8">
              {isHistoricalEpisodeIndex(activeEpisode) ? (
                <section role={detailError ? 'alert' : 'status'} className="border border-[var(--border-normal)] p-5 text-[13px] text-[var(--text-secondary)]">
                  {detailError ? <>
                    <p>历史作品详细证据加载失败：{detailError}。不能据此判断审核或阶段结果。</p>
                    <button type="button" className="mt-3 text-[var(--text-primary)] underline" onClick={() => setDetailRetry(n => n + 1)}>重新加载该作品</button>
                  </> : <p>正在按需加载《{activeEpisode.title}》的历史分镜和审核证据…</p>}
                </section>
              ) : <>
              <StoryNextAction episode={activeEpisode} onOpenWorkflow={() => setCurrentTab('pipeline')} />
              {/* 创作时先展示分镜和素材；完整阶段证据按需展开，不丢失任何门禁数据。 */}
              <details className="group border-b border-[var(--border-subtle)] pb-3" aria-label="生产阶段与制作指标">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
                  <span className="flex items-center gap-2"><ChevronDown size={14} className="-rotate-90 transition-transform group-open:rotate-0"/>生产阶段与制作指标 <span className="text-[var(--text-tertiary)] tabular-nums">{activeEpisode.completedFrames}/{activeEpisode.totalFrames} 帧 · 工作区证据</span></span>
                  <span className="text-[11px] text-[var(--text-tertiary)] group-open:hidden">展开生产证据</span><span className="hidden text-[11px] text-[var(--text-tertiary)] group-open:inline">收起生产证据</span>
                </summary>
                <div className="mt-4 space-y-4">
                  <StatusFlowBanner currentStage={activeEpisode.currentStage} onStageChange={handleStageChange} completedFrames={activeEpisode.completedFrames} totalFrames={activeEpisode.totalFrames} onOpenPipelineView={() => setCurrentTab('pipeline')}/>
                  <ProductionMetricsPanel activeEpisode={activeEpisode} onShowToast={showToast}/>
                </div>
              </details>

              {/* 素材 / 分镜主工作区与审核 Inspector */}
              <AntdSurface><ActivityStream
                key={activeEpisode.id}
                activeEpisode={activeEpisode}
                onGenerateBatch={handleQuickGenerateNextBatch}
                isGeneratingBatch={isGeneratingBatch}
                onReviewAction={handleReviewAction}
                onShowToast={showToast}
              /></AntdSurface>
              </>}
            </div>
          )}
          </Suspense>
        </main>

        {/* 3. 悬浮极简输入坞（纯黑底白字） */}
        {currentTab === 'workbench' && !isHistoricalEpisodeIndex(activeEpisode) && (
          <CommandDock
            onSendMessage={handleCommandSubmit}
            isLoading={isGeneratingBatch}
          />
        )}
      </div>

      {/* 4. 纯净右侧上下文与资产账本栏 (日志与大盘下自动让出全屏) */}
      {contextPanelOpen && currentTab === 'workbench' && !isHistoricalEpisodeIndex(activeEpisode) && (
        <ContextPanel
          activeEpisode={activeEpisode}
          onClose={() => setContextPanelOpen(false)}
          onShowToast={showToast}
        />
      )}

      {/* 5. 全局搜索模态弹窗 (Ctrl + K / 侧边栏搜索) */}
      {searchModalOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-start justify-center pt-24 px-4 backdrop-blur-xs"
          onClick={() => setSearchModalOpen(false)}
        >
          <div
            className="w-full max-w-lg overflow-hidden rounded-[8px] border border-[var(--border-normal)] bg-[var(--bg-elevated)] text-[var(--text-primary)] shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-3 border-b border-[var(--border-subtle)] flex items-center gap-2">
              <Search className="w-4 h-4 text-[var(--text-secondary)]" />
              <input
                type="text"
                autoFocus
                value={searchKeyword}
                onChange={(e) => setSearchKeyword(e.target.value)}
                placeholder="搜索剧集编号、标题、剧情关键词..."
                className="w-full bg-transparent text-sm text-[var(--text-primary)] placeholder-[var(--text-tertiary)] focus:outline-hidden"
              />
              <button
                type="button"
                onClick={() => setSearchModalOpen(false)}
                className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-xs px-1.5 py-0.5 rounded cursor-pointer"
              >
                ESC
              </button>
            </div>

            <div className="max-h-72 overflow-y-auto p-2 space-y-1">
              {searchResults.length === 0 ? (
                <div className="py-6 text-center text-xs text-[var(--text-tertiary)] font-mono">未找到匹配的故事资产</div>
              ) : (
                searchResults.map(ep => (
                  <button
                    key={ep.id}
                    type="button"
                    onClick={() => {
                      setActiveEpisode(ep);
                      setCurrentTab('workbench');
                      setSearchModalOpen(false);
                      showToast(`已切换至: ${ep.code} ${ep.title}`);
                    }}
                    className="w-full text-left p-2 rounded-lg hover:bg-[var(--bg-hover)] transition-colors flex items-center justify-between cursor-pointer"
                  >
                    <div>
                      <div className="text-xs font-semibold text-[var(--text-primary)] flex items-center gap-2">
                        <span className="font-mono text-[var(--text-tertiary)] font-bold">{ep.code}</span>
                        <span>{ep.title}</span>
                      </div>
                      <div className="text-[11px] text-[var(--text-secondary)] truncate max-w-sm">{ep.synopsis}</div>
                    </div>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[var(--bg-surface)] border border-[var(--border-normal)] text-[var(--text-secondary)]">
                      {ep.completedFrames}/{ep.totalFrames} 帧
                    </span>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* 6. 通知与流水抽屉 */}
      {notificationsOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex justify-end backdrop-blur-xs"
          onClick={() => setNotificationsOpen(false)}
        >
          <div
            className="w-80 bg-[var(--bg-elevated)] border-l border-[var(--border-normal)] h-full p-4 flex flex-col space-y-3 shadow-2xl text-[var(--text-primary)]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-[var(--border-subtle)] pb-3">
              <div className="flex items-center gap-2">
                <Bell className="w-4 h-4 text-[var(--text-primary)]" />
                <span className="text-xs font-bold text-[var(--text-primary)]">生产通知与质检流水</span>
              </div>
              <button
                type="button"
                onClick={() => setNotificationsOpen(false)}
                className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)] text-xs cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="flex-1 overflow-y-auto space-y-2">
              {notifications.map(n => (
                <div
                  key={n.id}
                  className={`p-2.5 rounded-xl border text-xs space-y-1 ${
                    n.unread
                      ? 'bg-[var(--bg-surface)] border-[var(--border-strong)] text-[var(--text-primary)] shadow-xs'
                      : 'bg-[var(--bg-workspace)] border-[var(--border-subtle)] text-[var(--text-secondary)]'
                  }`}
                >
                  <div className="flex items-center justify-between font-semibold">
                    <span className="text-[var(--text-primary)]">{n.title}</span>
                    <span className="text-[10px] font-mono text-[var(--text-tertiary)]">{n.time}</span>
                  </div>
                  <div className="text-[11px] leading-relaxed text-[var(--text-secondary)]">{n.desc}</div>
                </div>
              ))}
            </div>

            <button
              type="button"
              onClick={() => {
                setNotifications(prev => prev.map(n => ({ ...n, unread: false })));
                showToast('已全部标记为已读');
              }}
              className="w-full py-1.5 rounded-lg bg-white text-black font-semibold text-xs hover:bg-zinc-200 transition-colors cursor-pointer shadow-xs"
            >
              全部标记为已读
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
