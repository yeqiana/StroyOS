"""StoryOS current React/Ant Design Web Console API contract.

R35 migration of obsolete Vue-only file paths. These checks intentionally
target the current UI and backend API source without depending on demos.
Actual Chrome navigation is covered separately by the R28/R35 browser suites.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web-console"
SRC = WEB / "src"


def read(relative: str) -> str:
    path = WEB / relative
    assert path.is_file(), f"current React console source absent: {relative}"
    return path.read_text(encoding="utf-8")


def test_single_platform_api_base_url_contract():
    env = read(".env.example")
    config = read("src/config/appConfig.ts")
    client = read("src/api/httpClient.ts")
    assert "VITE_PLATFORM_API_URL=" in env
    configured = [line.split("=", 1)[0].strip() for line in env.splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
    assert "VITE_API_BASE_URL" not in configured
    assert "VITE_RUNTIME_STREAM_URL" not in configured
    assert "VITE_PLATFORM_API_URL" in config
    assert "appConfig.platformApiBaseUrl" in client
    assert "return path" in client
    assert not (SRC / "api/streaming.js").exists()


def test_dev_and_preview_reuse_one_readonly_platform_proxy():
    config = read("vite.config.ts")
    assert "const platformProxy" in config
    assert "'http://127.0.0.1:8080'" in config
    assert "STORYOS_PLATFORM_PROXY_TARGET" in config
    assert "proxy: platformProxy" in config
    assert "preview: { proxy: platformProxy }" in config
    assert "changeOrigin: true" in config


def test_main_react_console_renders_only_real_first_level_surfaces():
    app = read("src/App.tsx")
    for tab, component in (
        ("overview", "HomeOverviewView"),
        ("production_monitor", "ProductionMonitorView"),
        ("pipeline", "WorkflowWorkspaceView"),
        ("agents", "AgentWorkspaceView"),
        ("episodes", "SeriesLibraryView"),
        ("logs", "RuntimeLogsView"),
        ("settings", "SettingsView"),
    ):
        assert f"currentTab === '{tab}'" in app
        assert component in app
    assert "AntdSurface" in app
    assert "mock/episodes" not in app


def test_production_monitor_uses_canonical_runtime_without_faking_online_run():
    monitor = read("src/components/views/ProductionMonitorView.tsx")
    panel = read("src/components/views/RuntimeAuthorityPanel.tsx")
    assert "platformApi.runtimeStatuses(100, 0)" in monitor
    assert "REAL_STORY_RUNS" in monitor
    assert "historical" in monitor.lower() or "历史" in monitor
    assert "stage_source" not in panel or "state_source" in panel
    assert "local_workspace_episode_state_file" in panel
    assert "非实时 Runtime" in panel
    assert "mock/episodes" not in monitor + panel
    assert "ProgressNodes.vue" not in monitor + panel


def test_story_library_has_readonly_approved_source_and_no_cross_story_fallback():
    library = read("src/components/views/SeriesLibraryView.tsx")
    approved = read("src/api/localApprovedMedia.ts")
    assert "useLocalApprovedMedia" in library
    assert "findEpisode(ep.title,ep.code)" in library
    assert "已批准" in library
    assert "approved" in approved.lower()
    assert "mock/episodes" not in library


def test_runtime_logs_call_events_and_keep_empty_or_offline_distinct():
    logs = read("src/components/views/RuntimeLogsView.tsx")
    assert "platformApi.events(100, 0)" in logs
    assert "接口已返回，但当前未载入日志事件" in logs
    assert "事件 API 当前不可读取，无法确认是否存在日志" in logs
    assert "mock/episodes" not in logs
    assert "示例事件" not in logs


def test_supported_execution_trace_and_authority_urls_are_canonical():
    api = read("src/api/platformApi.ts")
    for route in (
        "/api/v1/executions/",
        "/api/v1/traces/",
        "/api/v1/traces?",
        "/api/v1/runtime/statuses?limit=",
        "/api/v1/runtime/events?limit=",
        "/api/v1/runtime/authority?episode=",
    ):
        assert route in api
    assert "encodeURIComponent(episodeRef)" in api
    assert "encodeURIComponent(episodeId)" in api
    assert not (SRC / "api/monitoring.js").exists()
    assert not (SRC / "api/workflow.js").exists()


def test_one_sidebar_settings_entry_and_real_main_navigation():
    app = read("src/App.tsx")
    sidebar = read("src/components/Sidebar.tsx")
    header = read("src/components/HeaderBar.tsx")
    assert "<Sidebar" in app
    assert "<HeaderBar" in app
    assert "onSelectTab" in sidebar
    assert "onSelectTab('settings')" in sidebar
    assert "onOpenSettings" in header
    assert "PageTabs.vue" not in app
    assert "src/router/index.js" not in app


def test_operational_tables_use_native_antd_not_reinvented_demo_grid():
    for relative in (
        "src/components/views/RuntimeAuthorityPanel.tsx",
        "src/components/views/WorkflowWorkspaceView.tsx",
        "src/components/views/SeriesLibraryView.tsx",
        "src/components/views/AgentWorkspaceView.tsx",
    ):
        page = read(relative)
        assert "from 'antd'" in page
        assert "<Table<" in page or "<Table " in page
        assert "pagination" in page
        assert "mock/episodes" not in page


def test_operational_filter_bars_keep_accessible_native_controls():
    for relative in (
        "src/components/views/RuntimeAuthorityPanel.tsx",
        "src/components/views/WorkflowWorkspaceView.tsx",
        "src/components/views/SeriesLibraryView.tsx",
        "src/components/views/AgentWorkspaceView.tsx",
        "src/components/views/RuntimeLogsView.tsx",
    ):
        page = read(relative)
        assert "from 'antd'" in page
        assert "Input.Search" in page or "<Input" in page
        assert "Select" in page
        assert "aria-label" in page


def test_r35_authority_source_requires_explicit_reader_and_never_grants_retry():
    routes = (ROOT / "platform/api/routes.py").read_text(encoding="utf-8")
    local = (ROOT / "scripts/storyos_local_readonly_api.py").read_text(encoding="utf-8")
    comp = (ROOT / "platform/api/default_app.py").read_text(encoding="utf-8")
    evidence = (ROOT / "platform/operations/runtime_authority_evidence.py").read_text(encoding="utf-8")
    assert '"/api/v1/runtime/authority"' in routes
    assert '"/api/v1/runtime/authority"' in local
    assert "RuntimeAuthorityApiController" in comp
    assert "if runtime_authority_service is not None" in comp
    assert '"production_authorization": False' in evidence
    assert '"can_retry": False' in evidence
    assert '"model_calls": 0' in evidence
