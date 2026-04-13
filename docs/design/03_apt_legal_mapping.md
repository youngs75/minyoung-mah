# 03. Apt-Legal Agent — minyoung-mah 위의 새 설계

**상태**: Draft 1 · 2026-04-13
**성격**: Greenfield. 기존 `apt-legal-mcp/docs/` 3개 문서의 **사용자 요구사항은 유지**하되, 아키텍처는 minyoung-mah에 자연스러운 shape로 **재설계**한다.

---

## 보존하는 요구사항 (negotiable한 것과 아닌 것)

### 보존 (사용자 facing 계약)

1. **사용자/이해관계자** — 아파트 입주민, 대표회의 임원, 관리사무소
2. **지원 분쟁 유형 10종** — NOISE / PARKING / PET / MGMT_FEE / DEFECT / RECON / REMODEL / BID / ELECTION / GENERAL
3. **법령·판례·행정해석 근거 기반 응답** + **면책 문구** 필수
4. **A2A 엔드포인트** — `/a2a` (tasks/send), `/a2a/stream` (SSE), `/.well-known/agent.json`
5. **MCP 서버(`apt-legal-mcp`)를 외부 도구로 호출** — 6 tools: search_law, get_law_article, search_precedent, get_precedent_detail, search_interpretation, compare_laws
6. **gpt-4o 기반** (env로 교체 가능해야 함)
7. **개인정보 저장 금지** — 특정 단지/개인 정보를 메모리에 쌓지 않음
8. **응답 JSON 스키마** — `{answer, legal_basis[], next_steps[], disclaimer}`
9. **AWS EKS 배포** — FastAPI + Dockerfile + k8s yaml

### 재설계 (negotiable)

- classifier / planner / responder의 **역할 경계** — 새 shape 필요하면 합쳐도, 쪼개도 됨
- classifier의 **키워드 기반 폴백 규칙** — minyoung-mah의 `RoleClassifier` 사용하거나 아예 LLM 하나로
- planner의 **분쟁 유형별 고정 호출 세트 매핑 테이블** — 데이터로 유지할지, LLM에 맡길지
- MCP 호출 **parallel/serial 순서** — static pipeline에서 어떻게 표현할지
- **에러 처리 전략** — 부분 실패 시 어디까지 성공으로 간주할지

---

## 1. 전체 아키텍처 (minyoung-mah 기반)

```
[ChatGPT Enterprise CustomGPT]
         ↓ A2A Protocol
[FastAPI app]                           ← apt-legal application
  ├─ /a2a/tasks/send → TaskHandler
  ├─ /a2a/stream     → SseHandler
  └─ /healthz
         ↓ orchestrator.run_pipeline(static)
[minyoung_mah.Orchestrator]             ← library
  ├─ classifier role   → gpt-4o (structured)
  ├─ retrieval_planner role → gpt-4o (structured)
  ├─ retrieval_executor (fan_out) → MCP tool adapters
  └─ responder role   → gpt-4o (free-form with schema)
         ↓ MCP Streamable HTTP
[apt-legal-mcp server]                  ← 별도 repo, 변경 없음
  └─ 6 tools
         ↓
[law.go.kr / 판례 DB]
```

### 주요 변경점 vs 기존 `03_vertical_agent_codex_spec.md`

| 기존 설계 | 새 설계 |
|---|---|
| `agent/orchestrator.py` 자체 구현 (hand-written pipeline) | `minyoung_mah.Orchestrator` 재사용, `StaticPipeline` 선언 |
| `agent/classifier.py` / `planner.py` / `responder.py` 3개 **클래스** | 3개 **`SubAgentRole`** 데이터 정의 + Orchestrator가 실행 |
| `mcp_client/client.py` 자체 구현 | `McpProxyToolAdapter` (minyoung-mah `ToolAdapter` 구현) × 6 |
| 병렬 호출 `asyncio.gather` hand-written | `StaticPipeline`의 `fan_out` |
| 재시도 logic hand-written | `minyoung_mah.resilience.retry_policy` + Observer wiring |
| `llm/gateway.py` 자체 LiteLLM wrapper | `SingleModelRouter(ChatOpenAI)` |
| A2A task 상태 머신 자체 관리 | A2A 레이어는 그대로, **Orchestrator 결과를 A2A artifact로 변환**만 |

---

## 2. 프로젝트 구조

```
apt-legal-agent/                        ← 별도 repo (또는 examples/apt_legal_agent/)
├── pyproject.toml                      # depends: minyoung-mah, fastapi, uvicorn, mcp
├── Dockerfile
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── ingress.yaml
├── apt_legal_agent/
│   ├── __init__.py
│   ├── app.py                          # FastAPI 앱 진입점
│   ├── a2a/
│   │   ├── agent_card.py               # /.well-known/agent.json
│   │   ├── task_handler.py             # /a2a/tasks/send → Orchestrator 호출
│   │   ├── sse_handler.py              # /a2a/stream
│   │   └── hitl_channel.py             # A2AHITLChannel (SSE push)
│   ├── roles/
│   │   ├── __init__.py
│   │   ├── classifier.py               # CLASSIFIER_ROLE definition
│   │   ├── retrieval_planner.py        # RETRIEVAL_PLANNER_ROLE
│   │   └── responder.py                # RESPONDER_ROLE
│   ├── prompts/
│   │   ├── classifier.py               # CLASSIFIER_SYSTEM_PROMPT
│   │   ├── retrieval_planner.py
│   │   └── responder.py
│   ├── tools/
│   │   ├── mcp_client.py               # httpx 기반 MCP Streamable HTTP client
│   │   └── mcp_adapters.py             # McpProxyToolAdapter × 6
│   ├── pipeline.py                     # StaticPipeline 정의
│   ├── models/
│   │   ├── dispute.py                  # DisputeType Enum, QueryIntent Enum
│   │   ├── classification.py           # Classification Pydantic (output_schema)
│   │   ├── plan.py                     # ExecutionPlan Pydantic
│   │   └── response.py                 # AgentResponse Pydantic
│   ├── config.py                       # AptLegalConfig(HarnessConfig)
│   └── bootstrap.py                    # Orchestrator composition root
├── tests/
│   ├── test_classifier_role.py
│   ├── test_planner_role.py
│   ├── test_responder_role.py
│   ├── test_pipeline_e2e.py            # with mocked MCP
│   ├── test_mcp_adapters.py
│   ├── test_a2a_handler.py
│   └── conftest.py
└── scripts/
    └── test_scenarios.py               # 3 demo scenarios (층간소음 단순/복합/재건축)
```

---

## 3. 역할 정의 (SubAgentRole × 3)

### 3.1 Classifier

**책임**: 사용자 질문을 `(dispute_type, keywords, intent, confidence)`로 분류. 도구 호출 없음. 단일 LLM call.

```python
# apt_legal_agent/models/classification.py
from enum import Enum
from pydantic import BaseModel, Field

class DisputeType(str, Enum):
    NOISE = "NOISE"; PARKING = "PARKING"; PET = "PET"; MGMT_FEE = "MGMT_FEE"
    DEFECT = "DEFECT"; RECON = "RECON"; REMODEL = "REMODEL"; BID = "BID"
    ELECTION = "ELECTION"; GENERAL = "GENERAL"

class QueryIntent(str, Enum):
    LAW_CHECK = "LAW_CHECK"
    PROCEDURE_GUIDE = "PROCEDURE_GUIDE"
    DISPUTE_RESOLUTION = "DISPUTE_RESOLUTION"
    COMPARISON = "COMPARISON"

class DisputeClassification(BaseModel):
    dispute_type: DisputeType
    keywords: list[str] = Field(default_factory=list, max_length=10)
    intent: QueryIntent
    confidence: float = Field(ge=0.0, le=1.0)
```

```python
# apt_legal_agent/roles/classifier.py
from minyoung_mah import SubAgentRole
from apt_legal_agent.models.classification import DisputeClassification
from apt_legal_agent.prompts.classifier import CLASSIFIER_SYSTEM_PROMPT

CLASSIFIER_ROLE = SubAgentRole(
    name="classifier",
    system_prompt=CLASSIFIER_SYSTEM_PROMPT,
    tool_allowlist=[],          # no tools
    model_tier="default",
    output_schema=DisputeClassification,  # **structured output**
    max_iterations=1,           # single LLM call, no loop
    build_user_message=lambda ctx: f"사용자 질문: {ctx.user_request}\n\n분류해 주세요.",
)
```

**note**: `max_iterations=1`과 `output_schema`가 함께 쓰이면 Orchestrator는 "LLM 한 번 호출, JSON 파싱, schema validation, 반환" 경로로 동작한다 (tool-call loop 없음).

### 3.2 Retrieval Planner

**책임**: 분류 결과를 받아 MCP tool 호출 계획을 produce. LLM 사용하지만 도구 호출 없음. 단일 call.

**설계 선택**: 기존 스펙의 "분쟁 유형별 고정 호출 세트 매핑 테이블"을 LLM 프롬프트에 예시로 넣고, LLM이 상황에 맞게 조정하도록 한다. 완전 규칙 기반 대신 LLM-guided. 이게 더 자연스럽고 minyoung-mah 철학(결과물 형식 강제 X)에도 맞다.

```python
# apt_legal_agent/models/plan.py
class ToolCallStep(BaseModel):
    index: int
    tool_name: str  # one of the 6 MCP tool names
    arguments: dict
    priority: int = Field(ge=1, le=3)
    depends_on: list[int] = Field(default_factory=list)
    rationale: str  # for observability

class ExecutionPlan(BaseModel):
    steps: list[ToolCallStep] = Field(max_length=8)
```

```python
# apt_legal_agent/roles/retrieval_planner.py
RETRIEVAL_PLANNER_ROLE = SubAgentRole(
    name="retrieval_planner",
    system_prompt=PLANNER_SYSTEM_PROMPT,  # 분쟁 유형별 예시 + MCP tool signatures
    tool_allowlist=[],
    model_tier="default",
    output_schema=ExecutionPlan,
    max_iterations=1,
    build_user_message=lambda ctx: (
        f"사용자 질문: {ctx.user_request}\n\n"
        f"분류 결과: {ctx.parent_outputs['classifier'].model_dump_json()}\n\n"
        "MCP Tool 호출 계획을 생성하세요. priority 1은 필수, 2는 보조, 3은 선택."
    ),
)
```

### 3.3 Retrieval Executor (role이 아니라 pipeline step)

**핵심 설계 선택**: Executor는 **역할이 아니다**. 역할은 LLM 호출을 전제로 하는데, executor는 plan을 받아 MCP tool을 호출하는 "순수 실행" 단계다. LLM이 끼어들 자리가 없다.

→ `StaticPipeline`의 step 중 하나로, `role=None`에 `fan_out: Callable`을 세팅하는 특수 타입을 지원한다. 또는 library에 **`ExecuteToolsStep`**을 추가해서 plan → tool calls 변환을 맡긴다.

이건 **library 요구사항이 추가됨**을 의미한다 → 04 open questions에 기록.

**임시 설계** (library 확장 후):

```python
# apt_legal_agent/pipeline.py
from minyoung_mah import StaticPipeline, PipelineStep, ExecuteToolsStep

def build_pipeline() -> StaticPipeline:
    return StaticPipeline(steps=[
        PipelineStep(
            role="classifier",
            input_mapping=lambda state: InvocationContext(
                task_summary="분류",
                user_request=state.user_request,
                parent_outputs={},
            ),
        ),
        PipelineStep(
            role="retrieval_planner",
            input_mapping=lambda state: InvocationContext(
                task_summary="계획",
                user_request=state.user_request,
                parent_outputs={"classifier": state["classifier"].output},
            ),
        ),
        ExecuteToolsStep(
            name="retrieval_executor",
            tool_calls_from=lambda state: [
                ToolCallRequest(
                    tool_name=step.tool_name,
                    args=step.arguments,
                    priority=step.priority,
                )
                for step in state["retrieval_planner"].output.steps
            ],
            parallel_within_priority=True,
            continue_on_failure=True,
        ),
        PipelineStep(
            role="responder",
            input_mapping=lambda state: InvocationContext(
                task_summary="응답 생성",
                user_request=state.user_request,
                parent_outputs={
                    "classifier": state["classifier"].output,
                    "tool_results": state["retrieval_executor"].results,
                },
            ),
        ),
    ])
```

### 3.4 Responder

**책임**: 분류 결과 + MCP tool 결과를 받아 `AgentResponse` JSON을 생성.

```python
# apt_legal_agent/models/response.py
class LegalBasisItem(BaseModel):
    type: Literal["law", "precedent", "interpretation"]
    reference: str
    summary: str

class AgentResponse(BaseModel):
    answer: str
    legal_basis: list[LegalBasisItem]
    next_steps: list[str]
    disclaimer: str = (
        "※ 본 답변은 일반적인 법률 정보 제공 목적이며, "
        "구체적 사안에 대해서는 법률 전문가 상담을 권장합니다."
    )
```

```python
# apt_legal_agent/roles/responder.py
RESPONDER_ROLE = SubAgentRole(
    name="responder",
    system_prompt=RESPONDER_SYSTEM_PROMPT,
    tool_allowlist=[],
    model_tier="default",
    output_schema=AgentResponse,
    max_iterations=1,
    build_user_message=lambda ctx: (
        f"[사용자 질문]\n{ctx.user_request}\n\n"
        f"[분류]\n{ctx.parent_outputs['classifier'].model_dump_json()}\n\n"
        f"[법령·판례·해석 조회 결과]\n{_format_tool_results(ctx.parent_outputs['tool_results'])}\n\n"
        "위 자료를 바탕으로 사용자 질문에 답변해 주세요."
    ),
)
```

---

## 4. MCP Tool Adapters

6개 MCP tool 각각을 `ToolAdapter`로 wrapping.

```python
# apt_legal_agent/tools/mcp_adapters.py
from minyoung_mah import ToolAdapter, ToolResult
from pydantic import BaseModel, Field

# ── Arg schemas ───────────────────────────────────────────
class SearchLawArgs(BaseModel):
    query: str
    law_name: str | None = None
    max_results: int = 5

class GetLawArticleArgs(BaseModel):
    law_name: str
    article_number: str
    include_history: bool = False

class SearchPrecedentArgs(BaseModel):
    query: str
    court_level: Literal["대법원", "고등법원", "지방법원"] | None = None
    max_results: int = 5

class GetPrecedentDetailArgs(BaseModel):
    case_number: str

class SearchInterpretationArgs(BaseModel):
    query: str
    source: str | None = None
    max_results: int = 5

class CompareLawsArgs(BaseModel):
    comparisons: list[dict]
    focus: str | None = None

# ── Generic wrapper ───────────────────────────────────────
class McpProxyToolAdapter(ToolAdapter):
    def __init__(self, client: "MCPClient", name: str, description: str,
                 arg_schema: type[BaseModel]):
        self.name = name
        self.description = description
        self.arg_schema = arg_schema
        self._client = client

    async def call(self, args: BaseModel) -> ToolResult:
        import time
        start = time.monotonic()
        try:
            result = await self._client.call_tool(self.name, args.model_dump(exclude_none=True))
            return ToolResult(
                ok=True, value=result, error=None,
                duration_ms=int((time.monotonic() - start) * 1000),
                metadata={"via": "mcp", "tool": self.name},
            )
        except Exception as e:
            return ToolResult(
                ok=False, value=None, error=str(e),
                duration_ms=int((time.monotonic() - start) * 1000),
                metadata={"via": "mcp", "tool": self.name},
            )

# ── Factory ───────────────────────────────────────────────
def make_mcp_adapters(client: "MCPClient") -> list[ToolAdapter]:
    return [
        McpProxyToolAdapter(client, "search_law", "키워드 기반 법령 조문 검색", SearchLawArgs),
        McpProxyToolAdapter(client, "get_law_article", "법률 조문 전문 조회", GetLawArticleArgs),
        McpProxyToolAdapter(client, "search_precedent", "판례 검색", SearchPrecedentArgs),
        McpProxyToolAdapter(client, "get_precedent_detail", "판례 상세", GetPrecedentDetailArgs),
        McpProxyToolAdapter(client, "search_interpretation", "행정해석 검색", SearchInterpretationArgs),
        McpProxyToolAdapter(client, "compare_laws", "법령 비교", CompareLawsArgs),
    ]
```

**MCP client** (`apt_legal_agent/tools/mcp_client.py`)는 `httpx` + `mcp` Python SDK 기반의 얇은 wrapper. library 외부.

---

## 5. A2A 레이어

A2A 프로토콜은 **Orchestrator 위에 얹히는 application layer**이다. minyoung-mah는 A2A를 모른다.

### TaskHandler

```python
# apt_legal_agent/a2a/task_handler.py
from minyoung_mah import Orchestrator
from apt_legal_agent.a2a.hitl_channel import A2AHITLChannel
from apt_legal_agent.bootstrap import build_orchestrator

TASKS: dict[str, dict] = {}  # in-memory task state

async def handle_tasks_send(request: dict) -> dict:
    task_id = request["params"]["id"]
    user_text = _extract_user_text(request["params"]["message"])

    TASKS[task_id] = {"state": "working", "artifacts": []}

    try:
        orch = build_orchestrator(hitl=A2AHITLChannel(task_id, sse_emitter=None))
        result = await orch.run_pipeline(build_pipeline(), user_request=user_text)
        response: AgentResponse = result["responder"].output

        TASKS[task_id] = {
            "state": "completed",
            "artifacts": [{
                "parts": [{
                    "type": "text",
                    "text": _render_response(response),
                }]
            }],
        }
    except Exception as e:
        TASKS[task_id] = {"state": "failed", "error": str(e)}

    return {
        "jsonrpc": "2.0",
        "result": {
            "id": task_id,
            "status": {"state": TASKS[task_id]["state"]},
            "artifacts": TASKS[task_id].get("artifacts", []),
        },
    }
```

### A2AHITLChannel (streaming 모드용)

```python
# apt_legal_agent/a2a/hitl_channel.py
from minyoung_mah import HITLChannel, HITLResponse, HITLEvent

class A2AHITLChannel(HITLChannel):
    """HITL for A2A SSE streaming mode.

    Since apt-legal is primarily passive (user asks, agent answers with no
    mid-stream interaction), `ask` is implemented as a no-op that returns
    the first option or a default. `notify` emits SSE events for progress.
    """

    def __init__(self, task_id: str, sse_emitter):
        self._task_id = task_id
        self._sse = sse_emitter

    async def ask(self, question, options, description, context) -> HITLResponse:
        # apt-legal doesn't interrupt mid-flow for clarification.
        # If needed later, we can queue the question and block until user replies.
        if options:
            return HITLResponse(choice=options[0], metadata={"auto": True})
        return HITLResponse(choice="", metadata={"auto": True})

    async def notify(self, event: HITLEvent) -> None:
        if self._sse is None:
            return
        await self._sse.send({
            "event": event.kind,
            "data": event.data,
        })
```

**note**: apt-legal에서는 `ask`가 거의 쓰이지 않을 것이다 (user는 질문하고 답을 받는 단일 턴). 하지만 향후 "법률 자문이 여러 해석 중 하나를 선택해야 할 때" HITL이 필요할 수 있으므로 인터페이스는 남겨둔다.

---

## 6. Composition Root (Bootstrap)

```python
# apt_legal_agent/bootstrap.py
from minyoung_mah import (
    Orchestrator, RoleRegistry, ToolRegistry,
    SingleModelRouter, NullMemoryStore, default_resilience, langfuse_observer,
)
from langchain_openai import ChatOpenAI

from apt_legal_agent.roles.classifier import CLASSIFIER_ROLE
from apt_legal_agent.roles.retrieval_planner import RETRIEVAL_PLANNER_ROLE
from apt_legal_agent.roles.responder import RESPONDER_ROLE
from apt_legal_agent.tools.mcp_client import MCPClient
from apt_legal_agent.tools.mcp_adapters import make_mcp_adapters
from apt_legal_agent.config import get_config

_MCP_CLIENT: MCPClient | None = None

def get_mcp_client() -> MCPClient:
    global _MCP_CLIENT
    if _MCP_CLIENT is None:
        _MCP_CLIENT = MCPClient(get_config().mcp_server_url)
    return _MCP_CLIENT

def build_orchestrator(hitl) -> Orchestrator:
    cfg = get_config()
    roles = RoleRegistry.of(CLASSIFIER_ROLE, RETRIEVAL_PLANNER_ROLE, RESPONDER_ROLE)
    tools = ToolRegistry.of(*make_mcp_adapters(get_mcp_client()))
    return Orchestrator(
        role_registry=roles,
        tool_registry=tools,
        model_router=SingleModelRouter(
            ChatOpenAI(model=cfg.llm_model, api_key=cfg.llm_api_key,
                       temperature=cfg.llm_temperature),
        ),
        memory=NullMemoryStore(),   # 개인정보 저장 금지
        hitl=hitl,
        resilience=default_resilience(),
        observer=langfuse_observer() if cfg.langfuse_enabled else None,
    )
```

---

## 7. 3 데모 시나리오의 pipeline 추적

### 시나리오 1: "층간소음 기준이 몇 데시벨이야?"

```
classifier  → dispute_type=NOISE, intent=LAW_CHECK, confidence=0.95
             keywords=["층간소음", "기준", "데시벨"]

retrieval_planner → ExecutionPlan(steps=[
    { idx=0, tool=search_law, args={query:"층간소음 기준"}, p=1 },
    { idx=1, tool=get_law_article, args={law_name:"공동주택관리법", article_number:"제20조"}, p=2, depends_on=[0] },
])

retrieval_executor → step 0 실행 → 결과 받음 → step 1의 law_name을 결과에서 추출 후 실행
    (depends_on 체이닝은 ExecuteToolsStep이 처리)

responder → AgentResponse(
    answer="공동주택관리법 제20조에 따르면...",
    legal_basis=[{type:"law", reference:"공동주택관리법 제20조", summary:"..."}],
    next_steps=[],
    disclaimer="..."
)
```

**총 LLM call 수**: 3 (classifier, planner, responder)
**총 MCP call 수**: 2
**예상 latency**: 5~8초

### 시나리오 2: "윗집 층간소음 법적 대응 방법?"

```
classifier  → NOISE, DISPUTE_RESOLUTION, 0.9

retrieval_planner → ExecutionPlan(steps=[
    { idx=0, search_law, {query:"층간소음"}, p=1 },
    { idx=1, search_precedent, {query:"층간소음 손해배상"}, p=1 },
    { idx=2, search_interpretation, {query:"층간소음 관리규약"}, p=2 },
    { idx=3, get_precedent_detail, {case_number:<from_0_or_1>}, p=2, depends_on=[1] },
])

retrieval_executor → p=1 2개 병렬 → p=2 2개 (depends_on 처리 후)

responder → 법령 + 판례 + 해석 + 단계별 대응 종합
```

**총 LLM call**: 3, **총 MCP call**: 4, **예상 latency**: 10~15초

### 시나리오 3: "재건축 동의율?"

```
classifier  → RECON, LAW_CHECK, 0.98

retrieval_planner → ExecutionPlan(steps=[
    { idx=0, search_law, {query:"재건축 동의율", law_name:"도시및주거환경정비법"}, p=1 },
    { idx=1, get_law_article, {law_name:"도시및주거환경정비법", article_number:"제35조"}, p=2, depends_on=[0] },
])

responder → 단계별 동의율 안내
```

**총 LLM call**: 3, **총 MCP call**: 2, **예상 latency**: 6~10초

---

## 8. 기존 설계 대비 얻는 것

| 항목 | 이전 (`03_vertical_agent_codex_spec.md`) | minyoung-mah 기반 |
|---|---|---|
| **코드 라인 수** (agent 전체) | ~2500 line 추정 | **~800 line 예상** (라이브러리가 대부분 흡수) |
| **자체 구현 필요** | orchestrator, classifier, planner, responder 4 클래스, retry, timeout, parallel 호출, state machine | **0 infra 코드**. 역할 데이터 + tool adapters + pipeline declaration + A2A layer만 |
| **Observability** | 자체 로깅 | Langfuse trace 자동, `timing.role.invoke` 자동 |
| **재시도/폴백** | hand-written per-call | `default_resilience()` 한 줄 |
| **테스트 작성 비용** | mocking orchestrator + mcp + llm | `roles`는 단순 data, mock 지점 최소 |
| **apt-legal이 minyoung-mah에게 요구** | (none) | `ExecuteToolsStep` 추가 (아래 10.1) |

---

## 9. 배포 구성

`ax-coding-agent`와 다르게 apt-legal은 stateless pod + 단일 LLM이므로 배포가 단순하다.

```yaml
# k8s/deployment.yaml (요약)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: apt-legal-agent
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: agent
        image: apt-legal-agent:1.0.0
        env:
        - name: MCP_SERVER_URL
          value: "http://apt-legal-mcp-svc:8001/mcp"
        - name: LLM_MODEL
          value: "gpt-4o"
        - name: LLM_API_KEY
          valueFrom: { secretKeyRef: { name: llm, key: openai } }
        - name: LANGFUSE_PUBLIC_KEY
          valueFrom: { secretKeyRef: { name: obs, key: langfuse_pk } }
        - name: LANGFUSE_SECRET_KEY
          valueFrom: { secretKeyRef: { name: obs, key: langfuse_sk } }
        - name: MINYOUNG_MAH_OBSERVER
          value: "langfuse"
        ports:
        - containerPort: 8000
        livenessProbe:
          httpGet: { path: /healthz, port: 8000 }
```

`Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -e .
COPY apt_legal_agent ./apt_legal_agent
EXPOSE 8000
CMD ["uvicorn", "apt_legal_agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 10. minyoung-mah에 요구되는 것 (library 쪽에 추가 필요)

이 설계를 돌리려면 library가 다음을 지원해야 한다. 04 open questions로 넘긴다.

1. **`ExecuteToolsStep`** — pipeline step 중 LLM 없이 plan → parallel tool calls만 수행하는 단계. `role=None`에 `fan_out` 대신 explicit step type.
2. **`StaticPipeline`의 `depends_on` 해석** — plan step의 `depends_on` 체이닝을 Orchestrator가 실행할지, ExecuteToolsStep이 자체 해결할지 결정 필요.
3. **`output_schema`가 있는 role의 단일 호출 경로** — `max_iterations=1` + `output_schema`가 함께 있을 때 Orchestrator는 tool-call loop을 건너뛰고 "LLM 1회 → JSON 파싱 → schema validation → 반환" 직결 경로를 가져야 한다. 이게 지금 명확하지 않다.
4. **`HITLChannel.ask`가 호출되지 않는 파이프라인에서도 정상 동작** — 현재 coding은 모든 role이 잠재적으로 ask를 부를 수 있음. apt-legal은 ask가 거의 없음. NullHITL에 가까운 구현이 1급 시민이어야 한다.
5. **`NullMemoryStore`** — 모든 write를 drop, read는 빈 결과 반환. library 기본 제공.
6. **`ResiliencePolicy`의 기본값이 A2A task 60초 제약**과 호환되는지 — 기본 watchdog timeout이 60초를 넘으면 apt-legal은 기본값을 override해야 한다.

---

## 11. 요구사항 대비 체크리스트

| 원본 요구사항 | 새 설계에서 어떻게 충족 |
|---|---|
| 공동주택관리법/집합건물법 등 법령 조회 | `search_law` + `get_law_article` MCP adapter |
| 분쟁 유형 분류 | `CLASSIFIER_ROLE` (structured output) |
| 판례 검색 | `search_precedent` + `get_precedent_detail` |
| 행정해석 검색 | `search_interpretation` |
| 법령 비교 | `compare_laws` (intent=COMPARISON에서 planner가 계획) |
| 면책 문구 | `AgentResponse.disclaimer` (Pydantic default) |
| A2A 연동 | `a2a/task_handler.py` — minyoung-mah 위에 얹힘 |
| MCP Streamable HTTP | `tools/mcp_client.py` |
| gpt-4o 기본 모델 | `SingleModelRouter(ChatOpenAI("gpt-4o"))` |
| EKS 배포 | Dockerfile + k8s yaml |
| 개인정보 비저장 | `NullMemoryStore()` |
| 병렬 MCP 호출 | `ExecuteToolsStep(parallel_within_priority=True)` |
| 부분 실패 허용 | `ExecuteToolsStep(continue_on_failure=True)` + responder가 실패 step 표시 |
| RateLimit 재시도 | `default_resilience()` (`retry_policy` 자동 적용) |
| Observability | `langfuse_observer()` |

---

## 다음 문서로 넘기는 질문

- `ExecuteToolsStep`이 library에 추가되면, coding agent의 delegate tool과 개념이 겹치지 않나? 정리 필요. (→ 04 question)
- `output_schema` + `max_iterations=1` 조합이 일반적인 "LLM structured call" 패턴이라면, 별도 fast path가 필요한가 아니면 일반 루프가 자연스럽게 처리하는가? (→ 04 question)
- apt-legal의 `NullMemoryStore`는 memory extraction도 건너뛰어야 하는데, `MemoryExtractor`가 optional이라는 건 어떻게 표현하는가? (→ 04 question)
- `retrieval_planner`의 분쟁 유형별 기본 호출 세트를 LLM에 예시로 주는 방식 vs 데이터 테이블로 하드코딩하는 방식 — 어느 쪽이 유지보수와 품질 trade-off가 좋은가? (→ 04 question)
- 시나리오 latency (5~15초)는 A2A task 60초 제한 내이지만, p=2 fan_out + depends_on 처리가 직렬화되면 12~15초는 쉽게 넘을 수 있음. watchdog timeout 기본값을 얼마로 잡는가? (→ 04 question)
