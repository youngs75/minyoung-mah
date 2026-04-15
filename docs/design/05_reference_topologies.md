# 05 — Reference Topologies

이 문서는 minyoung-mah의 6 protocol 위에 **어떤 multi-agent 구조를 얹을 수 있는지**를 보여주는 reference pattern 모음이다. library는 이 중 어떤 topology도 강제하지 않는다. 소비자가 자신의 도메인에 맞는 패턴을 골라 구성한다.

> **원칙 재확인:** minyoung-mah는 Safety / Detection / Clarity / Context / Observation 5책임만 맡는다. topology, 역할 정의, 프롬프트, 도구 구성은 전부 application의 결정.

---

## 1. Deep Insight 3-tier hierarchy (AWS, 2025)

출처: [AWS Blog — 프로덕션 Multi-Agent 시스템이 해결해야 할 5가지 문제: Deep Insight 아키텍처로 배우는 실전 설계](https://aws.amazon.com/ko/blogs/tech/practical-design-lessons-from-the-deep-insight-arch/) / [sample-deep-insight](https://github.com/aws-samples/sample-deep-insight)

### 구조

```
User Query
   ↓
Coordinator  ─── (단순 질의는 직접 답변)
   │
   ↓ (복잡 질의만 handoff)
Planner  ─── 실행 계획 수립
   │
   ↓
Plan Reviewer ─── HITL: 사용자가 plan 승인/수정 요청
   │   ↑         (수정 요청 시 Planner로 루프백, 최대 10회)
   │   └──────┘
   ↓
Supervisor ─── tool agent들에게 작업 위임 + 결과 집계
   │
   ↓
Tool Agents (병렬)
 ├─ Coder      — Python/Bash 실행으로 데이터 분석
 ├─ Reporter   — DOCX 리포트 생성
 ├─ Validator  — 결과 검증
 └─ Tracker    — 진행 상황 추적
```

### minyoung-mah 매핑

| Deep Insight 요소 | minyoung-mah 표현 |
|---|---|
| Coordinator / Planner / Supervisor / Tool agents | 각각 별개의 `SubAgentRole` |
| 계층 간 handoff | `StaticPipeline`의 step 나열 또는 `Orchestrator.invoke_role`의 명시적 호출 |
| Plan revision loop | `HITLChannel.ask(...)` + 애플리케이션이 plan 상태를 관리하며 `invoke_role("planner")` 재호출 |
| Tool agent 병렬 실행 | `ExecuteToolsStep` (priority 그룹 기반 fan-out) |
| per-agent 모델 선택 (COORDINATOR_MODEL_ID 등) | `TieredModelRouter` + 역할별 tier 태깅 |
| Execution 하드 리미트 (`set_max_node_executions(25)`) | `Orchestrator` 내부 iteration 카운터 + `ProgressGuard`의 중복 호출 감지 |

### 흡수 여부

**현재는 흡수하지 않는다.** Deep Insight의 3-tier는 "data analysis" 도메인에 특화된 canonical 패턴이고, 다른 vertical(법률, 코딩)에도 맞는다는 보장이 없다. minyoung-mah는 protocol만 제공하고, 소비자가 자기 도메인에 맞춰 이 패턴을 **베껴 쓴다**. 만약 3개 이상의 소비자에서 동일한 패턴이 반복되는 것이 관찰되면 그때 `HierarchicalOrchestrator` 헬퍼를 library에 흡수해도 늦지 않다.

### 학습 포인트

1. **Streaming event queue 패턴.** Deep Insight는 workflow를 백그라운드 `asyncio.Task`로 돌리고, tool agent들은 전역 `deque` + `threading.Lock`에 이벤트를 push, main loop가 consume한다. minyoung-mah의 `Observer`가 이 역할을 이미 수행하지만, **streaming 전용 `QueueObserver`** (application이 주입하는 `asyncio.Queue`로 이벤트를 forward)를 추가하면 FastAPI SSE/WebSocket과의 통합이 쉬워진다. Phase 2c 후보. 단, 이 패턴은 **orchestration-level 이벤트**만 다루고 LLM-level trace(prompt/completion/tokens)와는 무관하다 — 후자는 아래 "Observability 층 분할"에서 설명하는 LiteLLM callback이 담당한다.

2. **Execution 하드 리미트 vs 정체 감지는 별개.** Deep Insight의 `set_max_node_executions(25)`는 "총 몇 번 실행했는가"를 세고, minyoung-mah의 `ProgressGuard`는 "같은 tool을 같은 args로 반복 호출하는가"를 본다. 두 가드가 직교한다. Phase 2c에서 Orchestrator에 `max_iterations` 하드 스톱을 명시적으로 넣는 것을 검토한다.

3. **Plan reviewer loop는 HITLChannel의 자연스러운 확장.** 단일 질문-응답뿐 아니라 "계획 전체를 보여주고 approve/revise 중 선택"도 `HITLChannel.ask`의 한 형태로 표현 가능하다. 별도 protocol이 필요 없다.

4. **프롬프트는 `.md` 파일로 분리.** Deep Insight는 `src/prompts/coordinator.md`처럼 에이전트별 시스템 프롬프트를 markdown 파일로 저장하고 런타임에 읽는다. `SubAgentRole`의 `system_prompt` 필드가 이미 이 패턴을 허용한다 — library가 강제할 필요 없음.

---

## 2. Observability 층 분할 — LiteLLM 뒷단 Langfuse

minyoung-mah는 **orchestration-level trace**만 책임진다. LLM 호출 자체에 대한 trace(prompt/completion/token usage)는 **소비자가 LiteLLM의 callback 훅으로** 구성한다. 이 분할이 라이브러리의 "LLM을 직접 호출하지 않는다"는 원칙과 정확히 맞물린다.

### 두 층의 책임 분할

| 층 | 담당 | 누가 구현 | 이벤트 예시 |
|---|---|---|---|
| **LLM-level** | 모델 호출의 입출력·토큰·지연 | 소비자 (LiteLLM callback) | `prompt`, `completion`, `prompt_tokens`, `completion_tokens`, `model_id`, `latency_ms` |
| **Orchestration-level** | 역할 실행·도구 호출·파이프라인 진행 | minyoung-mah `Observer` | `orchestrator.run.start/end`, `role.invoke.start/end`, `pipeline.step.*`, `tool.call.*` |

### 소비자가 구성하는 방법

```python
import litellm
litellm.success_callback = ["langfuse"]           # LLM-level 자동 전송
litellm.failure_callback = ["langfuse"]

# minyoung-mah 쪽은 Observer로 orchestration-level 이벤트 발행
orchestrator = Orchestrator(..., observer=StructlogObserver())
# 또는 소비자 리포에서 만든 LangfuseOrchestrationObserver(trace_id=...)
```

두 층을 Langfuse에서 같은 trace로 묶고 싶다면 **trace_id**를 공유하면 된다:
- LiteLLM은 `metadata={"trace_id": ...}`를 통해 외부 trace에 붙일 수 있고,
- Observer 구현체는 같은 `trace_id`를 이벤트 metadata로 태깅한다.

### 왜 library가 Langfuse SDK를 의존하지 않는가

1. **중복 책임 회피** — LLM 호출 trace는 LiteLLM이 이미 잘 해결했다. library가 또 다른 경로로 prompt/completion을 수집하면 두 trace가 어긋나거나 중복된다.
2. **의존성 경계** — library의 runtime deps는 `pydantic` + `structlog`만 허용(04_open_questions K5 원칙). Langfuse SDK를 받으면 이 특권 상자가 열린다.
3. **Observer 프로토콜의 순수성** — `NullObserver`, `CollectingObserver`, `StructlogObserver`, `CompositeObserver` 4종이 "library가 책임지는 observability의 전부". 소비자가 Langfuse 계정/프로젝트/키를 가진 상태에서 orchestration-level trace를 Langfuse로 보내고 싶으면 **자신의 리포에서** `LangfuseOrchestrationObserver`를 구현하여 `Observer` 프로토콜을 만족시키면 된다 — library는 이 훅 지점만 제공한다.

### 지금 결정된 것 / 하지 않는 것

- **하지 않음**: library에 `LangfuseObserver` 어댑터 추가, `pyproject.toml`의 `[langfuse]` optional extra (2026-04-15 제거됨).
- **함**: canonical event 이름(`EVENT_NAMES`) 유지, metadata dict 자유 전달 허용(trace_id 등 소비자 맥락 주입용).
- **원칙 출처**: 2026-04-15 세션 0002에서 사용자(Youngsuk)가 "LiteLLM 뒷단 Langfuse"를 선호하는 것으로 확정. `04_open_questions.md` K4의 OBSOLETE 처리 근거.

---

## 3. (미정) 다른 레퍼런스 패턴

소비자 리포들이 실제로 돌기 시작하면 이 섹션에 축적한다. 후보:

- **Plan-and-Execute** (LangGraph 튜토리얼 기반)
- **ReAct loop** (단일 역할, dynamic tool calling — `run_loop` 구현 후 추가)
- **Critique-and-Revise** (생성-검증 2단계 루프)

---

## 참고: library가 "강제하지 않는다"는 것의 의미

5책임 철학을 유지하는 한, minyoung-mah는 특정 topology에 편향되는 코드를 받지 않는다. 예를 들어 `HierarchicalOrchestrator(coordinator=..., planner=..., supervisor=...)` 같은 헬퍼는 **편의**이지 **강제**가 아니어야 하고, 그 헬퍼가 없어도 소비자가 6 protocol만으로 같은 결과를 구성할 수 있어야 한다. 이 기준이 깨지면 그 코드는 library가 아니라 소비자 리포에 속한다.
