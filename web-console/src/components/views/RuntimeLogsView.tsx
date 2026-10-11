import React, { useState, useEffect, useMemo } from 'react';
import {Drawer, Pagination, Select} from 'antd';
import {
  Terminal,
  Download,
  Check,
  RefreshCw,
  Search,
  Filter,
  X,
  Copy,
  Clock,
  Activity,
  Layers,
  FileCode,
  ExternalLink,
  Code2,
  ListFilter
} from 'lucide-react';
import { platformApi } from '../../api/platformApi';

export interface LogEntry {
  id: string;
  time: string;
  timestampMs?: number;
  level: 'INFO' | 'SUCCESS' | 'WARN' | 'ERROR' | 'DEBUG';
  module: string;
  message: string;
  traceId: string;
  aggregateId?: string;
  durationMs?: number;
  statusCode?: number;
  payload?: Record<string, any>;
  context?: Record<string, any>;
}

interface FormattedJsonViewerProps {
  data: Record<string, any>;
}

const FormattedJsonViewer: React.FC<FormattedJsonViewerProps> = ({ data }) => {
  const [viewMode, setViewMode] = useState<'formatted' | 'raw'>('formatted');
  const [copied, setCopied] = useState(false);

  const formattedJsonString = useMemo(() => {
    try {
      return JSON.stringify(data, null, 2);
    } catch {
      return '{}';
    }
  }, [data]);

  const renderHighlightedJson = (json: string) => {
    const lines = json.split('\\n');
    return lines.map((line, idx) => (
      <div key={idx} className="whitespace-pre">
        {line.split(/"(.*?)"/g).map((part, i) => {
          if (i % 2 === 1) {
            const isKey = line.trim().startsWith('"' + part + '"');
            return (
              <span key={i} className={isKey ? 'text-[#79C0FF]' : 'text-[#A5D6FF]'}>
                {part}
              </span>
            );
          }
          return (
            <span key={i} className="text-[var(--text-secondary)]">
              {part}
            </span>
          );
        })}
      </div>
    ));
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(formattedJsonString);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="rounded-[6px] border border-[var(--border-subtle)] bg-[var(--bg-app)] overflow-hidden">
      <div className="flex items-center justify-between px-2.5 py-1.5 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)]">
        <div className="flex items-center gap-1">
          {(['formatted', 'raw'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setViewMode(mode)}
              className={`px-2.5 py-1 rounded-[4px] text-[11px] font-medium transition-colors cursor-pointer ${
                viewMode === mode
                  ? 'bg-[var(--bg-selected)] text-[var(--text-primary)] font-bold border border-[var(--border-normal)]'
                  : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]'
              }`}
            >
              {mode === 'formatted' ? '格式化' : '纯文本'}
            </button>
          ))}
        </div>

        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 px-2 py-0.5 rounded-[4px] bg-[var(--bg-surface)] border border-[var(--border-subtle)] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-[10px] transition-colors cursor-pointer"
          title="复制格式化 JSON"
        >
          {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
          <span>{copied ? '已复制' : '复制 JSON'}</span>
        </button>
      </div>

      <div className="p-3 overflow-x-auto max-h-[380px] scrollbar-thin select-text">
        {viewMode === 'formatted' ? (
          <div className="table w-full">{renderHighlightedJson(formattedJsonString)}</div>
        ) : (
          <pre className="text-[11px] text-[var(--text-primary)] whitespace-pre font-mono leading-5">
            {formattedJsonString}
          </pre>
        )}
      </div>
    </div>
  );
};

export const RuntimeLogsView: React.FC = () => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loadError, setLoadError] = useState<string>('');
  const [filterLevel, setFilterLevel] = useState<string>('ALL');
  const [filterModule, setFilterModule] = useState<string>('ALL');
  const [filterTimeRange, setFilterTimeRange] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // 分页状态
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(20);

  // 详情查看抽屉
  const [selectedLog, setSelectedLog] = useState<LogEntry | null>(null);

  // 复制与导出状态
  const [copiedAll, setCopiedAll] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);

  // 从后端 runtime/events 加载真实事件流（只映射后端已投射字段，缺字段显式置空）
  const fetchLogs = () => {
    setIsRefreshing(true);
    platformApi.events(100, 0)
      .then((res) => {
        const items = (res && res.items) || [];
        const mappedLogs: LogEntry[] = items.map((item, idx) => {
          const eventType = String(item.event_type || 'UNKNOWN');
          const isError = /FAIL|ERROR|CRASH|TIMEOUT/.test(eventType);
          const isWarn = /WARN|RETRY|DEGRADE/.test(eventType);
          const isSuccess = /COMPLETED|RELEASE|PASS|LOCKED|PUBLISHED/.test(eventType);
          const level: LogEntry['level'] = isError ? 'ERROR' : isWarn ? 'WARN' : isSuccess ? 'SUCCESS' : 'INFO';
          const occurredAt = item.occurred_at ? String(item.occurred_at).replace('T', ' ').slice(0, 23) : '';
          return {
            id: `evt-${item.event_id || idx}`,
            time: occurredAt || '-',
            level,
            module: eventType,
            message: `${item.aggregate_id || 'system'} 触发 ${eventType}`.trim(),
            traceId: item.trace_id ? String(item.trace_id) : '-',
            aggregateId: item.aggregate_id || undefined,
          };
        });
        setLogs(mappedLogs);
        setLoadError('');
      })
      .catch((err) => {
        console.warn('Load logs err', err);
        setLogs([]);
        setLoadError('无法读取审计事件：当前 API 未开放事件列表或连接失败。不会使用示例日志替代真实记录。');
      })
      .finally(() => {
        setIsRefreshing(false);
      });
  };
  useEffect(() => {
    fetchLogs();
  }, []);

  // 自动刷新轮询
  useEffect(() => {
    if (!autoRefresh) return;
    const timer = setInterval(() => {
      fetchLogs();
    }, 5000);
    return () => clearInterval(timer);
  }, [autoRefresh]);

  // 所有独特的模块列表用于筛选
  const availableModules = useMemo(() => {
    const set = new Set<string>();
    logs.forEach(l => set.add(l.module));
    return ['ALL', ...Array.from(set)];
  }, [logs]);

  // 多维筛选计算
  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      // 1. 级别筛选
      if (filterLevel !== 'ALL' && log.level !== filterLevel) {
        return false;
      }

      // 2. 模块筛选
      if (filterModule !== 'ALL' && log.module !== filterModule) {
        return false;
      }

      // 3. 搜索关键字 (支持搜 message, traceId, module, aggregateId, json内容)
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const msgMatch = log.message.toLowerCase().includes(q);
        const traceMatch = log.traceId.toLowerCase().includes(q);
        const moduleMatch = log.module.toLowerCase().includes(q);
        const aggMatch = log.aggregateId ? log.aggregateId.toLowerCase().includes(q) : false;
        let payloadMatch = false;
        if (log.payload) {
          try {
            payloadMatch = JSON.stringify(log.payload).toLowerCase().includes(q);
          } catch {
            payloadMatch = false;
          }
        }
        if (!msgMatch && !traceMatch && !moduleMatch && !aggMatch && !payloadMatch) {
          return false;
        }
      }

      return true;
    });
  }, [logs, filterLevel, filterModule, searchQuery]);

  // 分页计算
  const totalItems = filteredLogs.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

  // 确保当前页不越界
  const safeCurrentPage = Math.min(currentPage, totalPages);

  const paginatedLogs = useMemo(() => {
    const startIndex = (safeCurrentPage - 1) * pageSize;
    return filteredLogs.slice(startIndex, startIndex + pageSize);
  }, [filteredLogs, safeCurrentPage, pageSize]);


  // 复制全量日志
  const handleCopyLogs = () => {
    const text = filteredLogs
      .map(l => `[${l.time}] [${l.level}] [${l.module}] [${l.traceId}] ${l.message}`)
      .join('\n');
    navigator.clipboard.writeText(text);
    setCopiedAll(true);
    setTimeout(() => setCopiedAll(false), 1500);
  };

  // 清空筛选
  const handleResetFilters = () => {
    setFilterLevel('ALL');
    setFilterModule('ALL');
    setSearchQuery('');
    setCurrentPage(1);
  };

  return (
    <div id="runtime-logs-view" className="relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-[var(--bg-app)] font-sans text-[var(--text-primary)]">
      {/* 1. 顶部全局工具栏与状态统计 (占满宽度) */}
      <div className="os-console-toolbar flex shrink-0 flex-col justify-between gap-3 border-b border-[var(--border-subtle)] bg-[var(--bg-app)] px-4 py-3 lg:flex-row lg:items-center">
        <div className="flex items-center gap-3">
          <div className="text-[var(--text-tertiary)]">
            <Terminal className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="os-page-heading">
                审计日志
              </h1>
              <span className="inline-flex items-center gap-1.5 rounded-[5px] border border-[var(--border-normal)] px-2 py-0.5 text-[11px] font-medium text-[var(--text-secondary)]">
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--info)]" />
                <span>{autoRefresh ? '自动轮询' : '手动刷新'}</span>
              </span>
            </div>
            <p className="mt-1 text-[12px] text-[var(--text-secondary)]">
              审计事件 · 本次最多读取 100 条 · 已加载 {logs.length} 条（仅对已加载记录筛选与分页）
            </p>
          </div>
        </div>

        {/* 顶部操作快捷栏 */}
        <div className="flex items-center gap-2">
          {/* 自动刷新开关 */}
          <button
            type="button"
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-[4px] border text-xs font-mono transition-colors cursor-pointer ${
              autoRefresh
                ? 'bg-blue-500/15 border-blue-500/30 text-blue-400 font-medium'
                : 'bg-[var(--bg-elevated)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
            }`}
            title="每 5 秒自动拉取最新事件日志"
          >
            <Activity className="h-3.5 w-3.5" />
            <span>自动刷新: {autoRefresh ? '开启' : '关闭'}</span>
          </button>

          {/* 手动刷新 */}
          <button
            type="button"
            onClick={fetchLogs}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-[4px] bg-[var(--bg-elevated)] border border-[var(--border-subtle)] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-xs font-mono transition-colors cursor-pointer disabled:opacity-50"
            title="立即拉取最新事件日志"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-[#58A6FF]' : ''}`} />
            <span>刷新</span>
          </button>

          {/* 导出/复制 */}
          <button
            type="button"
            onClick={handleCopyLogs}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-[4px] bg-[var(--bg-elevated)] border border-[var(--border-subtle)] hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] text-xs font-mono transition-colors cursor-pointer"
            title="复制当前筛选条件下的日志文本到剪贴板"
          >
            {copiedAll ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Download className="w-3.5 h-3.5" />}
            <span>{copiedAll ? '已复制' : '复制日志'}</span>
          </button>


        </div>
      </div>

      {loadError && <p role="alert" className="shrink-0 border-b border-[var(--border-subtle)] px-4 py-2 text-[12px] text-[var(--warning)]">{loadError}</p>}

      {/* 2. 多维组合筛选条 (Filter Bar) */}
      <div className="os-console-filterbar shrink-0 p-3 lg:px-5 border-b border-[var(--border-subtle)] bg-[var(--bg-workspace)] flex flex-wrap items-center justify-between gap-2.5 text-xs">
        {/* 左侧：搜索框与筛选器 */}
        <div className="flex flex-wrap items-center gap-2 flex-1 min-w-[280px]">
          {/* 全文关键字搜索 */}
          <div className="relative w-full min-w-[190px] max-w-[360px] flex-1">
            <Search className="w-3.5 h-3.5 text-[var(--text-tertiary)] absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setCurrentPage(1);
              }}
              placeholder="搜索 Trace ID、模块、消息或 JSON 字段..."
              className="h-9 w-full pl-8 pr-7 rounded-[5px] bg-[var(--bg-surface)] border border-[var(--border-normal)] text-[var(--text-primary)] placeholder-[var(--text-tertiary)] text-xs focus:outline-hidden focus:border-[#58A6FF] font-mono"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>

          {/* 模块选择下拉 */}
          <div className="flex items-center gap-1.5">
            <span className="text-[12px] text-[var(--text-tertiary)] hidden sm:inline">模块:</span>
            <Select
              aria-label="筛选日志模块"
              value={filterModule}
              onChange={(value) => {
                setFilterModule(value);
                setCurrentPage(1);
              }}
              className="min-w-[168px] max-w-[260px]"
              style={{width:220}}
              options={[{value:'ALL',label:'全部微服务 / 模块'},...availableModules.filter(m => m !== 'ALL').map(mod=>({value:mod,label:mod}))]}
              showSearch
              optionFilterProp="label"
            />
          </div>

          {/* 级别标签切换组 */}
          <div className="flex items-center rounded-[5px] p-0.5 bg-[var(--bg-surface)] border border-[var(--border-subtle)]">
            {(['ALL', 'ERROR', 'WARN', 'INFO', 'SUCCESS', 'DEBUG'] as const).map((lvl) => {
              const count = lvl === 'ALL'
                ? logs.length
                : logs.filter(l => l.level === lvl).length;
              const isSelected = filterLevel === lvl;
              return (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => {
                    setFilterLevel(lvl);
                    setCurrentPage(1);
                  }}
                  className={`px-2 py-0.5 rounded-[3px] text-[11px] font-medium transition-colors cursor-pointer flex items-center gap-1 ${
                    isSelected
                      ? 'bg-[var(--bg-selected)] text-[var(--text-primary)] font-bold shadow-xs border border-[var(--border-normal)]'
                      : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]'
                  }`}
                >
                  <span>{lvl}</span>
                  {count > 0 && (
                    <span className={`text-[10px] px-1 rounded ${
                      lvl === 'ERROR' ? 'bg-red-500/20 text-red-400' :
                      lvl === 'WARN' ? 'bg-amber-500/20 text-amber-400' :
                      lvl === 'SUCCESS' ? 'bg-emerald-500/20 text-emerald-400' :
                      'bg-[var(--bg-hover)] text-[var(--text-tertiary)]'
                    }`}>
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {(searchQuery || filterModule !== 'ALL' || filterLevel !== 'ALL') && (
            <button
              type="button"
              onClick={handleResetFilters}
              className="text-[11px] font-mono text-[#58A6FF] hover:underline flex items-center gap-1 cursor-pointer ml-1"
            >
              <X className="w-3 h-3" />
              <span>重置条件</span>
            </button>
          )}
        </div>

        {/* 右侧：统计概况 */}
        <div className="text-[11px] font-mono text-[var(--text-tertiary)]">
          已加载范围内匹配 <span className="text-[var(--text-primary)] font-bold">{filteredLogs.length}</span> 条
        </div>
      </div>

      {/* 3. 中间日志主列表与抽屉容器 (Flex 1 填满剩余所有高度) */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* 表格容器 */}
        <div className="flex-1 overflow-y-auto overflow-x-auto scrollbar-thin">
          <table className="w-full border-collapse text-left font-mono text-xs">
            <thead className="sticky top-0 z-10 bg-[var(--bg-surface)] border-b border-[var(--border-subtle)] text-[11px] text-[var(--text-tertiary)] font-medium">
              <tr>
                <th className="py-2 px-3 w-44">时间戳</th>
                <th className="py-2 px-2 w-20">级别</th>
                <th className="py-2 px-2.5 w-40">微服务 / 模块</th>
                <th className="py-2 px-2.5 w-32">Trace ID</th>
                <th className="py-2 px-2 w-20 text-right">耗时</th>
                <th className="py-2 px-3">消息正文与上下文</th>
                <th className="py-2 px-3 w-20 text-center">详情</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-subtle)] bg-[var(--bg-app)]">
              {paginatedLogs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-16 text-center text-[var(--text-tertiary)] text-xs">
                    未检索到符合条件的日志条目
                  </td>
                </tr>
              ) : (
                paginatedLogs.map((log) => {
                  const isSelected = selectedLog?.id === log.id;
                  return (
                    <tr
                      key={log.id}
                      onClick={() => setSelectedLog(log)}
                      className={`hover:bg-[var(--bg-hover)] transition-colors cursor-pointer group ${
                        isSelected
                          ? 'bg-[var(--bg-selected)] border-l-2 border-l-[#58A6FF]'
                          : log.level === 'ERROR'
                          ? 'bg-red-500/5 hover:bg-red-500/10'
                          : log.level === 'WARN'
                          ? 'bg-amber-500/5 hover:bg-amber-500/10'
                          : ''
                      }`}
                    >
                      {/* 时间戳 */}
                      <td className="py-2 px-3 whitespace-nowrap text-[11px] text-[var(--text-tertiary)] font-mono">
                        {log.time}
                      </td>

                      {/* 级别 */}
                      <td className="py-2 px-2 whitespace-nowrap">
                        <span className={`inline-block px-1.5 py-0.2 rounded text-[10px] font-bold font-mono border ${
                          log.level === 'ERROR'
                            ? 'bg-red-500/15 text-red-400 border-red-500/25'
                            : log.level === 'WARN'
                            ? 'bg-amber-500/15 text-amber-400 border-amber-500/25'
                            : log.level === 'SUCCESS'
                            ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25'
                            : log.level === 'DEBUG'
                            ? 'bg-purple-500/15 text-purple-400 border-purple-500/25'
                            : 'bg-blue-500/15 text-blue-400 border-blue-500/25'
                        }`}>
                          {log.level}
                        </span>
                      </td>

                      {/* 模块 */}
                      <td className="py-2 px-2.5 whitespace-nowrap text-[11px] font-semibold text-[var(--text-primary)]">
                        {log.module}
                      </td>

                      {/* Trace ID */}
                      <td className="py-2 px-2.5 whitespace-nowrap text-[10px] text-[#58A6FF] font-mono group-hover:underline">
                        {log.traceId}
                      </td>

                      {/* 耗时 */}
                      <td className="py-2 px-2 whitespace-nowrap text-[10px] text-right text-[var(--text-tertiary)]">
                        {log.durationMs ? `${log.durationMs}ms` : '-'}
                      </td>

                      {/* 消息正文 */}
                      <td className="py-2 px-3 text-[11px] text-[var(--text-secondary)] max-w-md xl:max-w-xl truncate select-text" title={log.message}>
                        {log.message}
                      </td>

                      {/* 操作 */}
                      <td className="py-2 px-3 text-center whitespace-nowrap">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedLog(log);
                          }}
                          className="px-2 py-0.5 rounded-[4px] bg-[var(--bg-surface)] border border-[var(--border-subtle)] hover:border-[#58A6FF] hover:text-[#58A6FF] text-[10px] text-[var(--text-secondary)] transition-colors cursor-pointer"
                        >
                          查看
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* 4. 日志详情抽屉 (Detail Drawer，右侧滑出并格式化展示 JSON) */}
        {selectedLog && (
          <Drawer placement="right" width={560} open onClose={() => setSelectedLog(null)} title={null} closable={false} styles={{body:{padding:0,overflow:'hidden',display:'flex',flexDirection:'column'}}}>
          <div className="flex h-full min-h-0 flex-col bg-[var(--bg-elevated)]">
            {/* 抽屉头部 */}
            <div className="p-3.5 border-b border-[var(--border-subtle)] flex items-center justify-between bg-[var(--bg-surface)]">
              <div className="flex items-center gap-2">
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono border ${
                  selectedLog.level === 'ERROR'
                    ? 'bg-red-500/15 text-red-400 border-red-500/25'
                    : selectedLog.level === 'WARN'
                    ? 'bg-amber-500/15 text-amber-400 border-amber-500/25'
                    : selectedLog.level === 'SUCCESS'
                    ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25'
                    : 'bg-blue-500/15 text-blue-400 border-blue-500/25'
                }`}>
                  {selectedLog.level}
                </span>
                <span className="font-mono text-xs font-semibold text-[var(--text-primary)]">
                  日志详情 · {selectedLog.id}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setSelectedLog(null)}
                className="p-1 rounded-[4px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* 抽屉滚动内容区 */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4 font-sans select-text scrollbar-thin">
              {/* 关键元数据网格 */}
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2.5 rounded-[6px] bg-[var(--bg-surface)] border border-[var(--border-subtle)] space-y-0.5">
                  <div className="text-[10px] font-mono text-[var(--text-tertiary)]">微服务模块</div>
                  <div className="font-mono font-semibold text-[var(--text-primary)]">{selectedLog.module}</div>
                </div>

                <div className="p-2.5 rounded-[6px] bg-[var(--bg-surface)] border border-[var(--border-subtle)] space-y-0.5">
                  <div className="text-[10px] font-mono text-[var(--text-tertiary)]">响应耗时 / 状态</div>
                  <div className="font-mono font-semibold text-[var(--text-primary)] flex items-center gap-1.5">
                    <span>{selectedLog.durationMs ? `${selectedLog.durationMs} ms` : 'N/A'}</span>
                    <span className="text-[10px] px-1 rounded bg-[var(--bg-hover)] text-emerald-400">
                      {selectedLog.statusCode ? `HTTP ${selectedLog.statusCode}` : 'N/A'}
                    </span>
                  </div>
                </div>

                <div className="p-2.5 rounded-[6px] bg-[var(--bg-surface)] border border-[var(--border-subtle)] space-y-0.5 col-span-2">
                  <div className="text-[10px] font-mono text-[var(--text-tertiary)] flex items-center justify-between">
                    <span>Trace ID (链路追踪标识)</span>
                    <button
                      type="button"
                      onClick={() => navigator.clipboard.writeText(selectedLog.traceId)}
                      className="text-[#58A6FF] hover:underline flex items-center gap-1 cursor-pointer"
                    >
                      <Copy className="w-2.5 h-2.5" />
                      <span>复制</span>
                    </button>
                  </div>
                  <div className="font-mono text-xs text-[#58A6FF] font-semibold">{selectedLog.traceId}</div>
                </div>

                <div className="p-2.5 rounded-[6px] bg-[var(--bg-surface)] border border-[var(--border-subtle)] space-y-0.5 col-span-2">
                  <div className="text-[10px] font-mono text-[var(--text-tertiary)]">记录时间 (精确至毫秒)</div>
                  <div className="font-mono text-xs text-[var(--text-secondary)]">{selectedLog.time}</div>
                </div>
              </div>

              {/* 消息正文描述 */}
              <div className="space-y-1">
                <div className="text-[11px] font-mono text-[var(--text-tertiary)] uppercase font-semibold">
                  消息正文 (Event Message)
                </div>
                <div className="p-3 rounded-[6px] bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-xs text-[var(--text-primary)] font-mono leading-relaxed break-all">
                  {selectedLog.message}
                </div>
              </div>

              {/* JSON Payload 格式化展示 (核心要求) */}
              <div className="space-y-1.5">
                <div className="text-[11px] font-mono text-[var(--text-tertiary)] uppercase font-semibold flex items-center justify-between">
                  <span>结构化 JSON 数据 (Payload & Context)</span>
                </div>

                {selectedLog.payload ? (
                  <FormattedJsonViewer data={selectedLog.payload} />
                ) : (
                  <div className="p-3 rounded-[6px] bg-[var(--bg-surface)] border border-[var(--border-subtle)] text-xs text-[var(--text-tertiary)] text-center font-mono">
                    无结构化 JSON 载荷
                  </div>
                )}
              </div>

              {/* Context 上下文 JSON */}
              {selectedLog.context && Object.keys(selectedLog.context).length > 0 && (
                <div className="space-y-1.5">
                  <div className="text-[11px] font-mono text-[var(--text-tertiary)] uppercase font-semibold">
                    环境运行上下文 (Context)
                  </div>
                  <FormattedJsonViewer data={selectedLog.context} />
                </div>
              )}
            </div>
          </div>
          </Drawer>
        )}
      </div>

      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-2 text-[12px] text-[var(--text-secondary)]"><span>本次筛选结果：{totalItems} 条</span><Pagination size="small" current={safeCurrentPage} pageSize={pageSize} total={totalItems} showSizeChanger pageSizeOptions={["15","20","50","100"]} showTotal={(total,range)=>`${range[0]}–${range[1]} / ${total} 条`} onChange={(next,size)=>{setCurrentPage(next);setPageSize(size);}} /></div>
    </div>
  );
};
