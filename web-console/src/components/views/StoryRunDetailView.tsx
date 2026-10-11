import React, { useState, useEffect } from 'react';
import {Select} from 'antd';
import {useLocalApprovedMedia} from '../../api/localApprovedMedia';
import {
  ArrowLeft,
  Play,
  Pause,
  RotateCcw,
  Layers,
  Cpu,
  AlertCircle,
  Flame,
  Terminal,
  FileCode,
  Activity,
  Server,
  CheckCircle2,
  Clock,
  ShieldAlert,
  Copy,
  Check,
  Download,
  X,
  Search,
  Sparkles,
  ChevronRight,
  ChevronDown,
  Maximize2,
  Eye,
  RefreshCw,
  AlertTriangle, ImageOff
} from 'lucide-react';
import {
  StoryRunItem,
  FrameDetailItem,
  StoryRunStage,
  FrameStatus,
  StoryRunStatus
} from '../../types';

interface StoryRunDetailViewProps {
  run: StoryRunItem;
  onBack: () => void;
  onShowToast: (msg: string) => void;
  onUpdateRun?: (updated: StoryRunItem) => void;
}

type DetailTabKey =
  | 'overview'
  | 'exceptions'
  | 'events'
  | 'artifacts'
  | 'logs'
  | 'runtime';

type DangerousActionType = 'REGENERATE' | 'SKIP' | 'FORCE_PASS' | 'CANCEL';
const hasVerifiedPreview=(url?:string)=>Boolean(url && !url.startsWith('data:image/svg+xml') && !url.includes('/placeholder'));

export const StoryRunDetailView: React.FC<StoryRunDetailViewProps> = ({
  run,
  onBack,
  onShowToast,
  onUpdateRun
}) => {
  const {findEpisode}=useLocalApprovedMedia();
  const archiveCode=run.id.match(/^run-(\d{2}-\d{2})(?:$|-)/)?.[1];
  const approved=findEpisode(run.storyName,archiveCode);
  const approvedUrl=(frameNo:number)=>approved?.frames.find(x=>x.frame===frameNo)?.url;
  // 默认进入「概览」Tab
  const [activeTab, setActiveTab] = useState<DetailTabKey>('overview');

  // 默认打开 Frame 09（方便展示异常排错诊断）或 Frame 08（展示 PASSED 态）
  const [selectedFrame, setSelectedFrame] = useState<FrameDetailItem | null>(null);

  const [selectedStageKey, setSelectedStageKey] = useState<StoryRunStage>(run.currentStage);
  const [promptExpanded, setPromptExpanded] = useState(false);
  const [copiedText, setCopiedText] = useState<string | null>(null);
  const [logFilter, setLogFilter] = useState<'ALL' | 'INFO' | 'WARN' | 'ERROR' | 'DEBUG'>('ALL');
  const [logSearch, setLogSearch] = useState('');

  // 高清大图全屏预览模态框
  const [imageModalUrl, setImageModalUrl] = useState<string | null>(null);

  // 破坏性操作二次确认模态
  const [confirmAction, setConfirmAction] = useState<{
    type: DangerousActionType;
    frame: FrameDetailItem;
  } | null>(null);

  // 历史 Run 快照不包含经过验证的在线 Worker 心跳。
  const hb = {color:'text-[var(--text-tertiary)]',dot:'bg-[var(--text-tertiary)]',label:'心跳未验证'};

  // 监听 Escape 键，安全级联关闭大图预览、二次确认弹窗或 Frame 抽屉
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (imageModalUrl) {
          setImageModalUrl(null);
        } else if (confirmAction) {
          setConfirmAction(null);
        } else if (selectedFrame) {
          setSelectedFrame(null);
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [imageModalUrl, confirmAction, selectedFrame]);

  // StoryOS 规范状态指示器 (严格按 DESIGN.md: dot 6px, gap 6px, font 12px / 500 font-mono, 无大药丸大色块)
  const getRunStatusBadge = (status: StoryRunStatus) => {
    switch (status) {
      case 'RUNNING':
        return (
          <div className="inline-flex items-center gap-1.5 text-xs font-mono font-medium text-[#4C8DFF]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#4C8DFF]" />
            <span>运行中</span>
          </div>
        );
      case 'COMPLETED':
        return (
          <div className="inline-flex items-center gap-1.5 text-xs font-mono font-medium text-[#3FB950]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#3FB950]" />
            <span>已完成</span>
          </div>
        );
      case 'WAITING':
        return (
          <div className="inline-flex items-center gap-1.5 text-xs font-mono font-medium text-[#C9A227]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#C9A227]" />
            <span>排队中</span>
          </div>
        );
      case 'RETRYING':
        return (
          <div className="inline-flex items-center gap-1.5 text-xs font-mono font-medium text-[#D28B26]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#D28B26]" />
            <span>自动重试中</span>
          </div>
        );
      case 'BLOCKED':
        return (
          <div className="inline-flex items-center gap-1.5 text-xs font-mono font-semibold text-[#E05252]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#E05252]" />
            <span>阻塞 · 需人工介入</span>
          </div>
        );
      case 'FAILED':
        return (
          <div className="inline-flex items-center gap-1.5 text-xs font-mono font-medium text-[#E05252]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#E05252]" />
            <span>执行失败</span>
          </div>
        );
      default:
        return (
          <div className="inline-flex items-center gap-1.5 text-xs font-mono text-[#737D8A]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#505864]" />
            <span>未开始</span>
          </div>
        );
    }
  };

  // 复制文本辅助
  const handleCopy = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopiedText(label);
    onShowToast(`${label}已复制到剪贴板`);
    setTimeout(() => setCopiedText(null), 2000);
  };

  // Run Detail 只读：不允许本地修改 Frame / Run 的权威状态。
  const executeDangerousAction = () => {
    if (!confirmAction) return;
    onShowToast('当前无受控执行接口，未执行任何状态变更。');
    setConfirmAction(null);
  };

  const handleImmediateRetry = (_frame: FrameDetailItem) => {
    onShowToast('重试需要受控 Runtime API，当前未派发任何任务。');
  };

  // 过滤后的日志
  const filteredLogs = (run.logs || []).filter(lg => {
    if (logFilter !== 'ALL' && lg.level !== logFilter) return false;
    if (logSearch && !lg.message.toLowerCase().includes(logSearch.toLowerCase()) && !lg.component.toLowerCase().includes(logSearch.toLowerCase())) {
      return false;
    }
    return true;
  });

  // 获取 Frame 卡片底部状态文本规范
  const getFrameBottomLabel = (frame: FrameDetailItem): string => {
    switch (frame.status) {
      case 'PASSED':
        return frame.duration || 'PASSED';
      case 'GENERATING':
        return frame.currentSubAction ? `IMAGE_GEN / ${frame.duration || '时长未提供'}` : `Generating ${frame.duration || '时长未提供'}`;
      case 'RETRYING':
        return `RETRY ${frame.attempt.replace(/\s+/g, '')}`;
      case 'QUEUED':
        return 'QUEUED';
      case 'BLOCKED':
        return 'BLOCKED';
      case 'NOT_STARTED':
      default:
        return 'NOT_STARTED';
    }
  };

  // 选中的 Stage
  const currentSelectedStage = run.pipelineStages.find(s => s.key === selectedStageKey) || run.pipelineStages[0];
  const selectedPreview=selectedFrame&&(hasVerifiedPreview(selectedFrame.thumbnail) ? selectedFrame.thumbnail : approvedUrl(selectedFrame.frameNo));

  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden bg-[var(--bg-app)] font-sans text-[var(--text-primary)]">
      {/* ========================================================================= */}
      {/* 1. 顶部 Header 强化与精简化 (极简两行紧凑布局) */}
      {/* ========================================================================= */}
      <div className="os-console-toolbar bg-[var(--bg-surface)] border-b border-[var(--border-subtle)] px-4 py-2.5 shrink-0 flex flex-col gap-2">
        {/* 第一行：导航返回、剧目名称、状态与操作按钮 */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={onBack}
              className="px-2.5 py-1 rounded-[4px] bg-[var(--bg-hover)] border border-[var(--border-normal)] hover:bg-[var(--bg-selected)] text-[var(--text-primary)] transition-colors flex items-center gap-1.5 cursor-pointer font-medium text-xs font-mono shrink-0"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>返回列表</span>
            </button>
            <div className="h-3.5 w-px bg-[var(--border-subtle)] shrink-0" />
            <div className="flex min-w-0 flex-wrap items-baseline gap-2">
              <h1 className="text-base font-bold text-[var(--text-primary)] truncate font-sans">
                {run.storyName}
              </h1>
              <span className="text-[11px] font-mono text-[var(--text-secondary)] bg-[var(--bg-workspace)] px-1.5 py-0.5 rounded-[3px] border border-[var(--border-subtle)] shrink-0">
                {run.runId}
              </span>
            </div>
            {getRunStatusBadge(run.status)}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* 耗时与心跳 */}
            <div className="hidden sm:flex items-center gap-3 text-xs font-mono text-[var(--text-secondary)] mr-2">
              <span>快照耗时: <strong className="text-[var(--text-primary)]">{run.duration}</strong></span>
              <span className={`flex items-center gap-1 font-medium ${hb.color}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${hb.dot}`} />
                心跳未验证
              </span>
            </div>

            <button
              type="button"
              onClick={() => onShowToast('审计报告导出接口尚未接入，未生成或下载文件。')}
              className="px-2 py-1 rounded-[4px] bg-[var(--bg-hover)] border border-[var(--border-normal)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors text-xs font-mono flex items-center gap-1 cursor-pointer"
            >
              <Download className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">导出</span>
            </button>
            <span className="border border-[var(--border-normal)] px-2.5 py-1 text-[11px] text-[var(--text-tertiary)]" title="历史 Run 仅支持只读检视；暂停/恢复需要授权 Runtime API">只读 · 不可暂停/恢复</span>
          </div>
        </div>

        {/* 第二行：核心 Tab 切换栏 */}
        <div className="flex items-center gap-1 border-t border-[var(--border-subtle)] pt-2 overflow-x-auto no-scrollbar">
          {[
            { key: 'overview', label: '概览', icon: Activity },
            {
              key: 'exceptions',
              label: '异常',
              icon: ShieldAlert,
              badge: run.exceptionSummary !== '-' ? '1' : undefined,
              warn: run.exceptionSummary !== '-'
            },
            { key: 'events', label: '事件', icon: Clock, badge: '追踪' },
            { key: 'artifacts', label: '产物包', icon: FileCode },
            { key: 'logs', label: '日志', icon: Terminal },
            { key: 'runtime', label: '运行环境', icon: Server },
          ].map(tab => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveTab(tab.key as DetailTabKey)}
                className={`px-2.5 py-1 rounded-[4px] text-xs font-mono font-medium flex items-center gap-1.5 transition-colors cursor-pointer whitespace-nowrap ${
                  isActive
                    ? 'bg-[var(--bg-selected)] text-[var(--text-primary)] border border-[var(--border-normal)] font-semibold'
                    : 'text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] border border-transparent'
                }`}
              >
                <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-[#4C8DFF]' : 'text-[var(--text-tertiary)]'}`} />
                <span>{tab.label}</span>
                {tab.badge && (
                  <span className={`text-[10px] px-1.5 py-0.2 rounded-[3px] font-mono ${
                    isActive
                      ? 'bg-[var(--bg-hover)] text-[var(--text-primary)] border border-[var(--border-subtle)]'
                      : tab.warn
                      ? 'bg-[#E05252]/15 text-[#E05252] border border-[#E05252]/30'
                      : 'bg-[var(--bg-hover)] text-[var(--text-secondary)]'
                  }`}>
                    {tab.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      <p role="status" className="border-b border-[var(--border-subtle)] bg-[var(--bg-workspace)] px-5 py-2 text-[11px] leading-5 text-[var(--text-secondary)]">历史工作区 Run 快照 · 心跳、Worker 与阶段仅为保存时记录，不代表当前在线调度。暂停/恢复尚无授权 API。</p>
      {/* ========================================================================= */}
      {/* 2. 主体工作区 + 独立右侧 Frame Drawer */}
      {/* ========================================================================= */}
      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {/* 左侧主要内容面板 */}
        <div className="min-w-0 flex-1 space-y-4 overflow-y-auto p-3 lg:p-4">
          {/* ========================================================================= */}
          {/* Tab 1: 概览 (Overview) —— 简化后的紧凑生产矩阵 */}
          {/* ========================================================================= */}
          {activeTab === 'overview' && (
            <div className="w-full min-w-0 space-y-4">
              {/* 1.1 精简单行生产指标摘要栏 */}
              <div className="min-h-[44px] flex flex-wrap items-center justify-between gap-x-5 gap-y-2 border-y border-[var(--border-subtle)] px-3 py-2.5 text-[12px]">
                <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--text-tertiary)]">通过帧率</span>
                    <span className="font-semibold text-[var(--text-primary)]">{run.totalFrames > 0 ? Math.round(run.frames.filter(f => f.status === 'PASSED').length / run.totalFrames * 100) : 0}%</span>
                    <div className="w-20 h-1.5 rounded-[2px] bg-[var(--bg-workspace)] overflow-hidden border border-[var(--border-subtle)]">
                      <div className="h-full bg-[#4C8DFF] rounded-[2px]" style={{ width: `${run.totalFrames > 0 ? Math.round(run.frames.filter(f => f.status === 'PASSED').length / run.totalFrames * 100) : 0}%` }} />
                    </div>
                  </div>
                  <div className="h-3 w-px bg-[var(--border-subtle)]" />
                  <div className="flex items-center gap-1.5">
                    <span className="text-[var(--text-tertiary)]">审核通过:</span>
                    <span className="text-[var(--text-primary)] font-semibold">{run.frames.filter(f => f.status === 'PASSED').length}/{run.totalFrames} 帧</span>
                  </div>
                  <div className="h-3 w-px bg-[var(--border-subtle)]" />
                  <div className="hidden sm:flex items-center gap-1.5 truncate">
                    <span className="text-[var(--text-tertiary)]">当前阶段:</span>
                    <span className="text-[#4C8DFF] font-semibold">{run.stageLabel}</span>
                  </div>
                  <div className="h-3 w-px bg-[var(--border-subtle)]" />
                  <div className="hidden md:flex items-center gap-1.5 truncate">
                    <span className="text-[var(--text-tertiary)]">记录节点:</span>
                    <span className="text-[var(--text-secondary)]">{run.runtimeEnv?.workerId || '未提供'}</span>
                  </div>
                </div>

                <div className="text-[11px] text-[var(--text-tertiary)] tabular-nums">
                  <span>创建时间: {run.createdAt}</span>
                </div>
              </div>

              {/* 1.2 PIPELINE (8 Stages) 精简横向流水线步骤条 */}
              <div className="border-b border-[var(--border-subtle)] py-3 space-y-2">
                <div className="flex items-center justify-between text-xs font-mono">
                  <div className="text-[11px] font-bold text-[var(--text-primary)] uppercase tracking-wider flex items-center gap-1.5">
                    <Layers className="w-3.5 h-3.5 text-[var(--text-secondary)]" />
                    <span>流水线阶段</span>
                  </div>
                  <span className="text-[10px] text-[var(--text-tertiary)]">
                    已完成 {run.pipelineStages.filter(s => s.status === 'completed').length} / {run.pipelineStages.length} 阶段
                  </span>
                </div>

                {/* 横向步骤条 */}
                <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4 lg:grid-cols-8">
                  {run.pipelineStages.map((stage) => {
                    const isDone = stage.status === 'completed';
                    const isRunning = stage.status === 'running';
                    const isWarn = stage.status === 'warning';
                    const isSelected = selectedStageKey === stage.key;

                    return (
                      <button
                        key={stage.key}
                        type="button"
                        onClick={() => setSelectedStageKey(stage.key)}
                        className={`px-2 py-2 rounded-[4px] border text-left flex flex-col justify-between transition-colors cursor-pointer text-xs font-mono ${
                          isSelected ? 'ring-1 ring-[#4C8DFF] border-[#4C8DFF] bg-[var(--bg-selected)]' : ''
                        } ${
                          !isSelected && isDone
                            ? 'bg-[#3FB950]/10 border-[#3FB950]/30 text-[#3FB950]'
                            : !isSelected && isRunning
                            ? 'bg-[var(--bg-hover)] border-[#4C8DFF]/40 text-[#4C8DFF]'
                            : !isSelected && isWarn
                            ? 'bg-[#E05252]/10 border-[#E05252]/30 text-[#E05252]'
                            : !isSelected
                            ? 'bg-[var(--bg-workspace)] border-[var(--border-subtle)] text-[var(--text-tertiary)] hover:border-[var(--border-normal)]'
                            : ''
                        }`}
                      >
                        <div className="flex items-center justify-between gap-1">
                          <span className="font-sans text-[11px] truncate">{stage.label}</span>
                          <span className="text-[10px] shrink-0">{isDone ? '✓' : isRunning ? '●' : isWarn ? '!' : '○'}</span>
                        </div>
                        <span className="text-[10px] opacity-75 mt-0.5">{stage.timeCost || '待开始'}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* 1.3 FRAME PRODUCTION (01 ~ 20 矩阵网格) */}
              <div className="space-y-2.5">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <h2 className="text-xs font-bold text-[#F1F3F5] uppercase tracking-wider font-mono flex items-center gap-2">
                      <Flame className="w-3.5 h-3.5 text-[#F1F3F5]" />
                      <span>分镜生产记录</span>
                    </h2>
                    <p className="text-[11px] text-[#737D8A] mt-0.5 font-mono">
                      点击任意卡片在右侧呼出该分镜深度诊断抽屉
                    </p>
                  </div>

                  {/* 状态规范图例 */}
                  <div className="flex flex-wrap items-center gap-3 text-[11px] font-mono text-[#A7AFBA]">
                    <span className="flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#3FB950]" />
                      <span>通过（{run.frames.filter(f => f.status === 'PASSED').length}）</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#4C8DFF] animate-pulse" />
                      <span>生成中（{run.frames.filter(f => f.status === 'GENERATING').length}）</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#D28B26]" />
                      <span>重试（{run.frames.filter(f => f.status === 'RETRYING').length}）</span>
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#C9A227]" />
                      <span>排队（{run.frames.filter(f => f.status === 'QUEUED').length}）</span>
                    </span>
                  </div>
                </div>

                {/* 20 帧网格 (点击卡片在右侧直接展示 Frame Drawer) */}
                <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-7 lg:grid-cols-10 gap-2">
                  {run.frames.map((f) => {
                    const framePreview = hasVerifiedPreview(f.thumbnail) ? f.thumbnail : approvedUrl(f.frameNo);
                    const isPassed = f.status === 'PASSED';
                    const isGen = f.status === 'GENERATING';
                    const isRetry = f.status === 'RETRYING';
                    const isBlocked = f.status === 'BLOCKED';
                    const isQueued = f.status === 'QUEUED';
                    const isSelected = selectedFrame?.frameNo === f.frameNo;

                    return (
                      <button
                        key={f.frameNo}
                        type="button"
                        onClick={() => setSelectedFrame(f)}
                        className={`p-1.5 rounded-[4px] border text-left flex flex-col justify-between ${framePreview?'aspect-[4/5]':'min-h-[72px]'} transition-colors cursor-pointer relative overflow-hidden group ${
                          isSelected ? 'ring-1 ring-[#4C8DFF] border-[#4C8DFF]' : ''
                        } ${
                          isPassed
                            ? 'bg-[#0F1115] border-[#232830] text-[#F1F3F5] hover:border-[#3E4552]'
                            : isGen
                            ? 'bg-[#4C8DFF]/10 border-[#4C8DFF]/50 text-[#4C8DFF]'
                            : isRetry
                            ? 'bg-[#D28B26]/15 border-[#D28B26]/50 text-[#D28B26]'
                            : isBlocked
                            ? 'bg-[#E05252]/15 border-[#E05252]/50 text-[#E05252]'
                            : isQueued
                            ? 'bg-[#13161B] border-[#232830] text-[#C9A227] hover:border-[#3E4552]'
                            : 'bg-[#0F1115] border-[#1D2128] text-[#505864]'
                        }`}
                      >
                        {/* 顶部序号与状态标记 */}
                        <div className="flex items-center justify-between text-[11px] font-mono z-10">
                          <span className="font-semibold bg-[#0B0D10]/80 px-1 py-0.2 rounded-[2px]">
                            {String(f.frameNo).padStart(2, '0')}
                          </span>
                          <span className="w-1.5 h-1.5 rounded-full" style={{
                            backgroundColor: isPassed ? '#3FB950' : isGen ? '#4C8DFF' : isRetry ? '#D28B26' : isBlocked ? '#E05252' : isQueued ? '#C9A227' : '#505864'
                          }} />
                        </div>

                        {/* 缩略图预览 */}
                        {framePreview ? (
                          <img
                            src={framePreview}
                            alt={hasVerifiedPreview(f.thumbnail)?f.frameCode:'本地已批准 Frame '+f.frameNo}
                            className="absolute inset-0 w-full h-full object-cover opacity-90 group-hover:opacity-100 transition-opacity"
                          />
                        ) : <div className="absolute inset-0 flex items-center justify-center gap-1.5 text-[var(--text-tertiary)]"><ImageOff size={14}/><span className="text-[11px]">无原图</span></div>}

                        {/* 底部业务状态文本 (绝不靠颜色猜) */}
                        <div className="mt-auto z-10 bg-[#0B0D10]/90 px-1 py-0.5 rounded-[2px] text-[10px] font-mono truncate text-center font-medium">
                          {framePreview && !hasVerifiedPreview(f.thumbnail) ? '已批准素材' : getFrameBottomLabel(f)}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* Tab 2: 异常 (Exceptions) */}
          {/* ========================================================================= */}
          {activeTab === 'exceptions' && (
            <div className="space-y-4 max-w-5xl">
              <div>
                <h2 className="text-xs font-bold text-[#F1F3F5] uppercase tracking-wider font-mono flex items-center gap-2">
                  <ShieldAlert className="w-3.5 h-3.5 text-[#E05252]" />
                  <span>异常审计与自愈机制</span>
                </h2>
                <p className="text-[11px] text-[#737D8A] mt-0.5">
                  严格区分“需要人工处理（红色）”与“系统正在自动恢复（橙黄色）”
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {/* 需人工处理卡片 */}
                <div className="p-3.5 rounded-[6px] bg-[#13161B] border border-[#232830] space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold font-mono text-[#F1F3F5] flex items-center gap-1.5">
                      <AlertCircle className="w-3.5 h-3.5 text-[#3FB950]" />
                      <span>需人工介入处理 (0 项阻塞)</span>
                    </span>
                    <span className="text-[10px] font-mono text-[#3FB950] bg-[#3FB950]/15 border border-[#3FB950]/30 px-1.5 py-0.5 rounded-[3px]">
                      HEALTHY
                    </span>
                  </div>
                  <p className="text-xs text-[#737D8A]">
                    当前 Run 无任何阻塞死锁异常，所有核心资产契约（Character Contract、Visual Lock）已按时交付。
                  </p>
                </div>

                {/* 自动恢复中卡片 */}
                <div className="p-3.5 rounded-[6px] bg-[#13161B] border border-[#232830] space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold font-mono text-[#D28B26] flex items-center gap-1.5">
                      <RotateCcw className="w-3.5 h-3.5 text-[#D28B26]" />
                      <span>系统自愈中 (1 项生效中)</span>
                    </span>
                    <span className="text-[10px] font-mono text-[#D28B26] bg-[#D28B26]/15 border border-[#D28B26]/30 px-1.5 py-0.5 rounded-[3px]">
                      AUTO-RETRY
                    </span>
                  </div>
                  <div className="p-2.5 rounded-[4px] bg-[#0F1115] border border-[#232830] text-xs font-mono space-y-1">
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">目标分镜:</span>
                      <span className="text-[#F1F3F5] font-semibold">Frame 09</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">异常代码:</span>
                      <span className="text-[#D28B26] font-semibold">NETWORK_ERROR (Socket Timeout)</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">退避重试:</span>
                      <span className="text-[#A7AFBA] tabular-nums">Attempt 2 / 3 (17s 后自动触发)</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      const f09 = run.frames.find(f => f.frameNo === 9);
                      if (f09) {
                        setSelectedFrame(f09);
                        handleImmediateRetry(f09);
                      }
                    }}
                    className="w-full h-[30px] rounded-[4px] bg-[#D28B26] text-black font-semibold text-xs font-mono hover:bg-[#D28B26]/90 transition-colors cursor-pointer"
                  >
                    立即手动触发 Attempt 2/3
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* Tab 3: 事件 (Events) */}
          {/* ========================================================================= */}
          {activeTab === 'events' && (
            <div className="space-y-4 max-w-5xl">
              <div>
                <h2 className="text-xs font-bold text-[#F1F3F5] uppercase tracking-wider font-mono flex items-center gap-2">
                  <Clock className="w-3.5 h-3.5 text-[#F1F3F5]" />
                  <span>分布式链路事件流水 (Trace Events)</span>
                </h2>
                <p className="text-[11px] text-[#737D8A] mt-0.5">
                  精确至毫秒级的分布式全流程审计时间轴
                </p>
              </div>

              <div className="space-y-1.5 font-mono text-xs">
                {(run.events || []).map((ev) => (
                  <div
                    key={ev.id}
                    className="p-2.5 rounded-[4px] bg-[#13161B] border border-[#232830] flex items-start justify-between gap-4 hover:border-[#3E4552] transition-colors"
                  >
                    <div className="flex items-start gap-2.5">
                      <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${
                        ev.status === 'success' ? 'bg-[#3FB950]' : ev.status === 'error' ? 'bg-[#E05252]' : ev.status === 'warn' ? 'bg-[#D28B26]' : 'bg-[#4C8DFF]'
                      }`} />
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-[#F1F3F5] font-semibold">{ev.eventName}</span>
                          <span className="text-[10px] text-[#737D8A] bg-[#0F1115] px-1.5 py-0.2 rounded-[2px] border border-[#232830]">
                            {ev.stage}
                          </span>
                        </div>
                        <div className="text-[#A7AFBA] font-sans text-xs mt-0.5">
                          {ev.detail}
                        </div>
                      </div>
                    </div>
                    <span className="text-[#737D8A] text-[11px] tabular-nums shrink-0">{ev.timestamp}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* Tab 4: Artifacts (产物清单) */}
          {/* ========================================================================= */}
          {activeTab === 'artifacts' && (
            <div className="space-y-4 max-w-5xl">
              <div>
                <h2 className="text-xs font-bold text-[#F1F3F5] uppercase tracking-wider font-mono flex items-center gap-2">
                  <FileCode className="w-3.5 h-3.5 text-[#F1F3F5]" />
                  <span>产物交付清单 (Artifacts)</span>
                </h2>
                <p className="text-[11px] text-[#737D8A] mt-0.5">
                  流水线各阶段生成的机器与人类可读资产
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {(run.artifacts || []).map((art) => (
                  <div key={art.id} className="p-3 rounded-[4px] bg-[#13161B] border border-[#232830] flex flex-col justify-between space-y-2 hover:border-[#3E4552] transition-colors">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="text-xs font-semibold font-mono text-[#F1F3F5] flex items-center gap-1.5">
                          <span>📦</span>
                          <span>{art.name}</span>
                        </div>
                        <div className="text-[11px] text-[#737D8A] font-mono mt-0.5">
                          {art.stage} · {art.size} · {art.updatedAt}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => onShowToast('此处未提供可验证的下载链接，未发起下载。')}
                        aria-label="下载产物（当前不可用）"
                        title="下载产物（当前不可用）"
                        className="p-1 hover:text-[#F1F3F5] text-[#737D8A] rounded-[4px] hover:bg-[#1C2128] cursor-pointer"
                      >
                        <Download className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    {art.previewSnippet && (
                      <pre className="p-2 rounded-[3px] bg-[#0F1115] border border-[#232830] text-[11px] text-[#A7AFBA] font-mono overflow-x-auto">
                        {art.previewSnippet}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* Tab 5: 日志 (Runtime Logs) */}
          {/* ========================================================================= */}
          {activeTab === 'logs' && (
            <div className="space-y-3 max-w-5xl">
              <div className="os-console-filterbar flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border-subtle)] bg-[var(--bg-workspace)] px-3 py-3">
                <h2 className="os-section-heading flex items-center gap-2"><Terminal className="h-4 w-4" />执行终端日志</h2>
                <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2">
                  <label className="relative min-w-[170px] flex-1 sm:max-w-[300px]">
                    <Search aria-hidden="true" className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-tertiary)]" />
                    <input aria-label="搜索 Run 日志" type="search" value={logSearch} onChange={e=>setLogSearch(e.target.value)}
                      placeholder="搜索日志内容或组件" className="h-9 w-full rounded-[5px] border border-[var(--border-normal)] bg-[var(--bg-surface)] pl-9 pr-3 text-[12px] text-[var(--text-primary)]" />
                  </label>
                  <Select aria-label="筛选 Run 日志级别" value={logFilter} onChange={setLogFilter} style={{width:140}}
                    options={(['ALL','INFO','WARN','ERROR','DEBUG'] as const).map(v=>({value:v,label:v==='ALL'?'全部级别':v}))} />
                  <span className="text-[11px] tabular-nums text-[var(--text-tertiary)]">已匹配 {filteredLogs.length} 条</span>
                </div>
              </div>

              {/* 终端黑色面板 */}
              <div className="p-3.5 rounded-[6px] bg-[#0B0D10] border border-[#232830] font-mono text-[11px] space-y-1.5 max-h-[500px] overflow-y-auto">
                {filteredLogs.map(lg => {
                  const isErr = lg.level === 'ERROR';
                  const isWarn = lg.level === 'WARN';
                  return (
                    <div key={lg.id} className="flex items-start gap-2.5 leading-relaxed">
                      <span className="text-[#505864] tabular-nums shrink-0">{lg.timestamp}</span>
                      <span className={`px-1 py-0.2 rounded-[2px] text-[10px] shrink-0 font-semibold ${
                        isErr ? 'bg-[#E05252]/20 text-[#E05252]' : isWarn ? 'bg-[#D28B26]/20 text-[#D28B26]' : 'bg-[#171B21] text-[#737D8A]'
                      }`}>
                        {lg.level}
                      </span>
                      <span className="text-[#737D8A] shrink-0">[{lg.component}]</span>
                      <span className={isErr ? 'text-[#E05252] font-semibold' : isWarn ? 'text-[#D28B26]' : 'text-[#A7AFBA]'}>
                        {lg.message}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ========================================================================= */}
          {/* Tab 6: 运行环境 (Runtime Env) */}
          {/* ========================================================================= */}
          {activeTab === 'runtime' && (
            <div className="space-y-4 max-w-5xl font-mono text-xs">
              <div>
                <h2 className="text-xs font-bold text-[#F1F3F5] uppercase tracking-wider font-mono flex items-center gap-2">
                  <Server className="w-3.5 h-3.5 text-[#F1F3F5]" />
                  <span>底层硬件与推理环境 (Infrastructure Topology)</span>
                </h2>
                <p className="text-[11px] text-[#737D8A] mt-0.5">
                  Worker 节点、模型路由引擎、心跳链路拓扑
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="p-3.5 rounded-[6px] bg-[#13161B] border border-[#232830] space-y-3">
                  <div className="text-[#F1F3F5] font-semibold pb-2 border-b border-[#232830] flex items-center gap-1.5">
                    <Cpu className="w-3.5 h-3.5 text-[#3FB950]" />
                    <span>Worker 推理节点</span>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">Worker 实例:</span>
                      <span className="text-[#F1F3F5] font-semibold">{run.runtimeEnv?.workerId || '未提供'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">GPU 硬件规格:</span>
                      <span className="text-[#A7AFBA]">{run.runtimeEnv?.gpuNode || '未提供'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">心跳检测间隔:</span>
                      <span className="text-[#3FB950] font-semibold">{run.runtimeEnv?.heartbeatInterval || '未提供'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">并发池插槽:</span>
                      <span className="text-[#A7AFBA]">{run.runtimeEnv?.activeConcurrency || '未提供'}</span>
                    </div>
                  </div>
                </div>

                <div className="p-3.5 rounded-[6px] bg-[#13161B] border border-[#232830] space-y-3">
                  <div className="text-[#F1F3F5] font-semibold pb-2 border-b border-[#232830] flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5 text-[#4C8DFF]" />
                    <span>模型与出图规范</span>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">模型引擎:</span>
                      <span className="text-[#F1F3F5] font-semibold">{run.runtimeEnv?.modelProvider || '未提供'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">默认画幅比例:</span>
                      <span className="text-[#A7AFBA]">{run.runtimeEnv?.aspectRatio || '未提供'}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">原生输出分辨率:</span>
                      <span className="text-[#A7AFBA]">{run.runtimeEnv?.imageResolution || '未提供'}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ========================================================================= */}
        {/* 3. 右侧 Frame 详情抽屉 (Right Drawer) —— UI Baseline v1: 宽度 440px/480px, bg #13161B */}
        {/* ========================================================================= */}
        {selectedFrame && (
          <div role="dialog" aria-label="分镜详情检视" className="absolute inset-y-0 right-0 z-20 flex h-full w-full max-w-[440px] flex-col overflow-y-auto border-l border-[var(--border-normal)] bg-[var(--bg-elevated)] shadow-lg xl:max-w-[480px]">
            {/* 抽屉头部 */}
            <div className="h-[48px] px-4 border-b border-[#232830] flex items-center justify-between bg-[#0F1115] shrink-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold font-mono text-[#F1F3F5]">
                  {selectedFrame.frameCode}
                </span>
                <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded-[3px] font-medium ${
                  selectedFrame.status === 'PASSED'
                    ? 'bg-[#3FB950]/15 text-[#3FB950] border border-[#3FB950]/30'
                    : selectedFrame.status === 'RETRYING'
                    ? 'bg-[#D28B26]/20 text-[#D28B26] border border-[#D28B26]/30'
                    : selectedFrame.status === 'BLOCKED'
                    ? 'bg-[#E05252]/20 text-[#E05252] border border-[#E05252]/30'
                    : selectedFrame.status === 'GENERATING'
                    ? 'bg-[#4C8DFF]/20 text-[#4C8DFF] border border-[#4C8DFF]/30'
                    : 'bg-[#171B21] text-[#A7AFBA]'
                }`}>
                  {selectedFrame.status}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setSelectedFrame(null)}
                aria-label="关闭分镜详情"
                title="关闭分镜详情"
                className="p-1 hover:text-[#F1F3F5] rounded-[4px] hover:bg-[#1C2128] cursor-pointer text-[#737D8A]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* 抽屉滚动内容 */}
            <div className="p-4 space-y-4 text-xs font-mono flex-1 overflow-y-auto">
              {/* ===================== [上半部分：人看的信息] ===================== */}
              <div className="space-y-3">
                {/* 最终大图展示 */}
                {selectedPreview ? (
                  <div className="rounded-[4px] overflow-hidden border border-[#232830] relative group aspect-[4/5] bg-[#0B0D10]">
                    <img
                      src={selectedPreview || ''}
                      alt={hasVerifiedPreview(selectedFrame.thumbnail)?selectedFrame.frameCode:'已批准作品图片 '+selectedFrame.frameNo}
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent p-3 text-[11px] text-[#A7AFBA] flex justify-between items-center">
                      <span className="font-sans font-medium text-[#F1F3F5]">{hasVerifiedPreview(selectedFrame.thumbnail)?'历史 Run 存档图':'本地已批准作品素材 · 非该 Run 证据'}</span>
                      <button
                        type="button"
                        onClick={() => setImageModalUrl(selectedPreview || null)}
                        className="px-2 py-1 rounded-[3px] bg-[#0B0D10]/80 hover:bg-[#1C2128] hover:text-white border border-[#2D333D] transition-colors text-[10px] flex items-center gap-1 cursor-pointer"
                      >
                        <Maximize2 className="w-3 h-3" />
                        <span>全屏预览</span>
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-[4px] border border-dashed border-[#2D333D] aspect-[4/5] bg-[#0F1115] flex flex-col items-center justify-center text-[#737D8A] text-xs p-4 text-center">
                    <ImageOff className="w-6 h-6 text-[var(--text-tertiary)] mb-2" />
                    <span className="text-[var(--text-secondary)]">未附带可验证的原图</span>
                    <span className="text-[10px] text-[#505864] mt-1">
                      历史快照中仅保存帧状态，无法验证实时生成进度
                    </span>
                  </div>
                )}

                {/* 基础元数据网格 */}
                <div className="bg-[#0F1115] p-3 rounded-[4px] border border-[#232830] space-y-2">
                  <div className="flex justify-between">
                    <span className="text-[#737D8A]">状态 (Status):</span>
                    <span className={`font-semibold ${
                      selectedFrame.status === 'PASSED' ? 'text-[#3FB950]' :
                      selectedFrame.status === 'RETRYING' ? 'text-[#D28B26]' :
                      selectedFrame.status === 'GENERATING' ? 'text-[#4C8DFF]' : 'text-[#A7AFBA]'
                    }`}>
                      {selectedFrame.status}
                    </span>
                  </div>

                  <div className="flex justify-between">
                    <span className="text-[#737D8A]">耗时 (Duration):</span>
                    <span className="text-[#F1F3F5] font-medium tabular-nums">{selectedFrame.duration || '未提供'}</span>
                  </div>

                  <div className="flex justify-between">
                    <span className="text-[#737D8A]">Attempt 次数:</span>
                    <span className="text-[#F1F3F5] font-semibold tabular-nums">{selectedFrame.attempt}</span>
                  </div>

                  {selectedFrame.completedAt && (
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">完成时间:</span>
                      <span className="text-[#A7AFBA] tabular-nums">{selectedFrame.completedAt}</span>
                    </div>
                  )}

                  {selectedFrame.currentSubAction && (
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">子阶段动作:</span>
                      <span className="text-[#4C8DFF] font-semibold">{selectedFrame.currentSubAction}</span>
                    </div>
                  )}
                </div>
              </div>

              {/* ===================== [生成信息] ===================== */}
              <div className="space-y-3 pt-1 border-t border-[#232830]">
                <div className="text-xs font-bold text-[#F1F3F5] uppercase tracking-wider flex items-center justify-between">
                  <span>生成信息</span>
                  <span className="text-[10px] text-[#737D8A] font-normal">Inference Details</span>
                </div>

                <div className="bg-[#0F1115] p-3 rounded-[4px] border border-[#232830] space-y-2">
                  <div className="flex justify-between">
                    <span className="text-[#737D8A]">Provider:</span>
                    <span className="text-[#F1F3F5] font-mono">{selectedFrame.provider || '未提供'}</span>
                  </div>

                  <div className="flex justify-between">
                    <span className="text-[#737D8A]">Model:</span>
                    <span className="text-[#F1F3F5] font-mono">{selectedFrame.modelName || '未提供'}</span>
                  </div>

                  {selectedFrame.artifactName && (
                    <div className="flex justify-between items-center">
                      <span className="text-[#737D8A]">Artifact:</span>
                      <button
                        type="button"
                        onClick={() => onShowToast('此处未提供可验证的下载链接，未发起下载。')}
                        className="text-[#3FB950] hover:underline flex items-center gap-1 cursor-pointer"
                      >
                        <span>{selectedFrame.artifactName}</span>
                        <span className="text-[#737D8A]">({selectedFrame.artifactSize || '大小未知'})</span>
                        <ChevronRight className="w-3 h-3 text-[#737D8A]" />
                      </button>
                    </div>
                  )}

                  {selectedFrame.traceId && (
                    <div className="flex justify-between items-center">
                      <span className="text-[#737D8A]">Trace:</span>
                      <button
                        type="button"
                        onClick={() => handleCopy(selectedFrame.traceId || '', 'Trace ID')}
                        className="text-[#A7AFBA] hover:text-[#F1F3F5] underline cursor-pointer flex items-center gap-1 text-[11px]"
                      >
                        <span>{selectedFrame.traceId}</span>
                        {copiedText === 'Trace ID' ? <Check className="w-3 h-3 text-[#3FB950]" /> : <Copy className="w-3 h-3 text-[#737D8A]" />}
                      </button>
                    </div>
                  )}
                </div>

                {/* References 引用列表 (带小预览图) */}
                {selectedFrame.referenceItems && selectedFrame.referenceItems.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="text-[#737D8A] text-[11px] flex items-center justify-between">
                      <span>References (特征契约):</span>
                      <span className="text-[#505864] text-[10px]">已绑定视觉特征</span>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      {selectedFrame.referenceItems.map((ref, idx) => (
                        <div
                          key={idx}
                          className="flex items-center gap-2 p-1.5 rounded-[4px] bg-[#0F1115] border border-[#232830] hover:border-[#3E4552] transition-colors"
                        >
                          {ref.url && (
                            <img
                              src={ref.url}
                              alt={ref.name}
                              className="w-7 h-7 rounded-[3px] object-cover shrink-0 cursor-pointer"
                              onClick={() => setImageModalUrl(ref.url || null)}
                            />
                          )}
                          <div className="truncate">
                            <span className="block text-[#F1F3F5] font-semibold truncate text-[11px]">{ref.name}</span>
                            <span className="text-[10px] text-[#737D8A]">{ref.type || 'reference'}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Prompt 提示词 (可折叠/展开与一键复制) */}
                {selectedFrame.prompt && (
                  <div className="space-y-1.5">
                    <div className="text-[#737D8A] text-[11px] flex items-center justify-between">
                      <span>Prompt (生图提示词):</span>
                      <button
                        type="button"
                        onClick={() => handleCopy(selectedFrame.prompt || '', 'Prompt')}
                        className="text-[#F1F3F5] hover:underline flex items-center gap-1 text-[10px] cursor-pointer"
                      >
                        {copiedText === 'Prompt' ? <Check className="w-3 h-3 text-[#3FB950]" /> : <Copy className="w-3 h-3" />}
                        <span>{copiedText === 'Prompt' ? '已复制' : '复制 Prompt'}</span>
                      </button>
                    </div>
                    <div className="p-2.5 rounded-[4px] bg-[#0B0D10] border border-[#232830] text-[#A7AFBA] text-[11px] leading-relaxed relative">
                      <p className={promptExpanded ? '' : 'line-clamp-3'}>
                        {selectedFrame.prompt}
                      </p>
                      <button
                        type="button"
                        onClick={() => setPromptExpanded(!promptExpanded)}
                        className="mt-1 text-[10px] text-[#737D8A] hover:text-[#F1F3F5] flex items-center gap-0.5 cursor-pointer"
                      >
                        <span>{promptExpanded ? '收起提示词' : '查看完整提示词 >'}</span>
                        {promptExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* ===================== [异常诊断区 (仅异常 Frame 专属展示)] ===================== */}
              {(selectedFrame.status === 'RETRYING' || selectedFrame.status === 'BLOCKED' || selectedFrame.lastError) && (
                <div className="space-y-2 pt-1 border-t border-[#232830]">
                  <div className="text-xs font-bold text-[#D28B26] uppercase tracking-wider flex items-center justify-between">
                    <span className="flex items-center gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 text-[#D28B26]" />
                      <span>异常诊断</span>
                    </span>
                    <span className="text-[10px] text-[#D28B26]/80 font-normal">Diagnostic</span>
                  </div>

                  <div className="p-3 rounded-[4px] bg-[#0F1115] border border-[#D28B26]/30 space-y-2 text-xs">
                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">Error:</span>
                      <span className="text-[#D28B26] font-semibold">{selectedFrame.lastError || 'NETWORK_ERROR'}</span>
                    </div>

                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">Failure Stage:</span>
                      <span className="text-[#A7AFBA]">{selectedFrame.failureStage || 'provider_download'}</span>
                    </div>

                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">Last Attempt:</span>
                      <span className="text-[#A7AFBA] tabular-nums">{selectedFrame.failedAt || '11:18:22'}</span>
                    </div>

                    <div className="flex justify-between">
                      <span className="text-[#737D8A]">Retry:</span>
                      <span className="text-[#F1F3F5] font-semibold tabular-nums">{selectedFrame.attempt}</span>
                    </div>

                    {selectedFrame.status === 'RETRYING' && (
                      <div className="flex justify-between text-[#D28B26] font-semibold pt-1 border-t border-[#D28B26]/20">
                        <span>Next Retry:</span>
                        <span className="tabular-nums">{selectedFrame.nextRetryInSeconds || 17}s 倒计时</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* 分镜事件历史 */}
              {selectedFrame.recentEvents && selectedFrame.recentEvents.length > 0 && (
                <div className="space-y-1.5 pt-1 border-t border-[#232830]">
                  <div className="text-[#737D8A] text-[11px]">Frame Event Stream:</div>
                  <div className="space-y-1 p-2 rounded-[4px] bg-[#0B0D10] border border-[#232830] text-[11px]">
                    {selectedFrame.recentEvents.map((ev, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <span className="text-[#505864] tabular-nums shrink-0">{ev.time}</span>
                        <span className={ev.type === 'error' ? 'text-[#E05252] font-semibold' : ev.type === 'schedule' ? 'text-[#D28B26]' : 'text-[#A7AFBA]'}>
                          {ev.text}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* ========================================================================= */}
            {/* 抽屉底部操作条 —— 严格根据 Frame 状态动态变化，严禁在 PASSED 下出现“跳过此帧” */}
            {/* ========================================================================= */}
            <div className="p-3 border-t border-[#232830] bg-[#0F1115] shrink-0">
              {/* 1. PASSED 状态：查看原图 / 重新生成 / 日志 (跳过此帧绝不出现) */}
              {selectedFrame.status === 'PASSED' && (
                <div className="grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => setImageModalUrl(selectedPreview || null)}
                    className="h-[32px] rounded-[4px] bg-[#171B21] border border-[#2D333D] hover:bg-[#1C2128] text-[#C9D1D9] hover:text-[#F1F3F5] transition-colors text-xs font-mono cursor-pointer flex items-center justify-center gap-1.5"
                  >
                    <Eye className="w-3.5 h-3.5" />
                    <span>查看原图</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => onShowToast('当前仅供查看；该操作需要受控 Runtime API。')}
                    className="h-[32px] rounded-[4px] bg-[#4C8DFF] text-white font-medium hover:bg-[#4C8DFF]/90 transition-colors text-xs font-mono cursor-pointer flex items-center justify-center gap-1.5 shadow-sm"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    <span>重新生成</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setActiveTab('logs');
                      setLogSearch(selectedFrame.frameCode);
                    }}
                    className="h-[32px] rounded-[4px] bg-[#171B21] border border-[#2D333D] hover:bg-[#1C2128] text-[#C9D1D9] hover:text-[#F1F3F5] transition-colors text-xs font-mono cursor-pointer flex items-center justify-center gap-1.5"
                  >
                    <Terminal className="w-3.5 h-3.5" />
                    <span>日志</span>
                  </button>
                </div>
              )}

              {/* 2. RUNNING 状态：查看运行 / 取消本次 */}
              {selectedFrame.status === 'GENERATING' && (
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setActiveTab('logs');
                      setLogSearch(selectedFrame.frameCode);
                    }}
                    className="h-[32px] rounded-[4px] bg-[#4C8DFF] text-white font-medium hover:bg-[#4C8DFF]/90 transition-colors text-xs font-mono cursor-pointer flex items-center justify-center gap-1.5 shadow-sm"
                  >
                    <Terminal className="w-3.5 h-3.5" />
                    <span>查看运行日志</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => onShowToast('当前仅供查看；该操作需要受控 Runtime API。')}
                    className="h-[32px] rounded-[4px] bg-[#E05252]/15 border border-[#E05252]/40 text-[#E05252] hover:bg-[#E05252]/25 transition-colors text-xs font-mono cursor-pointer flex items-center justify-center gap-1.5"
                  >
                    <X className="w-3.5 h-3.5" />
                    <span>取消本次</span>
                  </button>
                </div>
              )}

              {/* 3. RETRYING 状态：立即重试 / 停止重试 / 日志 */}
              {selectedFrame.status === 'RETRYING' && (
                <div className="grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => handleImmediateRetry(selectedFrame)}
                    className="h-[32px] rounded-[4px] bg-[#D28B26] text-black font-semibold hover:bg-[#D28B26]/90 transition-colors text-xs font-mono cursor-pointer flex items-center justify-center gap-1.5 shadow-sm"
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
                    <span>立即重试</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => onShowToast('当前仅供查看；该操作需要受控 Runtime API。')}
                    className="h-[32px] rounded-[4px] bg-[#171B21] border border-[#2D333D] hover:bg-[#1C2128] text-[#C9D1D9] hover:text-[#F1F3F5] transition-colors text-xs font-mono cursor-pointer"
                  >
                    停止并跳过
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setActiveTab('logs');
                      setLogSearch(selectedFrame.frameCode);
                    }}
                    className="h-[32px] rounded-[4px] bg-[#171B21] border border-[#2D333D] hover:bg-[#1C2128] text-[#C9D1D9] hover:text-[#F1F3F5] transition-colors text-xs font-mono cursor-pointer flex items-center justify-center gap-1.5"
                  >
                    <Terminal className="w-3.5 h-3.5" />
                    <span>日志</span>
                  </button>
                </div>
              )}

              {/* 4. BLOCKED 状态：重试 / 强制通过 / 跳过此帧 */}
              {selectedFrame.status === 'BLOCKED' && (
                <div className="grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => handleImmediateRetry(selectedFrame)}
                    className="h-[32px] rounded-[4px] bg-[#4C8DFF] text-white font-medium hover:bg-[#4C8DFF]/90 transition-colors text-xs font-mono cursor-pointer"
                  >
                    重试修复
                  </button>

                  <button
                    type="button"
                    onClick={() => onShowToast('当前仅供查看；该操作需要受控 Runtime API。')}
                    className="h-[32px] rounded-[4px] bg-[#3FB950]/15 border border-[#3FB950]/40 text-[#3FB950] hover:bg-[#3FB950]/25 transition-colors text-xs font-mono cursor-pointer"
                  >
                    强制通过
                  </button>

                  <button
                    type="button"
                    onClick={() => onShowToast('当前仅供查看；该操作需要受控 Runtime API。')}
                    className="h-[32px] rounded-[4px] bg-[#171B21] border border-[#2D333D] hover:bg-[#1C2128] text-[#C9D1D9] hover:text-[#F1F3F5] transition-colors text-xs font-mono cursor-pointer"
                  >
                    跳过此帧
                  </button>
                </div>
              )}

              {/* 5. QUEUED 状态：提前执行 / 取消排队 */}
              {selectedFrame.status === 'QUEUED' && (
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => handleImmediateRetry(selectedFrame)}
                    className="h-[32px] rounded-[4px] bg-[#4C8DFF] text-white font-medium hover:bg-[#4C8DFF]/90 transition-colors text-xs font-mono cursor-pointer flex items-center justify-center gap-1.5 shadow-sm"
                  >
                    <Play className="w-3.5 h-3.5" />
                    <span>提前优先执行</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => onShowToast('当前仅供查看；该操作需要受控 Runtime API。')}
                    className="h-[32px] rounded-[4px] bg-[#171B21] border border-[#2D333D] hover:bg-[#1C2128] text-[#C9D1D9] hover:text-[#F1F3F5] transition-colors text-xs font-mono cursor-pointer"
                  >
                    取消排队
                  </button>
                </div>
              )}

              {/* 6. NOT_STARTED 状态：立即触发生成 */}
              {selectedFrame.status === 'NOT_STARTED' && (
                <button
                  type="button"
                  onClick={() => handleImmediateRetry(selectedFrame)}
                  className="w-full h-[32px] rounded-[4px] bg-[#4C8DFF] text-white font-medium hover:bg-[#4C8DFF]/90 transition-colors text-xs font-mono cursor-pointer flex items-center justify-center gap-1.5 shadow-sm"
                >
                  <Play className="w-3.5 h-3.5" />
                  <span>立即触发此帧渲染</span>
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ========================================================================= */}
      {/* 4. 二次确认模态框 (覆盖：重新生成、跳过、强制通过、取消本次) */}
      {/* ========================================================================= */}
      {confirmAction && (
        <div className="fixed inset-0 z-70 bg-black/80 flex items-center justify-center p-4 backdrop-blur-xs">
          <div className="bg-[#13161B] border border-[#232830] rounded-[6px] max-w-sm w-full p-4 space-y-3.5 text-[#F1F3F5] shadow-2xl animate-in fade-in">
            <div className="flex items-center gap-2 text-[#D28B26] font-semibold text-sm">
              <AlertTriangle className="w-4 h-4 text-[#D28B26] shrink-0" />
              <span>
                {confirmAction.type === 'REGENERATE' && `确认重新生成 ${confirmAction.frame.frameCode}？`}
                {confirmAction.type === 'SKIP' && `确认跳过 ${confirmAction.frame.frameCode}？`}
                {confirmAction.type === 'FORCE_PASS' && `确认强制放行 ${confirmAction.frame.frameCode}？`}
                {confirmAction.type === 'CANCEL' && `确认取消 ${confirmAction.frame.frameCode} 渲染？`}
              </span>
            </div>

            <p className="text-xs text-[#A7AFBA] leading-relaxed font-sans">
              {confirmAction.type === 'REGENERATE' && '当前未开放受控重生成接口；本页面不会直接生成或覆盖产物。'}
              {confirmAction.type === 'SKIP' && '当前未开放受控跳过接口；本页面不会更改分镜阶段。'}
              {confirmAction.type === 'FORCE_PASS' && '当前未开放受控审核接口；本页面不会跳过任何门禁。'}
              {confirmAction.type === 'CANCEL' && '当前未开放受控取消接口；本页面不会中断 Worker。'}
            </p>

            <div className="flex justify-end gap-2 pt-1 font-mono text-xs">
              <button
                type="button"
                onClick={() => setConfirmAction(null)}
                className="h-[30px] px-3 rounded-[4px] bg-[#171B21] border border-[#2D333D] text-[#C9D1D9] hover:text-[#F1F3F5] hover:bg-[#1C2128] transition-colors cursor-pointer"
              >
                取消
              </button>
              <button
                type="button"
                onClick={executeDangerousAction}
                className="h-[30px] px-3.5 rounded-[4px] bg-[#4C8DFF] text-white font-medium hover:bg-[#4C8DFF]/90 transition-colors cursor-pointer shadow-sm"
              >
                确认执行
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* 5. 高清原图全屏预览模态框 */}
      {/* ========================================================================= */}
      {imageModalUrl && (
        <div
          className="fixed inset-0 z-80 bg-black/90 flex items-center justify-center p-2 sm:p-4 backdrop-blur-sm"
          onClick={() => setImageModalUrl(null)}
        >
          <div className="relative max-w-[min(1024px,96vw)] w-full max-h-[94dvh] min-w-0 flex flex-col items-center">
            <button
              type="button"
              onClick={() => setImageModalUrl(null)}
              className="absolute -top-10 right-0 p-1.5 rounded-[4px] bg-[#171B21] border border-[#2D333D] hover:bg-[#1C2128] hover:text-[#F1F3F5] text-[#A7AFBA] cursor-pointer transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
            <img
              src={imageModalUrl}
              alt="High Res Preview"
              className="max-h-[85vh] object-contain rounded-[4px] border border-[#232830] shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        </div>
      )}
    </div>
  );
};
