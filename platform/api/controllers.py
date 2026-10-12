from __future__ import annotations

from platform.api.contracts import ApiResponse, CreateAgentRequest, MemorySearchRequest, StartWorkflowRunRequest
from platform.api.service_ports import (
    AgentServicePort,
    ExecutionServicePort,
    MemoryServicePort,
    RegistryServicePort,
    RuntimeEventServicePort,
    RuntimeStatusServicePort,
    RuntimeAuthorityEvidenceServicePort,
    TraceServicePort,
    WorkflowServicePort,
)


class AgentApiController:
    def __init__(self, service: AgentServicePort) -> None:
        self._service = service

    def create_agent(self, request: CreateAgentRequest) -> ApiResponse[dict]:
        return ApiResponse.ok(self._service.create_agent(request))

    def get_agent(self, agent_id: str) -> ApiResponse[dict]:
        agent = self._service.get_agent(agent_id)
        if agent is None:
            return ApiResponse.error("AGENT_NOT_FOUND", f"agent not found: {agent_id}")
        return ApiResponse.ok(agent)

    def list_executions(self, agent_id: str) -> ApiResponse[list[dict]]:
        return ApiResponse.ok(self._service.list_agent_executions(agent_id))


class WorkflowApiController:
    def __init__(self, service: WorkflowServicePort) -> None:
        self._service = service

    def start_run(self, workflow_code: str, request: StartWorkflowRunRequest) -> ApiResponse[dict]:
        return ApiResponse.ok(self._service.start_run(workflow_code, request))

    def get_run(self, run_id: str) -> ApiResponse[dict]:
        run = self._service.get_run(run_id)
        if run is None:
            return ApiResponse.error("WORKFLOW_RUN_NOT_FOUND", f"workflow run not found: {run_id}")
        return ApiResponse.ok(run)


class ExecutionApiController:
    def __init__(self, service: ExecutionServicePort) -> None:
        self._service = service

    def get_execution(self, execution_id: str) -> ApiResponse[dict]:
        execution = self._service.get_execution(execution_id)
        if execution is None:
            return ApiResponse.error("EXECUTION_NOT_FOUND", f"execution not found: {execution_id}")
        return ApiResponse.ok(execution)


class RuntimeStatusApiController:
    def __init__(self, service: RuntimeStatusServicePort) -> None:
        self._service = service

    def get_episode_status(self, episode: str) -> ApiResponse[dict]:
        try:
            status = self._service.get_episode_status(episode)
        except ValueError as exc:
            return ApiResponse.error("INVALID_REQUEST", str(exc))
        if status is None:
            return ApiResponse.error("EPISODE_NOT_FOUND", f"episode not found: {episode}")
        return ApiResponse.ok(status)

    def list_episode_statuses(self, limit: str = "50", offset: str = "0") -> ApiResponse[dict]:
        try:
            return ApiResponse.ok(self._service.list_episode_statuses(limit=limit, offset=offset))
        except ValueError as exc:
            return ApiResponse.error("INVALID_REQUEST", str(exc))


class RuntimeAuthorityApiController:
    """Read-only authority evidence. This endpoint never starts or retries tasks."""

    def __init__(self, service: RuntimeAuthorityEvidenceServicePort) -> None:
        self._service = service

    def get_episode_authority(self, episode: str) -> ApiResponse[dict]:
        try:
            evidence = self._service.get_episode_authority(episode)
        except ValueError:
            return ApiResponse.error("INVALID_REQUEST", "invalid Episode authority identity")
        except Exception:
            # Read-only source errors may contain credentials and host paths.
            return ApiResponse.error("AUTHORITY_STATUS_UNAVAILABLE", "Runtime authority source unavailable")
        if evidence is None:
            return ApiResponse.error("EPISODE_NOT_FOUND", "Episode authority evidence not found")
        return ApiResponse.ok(evidence)


class RuntimeEventApiController:
    def __init__(self, service: RuntimeEventServicePort) -> None:
        self._service = service

    def list_events(
        self,
        limit: str = "50",
        offset: str = "0",
        episode_id: str = "",
    ) -> ApiResponse[dict]:
        try:
            return ApiResponse.ok(
                self._service.list_events(
                    limit=limit,
                    offset=offset,
                    episode_id=episode_id,
                )
            )
        except ValueError as exc:
            return ApiResponse.error("INVALID_REQUEST", str(exc))


class MemoryApiController:
    def __init__(self, service: MemoryServicePort) -> None:
        self._service = service

    def search(self, request: MemorySearchRequest) -> ApiResponse[list[dict]]:
        try:
            request.validate()
        except ValueError as exc:
            return ApiResponse.error("INVALID_REQUEST", str(exc), data=[])
        return ApiResponse.ok(self._service.search(request))

    def get_memory(self, memory_id: str) -> ApiResponse[dict]:
        memory = self._service.get_memory(memory_id)
        if memory is None:
            return ApiResponse.error("MEMORY_NOT_FOUND", f"memory not found: {memory_id}")
        return ApiResponse.ok(memory)


class RegistryApiController:
    def __init__(self, service: RegistryServicePort) -> None:
        self._service = service

    def list_skills(self) -> ApiResponse[list[dict]]:
        return ApiResponse.ok(self._service.list_skills())

    def list_mcp_tools(self) -> ApiResponse[list[dict]]:
        return ApiResponse.ok(self._service.list_mcp_tools())


class TraceApiController:
    def __init__(self, service: TraceServicePort) -> None:
        self._service = service

    def get_trace(self, trace_id: str) -> ApiResponse[dict]:
        trace = self._service.get_trace(trace_id)
        if trace is None:
            return ApiResponse.error("TRACE_NOT_FOUND", f"trace not found: {trace_id}")
        return ApiResponse.ok(trace)

    def list_traces(
        self,
        limit: str = "50",
        offset: str = "0",
        episode_id: str = "",
        trace_id: str = "",
    ) -> ApiResponse[dict]:
        try:
            limit_value = int(limit)
            offset_value = int(offset)
        except (TypeError, ValueError):
            return ApiResponse.error("INVALID_REQUEST", "limit and offset must be integers")
        if limit_value < 1 or limit_value > 100:
            return ApiResponse.error("INVALID_REQUEST", "limit must be between 1 and 100")
        if offset_value < 0:
            return ApiResponse.error("INVALID_REQUEST", "offset must be non-negative")
        return ApiResponse.ok(
            self._service.list_traces(
                limit=limit_value,
                offset=offset_value,
                episode_id=episode_id,
                trace_id=trace_id,
            )
        )
