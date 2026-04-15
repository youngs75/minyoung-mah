# 01. Core Abstractions — minyoung-mah 라이브러리의 모양

**상태**: Draft 1 · 2026-04-13 / 0.1.0 반영 · 2026-04-15
**목적**: minyoung-mah가 외부로 노출할 **6개의 core protocol**을 정의한다. 이 문서가 라이브러리 API surface의 **설계 근거**이고, 모든 구체 구현(coding agent, apt-legal-agent)은 이 protocol을 composition하는 application이 된다.

> **0.1.0 갱신 노트**: 이 문서의 초안은 `Orchestrator.run_loop` + `LoopState` + `LoopResult`를 포함했지만, 첫 실소비자(apt-legal-agent)가 시나리오 1~4 구현 과정에서 필요로 하지 않았고, 빈 shape를 유지하는 비용이 추후 구현하는 비용보다 크다는 판단 하에 **0.1.0에서 전면 삭제**됐습니다. 동적 driver-role loop가 필요한 소비자는 `Orchestrator.invoke_role` 위에서 자기 루프를 직접 조립합니다. `04_open_questions.md`의 A1/A2/A6/K1 항목이 그 결정을 기록합니다.

---

## 설계 원칙 — 5책임만 책임진다

원본 프로젝트(`docs/origin/session-2026-04-12-0005.md`)에서 정립된 Harness 5책임 철학이 이 라이브러리의 경계를 정한다.

1. **Safety** — 권한 경계, 안전 중단, 무한 루프 방지
2. **Detection** — 장애·정체·반복 감지 (ProgressGuard, Watchdog)
3. **Clarity** — 관찰 가능한 로그와 trace
4. **Context** — SubAgent 간 context 전달 규칙
5. **Observation** — Langfuse 통합, timing 계측

라이브러리는 **결과물의 형식을 강제하지 않는다**. 역할 프롬프트, 도구 선택, 산출물 구조, 파이프라인 shape는 모두 **application이 결정**한다.

---

## 왜 6개인가 — 두 도메인 교집합에서 도출

Coding agent와 apt-legal-agent가 **공통으로 필요로 하는 것**만 추려서 6개가 나왔다.

| # | Protocol | 책임 |
|---|---|---|
| 1 | `SubAgentRole` | "이 역할은 무엇을 하는 무엇이다" — 역할 정의 (데이터) |
| 2 | `ToolAdapter` | "이 도구는 어떻게 호출한다" — 외부 세계와의 접점 |
| 3 | `Orchestrator` | "역할들을 어떤 순서로 실행한다" — 파이프라인 실행기 |
| 4 | `ModelRouter` | "이 역할/tier에 어떤 모델을 쓴다" — 모델 선택 |
| 5 | `MemoryStore` | "이 정보를 기억하고 꺼낸다" — 장기 컨텍스트 |
| 6 | `HITLChannel` | "사용자에게 물어보고 응답을 받는다" — 외부 사용자 채널 |

이외의 모든 것(resilience policy, observer, tool registry, role registry)은 이 6개의 **보조 유틸리티** 또는 **opinionated default**로 제공한다.

---

## 1. `SubAgentRole` — 역할 정의 (데이터)

역할은 **실행하는 객체가 아니라 데이터**이다. 실행은 Orchestrator가 한다.

```python
from typing import Protocol, runtime_checkable
from pydantic import BaseModel

@runtime_checkable
class SubAgentRole(Protocol):
    """A role is a declarative bundle that tells the Orchestrator how to
    invoke a SubAgent for a specific purpose."""

    name: str
    """Unique role name within an application. e.g. "planner", "classifier"."""

    system_prompt: str
    """The system prompt. May contain {placeholders} filled by build_user_message."""

    tool_allowlist: list[str]
    """Tool names this role is allowed to call. Looked up in ToolRegistry."""

    model_tier: str
    """Model tier name. Resolved by ModelRouter. Default: "default"."""

    output_schema: type[BaseModel] | None
    """If set, the role must produce structured output matching this schema.
    If None, the role is free-form (text response + optional tool calls)."""

    max_iterations: int
    """Safety limit on tool-call loop iterations within a single invocation.
    Default: 20. The Orchestrator aborts and returns INCOMPLETE if exceeded."""

    def build_user_message(self, invocation: InvocationContext) -> str:
        """Construct the initial user message for this role invocation from
        the context provided by the Orchestrator."""
```

### `InvocationContext` (라이브러리 제공)

```python
@dataclass
class InvocationContext:
    task_summary: str               # what this invocation should accomplish
    parent_outputs: dict[str, Any]  # outputs from prior roles in the pipeline
    shared_state: dict[str, Any]    # application-writable shared state
    user_request: str               # original user request (never mutated)
    memory_snippets: list[str]      # pre-retrieved memory context (optional)
```

### 설계 결정

- **역할 = 데이터**: 역할이 active object가 되면 상속과 override로 복잡해진다. dataclass/Pydantic 모델처럼 순수 데이터로 두면 application이 자유롭게 정의하고, 라이브러리는 실행만 맡는다.
- **`tool_allowlist`는 이름 목록**: 도구 자체가 아니라 이름 참조. 같은 이름의 도구를 Dev/Prod에서 다르게 주입할 수 있다.
- **`output_schema` optional**: free-form(코딩 planner/coder)과 structured(classifier/responder) 양쪽 지원.
- **`max_iterations`는 역할 단위**: 전역이 아니라 역할별로. classifier는 1회, coder는 20회처럼 다르게 줄 수 있다.

### 두 도메인 예시

```python
# Coding agent
PlannerRole = SimpleNamespace(
    name="planner",
    system_prompt=PLANNER_PROMPT,  # 기존 factory.py의 _PLANNER_PROMPT
    tool_allowlist=["write_file", "read_file", "ask_user_question", "write_todos"],
    model_tier="reasoning",
    output_schema=None,
    max_iterations=15,
    build_user_message=lambda ctx: f"Task: {ctx.task_summary}\nUser request: {ctx.user_request}",
)

# apt-legal
ClassifierRole = SimpleNamespace(
    name="classifier",
    system_prompt=CLASSIFIER_SYSTEM_PROMPT,
    tool_allowlist=[],  # no tools, pure structured output
    model_tier="default",
    output_schema=DisputeClassification,  # Pydantic model
    max_iterations=1,  # single LLM call
    build_user_message=lambda ctx: ctx.user_request,
)
```

---

## 2. `ToolAdapter` — 외부 세계 접점

모든 도구 호출은 이 protocol로 통합된다. 내부 구현(file_ops)이든 외부 프록시(MCP client)든 동일.

```python
@runtime_checkable
class ToolAdapter(Protocol):
    name: str
    description: str
    arg_schema: type[BaseModel]

    async def call(self, args: BaseModel) -> ToolResult:
        ...


@dataclass
class ToolResult:
    ok: bool
    value: Any           # structured result or raw text
    error: str | None    # set when ok=False
    duration_ms: int
    metadata: dict[str, Any]  # for observer (e.g., cache_hit, retry_count)
```

### 설계 결정

- **`arg_schema`는 Pydantic 모델**: 라이브러리가 JSON schema를 자동 생성해서 LLM에 전달할 수 있도록.
- **`call`은 async**: 병렬 호출(apt-legal의 `asyncio.gather`)과 장시간 실행(coding의 shell/pytest) 양쪽 지원.
- **`ToolResult`에 `error` 필드**: 예외를 raise하지 않고 구조화된 실패를 반환. resilience layer가 retry/escalation 판단에 사용.
- **`metadata`는 확장 지점**: cache_hit, 원격 trace id, token usage 등 observer가 수집할 것들.

### Adapter 예시

```python
# Coding: 내부 실행
class ShellToolAdapter:
    name = "shell"
    description = "Execute a shell command"
    arg_schema = ShellArgs

    async def call(self, args: ShellArgs) -> ToolResult:
        proc = await asyncio.create_subprocess_shell(...)
        ...


# apt-legal: MCP proxy
class McpProxyToolAdapter:
    def __init__(self, client: McpClient, tool_name: str, description: str, schema: type[BaseModel]):
        self.name = tool_name
        self.description = description
        self.arg_schema = schema
        self._client = client

    async def call(self, args: BaseModel) -> ToolResult:
        start = time.monotonic()
        try:
            result = await self._client.call_tool(self.name, args.model_dump())
            return ToolResult(ok=True, value=result, error=None,
                              duration_ms=int((time.monotonic()-start)*1000),
                              metadata={"via": "mcp"})
        except McpError as e:
            return ToolResult(ok=False, value=None, error=str(e),
                              duration_ms=int((time.monotonic()-start)*1000),
                              metadata={})
```

### `ToolRegistry` (라이브러리 제공)

```python
class ToolRegistry:
    def register(self, adapter: ToolAdapter) -> None: ...
    def get(self, name: str) -> ToolAdapter: ...
    def filter(self, allowlist: list[str]) -> list[ToolAdapter]: ...
```

---

## 3. `Orchestrator` — 파이프라인 실행기

**핵심**: static mode와 dynamic mode를 **같은 Orchestrator 안에서** 모두 지원한다. 두 모드는 "누가 다음 역할을 결정하는가"의 차이일 뿐이다.

```python
class Orchestrator:
    def __init__(
        self,
        role_registry: RoleRegistry,
        tool_registry: ToolRegistry,
        model_router: ModelRouter,
        memory: MemoryStore,
        hitl: HITLChannel,
        resilience: ResiliencePolicy,
        observer: Observer,
    ): ...

    # ─── Static mode ─────────────────────────────────────────
    async def run_pipeline(
        self,
        pipeline: StaticPipeline,
        user_request: str,
    ) -> PipelineResult:
        """Execute a fixed DAG of roles. Edges are conditional on role output."""

    # ─── Primitive (run_pipeline 내부에서 사용; 소비자가 직접 조립하는
    #     dynamic driver-role loop의 단위이기도 함) ─────────────
    async def invoke_role(
        self,
        role_name: str,
        invocation: InvocationContext,
    ) -> RoleInvocationResult:
        """Invoke one role and return its output."""
```

> **Note (0.1.0 scope)**: 초안에는 `run_loop(driver_role, stop_when, ...)`이 있었지만, 첫 실소비자(apt-legal-agent) 경험에서 필요 없다는 것이 확인되어 **0.1.0에서 전면 삭제**했습니다. 동적 driver-role loop가 필요한 소비자는 `invoke_role` 위에서 자기 loop를 직접 조립하고, 필요하면 `default_resilience(enable_progress_guard=True)`로 `ProgressGuard`를 활성화합니다. 배경: 이전 초안의 `run_loop` shape는 코딩 에이전트 이식 때 거의 확실히 재설계가 필요한 부채였고, 빈 껍데기를 유지하는 비용이 나중에 구현하는 비용보다 컸습니다.

### `StaticPipeline` (static mode 전용)

```python
@dataclass
class PipelineStep:
    role: str
    input_mapping: Callable[[PipelineState], InvocationContext]
    condition: Callable[[PipelineState], bool] | None  # skip if False
    fan_out: Callable[[PipelineState], list[InvocationContext]] | None
    # if fan_out is set, the role is invoked N times in parallel

@dataclass
class StaticPipeline:
    steps: list[PipelineStep]
    on_step_failure: Literal["abort", "continue", "escalate_hitl"] = "abort"
```

### 설계 결정

- **`invoke_role`이 원자 단위**: static/dynamic 둘 다 이 메서드를 조립한다. Resilience/observer hook도 이 한 곳에만 붙이면 된다.
- **Static의 edge는 코드(함수)**: YAML/JSON DSL을 만들지 않는다. 조건이 복잡해지면 DSL이 무너진다. Python 함수가 가장 유연하고 타입 안전.
- **Dynamic mode의 driver는 일반 role**: 특수 역할이 아니라 "delegate tool을 쓸 수 있는 role". 즉 Orchestrator는 driver role에게 `delegate(role_name, task_summary)` tool을 자동으로 제공한다.
- **`fan_out`은 apt-legal의 priority-based parallel tool call**을 수용. planner가 3개의 search_law 호출을 만들면 같은 role을 3번 병렬 invoke.

### 사용 예 (0.1.0)

```python
# apt-legal (static, 실소비자 패턴)
pipeline = StaticPipeline(
    shared_state={"complex_id": complex_id},  # 모든 step의 InvocationContext에 자동 merge
    steps=[
        PipelineStep(
            name="route",
            role="router",
            input_mapping=lambda state: InvocationContext(
                task_summary="질의 라우팅", user_request=""
            ),
        ),
        PipelineStep(
            name="legal_lookup",
            role="legal_lookup",
            condition=lambda state: bool(
                (d := state["route"].payload_as(RouterDecision)) and d.need_legal
            ),
            input_mapping=lambda state: InvocationContext(
                task_summary="국가 법령 조회", user_request=""
            ),
        ),
        PipelineStep(
            name="synthesize",
            role="synthesizer",
            input_mapping=lambda state: InvocationContext(
                task_summary="최종 답변", user_request="", parent_outputs=state
            ),
        ),
    ],
)
result = await orch.run_pipeline(pipeline, user_request=user_input)

# Synthesizer의 build_user_message 안에서 상태 배너와 함께 읽기
for step_name, step_result in (ctx.parent_outputs or {}).items():
    if isinstance(step_result, PipelineStepResult):
        block = step_result.format_for_llm()  # INCOMPLETE 상태는 배너로 surface
        if block:
            parts.append(f"\n[{step_name}]\n{block}")
```

동적 driver-role loop가 필요하면 소비자가 `invoke_role`을 자기 while 루프에서 호출하고 stop 조건을 직접 평가합니다. Library는 `ProgressGuard` / `ResiliencePolicy`만 제공합니다.

---

## 4. `ModelRouter` — 모델 선택

```python
@runtime_checkable
class ModelRouter(Protocol):
    def resolve(self, tier: str, role_name: str) -> ModelHandle:
        """Return a LangChain-compatible chat model for the given tier/role.
        The router may consider both tier and role name for special cases."""
```

### 설계 결정

- **Tier는 string**: enum이 아니라. Application이 tier 이름을 자유롭게 정한다. ax-coding은 `reasoning/strong/default/fast`, apt-legal은 `default` 하나만.
- **Degenerate case(단일 모델) 지원**: `SingleModelRouter(model)`를 라이브러리가 기본 제공.
- **`role_name`도 받음**: "classifier role은 gpt-4o-mini로, 나머지는 gpt-4o로" 같은 우회 override를 가능하게.

```python
# 라이브러리 제공 기본 구현들
class SingleModelRouter(ModelRouter):
    def __init__(self, model: BaseChatModel): ...

class TieredModelRouter(ModelRouter):
    def __init__(self, tiers: dict[str, BaseChatModel]): ...
```

---

## 5. `MemoryStore` — 장기 컨텍스트

**중요**: 3계층(user/project/domain)을 강제하지 않는다. Tier는 application이 정한다.

```python
@runtime_checkable
class MemoryStore(Protocol):
    async def write(self, tier: str, key: str, value: str, metadata: dict) -> None: ...
    async def read(self, tier: str, key: str) -> MemoryEntry | None: ...
    async def search(self, tier: str, query: str, limit: int = 5) -> list[MemoryEntry]: ...
    async def list_tiers(self) -> list[str]: ...

@dataclass
class MemoryEntry:
    tier: str
    key: str
    value: str
    metadata: dict
    created_at: datetime
    updated_at: datetime
```

### 설계 결정

- **Tier는 런타임 dict**: 생성 시 `tiers=["user", "scope", "domain"]` 또는 `tiers=["session", "knowledge"]`처럼 자유롭게 선언.
- **Extractor는 별개 protocol** (`MemoryExtractor`, optional): 어떤 대화에서 무엇을 memory로 추출할지는 application 결정. 라이브러리는 hook point만 제공하고 default extractor는 **제공하지 않는다**(privacy 민감 app이 우회하기 쉽도록).
- **SQLite+FTS5 기본 구현 포함**: `SqliteMemoryStore`를 opinionated default로 제공.

```python
# Coding agent
memory = SqliteMemoryStore(path="memory.db", tiers=["user", "project", "domain"])

# apt-legal (개인정보 저장 금지)
memory = NullMemoryStore()  # 라이브러리 제공, 모든 write를 drop
# 또는
memory = SqliteMemoryStore(path="memory.db", tiers=["domain"])  # 법률 용어만
```

---

## 6. `HITLChannel` — 사용자 응답 채널

```python
@runtime_checkable
class HITLChannel(Protocol):
    async def ask(
        self,
        question: str,
        options: list[str] | None,
        description: str | None,
        context: dict[str, Any],
    ) -> HITLResponse:
        """Ask the user a question and wait for their response.
        The channel is responsible for presenting the question and collecting
        the response however it wants (terminal prompt, SSE stream, webhook, ...)"""

    async def notify(self, event: HITLEvent) -> None:
        """Push a non-blocking status update to the user.
        Channels may no-op this."""

@dataclass
class HITLResponse:
    choice: str                 # user's selected option or free text
    metadata: dict[str, Any]    # e.g. latency, channel-specific info

@dataclass
class HITLEvent:
    kind: Literal["role_start", "role_end", "tool_call", "progress", "error"]
    data: dict[str, Any]
```

### 설계 결정

- **`ask`는 blocking async**: channel 구현체가 어떻게 blocking하는지는 자유(Queue, asyncio.Event, HTTP long-polling, SSE await).
- **`notify`는 non-blocking**: 중간 상태 push. terminal channel은 로그 출력, SSE channel은 이벤트 emit.
- **라이브러리 제공 기본 구현**: `TerminalHITLChannel`, `NullHITLChannel`(모든 ask에 default 응답), `QueueHITLChannel`(외부에서 응답 주입).

```python
# Coding
hitl = TerminalHITLChannel()

# apt-legal (A2A SSE)
hitl = A2AHITLChannel(task_id=task_id, sse_emitter=emitter)
# — apt-legal의 A2A task_handler가 이 channel을 생성하고 Orchestrator에 주입
```

---

## 보조 컴포넌트 (core 밖, but 라이브러리 제공)

| 컴포넌트 | 역할 | 주입 위치 |
|---|---|---|
| `RoleRegistry` | 역할 이름 → SubAgentRole 매핑 | Orchestrator 생성자 |
| `ToolRegistry` | 이름 → ToolAdapter | Orchestrator 생성자 |
| `ResiliencePolicy` | watchdog/retry/progress_guard/safe_stop 묶음 | Orchestrator 생성자 |
| `Observer` | Langfuse trace, timing logs | Orchestrator 생성자 |
| `MemoryExtractor` (optional) | 대화에서 memory 추출 hook | Orchestrator.run_* 완료 후 호출 |

모두 **protocol로 정의**되고, 라이브러리가 **opinionated default 구현**을 함께 제공한다 (SQLite Memory, Structlog Observer, Langfuse Observer, default Resilience).

---

## 라이브러리 composition 예

### Coding agent (가상 — dynamic driver-role loop)

Library가 `run_loop`을 더 이상 제공하지 않으므로, 코딩 에이전트 같은 동적 topology는 소비자가 `invoke_role`을 자기 while 루프로 감싸는 형태가 됩니다.

```python
from minyoung_mah import Orchestrator, SqliteMemoryStore, TieredModelRouter, \
    TerminalHITLChannel, default_resilience, StructlogObserver, InvocationContext

orch = Orchestrator(
    role_registry=role_reg,
    tool_registry=tool_reg,
    model_router=TieredModelRouter({"reasoning": qwen3_max, "default": qwen3_coder_plus}),
    memory=SqliteMemoryStore("memory.db"),
    hitl=TerminalHITLChannel(),
    # 동적 loop에서는 ProgressGuard 활성화 권장 — 반복 탐지는 library가 제공
    resilience=default_resilience(enable_progress_guard=True),
    observer=StructlogObserver(),
)

ctx = InvocationContext(task_summary="implement feature X", user_request=user_input)
while True:
    result = await orch.invoke_role("planner", ctx)
    if final_summary_detected(result):
        break
    ctx = next_context_from(result)
```

### apt-legal-agent (실소비자 — static pipeline)

실제로 동작하는 패턴은 [`examples/apt_legal_minimal.py`](../../examples/apt_legal_minimal.py)에 단일 파일로 박제되어 있습니다. 요약:

```python
from minyoung_mah import (
    Orchestrator, NullMemoryStore, SingleModelRouter,
    StaticPipeline, PipelineStep, InvocationContext,
    StructlogObserver, default_resilience,
)

pipeline = StaticPipeline(
    shared_state={"complex_id": complex_id},  # 모든 step에 자동 merge
    steps=[
        PipelineStep(
            name="route",
            role="router",
            input_mapping=lambda s: InvocationContext(task_summary="라우팅", user_request=""),
        ),
        PipelineStep(
            name="legal_lookup",
            role="legal_lookup",
            condition=lambda s: bool(
                (d := s["route"].payload_as(RouterDecision)) and d.need_legal
            ),
            input_mapping=lambda s: InvocationContext(task_summary="법령 조회", user_request=""),
        ),
        PipelineStep(
            name="synthesize",
            role="synthesizer",
            input_mapping=lambda s: InvocationContext(
                task_summary="합성", user_request="", parent_outputs=s
            ),
        ),
    ],
)

orch = Orchestrator(
    role_registry=role_reg,
    tool_registry=tool_reg,  # MCP tool adapters
    model_router=SingleModelRouter(chat_litellm),
    memory=NullMemoryStore(),
    observer=StructlogObserver(),
    resilience=default_resilience(
        role_timeouts={"router": 30, "legal_lookup": 300, "synthesizer": 120},
    ),
)
result = await orch.run_pipeline(pipeline, user_request=user_request)
```

---

## 의도적으로 배제한 것들

라이브러리 경계를 흐리지 않기 위해 **일부러 넣지 않은** 것들이다.

1. **Agent Card / A2A protocol** — apt-legal application layer. 라이브러리는 orchestration만.
2. **MCP server/client 구현** — tool adapter 안쪽의 세부. 라이브러리는 ToolAdapter protocol만.
3. **분쟁 유형 분류 규칙** — apt-legal 도메인 지식. 라이브러리는 역할 실행만.
4. **Conventional Commits, PRD/SPEC 템플릿** — coding 도메인 지식. 라이브러리는 역할 실행만.
5. **CLI(Rich + prompt-toolkit)** — coding app의 UI. 라이브러리는 HITLChannel protocol만.
6. **LLM provider 선택 로직** — application 책임. 라이브러리는 ModelRouter protocol만.
7. **Token/cost tracking** — Observer가 할 일이지만 **기본 Observer에는 넣지 않는다**. 필요한 app이 custom Observer로 확장.

---

## Open questions (→ 04_open_questions.md)

이 sketch에서 확신이 부족한 지점들을 04_open_questions.md로 넘긴다:

1. **Dynamic mode의 `delegate` tool** — 라이브러리가 자동 제공하는 tool이어야 하나, 아니면 application이 수동 등록하는 tool이어야 하나?
2. **Memory extractor의 timing** — `run_pipeline` **완료 후** 한 번? 중간 단계마다? Extractor 자체가 LLM을 쓴다면 HITLChannel을 쓸 권한이 있나?
3. **`InvocationContext.shared_state`의 동시성** — static mode의 fan_out에서 여러 role이 동시에 write하면? 락? merge function?
4. **`ToolResult.value`의 타입** — `Any`로 두면 LLM에 전달할 때 직렬화 책임이 애매. 라이브러리가 `str` 또는 `BaseModel`로 좁혀야 하나?
5. **Role의 `output_schema`와 free-form 전환** — structured output을 요구하는 role이 tool_call도 할 수 있어야 하나? 두 개를 섞으면 LLM이 혼란.
6. **Static pipeline에서 HITL interrupt** — 파이프라인 중간에 user가 HITL을 통해 상태 변경을 요구하면? 파이프라인은 resume 가능해야 하나?
7. **Resilience가 role-level인가 tool-level인가** — retry를 role이 받나, tool이 받나, 둘 다?
8. **Observer event schema 표준화** — Langfuse 외 다른 backend(OpenTelemetry, custom)를 꽂기 쉽게 하려면 이벤트 스키마가 standardize되어야 함.

---

## 다음 단계

- `02_coding_agent_mapping.md`: 기존 `coding_agent/` 코드가 위 6 protocol에 어떻게 들어가는지 매핑
- `03_apt_legal_mapping.md`: apt-legal-agent를 위 6 protocol 위에 처음부터 설계
- `04_open_questions.md`: 위 open questions + 매핑 과정에서 발견될 추가 질문
