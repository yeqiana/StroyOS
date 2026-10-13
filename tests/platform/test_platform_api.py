from platform.api import (
    AgentApiController,
    CreateAgentRequest,
    MemoryApiController,
    MemorySearchRequest,
    PLATFORM_API_ROUTES,
    WorkflowApiController,
    StartWorkflowRunRequest,
)


class FakeAgentService:
    def create_agent(self, request):
        return {"id": "agent-1", "agent_code": request.agent_code}

    def get_agent(self, agent_id):
        if agent_id == "agent-1":
            return {"id": agent_id, "status": "ACTIVE"}
        return None

    def list_agent_executions(self, agent_id):
        return [{"id": "exec-1", "agent_id": agent_id}]


class FakeWorkflowService:
    def start_run(self, workflow_code, request):
        return {
            "id": "run-1",
            "workflow_code": workflow_code,
            "project_id": request.project_id,
            "status": "CREATED",
        }

    def get_run(self, run_id):
        return {"id": run_id, "status": "RUNNING"} if run_id == "run-1" else None


class FakeMemoryService:
    def search(self, request):
        return [{"id": "memory-1", "query": request.query}]

    def get_memory(self, memory_id):
        return {"id": memory_id} if memory_id == "memory-1" else None


class FakeTraceService:
    def get_trace(self, trace_id):
        return {"trace_id": trace_id, "span_id": "span-1"}

    def list_traces(self, **kwargs):
        return {"items": [], "count": 0, **kwargs}


def test_agent_api_delegates_to_service_and_wraps_response():
    controller = AgentApiController(FakeAgentService())

    response = controller.create_agent(
        CreateAgentRequest(
            agent_code="story_agent",
            agent_name="Story Agent",
            agent_type="STORY",
        )
    )

    assert response.code == "OK"
    assert response.data == {"id": "agent-1", "agent_code": "story_agent"}
    assert response.trace_id
    assert response.timestamp


def test_agent_api_returns_stable_not_found_contract():
    response = AgentApiController(FakeAgentService()).get_agent("missing")

    assert response.code == "AGENT_NOT_FOUND"
    assert response.data is None


def test_workflow_api_starts_run_without_runtime_implementation():
    response = WorkflowApiController(FakeWorkflowService()).start_run(
        "AI_STORY_PRODUCTION",
        StartWorkflowRunRequest(project_id="project-1", input_data={"episode": "EP002"}),
    )

    assert response.code == "OK"
    assert response.data["id"] == "run-1"
    assert response.data["workflow_code"] == "AI_STORY_PRODUCTION"


def test_memory_search_validates_request_before_service_call():
    controller = MemoryApiController(FakeMemoryService())

    invalid = controller.search(MemorySearchRequest(query=" ", limit=10))
    valid = controller.search(MemorySearchRequest(query="visual identity", limit=5))

    assert invalid.code == "INVALID_REQUEST"
    assert invalid.data == []
    assert valid.code == "OK"
    assert valid.data[0]["id"] == "memory-1"


def test_trace_api_lists_bounded_spans_with_compatible_filters():
    from platform.api.controllers import TraceApiController

    response = TraceApiController(FakeTraceService()).list_traces(
        limit="20", offset="5", episode_id="EP001", trace_id="trace-1"
    )

    assert response.code == "OK"
    assert response.data["limit"] == 20
    assert response.data["offset"] == 5
    assert response.data["episode_id"] == "EP001"


def test_platform_route_catalog_matches_p51_contract():
    actual = {(route.method, route.path) for route in PLATFORM_API_ROUTES}

    expected = {
        ("POST", "/api/v1/agents"),
        ("GET", "/api/v1/agents/{id}"),
        ("GET", "/api/v1/agents/{id}/executions"),
        ("POST", "/api/v1/workflows/{code}/runs"),
        ("GET", "/api/v1/workflows/runs/{id}"),
        ("GET", "/api/v1/executions/{id}"),
        ("GET", "/api/v1/runtime/status"),
        ("GET", "/api/v1/runtime/statuses"),
        ("GET", "/api/v1/runtime/authority"),
        ("POST", "/api/v1/memory/search"),
        ("GET", "/api/v1/memory/{id}"),
        ("GET", "/api/v1/skills"),
        ("GET", "/api/v1/mcp/tools"),
        ("GET", "/api/v1/runtime/events"),
        ("GET", "/api/v1/traces"),
        ("GET", "/api/v1/traces/{id}"),
    }

    assert actual == expected
