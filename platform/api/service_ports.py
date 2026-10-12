from __future__ import annotations

from typing import Any, Protocol

from platform.api.contracts import CreateAgentRequest, MemorySearchRequest, StartWorkflowRunRequest


class AgentServicePort(Protocol):
    def create_agent(self, request: CreateAgentRequest) -> dict[str, Any]: ...

    def get_agent(self, agent_id: str) -> dict[str, Any] | None: ...

    def list_agent_executions(self, agent_id: str) -> list[dict[str, Any]]: ...


class WorkflowServicePort(Protocol):
    def start_run(self, workflow_code: str, request: StartWorkflowRunRequest) -> dict[str, Any]: ...

    def get_run(self, run_id: str) -> dict[str, Any] | None: ...


class ExecutionServicePort(Protocol):
    def get_execution(self, execution_id: str) -> dict[str, Any] | None: ...


class MemoryServicePort(Protocol):
    def search(self, request: MemorySearchRequest) -> list[dict[str, Any]]: ...

    def get_memory(self, memory_id: str) -> dict[str, Any] | None: ...


class RegistryServicePort(Protocol):
    def list_skills(self) -> list[dict[str, Any]]: ...

    def list_mcp_tools(self) -> list[dict[str, Any]]: ...


class TraceServicePort(Protocol):
    def get_trace(self, trace_id: str) -> dict[str, Any] | None: ...

    def list_traces(
        self,
        *,
        limit: int | str = 50,
        offset: int | str = 0,
        episode_id: str = "",
        trace_id: str = "",
    ) -> dict[str, Any]: ...


class RuntimeStatusServicePort(Protocol):
    def get_episode_status(self, episode_ref: str) -> dict[str, Any] | None: ...

    def list_episode_statuses(self, *, limit: int | str = 50, offset: int | str = 0) -> dict[str, Any]: ...


class RuntimeAuthorityEvidenceServicePort(Protocol):
    def get_episode_authority(self, episode: str) -> dict[str, Any] | None: ...


class RuntimeEventServicePort(Protocol):
    def list_events(
        self,
        *,
        limit: int | str = 50,
        offset: int | str = 0,
        episode_id: str = "",
    ) -> dict[str, Any]: ...
