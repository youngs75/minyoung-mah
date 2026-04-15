# 04. Open Questions — 매핑 과정에서 드러난 결정 대기 항목

**상태**: Draft 1 · 2026-04-13 작성 / 2026-04-15 status banner 추가 / 2026-04-15 0.1.0 재정렬
**목적**: 01~03 문서에서 확신이 부족했거나 두 도메인(coding, apt-legal) 사이에서 충돌한 설계 질문을 모은다. 이 문서는 이제 **설계 사고의 타임라인 보존**용이며, 현재의 진실은 아래 표와 코드(`minyoung_mah/core/`)입니다.

---

## ⚠️ 상태 공지 (Status Banner)

이 문서는 **Phase 2a 착수 전(2026-04-13)**에 작성됐습니다. 이후 두 단계의 변화가 있었습니다:

1. **2026-04-15 경계 재정의** — `examples/apt_legal_agent/`가 `archive/`로 이동, library가 순수 protocol 레이어로 scope-down. 많은 질문이 **해결**되거나 **폐기**됨.
2. **2026-04-15 0.1.0 — apt-legal 실소비자 피드백** — 첫 실소비자(apt-legal-agent)가 시나리오 1~4를 돌려 실측한 gap을 반영. `run_loop` shape를 전면 삭제하고, `shared_state` / `payload_as` / `format_for_llm` 같은 library-ness 헬퍼를 추가. 그 결과 `run_loop` 관련 open question(A1/A2/A6/K1/K3)은 **[REMOVED]** 처리됨.

각 주제 앞에 붙은 **[RESOLVED]** / **[OBSOLETE]** / **[REMOVED]** / **[OPEN]** 태그를 기준으로 읽습니다.

### 빠른 요약 표 (0.1.0 업데이트본)

| ID | 원래 질문 | 현재 상태 | 코멘트 |
|---|---|---|---|
| A1 | Delegate tool 주입 | **[REMOVED]** | `run_loop` 자체가 0.1.0에서 삭제됨. 동적 loop가 필요한 소비자는 `invoke_role` 위에서 자기 delegate 패턴을 직접 조립한다. |
| A2 | SubAgent 인스턴스 생성 | **[REMOVED]** | A1과 동일 이유. |
| A3 | Pipeline HITL interrupt | **[RESOLVED]** | `run_pipeline`은 async blocking. `HITLChannel.ask`가 자연스럽게 await된다. Suspension 없음. |
| A4 | output_schema fast path | **[RESOLVED]** | `Orchestrator.invoke_role`이 `output_schema` + `max_iterations == 1` + `tool_allowlist=[]` 3-조건에서 structured path로 분기. apt-legal `router_role`이 실전 검증. |
| A5 | ExecuteToolsStep vs delegate | **[RESOLVED]** | `ExecuteToolsStep`은 library에 추가됨. Delegate는 A1 REMOVED와 함께 library 범위 밖. |
| A6 | pipeline vs loop 통합 | **[REMOVED]** | `run_loop`을 삭제했으므로 통합 여부 자체가 moot. |
| B1 | output_schema + tools 혼용 | **[RESOLVED]** | 일단 exclusive. 필요해지면 재검토. |
| B2 | max_iterations semantics | **[RESOLVED]** | LLM turn 수로 통일. |
| C1 | ToolResult.value 타입 | **[RESOLVED]** | `str | BaseModel | dict` 3종. |
| C2 | Retry layer | **[RESOLVED]** | tool-level(transient) + 호출자 판단(semantic). `DEFAULT_TOOL_RETRY`가 library default. |
| D1 | Memory schema migration | **[RESOLVED]** | 기존 DB 버림. `tier/scope` 스키마로 clean start. |
| D2 | Memory extractor optional | **[RESOLVED]** | `MemoryExtractor`는 protocol이지만 Orchestrator 생성자가 None 허용. |
| D3 | Cross-scope search | **[RESOLVED]** | `scope=None` 허용. `SqliteMemoryStore.search`가 구현. |
| D4 | Extractor의 HITL 권한 | **[OBSOLETE]** | 경계 재정의로 memory extractor 구현체를 library가 제공하지 않음. 소비자 관심사. |
| E1 | ask blocking vs timeout | **[RESOLVED]** | HITLChannel 구현체 책임으로 확정. |
| F1 | ErrorCategory coding 가정 | **[RESOLVED]** | 7종 일반화 완료, coding-specific 없음. |
| F2 | Watchdog timeout 기본값 | **[RESOLVED]** | 0.1.0에서 apt-legal 실측 기반으로 `fallback_timeout_s=180`, `role_timeouts` per-role override 지원. |
| F3 | ProgressGuard 기본값 | **[RESOLVED]** | opinionated default 제공, injectable `key_extractor`로 override. |
| G1 | Observer event schema | **[RESOLVED]** | `EVENT_NAMES` 표준 이벤트 집합 확정 (`orchestrator.run.*`, `role.invoke.*`, `tool.call.*` 등). backend adapter 구조. |
| H1 | shared_state 동시성 | **[RESOLVED]** | 0.1.0에서 `StaticPipeline.shared_state`는 pipeline-wide 상수(read-only), 각 step이 override 가능. fan_out은 결과를 list로 수집. |
| I1 | apt-legal planner 전술 | **[OBSOLETE]** | apt-legal은 별도 리포. library 범위 아님. |
| J1 | library vs coding agent 구현 순서 | **[OBSOLETE]** | 경계 재정의로 "coding agent 이식" 자체가 이 리포의 로드맵에서 빠짐. 각 소비자 리포에서 진행. |
| J2 | apt-legal repo 위치 | **[OBSOLETE]** | 별도 리포로 확정됨. |
| K1 | `run_loop` 설계 | **[REMOVED]** | 0.1.0에서 `run_loop`/`LoopState`/`LoopResult` 전면 삭제. 이유: 첫 실소비자(apt-legal)가 필요로 하지 않았고, 빈 껍데기를 유지하는 비용이 나중에 구현하는 비용보다 컸음. |
| K3 | `max_iterations` 하드 스톱 | **[DEFERRED]** | static pipeline은 구조상 bounded. 동적 loop를 자기 리포에서 조립하는 소비자가 생기면 재검토. |

**→ 아래 원문은 Phase 2a 진입 전 설계 사고의 기록으로 보존한다. 현재 진실은 위 표와 코드(`minyoung_mah/core/`)입니다.**

---



---

## 주제 A — Orchestrator 실행 모델

### A1. Dynamic mode의 `delegate` tool은 library가 자동 주입하는가, application이 등록하는가?

**맥락** (doc 1 §3, doc 2 §3.5). Coding agent의 run_loop는 planner role이 runtime에 `task_tool`을 호출하여 다른 역할(coder/verifier/fixer)로 위임한다. apt-legal은 static pipeline이라 이 기능이 필요 없다.

**질문**: `run_loop(driver_role="planner", ...)`을 호출하면 Orchestrator가 자동으로 `delegate` tool을 driver role에 **주입**해야 하는가, 아니면 application이 명시적으로 `DelegateTool`을 `tool_allowlist`에 포함시켜야 하는가?

**옵션**:
- **(a) 자동 주입** — driver role은 자동으로 `delegate` tool을 부를 수 있다. 단순하고 "dynamic mode"의 의미가 명확해짐.
- **(b) 명시 등록** — application이 `DelegateTool(orchestrator)` 인스턴스를 만들어 `ToolRegistry`에 넣고, role의 `tool_allowlist`에 `"delegate"`를 포함해야 함. 대신 tool 이름/args 스키마를 커스터마이즈 가능.

**권장**: **(b) 명시 등록**. 이유는 coding agent가 `task_tool`에서 이미 TASK-NN 관습(task_id extra field)을 subclass로 넣고 있기 때문이다. 라이브러리가 자동 주입하면 이 subclass 주입이 어색해진다. 대신 library가 `make_delegate_tool(orchestrator)` 팩토리를 제공하여 boilerplate를 줄인다.

**의존 결정**: A2, A4, B1

---

### A2. `delegate` 호출은 새 SubAgent 인스턴스를 만드는가, 기존 인스턴스를 재사용하는가?

**맥락** (doc 2 §3 말미). 현재 `coding_agent/core/loop.py`는 delegate 시마다 새 `SubAgentInstance`를 `registry.create_instance`로 만들고 상태 머신을 진행시킨다 (CREATED → ASSIGNED → RUNNING → COMPLETED → DESTROYED). Parent-child 관계는 `parent_id`로 추적.

**질문**: 새 설계에서도 invocation마다 새 SubAgentInstance를 생성하는가, 아니면 **역할별로 하나의 인스턴스를 유지**하고 `invoke_role`이 해당 인스턴스를 재호출하는가?

**옵션**:
- **(a) invocation마다 생성** — 현재 동작. 각 TASK-04 위임이 별도 인스턴스. Trace/observability가 풍부, parent-child tree가 정확. 하지만 인스턴스 생성 overhead.
- **(b) 역할별 싱글턴** — `planner`는 하나의 인스턴스, 호출될 때마다 상태 reset. 간단하지만 parent-child tree를 별도로 track해야 함 (invocation id).

**권장**: **(a) invocation마다 생성**. 이유: coding에서 "이 TASK-04가 누구의 호출에서 나온 것인가"라는 질문이 debugging에 핵심이고, apt-legal은 static pipeline이라 생성 overhead가 문제되지 않음 (3~4 호출뿐). Trace 품질 > 성능 최적화.

**의존 결정**: 없음. 이 결정이 A3, D1에 영향을 줌.

---

### A3. Static pipeline에서 중간에 HITL interrupt가 발생하면?

**맥락** (doc 1 §open questions, doc 3 §5 A2AHITLChannel). Coding agent의 run_loop는 역할이 `ask_user_question`을 부르면 자연스럽게 blocking되고, 사용자 응답 후 재개된다. Static pipeline은 어떻게?

**질문**: `run_pipeline(pipeline, ...)` 실행 중 어떤 role이 `HITLChannel.ask`를 호출하면:
- (1) Pipeline이 그 자리에서 blocking되고, 응답 후 이어서 실행하는가?
- (2) Pipeline이 `paused` 상태로 반환되고, 외부에서 resume을 호출해야 하는가?

**옵션**:
- **(a) blocking** — `HITLChannel.ask`가 async로 block하면 pipeline도 그 자리에서 await. 구현 단순, apt-legal의 A2AHITLChannel은 SSE로 long-poll하면 됨. 하지만 A2A task가 60초 제한이면 HITL이 느린 경우 timeout.
- **(b) suspension/resume** — Orchestrator가 `PipelineSuspended` exception/result를 반환하고, 외부가 `orch.resume(pipeline_id, hitl_response)`로 재개. 복잡하지만 HTTP request-response 싸이클과 궁합 좋음.

**권장**: **(a) blocking을 기본, suspension은 Phase 4 이후**. 이유: apt-legal의 첫 3 시나리오는 HITL이 거의 없고, coding agent는 이미 blocking으로 잘 동작. suspension/resume은 distributed/persistent task 환경에서나 필요한데, 지금은 오버엔지니어링.

**의존 결정**: E1 (HITLChannel 구현자가 long-blocking을 어떻게 감당하는지)

---

### A4. `output_schema` + `max_iterations=1` 조합의 fast path

**맥락** (doc 1 §1, doc 3 §3.1 CLASSIFIER, §10.3). Classifier, retrieval_planner, responder 모두 `output_schema=<BaseModel>`이고 tool 호출이 없다. Coding agent의 일반 role은 free-form + tool loop. Orchestrator는 이 두 경우를 어떻게 구분하는가?

**질문**: `invoke_role`의 로직이 하나의 일반 경로인가, 아니면 `output_schema is not None and max_iterations == 1`일 때 별도 fast path인가?

**옵션**:
- **(a) 일반 경로 통일** — 항상 tool loop을 돌리고, 1회만 돌고 끝나도록 하며, 마지막에 output_schema validation을 씌움. 코드 단순.
- **(b) fast path 분리** — structured 호출은 `llm.with_structured_output(schema).invoke(messages)`로 직결. LangChain/LiteLLM의 structured output API를 그대로 사용. tool calling loop 건너뜀. 성능과 정확도 모두 유리.

**권장**: **(b) fast path 분리**. 이유: LangChain의 `with_structured_output`은 OpenAI function calling 또는 JSON mode를 안정적으로 활용하고, 자체 파싱보다 훨씬 견고. 둘의 코드 분기는 `invoke_role` 내부 한 함수에 격리할 수 있어서 표면적 복잡도도 낮음.

```python
async def invoke_role(self, role_name, ctx):
    role = self._roles.get(role_name)
    if role.output_schema is not None and role.max_iterations == 1 and not role.tool_allowlist:
        return await self._invoke_structured(role, ctx)
    return await self._invoke_loop(role, ctx)
```

---

### A5. `ExecuteToolsStep`과 delegate tool의 개념 정리

**맥락** (doc 3 §3.3, §10.1). apt-legal은 LLM 없이 plan → parallel tool calls만 수행하는 단계가 필요. 이게 coding agent의 delegate tool과 기능적으로 겹치는가?

**분석**:
- `delegate tool`은 driver role이 **LLM 호출 중간에** 다른 role에게 위임하는 메커니즘. 호출 주체 = LLM.
- `ExecuteToolsStep`은 parent role의 **output(ExecutionPlan)을 입력으로 받아** 순수 tool 호출만 하는 pipeline step. 호출 주체 = Orchestrator.

**결론**: 겹치지 않는다. 서로 독립적인 개념이다.
- `delegate tool` → dynamic mode의 primitive
- `ExecuteToolsStep` → static mode의 primitive

둘 다 library에 포함. 다만 구현 시 공통 추출물은 `ToolInvocationEngine`으로 묶을 수 있다 (parallel 실행, retry, observer hook을 공유).

**권장**: 둘 다 library에 추가. 공통부는 `core/tool_invocation.py`로 리팩토링.

---

### A6. `run_pipeline`과 `run_loop`를 하나로 통합 가능한가?

**맥락** (doc 1 §3). 처음에는 둘을 나눴지만, 사실 "static DAG은 edge가 결정론적인 dynamic loop"라고 볼 수도 있다.

**질문**: Static pipeline을 "매 iteration마다 driver가 고정된 다음 스텝을 결정하는 특수한 dynamic loop"로 구현하는 게 가능한가?

**분석**: 가능은 하지만 억지스러움. Static pipeline은:
- 다음 스텝이 data(지난 step 결과) 기반으로 결정됨 — LLM 없음
- Fan-out이 자연스럽게 표현됨
- Debugging/시각화가 명확

Dynamic loop은:
- 다음 스텝이 LLM 판단으로 결정됨
- 종료 조건이 LLM 출력 기반

이 둘을 강제로 합치면 "이 loop iteration에 LLM을 호출하는가"를 런타임에 분기하게 되어 코드가 오히려 복잡해진다.

**권장**: 분리 유지. `invoke_role`만 원자로 공유하고, `run_pipeline` / `run_loop`는 별도 public method.

---

## 주제 B — Role과 Output Schema

### B1. `output_schema`가 있는 role도 tool을 쓸 수 있어야 하는가?

**맥락** (doc 1 §1 설계 결정). Free-form + tool loop vs structured output은 mutually exclusive로 보이지만, "도구 여러 번 호출 후 최종 구조화 출력" 패턴은 실제로 유용함 (예: search 여러 번 → structured summary).

**옵션**:
- **(a) mutually exclusive** — `output_schema`가 있으면 `tool_allowlist`는 반드시 빈 리스트. 구현 단순, LLM 혼란 없음.
- **(b) 허용** — LLM이 tool을 호출하다가 최종에 structured output을 낸다. 현재 OpenAI API가 `tools`와 `response_format`을 함께 받을 수 있으므로 기술적 가능.

**권장**: **(a) mutually exclusive를 Phase 1에 적용**, (b)는 Phase 4+에 재검토. 이유: coding과 apt-legal 모두 현재 이 혼합 패턴을 안 씀. 나중에 필요해지면 `output_schema_final`이라는 별도 필드로 추가할 수 있음.

---

### B2. Role의 `max_iterations` semantics — tool call 횟수인가 LLM turn 수인가?

**맥락** (doc 1 §1). `max_iterations=20`이 의미하는 게:
- (a) LLM 호출 20회 (tool response 후 다시 LLM 호출하는 것 포함)
- (b) tool call 20회 (LLM이 tool 호출한 총 횟수)

이 둘은 보통 같은 숫자지만, parallel tool calls에서 차이가 난다.

**권장**: **LLM 호출 횟수** (turn). 이유: parallel tool call이 있어도 한 turn에 여러 tool이 실행됨. "얼마나 많은 LLM 생각을 했는가"가 복잡도의 척도로 더 자연스러움.

---

## 주제 C — Tool Adapter 계약

### C1. `ToolResult.value`의 타입 좁히기

**맥락** (doc 1 §2 open questions). 현재 `value: Any`. LLM에 전달 시 직렬화 책임이 애매하다.

**옵션**:
- **(a) `value: Any`** — 현재 초안. 각 adapter가 자유롭게 반환, Orchestrator가 직렬화.
- **(b) `value: str | BaseModel | dict`** — 세 가지로 제한. LLM 전달 시 각각 다르게 처리.
- **(c) `value: str`만 허용** — 모든 adapter가 스스로 문자열 변환. LLM 전달 단순, 대신 복잡한 구조를 다시 파싱하려면 JSON string으로.

**권장**: **(b) `value: str | BaseModel | dict`**. 이유: (c)는 너무 제약적(판례 JSON 결과를 string으로 flatten하면 responder가 재파싱해야 함). (a)는 느슨. (b)는 타입 safety + LLM 친화성의 타협점.

Orchestrator는 LLM 전달 시:
- `str` → 그대로
- `BaseModel` → `.model_dump_json()`
- `dict` → `json.dumps()`

---

### C2. Tool 실패 시 retry는 tool-level인가 role-level인가?

**맥락** (doc 1 §open questions 7).

**옵션**:
- **(a) tool-level** — `retry_policy`가 `ToolAdapter.call`을 wrap해서 투명하게 재시도.
- **(b) role-level** — role이 tool 실패를 보고 스스로 재시도 여부 결정.
- **(c) 둘 다** — tool-level은 일시적 failure(네트워크, 429), role-level은 의미적 failure(결과가 기대와 다름).

**권장**: **(c) 둘 다**. 일시적 failure(timeout, rate limit, network)는 library가 tool-level로 투명 재시도. 의미적 failure(검색 결과 0건, 잘못된 인자)는 ToolResult.ok=True로 반환하고 LLM이 판단.

구분 기준: `ErrorCategory`가 `{TIMEOUT, RATE_LIMIT, NETWORK, AUTH}`이면 tool-level retry. `{TOOL_ERROR, PARSE_ERROR}`는 LLM에 그대로 전달.

---

## 주제 D — Memory

### D1. Memory schema 변경은 파괴적 migration. 기존 DB는?

**맥락** (doc 2 §5). `layer` → `tier`, `project_id` → `scope` 변경은 기존 `memory_store/*.db`를 호환 못한다.

**옵션**:
- **(a) migration 스크립트 제공** — `minyoung-mah migrate-memory --from <old.db>` 같은 1회성 도구.
- **(b) 기존 DB 버림** — coding agent가 minyoung-mah로 옮길 때 memory를 처음부터 쌓음. 실용적으로 문제 없음 (memory는 누적형이라 재구축 가능).
- **(c) dual-mode support** — library가 old schema도 읽을 수 있도록 version detection.

**권장**: **(b) 기존 DB 버림**. 이유: coding agent의 현재 memory DB는 실사용자 데이터가 아니라 개발 과정의 누적이고, minyoung-mah로 옮기는 건 대규모 변경의 일부이므로 clean start가 합리적. 사용자에게 분명히 알리기만 하면 됨.

---

### D2. Memory extractor가 optional인 것을 어떻게 표현하는가?

**맥락** (doc 1 §5, doc 3 §10.5).

**옵션**:
- **(a) Orchestrator 생성자의 `memory_extractor` 인자가 `None` 허용** — `None`이면 완료 후 extraction skip.
- **(b) `NullMemoryExtractor`를 기본 제공** — `None` 대신 no-op 구현 주입.
- **(c) `memory_extractor`는 protocol이 아니라 lifecycle hook(event subscriber)** — Observer event에 subscribing하는 방식. 완전 optional.

**권장**: **(a) None 허용**. 이유: (b)는 no-op을 매번 생성하는 형식적 비용, (c)는 hook을 일반화하지만 "memory write는 특별한 lifecycle 지점"이라는 의미를 흐림.

```python
Orchestrator(
    ...,
    memory=NullMemoryStore(),
    memory_extractor=None,  # or SomeExtractor()
)
```

---

### D3. `scope` 필드의 cross-scope search semantics

**맥락** (doc 2 §5 end). `scope`를 application이 자유롭게 쓴다면, "scope A의 memory도 scope B에서 검색 가능한가?"

**옵션**:
- **(a) `search(tier, query, scope=None)` 시 scope=None은 모든 scope** — coding agent가 "현재 project의 memory + user global memory"를 섞을 수 있음.
- **(b) `search(tier, query, scope)` 필수** — 명시적 격리. 섞고 싶으면 여러 번 호출 후 merge.

**권장**: **(a) scope=None 허용**. 이유: coding의 실제 사용 패턴이 "user tier는 scope 없이 검색 / project tier는 현재 scope로 검색". 강제 필수는 boilerplate만 늘린다.

---

### D4. Memory extractor가 HITL을 쓸 권한이 있는가?

**맥락** (doc 1 §open questions 2). Memory extractor가 LLM으로 "이 기억을 저장할까요?" 같은 질문을 하면 `HITLChannel`이 필요해진다.

**권장**: **있음. 단, Orchestrator가 끝난 후 동일한 HITLChannel 인스턴스를 재사용.** 이유: extraction 시점은 pipeline 완료 직후이므로 동일한 user session이다. 별도 channel을 요구하는 건 application 복잡도만 높인다.

---

## 주제 E — HITL

### E1. `HITLChannel.ask`의 blocking과 A2A task timeout

**맥락** (doc 3 §5 A2AHITLChannel). A2A task가 60초 안에 응답해야 하는데 `ask`가 1분 넘게 blocking하면 task failed.

**옵션**:
- **(a) HITLChannel 구현체의 책임** — A2AHITLChannel이 스스로 "30초 안에 응답 없으면 default 리턴" 처리.
- **(b) Orchestrator의 timeout** — watchdog이 ask를 wrapping.
- **(c) "ask는 interactive 환경에서만 쓴다"는 관례** — apt-legal은 애초에 ask를 안 쓴다.

**권장**: **(c) + (a) 보조**. apt-legal 초기에는 ask가 없음. 향후 필요하면 A2AHITLChannel이 자체 timeout을 가지도록 구현. library의 책임 아님.

---

## 주제 F — Resilience / Error

### F1. `ErrorCategory` 7종 중 coding 가정이 박힌 게 있는가?

**맥락** (doc 2 §resilience 표). 현재 `error_handler.py`를 확인하지 않고 일반적이라고 추정했음.

**추정되는 7종**: TIMEOUT, RATE_LIMIT, NETWORK, AUTH, TOOL_ERROR, PARSE_ERROR, UNKNOWN

**결정 대기**: Phase 2a 시작 시 `error_handler.py` 실제 확인 후, 혹시 "conftest 실패", "pytest timeout" 같은 coding-specific 카테고리가 있다면 application layer로 분리. 기본값은 7종 모두 library.

---

### F2. Resilience의 watchdog timeout 기본값

**맥락** (doc 3 §10.6). A2A task 60초 vs coding의 coder invoke 평균 84s. 기본값 통일 불가능.

**권장**: **role-level default_timeout**. `SubAgentRole.timeout_s` 필드를 추가하거나, Orchestrator의 resilience policy가 `role_timeouts: dict[str, int]`를 받는다.

```python
default_resilience(
    role_timeouts={
        "classifier": 10,
        "retrieval_planner": 15,
        "responder": 30,
        "coder": 180,
        "verifier": 120,
    },
    fallback_timeout=90,
)
```

---

### F3. ProgressGuard의 `task_repeat_threshold` 같은 숫자는 library 기본값인가 application 설정인가?

**맥락** (doc 2 §3.4). 현재 `window_size=10, stall_threshold=3, max_iterations=50, task_window_size=12, task_repeat_threshold=6`.

**권장**: **library가 opinionated default 제공**, application이 override. 이유: 9차 E2E에서 검증된 숫자이므로 처음 쓰는 사용자가 0부터 튜닝할 필요 없음. 하지만 apt-legal 같은 고정 pipeline은 progress guard 자체가 거의 의미 없을 수 있으므로 `ProgressGuard.disabled()`도 제공.

---

## 주제 G — Observability

### G1. Observer event schema 표준화

**맥락** (doc 1 §open questions 8).

**질문**: Observer가 발행하는 이벤트가 Langfuse에 맞춰지면 OpenTelemetry로 바꾸기 어려움. 추상 event schema를 정의해야 하는가?

**권장**: **이벤트 이름과 필드를 표준화**, backend는 어댑터. 표준 이벤트 예:

- `orchestrator.run.start` / `.end`
- `orchestrator.role.invoke.start` / `.end`
- `orchestrator.tool.call.start` / `.end`
- `orchestrator.hitl.ask` / `.respond`
- `orchestrator.memory.read` / `.write`
- `orchestrator.resilience.retry` / `.escalate`

각 이벤트는 `{timestamp, event, role, tool, duration_ms, ok, metadata}` 공통 필드. Langfuse adapter는 이걸 span으로 변환, structlog adapter는 log entry로 변환.

**결정 대기**: Phase 2a 착수 시점에 현재 `coding_agent`의 실제 이벤트 집합을 스캔하여 표준 이벤트 목록을 확정.

---

## 주제 H — 동시성과 Shared State

### H1. `InvocationContext.shared_state`의 동시성

**맥락** (doc 1 §open questions 3). `fan_out`이 같은 pipeline state를 여러 role이 동시에 읽고 쓰는 경우.

**옵션**:
- **(a) read-only** — `shared_state`는 parent step이 쓰고, child는 읽기만. Fan_out도 각자 별도 결과를 반환.
- **(b) merge function 요구** — fan_out step에 `merge: Callable[[list[RoleOutput]], dict]` 인자를 받아 결과 merge.
- **(c) 락 기반 write** — application이 동시성 책임.

**권장**: **(a) + (b)**. shared_state는 read-only, fan_out 결과는 별도 리스트로 수집되어 다음 step의 parent_outputs에 들어감. merge가 필요하면 다음 step의 `input_mapping`에서 처리.

```python
PipelineStep(
    role="retrieval_executor",
    fan_out=...,
    # results are collected into state["retrieval_executor"].outputs: list[RoleOutput]
),
PipelineStep(
    role="responder",
    input_mapping=lambda state: InvocationContext(
        parent_outputs={
            "classifier": state["classifier"].output,
            "tool_results": [r.output for r in state["retrieval_executor"].outputs],
        },
        ...
    ),
),
```

---

## 주제 I — Planner 설계 전술 (apt-legal 전용)

### I1. Retrieval planner: LLM 예시 vs 규칙 테이블

**맥락** (doc 3 §3.2). apt-legal의 분쟁 유형별 기본 호출 세트를 LLM 프롬프트에 예시로 넣을지, 규칙 테이블로 하드코딩할지.

**옵션**:
- **(a) LLM 예시 기반** — 시스템 프롬프트에 10개 분쟁 유형 × 기본 호출 세트를 예시로. LLM이 상황에 맞게 조정.
- **(b) 규칙 테이블** — Python dict로 `{NOISE: [search_law, search_precedent, ...], ...}` 하드코딩. LLM은 keywords만 채움.

**권장**: **(a) LLM 예시 기반을 Phase 3 초기**, 성능 문제 시 (b)로 fallback. 이유:
- (a)가 유연하고 edge case에 강함 (예: keywords에 "재건축 동의율"이 있으면 즉시 `get_law_article` 추가 계획)
- gpt-4o는 이 정도 complexity를 안정적으로 처리
- (b)는 유지보수 비용이 높음 (분쟁 유형 추가 = 코드 수정)
- Langfuse trace로 planner output을 관찰하여 품질 모니터링 가능

이건 apt-legal 내부 결정이라 library에는 영향 없음.

---

## 주제 J — 구현 순서와 점진 통합

### J1. Phase 2a에서 library만 뼈대 만들지, coding agent도 함께 리팩토링할지

**옵션**:
- **(a) library + coding agent 동시 리팩토링** — Phase 2 한 번에. 완벽한 cut-over.
- **(b) library 뼈대만 먼저, coding agent는 기존 그대로** — library가 production-ready가 된 후 coding agent 이식.

**권장**: **(b) 점진 통합**. Phase 2a에서 minyoung-mah 뼈대만 세우고 unit test로 검증, Phase 3 동안 apt-legal이 실제로 library를 사용하며 API를 flesh out, Phase 4에서 coding agent를 이식. 이유: coding agent는 이미 잘 동작하므로 건드릴 이유가 없음. apt-legal이 첫 진짜 사용자가 되고, 그 과정에서 발견되는 API gap을 반영한 후 coding agent 이식.

이건 가장 중요한 sequencing 결정이다.

---

### J2. apt-legal repo 위치 — minyoung-mah/examples/ 내부 vs 별도 repo

**맥락** (doc 3 §2).

**옵션**:
- **(a) `minyoung-mah/examples/apt_legal_agent/`** — 같은 repo, 같이 움직임. 초기 개발 속도 유리.
- **(b) `apt-legal-agent/` 별도 repo, minyoung-mah를 pip dependency로 참조** — 실전 분리. api versioning 강제.

**권장**: **(a) 초기, Phase 4 이후 (b)로 분리**. 이유: Phase 3 개발 중에 minyoung-mah API를 자주 수정할 것이므로, 같은 repo에서 atomic commit으로 양쪽을 수정하는 게 훨씬 빠름. API 안정화 후 분리.

---

## 결정 요약 표 (권장안 받아들인 기준)

| ID | 주제 | 권장안 |
|---|---|---|
| A1 | Delegate tool 주입 방식 | 명시 등록 + `make_delegate_tool` 팩토리 |
| A2 | SubAgent 인스턴스 생성 | invocation마다 새 인스턴스 |
| A3 | Pipeline HITL interrupt | blocking async 기본, suspension 없음 |
| A4 | output_schema fast path | 분리 (`with_structured_output`) |
| A5 | ExecuteToolsStep vs delegate | 둘 다 별개 개념, 공통부만 `ToolInvocationEngine`으로 |
| A6 | pipeline vs loop 통합 | 분리 유지, `invoke_role`만 공유 |
| B1 | output_schema + tools 혼용 | 일단 exclusive, 나중에 재검토 |
| B2 | max_iterations semantics | LLM turn 수 |
| C1 | ToolResult.value 타입 | `str | BaseModel | dict` |
| C2 | Retry layer | tool-level(transient) + role-level(semantic) |
| D1 | Memory schema migration | 기존 DB 버림 |
| D2 | Memory extractor optional | `memory_extractor: ... | None` |
| D3 | Cross-scope search | scope=None = all scopes |
| D4 | Extractor의 HITL 권한 | 있음, 동일 channel 재사용 |
| E1 | ask blocking vs timeout | 구현체 책임 |
| F1 | ErrorCategory coding 가정 | Phase 2a 시작 시 확인 |
| F2 | Watchdog timeout 기본값 | role-level `role_timeouts` dict |
| F3 | ProgressGuard 기본값 | library opinionated default, app override 가능 |
| G1 | Observer event schema | 표준 이벤트 이름 + 공통 필드, backend adapter |
| H1 | shared_state 동시성 | read-only + fan_out results list |
| I1 | apt-legal planner 전술 | LLM 예시 기반 초기, 성능 문제 시 fallback |
| J1 | 구현 순서 | library 뼈대 → apt-legal 구축 → coding 이식 |
| J2 | apt-legal repo 위치 | minyoung-mah/examples/ 내부, 나중에 분리 |

**사용자 결정이 필요한 것**: 위 권장안 중 동의하지 않는 것. 특히 **J1 (구현 순서)**이 가장 중요 — 이게 결정되면 다음 세션의 Phase 2a 스코프가 확정됨.

---

## Phase 2a 진입 조건 (다음 세션 시작 전 필요)

1. 위 권장안 검토 및 반대 항목 표기
2. `apt-legal-mcp/docs/02_mcp_server_codex_spec.md`는 apt-legal application이 알아서 할 일이므로 별도 설계 세션 불필요
3. Phase 2a 스코프 합의:
   - (a) **최소 library**: protocol 정의 + `SqliteMemoryStore` + `SingleModelRouter`/`TieredModelRouter` + `NullHITLChannel`만. Orchestrator는 stub.
   - (b) **run_pipeline 포함**: (a) + 실제 작동하는 `run_pipeline` (static only). apt-legal Phase 3 시작 가능.
   - (c) **run_pipeline + run_loop 모두**: (b) + run_loop. coding agent 이식 가능.

**권장**: **(b)**. 이유: Phase 3가 apt-legal이고 apt-legal은 static pipeline이라 run_loop이 없어도 진행 가능. run_loop은 Phase 4(coding agent 이식) 시작 시 추가. 총 소요 시간 최소화.

---

## Phase 2c — 신규 Open Questions (2026-04-15 추가)

Phase 2b 클린업이 끝난 시점에서 library가 다음에 진행할 수 있는 작업들. 모두 **소비자 리포에서 실제 gap이 관찰될 때 착수**한다. 선제적으로 구현하지 않는다.

### K1. `run_loop` 설계 — dynamic mode의 최소 표면적 [OPEN]

**맥락**: `Orchestrator.run_loop`는 현재 `NotImplementedError`. static pipeline(`run_pipeline`)만으로는 ReAct-style agent(예: Deep Insight의 coordinator, coding agent의 planner)를 표현할 수 없다.

**질문**: `run_loop`의 signature와 종료 조건을 어떻게 정의할 것인가?

**옵션**:
- **(a)** `run_loop(driver_role, ctx, max_iterations, stop_when)` — driver가 LLM 호출 → tool 호출 루프, `stop_when` 또는 driver가 `final=True`를 내면 종료.
- **(b)** `run_loop`을 `run_pipeline`의 특수 케이스로 취급 — `LoopStep(driver_role, stop_condition)`을 `PipelineStep`의 한 변종으로 추가, `run_pipeline`만 유지.
- **(c)** 별도 `AgentLoop` 클래스 — Orchestrator는 단순 `invoke_role` 디스패처로 남기고, loop 로직은 별개 클래스로 분리.

**결정 기준**: 소비자(apt-legal 또는 coding) 중 하나가 실제로 ReAct 루프를 필요로 할 때, 그 요구사항을 먼저 본 뒤 결정.

### K2. `QueueObserver` — streaming을 위한 observer 변종 [OPEN]

**맥락**: Deep Insight는 전역 `deque` + `threading.Lock`으로 tool agent의 이벤트를 main loop에 forward한다 (`05_reference_topologies.md` 1번). FastAPI SSE/WebSocket 통합 시 동일 패턴이 필요할 가능성 높음.

**질문**: `Observer` 프로토콜의 표준 구현으로 `QueueObserver(queue: asyncio.Queue)`를 추가할 것인가?

**권장**: **소비자가 요구할 때 추가**. 현재 `CompositeObserver`와 application-level observer 구현으로 충분히 감당 가능. Deep Insight 스타일 전역 queue는 `CollectingObserver` + custom forwarder로 이미 흉내낼 수 있음.

### K3. `Orchestrator.max_iterations` 하드 스톱 [OPEN]

**맥락**: `ProgressGuard`는 "같은 행동 반복"을 잡고, Deep Insight의 `set_max_node_executions(25)`는 "총 실행 횟수 상한"을 본다. 두 가드가 직교한다.

**질문**: `Orchestrator` 또는 `run_pipeline`/`run_loop`에 "total step/iteration count" 하드 리미트를 명시적으로 추가할 것인가?

**권장**: `run_loop` 설계 시 같이 결정. static pipeline은 step 수가 구조적으로 bounded라 필요 없음. dynamic loop에서만 의미 있는 가드.

### K4. Langfuse observer 실구현 [OBSOLETE — 2026-04-15]

**결정**: library는 Langfuse adapter를 **직접 구현하지 않는다**. `pyproject.toml`의 `[langfuse]` optional extra도 제거됨.

**원칙 (LiteLLM 뒷단 Langfuse)**:
- library는 LLM을 직접 호출하지 않는다. `ModelRouter`는 "어떤 모델을 쓸지"만 알려주고 실제 호출은 소비자 책임.
- **LLM-level trace** (prompt / completion / token usage)는 소비자가 LiteLLM의 자동 Langfuse 통합으로 커버한다: `litellm.success_callback = ["langfuse"]`.
- **Orchestration-level trace** (`orchestrator.run.*`, `role.invoke.*`, `pipeline.step.*`, `tool.call.*`)는 library의 `Observer` 프로토콜이 담당한다.
- 두 층은 같은 `trace_id`로 Langfuse에서 연결 가능 (LiteLLM metadata 또는 Observer metadata를 통해 전달) — 구성은 소비자 책임.

**결과**: library에 Langfuse SDK 의존성이 없고, Observer 구현은 `Null/Collecting/Structlog/Composite` 4종만 유지. 자세한 서술은 `05_reference_topologies.md`의 "Observability 층 분할" 참조.

### K5. pyproject.toml 의존성 재재검토 [OPEN]

**맥락**: 2026-04-15에 11개 → 2개(pydantic, structlog)로 줄임. 만약 추후 `run_loop` 구현에서 `asyncio` 외에 무언가 더 필요해지면 (예: 상태 직렬화에 `msgpack`, trace id 생성에 `uuid7`) 조심스럽게 추가.

**원칙**: runtime dependency는 **정당화가 필요한 특권**. 새 의존성을 받을 때마다 "이게 optional extra로 가능한가?"를 먼저 묻는다.
