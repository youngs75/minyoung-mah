# 02. Coding Agent Mapping — 기존 코드가 6 protocol에 어떻게 들어가는가

**상태**: Draft 1 · 2026-04-13
**대상**: `ax_advanced_coding_ai_agent/coding_agent/` 전체를 `01_core_abstractions.md`의 6 protocol로 매핑한다. 라이브러리(minyoung-mah)와 application(coding_agent)이 어디서 갈라지는지 구체적으로 정한다.

---

## 요약 매핑 표

| 원본 경로 | minyoung-mah 위치 | 비고 |
|---|---|---|
| `coding_agent/core/loop.py` (725 L) | `minyoung_mah/core/orchestrator.py` (library) | **run_loop + invoke_role**의 구현 본체. 일부는 library, 일부는 application |
| `coding_agent/core/orchestrator.py` (84 L) | `examples/coding_agent/entry.py` | "direct vs delegate" 분류기 — **application 진입점 로직** |
| `coding_agent/core/state.py` | `minyoung_mah/core/state.py` | LangGraph state container. **library** |
| `coding_agent/core/tool_adapter.py` | `minyoung_mah/core/tool_bind.py` | 모델별 native/prompt-based tool calling 어댑터. **library** |
| `coding_agent/core/tool_call_utils.py` | `minyoung_mah/core/tool_bind.py` | JSON args 복구 유틸. **library** |
| `coding_agent/subagents/manager.py` | `minyoung_mah/core/subagent_runner.py` | `invoke_role` 내부의 실행 엔진. **library** |
| `coding_agent/subagents/models.py` | `minyoung_mah/core/subagent_runner.py` | SubAgentInstance 상태 머신. **library** |
| `coding_agent/subagents/registry.py` | `minyoung_mah/core/registry.py` | RoleRegistry, ToolRegistry. **library** |
| `coding_agent/subagents/factory.py` (375 L) | **분리**: 상반부 → `examples/coding_agent/roles.py`, 하반부 → `minyoung_mah/core/role_classifier.py` (optional) | `ROLE_TEMPLATES` dict는 **coding-specific**, 역할 분류 로직은 library에 optional로 제공 |
| `coding_agent/tools/file_ops.py` | `examples/coding_agent/tools/file_ops.py` | 순수 coding tool |
| `coding_agent/tools/shell.py` | `examples/coding_agent/tools/shell.py` | 순수 coding tool |
| `coding_agent/tools/todo_tool.py` | `examples/coding_agent/tools/todo_tool.py` | coding workflow tool (TODO list, SPEC ID 의존) |
| `coding_agent/tools/task_tool.py` | `examples/coding_agent/tools/task_tool.py` **+** `minyoung_mah/core/delegate_tool.py` | TASK-NN delegate tool. 이름은 coding이지만 **기저 delegate 메커니즘은 library**. 아래 3.5 참조 |
| `coding_agent/tools/ask_tool.py` | **split**: protocol은 `minyoung_mah/hitl/`, 구현은 `examples/coding_agent/hitl_terminal.py` | HITLChannel의 첫 구현체 |
| `coding_agent/memory/store.py` | `minyoung_mah/memory/sqlite_store.py` (**schema 변경**) | `layer` / `project_id` false-neutral 제거 |
| `coding_agent/memory/schema.py` | `minyoung_mah/memory/schema.py` | `MemoryRecord` 데이터클래스 |
| `coding_agent/memory/extractor.py` | `examples/coding_agent/memory_extractor.py` | LLM 추출 로직, **coding-specific prompts**. library는 hook point만 |
| `coding_agent/memory/middleware.py` | `minyoung_mah/memory/middleware.py` | 맥락 주입 미들웨어. **library** |
| `coding_agent/resilience/watchdog.py` (72 L) | `minyoung_mah/resilience/watchdog.py` | timeout 감시. **library** |
| `coding_agent/resilience/retry_policy.py` (241 L) | `minyoung_mah/resilience/retry_policy.py` | exponential backoff. **library** |
| `coding_agent/resilience/error_handler.py` (233 L) | `minyoung_mah/resilience/error_handler.py` | 7가지 장애 분류. **library** — coding specificity 점검 필요 |
| `coding_agent/resilience/progress_guard.py` (226 L) | **split**: 엔진 → `minyoung_mah/resilience/progress_guard.py`, TASK-NN regex → `examples/coding_agent/task_pattern.py` | 아래 3.4 참조 |
| `coding_agent/resilience/safe_stop.py` | `minyoung_mah/resilience/safe_stop.py` | keyboard interrupt 처리. **library** |
| `coding_agent/cli/` 전체 | `examples/coding_agent/cli/` | Rich/prompt-toolkit UI. **application** |
| `coding_agent/config.py` | **split**: core config → `minyoung_mah/config.py`, LiteLLM/env → `examples/coding_agent/config.py` | 아래 3.6 참조 |
| `coding_agent/models.py` (184 L) | **split**: protocol → `minyoung_mah/core/model_router.py`, tier 정의 → `examples/coding_agent/model_router.py` | 4-tier 자체는 coding-specific. `TieredModelRouter` 일반 구현은 library |
| `coding_agent/logging_config.py` | `minyoung_mah/observer/structlog_config.py` | **library** |
| `coding_agent/utils/langfuse_trace_exporter.py` | `minyoung_mah/observer/langfuse_exporter.py` | **library** (optional extra) |
| `tests/test_memory.py` | `tests/library/test_memory.py` + `tests/application/coding/test_memory_integration.py` | schema 변경 때문에 분리 필요 |
| `tests/test_subagents.py` | `tests/library/test_subagent_runner.py` | 상태 머신 검증 |
| `tests/test_resilience.py` | `tests/library/test_resilience.py` | 대부분 library |
| `tests/test_shell_tool.py` | `tests/application/coding/test_shell_tool.py` | 명백히 application |
| `tests/test_p35_phase3.py` | `tests/application/coding/` | coding workflow |

**총계**: 67개 원본 파일 중 대략 **library 35 / application 27 / split 5**.

---

## 1. `SubAgentRole` 매핑 — `coding_agent/subagents/factory.py`

### 현재 구조

```python
# factory.py
_PLANNER_PROMPT = """...""" + _FORK_RULES
_CODER_PROMPT   = """...""" + _FORK_RULES
# ... 6 roles total

ROLE_TEMPLATES: dict[str, _RoleTemplate] = {
    "planner":    _RoleTemplate(_PLANNER_PROMPT,  [read_file, write_file, ...], "reasoning"),
    "coder":      _RoleTemplate(_CODER_PROMPT,    [read_file, write_file, edit_file, execute, ...], "strong"),
    "reviewer":   _RoleTemplate(_REVIEWER_PROMPT, [read_file, glob_files, grep], "default"),
    "fixer":      _RoleTemplate(_FIXER_PROMPT,    [read_file, edit_file, ...], "strong"),
    "researcher": _RoleTemplate(_RESEARCHER_PROMPT, [read_file, glob_files, grep], "default"),
    "verifier":   _RoleTemplate(_VERIFIER_PROMPT, [read_file, execute, ...], "fast"),
}
```

### 새 구조

```python
# examples/coding_agent/roles.py

from minyoung_mah import SubAgentRole

FORK_RULES = """..."""  # coding-specific output contract

PLANNER = SubAgentRole(
    name="planner",
    system_prompt=PLANNER_PROMPT + FORK_RULES,
    tool_allowlist=["read_file", "write_file", "glob_files", "grep", "ask_user_question", "write_todos"],
    model_tier="reasoning",
    output_schema=None,
    max_iterations=15,
    build_user_message=lambda ctx: f"Task: {ctx.task_summary}\n\nUser request: {ctx.user_request}",
)
# CODER, REVIEWER, FIXER, RESEARCHER, VERIFIER 동일 패턴
```

### 뭐가 library로 올라가는가

- `_RoleTemplate` dataclass → `SubAgentRole` protocol (library)
- `SubAgentFactory.build_system_prompt`의 "tools 이름 injection" 로직 → library (모든 application이 필요)
- `ROLE_TEMPLATES` dict 자체 → **application**. 코딩 workflow에만 맞는 역할 분해이기 때문

### Optional library 기능: role classifier

`_analyze_task` (keyword + LLM fallback)는 **"여러 역할 중 하나 고르기"**라는 general 패턴이다. `minyoung_mah/core/role_classifier.py`에 optional utility로 제공:

```python
class RoleClassifier:
    def __init__(self, roles: list[str], keywords: dict[str, list[str]],
                 llm_fallback: ModelHandle | None = None): ...
    async def classify(self, text: str) -> str: ...
```

coding_agent는 이걸 주입받아 쓴다. apt-legal은 안 쓴다 (dispute type classifier가 별도 SubAgentRole이므로).

### False-neutral 지점

- **`_FORK_RULES`** — "summary 500 words 형식 / Files changed 리스트 / Scope / Result" 같은 출력 규약. 완전히 coding workflow. application으로.
- **"## Language Policy (MANDATORY) 한국어"** — coding agent의 사용자 preference. application으로.
- **`{task_summary}`, `{tools}` placeholder 형식** — 이건 `SubAgentRole.build_user_message`가 흡수한다.

---

## 2. `ToolAdapter` 매핑 — `coding_agent/tools/`

### 파일별 처리

| 파일 | 처리 | 이유 |
|---|---|---|
| `file_ops.py` (273 L) | 전체 application | 파일 시스템 직접 조작, coding-specific |
| `shell.py` (368 L) | 전체 application | bash/subprocess, coding-specific |
| `todo_tool.py` (258 L) | 전체 application | SPEC ID (TASK-NN) 의존, coding workflow |
| `ask_tool.py` (214 L) | **split**: 인터페이스는 library `HITLChannel`, 구현은 application `TerminalHITLChannel` | HITL protocol 참조 |
| `task_tool.py` (273 L) | **split** (아래 3.5 참조) | delegate 메커니즘은 library, TASK-NN 의미는 application |

### `ToolAdapter` protocol로 변환 예 (shell)

```python
# examples/coding_agent/tools/shell.py

from minyoung_mah import ToolAdapter, ToolResult
from pydantic import BaseModel, Field

class ShellArgs(BaseModel):
    command: str = Field(description="bash command to execute")
    timeout_s: int = Field(default=90, description="timeout in seconds")

class ShellToolAdapter(ToolAdapter):
    name = "execute"
    description = "Execute a bash command and return stdout/stderr"
    arg_schema = ShellArgs

    def __init__(self, workspace: Path, default_timeout: int = 90):
        self._workspace = workspace
        self._default_timeout = default_timeout

    async def call(self, args: ShellArgs) -> ToolResult:
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_shell(
                args.command, cwd=self._workspace,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=args.timeout_s or self._default_timeout,
            )
            return ToolResult(
                ok=(proc.returncode == 0),
                value={"stdout": stdout.decode(), "stderr": stderr.decode(),
                       "returncode": proc.returncode},
                error=None if proc.returncode == 0 else f"exit {proc.returncode}",
                duration_ms=int((time.monotonic() - start) * 1000),
                metadata={"command": args.command[:200]},
            )
        except asyncio.TimeoutError:
            return ToolResult(ok=False, value=None, error=f"timeout after {args.timeout_s}s",
                              duration_ms=int((time.monotonic() - start) * 1000),
                              metadata={"command": args.command[:200]})
```

### Library가 tool 호출 loop에서 책임질 것

- LLM 응답에서 tool_calls 추출 (native + prompt-based 폴백) — `core/tool_bind.py`
- ToolRegistry 룩업 + arg schema validation
- `ToolAdapter.call` 실행 + Observer 이벤트 발행
- `ToolResult.ok == False` 시 retry_policy 적용
- Progress guard에 action 기록

이 루프는 library가 owning하므로 application 개발자는 `ToolAdapter.call`만 구현하면 된다.

---

## 3. `Orchestrator` 매핑 — `coding_agent/core/loop.py` (725 L)

### 현재 loop.py가 하는 일

1. LangGraph StateGraph 구축 (`agent_node`, `tool_node`, `summary_node`)
2. SubAgent 생성 + invoke (direct vs delegate 결정 포함)
3. tool_bind 적용 (native/prompt-based)
4. ProgressGuard 호출 + verdict에 따른 분기
5. Watchdog timeout
6. Memory 주입 (middleware)
7. Safe stop 시그널 처리
8. Structlog + Langfuse 이벤트 발행
9. 최종 summary 추출

### 새 구조로의 분해

| loop.py 내부 로직 | 새 위치 | 이유 |
|---|---|---|
| LangGraph StateGraph 구축 | `minyoung_mah/core/orchestrator.py` | library |
| `invoke_role` (한 번의 SubAgent 실행) | `minyoung_mah/core/orchestrator.py` | library의 **원자 단위** |
| `run_loop` (driver role 재호출 루프) | `minyoung_mah/core/orchestrator.py` | library |
| `run_pipeline` (static DAG) | `minyoung_mah/core/orchestrator.py` | library (**신규**) |
| ProgressGuard wiring | library | library |
| Watchdog wiring | library | library |
| Memory middleware 호출 | library | library |
| Safe stop 시그널 | library | library |
| Langfuse observer 이벤트 | library | library |
| direct vs delegate 초기 분류 | `examples/coding_agent/entry.py` | **application 진입점 판단** |
| FORK_RULES가 포함된 final summary parsing | `examples/coding_agent/summary_parser.py` | coding-specific 출력 규약 |

### 현재 orchestrator.py (84 L)는?

단순히 "사용자 입력이 direct 응답이면 LLM 한 번, 아니면 run_loop 호출"하는 **application 진입점**이다. `examples/coding_agent/entry.py`로 옮긴다.

```python
# examples/coding_agent/entry.py
async def handle_user_message(msg: str, orch: Orchestrator, roles: RoleRegistry) -> str:
    if len(msg.strip()) < 20:
        return await direct_chat(msg)
    if not any(kw in msg.lower() for kw in DELEGATE_KEYWORDS):
        return await direct_chat(msg)
    return (await orch.run_loop(
        driver_role="planner",
        user_request=msg,
        stop_when=final_summary_detected,
    )).summary
```

### 3.5 `task_tool.py` (delegate tool) 분해

현재 `task_tool.py`는 "TASK-NN ID를 가진 SubAgent를 생성하는 tool"이다. 두 부분이 섞여 있다:

**library 부분** (`minyoung_mah/core/delegate_tool.py`):
- `DelegateTool` — Orchestrator가 dynamic mode에서 driver role에게 자동 주입하는 tool
- args: `{role: str, task_summary: str, context: dict}`
- 실행: `orchestrator.invoke_role(role, InvocationContext(...))`
- child agent id 생성 / parent-child 관계 관리

**application 부분** (`examples/coding_agent/task_pattern.py`):
- "TASK-NN" ID 형식 규약 (SPEC/PRD에서 task ID 추출)
- DelegateTool의 args에 `task_id` extra field 추가 (subclass)
- Progress guard에 TASK-NN regex 주입

```python
# library
class DelegateTool(ToolAdapter):
    name = "delegate"
    description = "Delegate a subtask to another SubAgent role"
    arg_schema = DelegateArgs  # {role: str, task_summary: str}

    def __init__(self, orchestrator_ref: weakref.ref[Orchestrator]): ...

    async def call(self, args: DelegateArgs) -> ToolResult:
        orch = self._orch_ref()
        result = await orch.invoke_role(
            args.role,
            InvocationContext(task_summary=args.task_summary, ...),
        )
        return ToolResult(ok=result.ok, value=result.summary, ...)
```

```python
# application
class CodingDelegateTool(DelegateTool):
    arg_schema = CodingDelegateArgs  # adds task_id: str | None

    async def call(self, args: CodingDelegateArgs) -> ToolResult:
        # wrap task_summary with task_id prefix for progress guard
        ...
```

### 3.4 ProgressGuard 분해

```python
# library
class ProgressGuard:
    def __init__(self,
                 window_size: int = 10, stall_threshold: int = 3,
                 max_iterations: int = 50,
                 delegate_dedupe: DelegateDedupeConfig | None = None): ...

    def record_action(self, action_key: str) -> GuardVerdict: ...
    def record_delegate(self, target_key: str) -> GuardVerdict: ...  # 별도 window

@dataclass
class DelegateDedupeConfig:
    window_size: int = 12
    repeat_threshold: int = 6
    key_extractor: Callable[[str], str] | None = None  # application이 주입
```

```python
# application
# examples/coding_agent/task_pattern.py
TASK_ID_PATTERN = re.compile(r"\bTASK-\d{2,}\b", re.IGNORECASE)

def task_id_extractor(task_summary: str) -> str:
    m = TASK_ID_PATTERN.search(task_summary)
    return m.group(0) if m else task_summary[:40]

progress_guard = ProgressGuard(
    delegate_dedupe=DelegateDedupeConfig(
        window_size=12, repeat_threshold=6,
        key_extractor=task_id_extractor,
    ),
)
```

---

## 4. `ModelRouter` 매핑 — `coding_agent/models.py`

### 현재 구조

- `TierName = Literal["reasoning", "strong", "default", "fast"]`
- `get_model(tier) → ChatOpenAI` (LiteLLM proxy or direct provider)
- 모델별 tool calling compatibility profile (`_NO_NATIVE_TOOL_CALLING`, `_QUIRKY_TOOL_CALLING`)
- `FALLBACK_ORDER`, `get_fallback_model`
- instance cache by (tier, temperature)

### 분해

| 기능 | 위치 | 이유 |
|---|---|---|
| `ModelRouter` protocol | library | |
| `SingleModelRouter` | library | degenerate case |
| `TieredModelRouter` | library | 일반 n-tier |
| Instance cache | library | optimization, not policy |
| Tool calling compatibility profile | library | **모델에 내재한 quirks이므로 library가 아는 게 합리적** |
| 4-tier 이름 리터럴 (`reasoning/strong/default/fast`) | application | coding agent의 선택 |
| LiteLLM proxy / direct provider 분기 | application | deployment 결정 |
| `FALLBACK_ORDER` policy | application | "reasoning 실패 → strong" 같은 순서는 도메인 판단 |

### 예시

```python
# library
class TieredModelRouter(ModelRouter):
    def __init__(self, tiers: dict[str, BaseChatModel],
                 fallback_order: list[str] | None = None): ...
    def resolve(self, tier: str, role_name: str) -> ModelHandle: ...

# application
# examples/coding_agent/model_router.py
def build_model_router() -> TieredModelRouter:
    return TieredModelRouter(
        tiers={
            "reasoning": _build_chat_openai(cfg.model_tier.reasoning),
            "strong":    _build_chat_openai(cfg.model_tier.strong),
            "default":   _build_chat_openai(cfg.model_tier.default),
            "fast":      _build_chat_openai(cfg.model_tier.fast),
        },
        fallback_order=["reasoning", "strong", "default", "fast"],
    )
```

### Tool calling compatibility를 library가 가지는 이유

`_QUIRKY_TOOL_CALLING = ("glm", "minimax", "nemotron", "qwen")` 같은 지식은 **어느 application이든 쓸 수 있어야** 한다. apt-legal이 나중에 gpt-4o 대신 glm을 시험해보려 할 때, 우리가 이미 알고 있는 quirks를 재발견할 필요가 없다. 이 지식은 library의 `model_compatibility.py`에 둔다.

---

## 5. `MemoryStore` 매핑 — `coding_agent/memory/`

### 현재 구조의 false-neutral 지점

```sql
CREATE TABLE memories (
    id         TEXT PRIMARY KEY,
    layer      TEXT NOT NULL,           -- user/project/domain (**좋음**)
    category   TEXT NOT NULL,           -- coding_style/convention/... (**coding**)
    key        TEXT NOT NULL,
    content    TEXT NOT NULL,
    source     TEXT DEFAULT '',
    project_id TEXT,                    -- **coding-specific** (!)
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(layer, project_id, key)      -- **coding-specific**
);
```

두 가지 문제:
1. **`project_id` 컬럼이 스키마에 박혀 있음** — apt-legal에서 "단지 ID"를 project_id에 억지로 넣을 수도 있지만, 의미 오염이다.
2. **`UNIQUE(layer, project_id, key)` 제약** — project_id가 null인 layer(user)에서 중복 허용되는 의미가 애매.

### 새 스키마 (library)

```sql
CREATE TABLE memories (
    id         TEXT PRIMARY KEY,
    tier       TEXT NOT NULL,           -- application-defined tier name
    category   TEXT NOT NULL,
    key        TEXT NOT NULL,
    content    TEXT NOT NULL,
    source     TEXT DEFAULT '',
    scope      TEXT,                    -- optional scoping (workspace/session/project/tenant id)
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(tier, scope, key)
);
```

변경점:
- `layer` → `tier` (용어 통일)
- `project_id` → `scope` (tier 내부에서 추가 격리가 필요할 때 사용하는 **일반** 필드)
- coding_agent는 `scope=<project_path>`로 쓰면 되고, apt-legal은 `scope=<아파트단지_id>` 혹은 `NULL`로 쓰면 된다.

### Category는 어떻게?

`category`는 **free-form string**이다. application이 자기 도메인에 맞게 정한다. library는 FTS 검색 필드로만 취급하고 의미를 해석하지 않는다. 기존 coding_agent의 "coding_style", "convention" 등은 application 레이어의 constant로 둔다.

### Extractor는 application

`memory/extractor.py`의 LLM 기반 추출 로직은 프롬프트가 "개발 결정 사항", "코드 컨벤션" 등 coding-specific이다. application으로. library는 Orchestrator 완료 시 `memory_extractor: MemoryExtractor | None` hook만 호출한다.

---

## 6. `HITLChannel` 매핑 — `coding_agent/tools/ask_tool.py`

### 현재 구조

`ask_user_question` tool이 prompt-toolkit으로 터미널에 질문을 출력하고 사용자 입력을 기다린다. 옵션 선택 / 자유 텍스트 / description 표시 지원.

### 분해

```python
# library
# minyoung_mah/hitl/protocol.py
class HITLChannel(Protocol):
    async def ask(self, question: str, options: list[str] | None,
                  description: str | None, context: dict) -> HITLResponse: ...
    async def notify(self, event: HITLEvent) -> None: ...

class AskUserQuestionTool(ToolAdapter):
    """Library-provided tool that forwards ask_user_question tool calls
    from LLM to the injected HITLChannel."""
    name = "ask_user_question"
    arg_schema = AskArgs

    def __init__(self, channel: HITLChannel): ...
    async def call(self, args): ...
```

```python
# application
# examples/coding_agent/hitl_terminal.py
class TerminalHITLChannel(HITLChannel):
    """prompt-toolkit 기반 터미널 구현."""
    async def ask(self, ...): ...
    async def notify(self, ...): ...
```

`AskUserQuestionTool`은 library가 제공하지만, 이름(`ask_user_question`), description, arg schema는 coding agent가 선택한 관습을 그대로 차용한다. 다른 application도 이 이름을 쓰고 싶으면 그대로 쓰고, 다른 이름이 좋으면 자체 ToolAdapter로 교체한다.

---

## Resilience 매핑 요약

| 모듈 | library에 포함 | coding 특이성 |
|---|---|---|
| `watchdog.py` | 그대로 | 없음 |
| `retry_policy.py` | 그대로 | 없음 (exponential backoff 일반) |
| `error_handler.py` | 점검 후 포함 | `ErrorCategory` 7종에 coding 가정 있나 확인 필요 — 대부분 generic (TIMEOUT, RATE_LIMIT, AUTH, NETWORK, TOOL_ERROR, PARSE_ERROR, UNKNOWN) |
| `progress_guard.py` | engine만 | TASK-NN regex는 application |
| `safe_stop.py` | 그대로 | 없음 (signal handler) |

---

## Config 분해 (`coding_agent/config.py`)

```python
# library
# minyoung_mah/config.py
class HarnessConfig(BaseSettings):
    # timeouts
    llm_timeout: int = 120
    default_tool_timeout: int = 90
    # progress guard
    pg_window_size: int = 10
    pg_stall_threshold: int = 3
    pg_max_iterations: int = 50
    # observer
    observer_backend: Literal["structlog", "langfuse", "both"] = "structlog"
```

```python
# application
# examples/coding_agent/config.py
class CodingConfig(HarnessConfig):
    # LLM provider
    litellm_proxy_url: str | None
    openrouter_api_key: str | None
    dashscope_api_key: str | None
    # 4-tier model names
    class ModelTier(BaseModel):
        reasoning: str
        strong: str
        default: str
        fast: str
    model_tier: ModelTier
    # coding workspace
    workspace_path: Path
    max_task_delegation_depth: int = 3
```

Application config가 library config를 상속한다. 이건 application이 library의 사용 모드를 결정하는 자연스러운 지점이다.

---

## 최종 파일 이동 계획 (Phase 2 preview)

1. **library 생성** (`minyoung_mah/` 안에서 재배치)
   - `core/` → `core/` (loop → orchestrator, tool_adapter → tool_bind 등 rename)
   - `subagents/` → `core/` 병합 (별도 디렉토리 불필요)
   - `memory/` → `memory/` (schema 변경 포함)
   - `resilience/` → `resilience/` (progress_guard split)
   - `hitl/` **신규**
   - `observer/` **신규**

2. **application 추출** (`examples/coding_agent/` 생성)
   - `roles.py` — SubAgentRole 6개 + FORK_RULES
   - `tools/` — file_ops, shell, todo, task_pattern
   - `hitl_terminal.py`
   - `memory_extractor.py`
   - `model_router.py`
   - `config.py` (CodingConfig)
   - `entry.py` (direct vs delegate 분기)
   - `cli/` (전체 이동)

3. **import 경로 전면 변경**
   - `from coding_agent.xxx` → `from minyoung_mah.xxx` (library) 또는 `from examples.coding_agent.xxx` (application)
   - 예상 변경 파일 수: 60+

4. **tests 분리**
   - `tests/library/` — 순수 protocol/engine 테스트
   - `tests/application/coding/` — 기존 coding agent 회귀

---

## 다음 문서로 넘기는 질문

- `run_loop`의 driver role이 `delegate` tool을 호출할 때, delegate 호출이 **새 SubAgent 인스턴스**를 의미하는가 **기존 인스턴스의 재호출**을 의미하는가? 현재 loop.py 동작은? (→ 04 question)
- `scope` 필드의 semantics를 application에 완전히 맡기면, cross-scope search가 어떻게 작동하는가? coding agent가 "이 memory는 어느 project의 것인가"를 쉽게 필터링할 수 있어야 한다. (→ 04 question)
- `error_handler.py`의 `ErrorCategory` 7종 중 coding 가정이 박힌 게 있는지 실제 파일 읽고 확정 필요. (→ 04 question)
- Memory schema 변경은 **파괴적 migration**이다. 기존 `memory_store/*.db` 파일을 어떻게 하는가? (→ 04 question)
