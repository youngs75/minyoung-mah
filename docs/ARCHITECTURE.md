# minyoung-mah Architecture

이 문서는 minyoung-mah 라이브러리의 **전체 그림**을 한 곳에 엮습니다. 각 컴포넌트의 상세 규칙은 해당 디렉토리의 `AGENTS.md`를, 프로토콜 시그니처의 근거는 `docs/design/01_core_abstractions.md`를 참조하세요.

## 1. 라이브러리란 무엇인가

minyoung-mah는 **multi-agent harness의 5책임만 지는 라이브러리**입니다:

1. **Safety** — 권한 경계, 안전 중단, 무한 루프 방지
2. **Detection** — 장애·정체·반복 감지
3. **Clarity** — 관찰 가능한 로그와 trace (canonical observer events)
4. **Context** — SubAgent 간 context 전달 규칙 (`InvocationContext`)
5. **Observation** — timing 계측 + observer hook 포인트

그 외 모든 것(역할 프롬프트, 도구 선택, 산출물 형식, 모델 tier 정의, 도메인 분류)은 **소비자가 결정**합니다. 이 경계는 원본 프로젝트(`ax_advanced_coding_ai_agent`)의 7~9차 E2E 실증으로 정립되었고, `docs/origin/`에 서사가 박제되어 있습니다.

## 2. 6 Core Protocols

라이브러리의 퍼블릭 API 표면. `minyoung_mah/core/protocols.py`에 정의됩니다.

| # | Protocol | 책임 | 기본 구현 |
|---|---|---|---|
| 1 | `SubAgentRole` | 역할의 데이터 정의 (이름, system prompt, tool allowlist, model tier, output schema, max iterations, `build_user_message`) | 소비자가 dataclass로 선언 — 라이브러리는 기본 구현을 제공하지 않음 |
| 2 | `ToolAdapter` | 도구 호출 계약 (name, description, `arg_schema`, `async call`) | 소비자가 구현 — MCP, HTTP, shell 등 |
| 3 | `Orchestrator` | 역할을 조립·실행 (`run_pipeline`, `invoke_role`, `run_loop`) | `minyoung_mah.core.orchestrator.Orchestrator` |
| 4 | `ModelRouter` | `(tier, role_name) → ModelHandle` 해결 | `SingleModelRouter`, `TieredModelRouter` |
| 5 | `MemoryStore` | async tier/scope 기반 메모리 저장·검색 | `SqliteMemoryStore`, `NullMemoryStore` |
| 6 | `HITLChannel` | 사용자 질의·응답 브리지 (`ask`, `notify`) | `NullHITLChannel`, `TerminalHITLChannel`, `QueueHITLChannel` |
| (+) | `Observer` | canonical 이벤트 수신 (`emit`) — 엄밀히는 7번째 | `NullObserver`, `CollectingObserver`, `StructlogObserver`, `CompositeObserver` |

**Observer는 의미상 7번째 프로토콜**이지만, 5책임의 "Observation"과 구분하기 위해 관례적으로 "6 protocols + Observer"라고 부릅니다. `MemoryExtractor`는 선택적 애플리케이션 훅이며 기본 구현을 제공하지 않습니다(privacy opt-in).

## 3. Orchestrator 실행 경로

```
run_pipeline(StaticPipeline, user_request)
    │
    ├── for each PipelineStep | ExecuteToolsStep in pipeline.steps:
    │     │
    │     ├── PipelineStep:
    │     │     ├── condition(state) → skip?
    │     │     ├── fan_out(state) → [InvocationContext, …]  (병렬)
    │     │     │     └─ 또는 input_mapping(state) → InvocationContext  (단일)
    │     │     └── for each context: invoke_role(role, context)
    │     │                             │
    │     │                             ├── fast path: role.output_schema + max_iterations=1 + no tools
    │     │                             │     └── model.with_structured_output(schema).ainvoke()
    │     │                             └── general path: tool-calling loop
    │     │                                   ├── model.bind_tools(…).ainvoke(messages)
    │     │                                   ├── tool_calls 있으면 ToolInvocationEngine.call_one
    │     │                                   │     └── tool-level retry (TRANSIENT_ERRORS만)
    │     │                                   └── 없으면 COMPLETED, iteration 상한 초과면 INCOMPLETE
    │     │
    │     └── ExecuteToolsStep (LLM 없는 병렬 디스패치):
    │           ├── tool_calls_from(state) → [(ToolCallRequest, priority), …]
    │           └── 우선순위 그룹별 순차, 그룹 내 병렬 실행
    │
    ├── step 실패 시: pipeline.on_step_failure ∈ {"abort", "continue", "escalate_hitl"}
    └── 완료 후: memory_extractor?.extract(user_request, result, memory)
```

모든 경계에서 watchdog timeout(`ResiliencePolicy.timeout_for(role)`)이 `asyncio.wait_for`로 강제됩니다. 모든 경계에서 canonical observer event가 emit됩니다.

## 4. 데이터 흐름

```
InvocationContext                    RoleInvocationResult
  task_summary        ──────▶ role ──────▶  status (COMPLETED/INCOMPLETE/FAILED/ABORTED)
  user_request                               output (str | BaseModel | dict | None)
  parent_outputs                             tool_calls / tool_results
  shared_state                               iterations / duration_ms / error
  memory_snippets
  metadata

PipelineState = dict[step_name → PipelineStepResult]
  PipelineStepResult
    step_name / role_name
    outputs: list[RoleInvocationResult]   (fan_out이면 N개)
    tool_results: list[ToolResult]         (ExecuteToolsStep 전용)
    skipped
```

`PipelineState`는 누적되며 뒤 step만 앞 step의 출력을 읽습니다. 뒤 step이 앞 state를 **수정**하는 경로는 없습니다 (단방향).

## 5. Canonical Observer Events

`minyoung_mah/observer/events.py::EVENT_NAMES`에 동결되어 있는 어휘. 스키마는 `orchestrator.<subject>.<action>`.

| 이벤트 | 언제 |
|---|---|
| `orchestrator.run.start` / `.end` | `run_pipeline` 시작/종료 |
| `orchestrator.pipeline.step.start` / `.end` | 각 step 진입/종료 (skipped/fan_out 메타 포함) |
| `orchestrator.role.invoke.start` / `.end` | 개별 `invoke_role` 경계 |
| `orchestrator.tool.call.start` / `.end` | `ToolInvocationEngine`이 발행 |
| `orchestrator.hitl.ask` / `.respond` | HITL 경계 |
| `orchestrator.memory.read` / `.write` | 메모리 경계 |
| `orchestrator.resilience.retry` / `.escalate` | tool-level retry, resilience escalation |

Payload는 공통 필드(`role`, `tool`, `duration_ms`, `ok`) + 자유 형식 `metadata`. 직렬화 가능해야 합니다.

이벤트 추가·제거는 4곳을 함께 움직여야 합니다: `EVENT_NAMES` / emit 코드 / 이 표 / 테스트(`test_observer_events.py`).

## 6. Observability 층 분할 (LiteLLM 뒷단 Langfuse)

라이브러리가 직접 Langfuse SDK에 의존하지 않습니다. 관찰성은 두 층으로 나뉩니다:

| 층 | 담당 | 어디서 구성 |
|---|---|---|
| **LLM-level** (프롬프트, 토큰, 응답) | LiteLLM의 `success_callback = ["langfuse"]` | 소비자 bootstrap 코드 |
| **Orchestration-level** (역할/step/툴 경계) | minyoung-mah `Observer` 프로토콜 | 소비자가 원하는 백엔드 연결 |

공통 `trace_id`로 Langfuse 쪽에서 두 층이 연결됩니다. 소비자가 orchestration 이벤트도 Langfuse로 보내고 싶다면 자기 리포에서 `LangfuseOrchestrationObserver`를 구현해 `Observer` 프로토콜을 만족시키면 됩니다 — 라이브러리는 훅 지점만 제공합니다.

라이브러리가 Langfuse SDK에 의존하지 않는 이유 3가지:

1. **중복 책임 회피** — LiteLLM이 이미 LLM-level을 담당.
2. **의존성 경계** — runtime deps는 `pydantic` + `structlog`만 유지.
3. **Observer 순수성** — `Observer` 프로토콜은 벤더 중립을 유지해야 함.

자세한 서술: `docs/design/05_reference_topologies.md` §2.

## 7. 두 Retry 레이어

에러 처리는 의도적으로 두 층으로 분리됩니다(decision C2, 8차 세션 근거).

| 레이어 | 위치 | 대상 | 결정자 |
|---|---|---|---|
| **tool-level** | `core/tool_invocation.py::ToolRetryPolicy` | 전이 오류만 (`TIMEOUT`, `RATE_LIMIT`, `NETWORK`) | 자동 exponential backoff |
| **role-level** | `resilience/policy.py::role_max_retries` | semantic 실패 (역할 판단) | 역할이 재호출; 정책은 상한만 |

두 층을 섞으면 "네트워크 오류인데 역할 로직이 다시 돌면서 프롬프트가 오염되는" 클래스의 버그가 재발합니다. tool-level에서 이미 처리된 오류를 role-level로 끌어올리지 마세요.

`ErrorCategory`의 `AUTH`는 즉시 surface됩니다 (retry로 고칠 수 없음). `TOOL_ERROR`, `PARSE_ERROR`는 LLM에게 전달되어 역할이 판단합니다.

## 8. Fast path vs General path

`Orchestrator._invoke_inner`가 분기합니다:

- **Fast path** (`_invoke_structured`): `role.output_schema is not None` AND `role.max_iterations == 1` AND `not role.tool_allowlist` → `model.with_structured_output(schema).ainvoke()` 한 번. 툴 루프 없음, 가장 빠름.
- **General path** (`_invoke_loop`): 그 외 — `bind_tools`로 툴 바인딩, iteration 루프, 각 AIMessage의 `tool_calls` 실행, 결과를 `ToolMessage`로 메시지 히스토리에 축적, 빈 `tool_calls`가 나오면 COMPLETED.

구조화된 classifier·summarizer 같은 역할은 fast path로, 실제 도구 사용이 필요한 분석·코딩 역할은 general path로 자연히 갈립니다.

## 9. 무엇이 라이브러리가 아닌가

- ❌ 역할 정의 (prompt, output schema 선언) — 소비자가 합니다.
- ❌ 툴 구현 (MCP 서버, HTTP 클라이언트) — 소비자가 합니다.
- ❌ 모델 구성 (API key, base URL, provider 선택) — 소비자가 합니다.
- ❌ FastAPI / A2A / SSE 전달 계층 — 소비자가 합니다.
- ❌ 도메인 분류, 법령 parsing, 코드 생성 프롬프트 — 소비자가 합니다.
- ❌ `run_loop` (dynamic driver-role loop) — Phase 4로 연기. 현재 `NotImplementedError`.
- ❌ Langfuse SDK import — LiteLLM 뒷단에서 소비자가 구성.
- ❌ `MemoryExtractor` 기본 구현 — privacy opt-in.

라이브러리에 추가하고 싶은 것이 이 목록 중 하나라면 멈추고 소비자 리포로 가야 합니다.

## 10. 참고 패턴 (강제 아님)

`docs/design/05_reference_topologies.md`는 **참고용 박제**이지 구현 강제가 아닙니다. Deep Insight 3-tier router(nano/mini/standard/max)나 streaming event queue 같은 패턴이 필요한 소비자가 생기면 자기 리포에서 이 문서를 참고하여 조립합니다. 라이브러리 경계 안에 흡수할 만큼 일반화된 것이 보이면 그때 여기로 옮겨 옵니다.

## 11. Phase 상태

- Phase 1 — Bootstrap & Design Sketch ✅
- Phase 2a — Library 뼈대 구축 ✅ (6 protocol + `ExecuteToolsStep` + 33 tests)
- 경계 재정의 ✅ (2026-04-15) — co-design 산출물을 `archive/`로 이동
- Phase 2b — 제자리 클린업 ✅ (2026-04-15) — broken 사본 모듈 전부 제거, 의존성 11→2개
- Phase 2c — 선택적 확장 ⏸️ 소비자 요구 시 (`run_loop`, `QueueObserver`, `Orchestrator.max_iterations`)

## 12. 관련 문서

- **리포 규칙**: [`../AGENTS.md`](../AGENTS.md)
- **패키지 트리 규칙**: [`../minyoung_mah/AGENTS.md`](../minyoung_mah/AGENTS.md)
- **6 protocol 시그니처 근거**: [`design/01_core_abstractions.md`](design/01_core_abstractions.md)
- **미해결·OBSOLETE 질문들**: [`design/04_open_questions.md`](design/04_open_questions.md)
- **참고 토폴로지 패턴**: [`design/05_reference_topologies.md`](design/05_reference_topologies.md)
- **원본 프로젝트 서사**: [`origin/`](origin/) (읽기 전용)
