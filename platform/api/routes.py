from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteDefinition:
    method: str
    path: str
    handler: str


PLATFORM_API_ROUTES: tuple[RouteDefinition, ...] = (
    RouteDefinition("POST", "/api/v1/agents", "AgentApiController.create_agent"),
    RouteDefinition("GET", "/api/v1/agents/{id}", "AgentApiController.get_agent"),
    RouteDefinition("GET", "/api/v1/agents/{id}/executions", "AgentApiController.list_executions"),
    RouteDefinition("POST", "/api/v1/workflows/{code}/runs", "WorkflowApiController.start_run"),
    RouteDefinition("GET", "/api/v1/workflows/runs/{id}", "WorkflowApiController.get_run"),
    RouteDefinition("GET", "/api/v1/executions/{id}", "ExecutionApiController.get_execution"),
    RouteDefinition("GET", "/api/v1/runtime/status", "RuntimeStatusApiController.get_episode_status"),
    RouteDefinition("GET", "/api/v1/runtime/statuses", "RuntimeStatusApiController.list_episode_statuses"),
    RouteDefinition("GET", "/api/v1/runtime/authority", "RuntimeAuthorityApiController.get_episode_authority"),
    RouteDefinition("GET", "/api/v1/runtime/events", "RuntimeEventApiController.list_events"),
    RouteDefinition("POST", "/api/v1/memory/search", "MemoryApiController.search"),
    RouteDefinition("GET", "/api/v1/memory/{id}", "MemoryApiController.get_memory"),
    RouteDefinition("GET", "/api/v1/skills", "RegistryApiController.list_skills"),
    RouteDefinition("GET", "/api/v1/mcp/tools", "RegistryApiController.list_mcp_tools"),
    RouteDefinition("GET", "/api/v1/traces", "TraceApiController.list_traces"),
    RouteDefinition("GET", "/api/v1/traces/{id}", "TraceApiController.get_trace"),
)
