# `minyoung_mah/core/` — 프로토콜과 Orchestrator

라이브러리의 **심장**. 6 protocol의 정의, `Orchestrator`의 실행 경로, 데이터 타입, 레지스트리, 툴 호출 엔진이 모두 여기 모입니다. 이 디렉토리 밖의 모든 것은 이 파일들에 선언된 계약을 만족시키는 구현에 불과합니다.

## 파일별 역할

| 파일 | 무엇이 들어 있나 | 건드릴 때 주의할 것 |
|---|---|---|
| `protocols.py` | 6 Core Protocol (`SubAgentRole`, `ToolAdapter`, `ModelRouter`, `MemoryStore`, `HITLChannel`, `Observer`) + optional `MemoryExtractor` | 시그니처 변경은 **파급 효과가 큽니다**. `docs/design/01_core_abstractions.md`와 `docs/ARCHITECTURE.md`를 같은 커밋에서 갱신하고, 모든 기본 구현과 테스트가 새 계약을 만족하는지 확인. |
| `types.py` | passive dataclass/Enum만 (`InvocationContext`, `RoleInvocationResult`, `ToolResult`, `StaticPipeline`, `ExecuteToolsStep`, `ObserverEvent` 등). **active 객체 금지**. | 새 타입은 dataclass 또는 Enum으로만. 여기에 메서드를 쌓기 시작하면 protocols와 책임이 섞입니다. |
| `orchestrator.py` | `Orchestrator` 클래스. `run_pipeline` / `invoke_role` / (아직 `NotImplementedError`인) `run_loop`. 구조화 출력 fast path와 툴 호출 루프의 두 경로 분기. | 5책임 중 **Safety/Detection/Clarity/Context/Observation을 모두 집행**하는 지점. 옵저버 emit 위치를 추가·삭제하면 canonical event 세트가 흔들립니다. `EVENT_NAMES`와 동기화 필수. |
| `registry.py` | `RoleRegistry`, `ToolRegistry`. 이름→객체 매핑의 얇은 래퍼. | 이름 충돌과 allowlist 필터링만 책임. 조회 이상의 로직(캐싱, TTL)을 넣지 않습니다. |
| `tool_invocation.py` | `ToolInvocationEngine` — 단일/병렬 tool call, tool-level 전이 오류 retry, observer emit. | retry는 `TRANSIENT_ERRORS`(`TIMEOUT`, `RATE_LIMIT`, `NETWORK`)만. 여기에 semantic retry를 섞지 않습니다 (그건 role 레벨). |

## 설계 원칙

1. **Protocol은 데이터·계약만 말한다.** 구체 동작은 `Orchestrator` 또는 구현 모듈이 진다. Protocol 안에 헬퍼 메서드를 넣지 않습니다.
2. **Orchestrator는 단방향으로 데이터를 본다.** `PipelineState`는 누적되고, 각 step은 이전 state를 읽어 `InvocationContext`를 짓는다. Step이 state를 거꾸로 수정하지 않습니다.
3. **모든 실패는 값으로 돌아온다.** `ToolResult(ok=False, …)`, `RoleInvocationResult(status=FAILED, …)`. Orchestrator로 예외를 던지는 경로는 `OrchestratorError`(미등록 role) 같은 **불가역 구성 오류**뿐입니다.
4. **Observer emit은 try/except로 감싸서 절대 파이프라인을 깨뜨리지 않습니다.** `_emit()` 헬퍼를 우회하지 마세요.
5. **langchain 의존은 함수 내부 import.** 모듈 로드 시점에 `from langchain_core.messages import …`를 쓰면 optional extra 경계가 깨집니다.

## 테스트 범위 (`tests/library/`)

- `test_orchestrator_structured.py` — fast path 분기
- `test_orchestrator_tool_loop.py` — 일반 tool-call 루프, iteration 상한, tool-not-in-allowlist
- `test_pipeline.py` — 정적 파이프라인 조립, `fan_out`, `condition`, `on_step_failure` 모드
- `test_execute_tools_step.py` — LLM 없는 툴 디스패치, 우선순위 그룹, `continue_on_failure`
- `test_tool_invocation.py` — tool-level retry, 전이 오류 분류
- `test_registry.py` — 이름 충돌 / allowlist

새 분기를 추가하면 이 목록에 해당하는 테스트 파일을 먼저 찾고 같은 커밋에서 확장합니다.
