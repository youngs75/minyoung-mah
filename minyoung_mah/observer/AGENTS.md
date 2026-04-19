# `minyoung_mah/observer/` — Observer 기본 구현 + canonical event 이름

5책임 중 **Clarity / Observation**의 경계가 실제로 박제되는 곳입니다.

## 파일

- `events.py` — `EVENT_NAMES`(canonical 이벤트 이름 집합) + `NullObserver` / `CollectingObserver` / `StructlogObserver` / `CompositeObserver` 네 가지 백엔드.

## canonical event 이름

`EVENT_NAMES`는 Orchestrator가 emit하는 모든 이벤트 이름의 **동결된 어휘**입니다. 백엔드(Langfuse, OTel, structlog, 테스트 collector)가 바뀌어도 dashboard가 이식 가능하도록 이 세트를 공통 언어로 씁니다.

현재 포함:

```
orchestrator.run.start                 orchestrator.run.end
orchestrator.pipeline.step.start       orchestrator.pipeline.step.end
orchestrator.role.invoke.start         orchestrator.role.invoke.end
role.tool.call.start                   role.tool.call.end
role.resilience.retry
orchestrator.hitl.ask                  orchestrator.hitl.respond
orchestrator.memory.read               orchestrator.memory.write
orchestrator.resilience.escalate
```

## 두 네임스페이스: `orchestrator.*` vs `role.*`

`orchestrator.*` 는 **Orchestrator 자신의 행동** — 파이프라인 step, role 을 invoke 한 경계, HITL 중재, 메모리 접근 등. `role.*` 은 **role 이 현재 소유한 ToolInvocationEngine 이 부르는 tool 수준 이벤트** — 어떤 role 인지는 둘러싼 `orchestrator.role.invoke` span 으로 식별합니다. `ToolInvocationEngine` 은 의도적으로 role-agnostic (`The engine does not know about LLMs or roles`) 이라 개별 tool-call 이벤트에 role 이름 필드를 달지 않습니다. Langfuse·OTel 소비자는 trace parent 체인으로 자연스럽게 연결됩니다.

이벤트를 추가·제거할 때는:

1. `events.py::EVENT_NAMES`를 수정
2. `orchestrator.py`(또는 호출 측)에서 실제 emit 지점 수정
3. `docs/ARCHITECTURE.md`의 이벤트 표 갱신
4. 해당 이벤트를 기대하는 테스트(`test_observer_events.py`, `test_orchestrator_*.py`) 갱신

네 군데를 같이 움직여야 canonical 계약이 깨지지 않습니다.

## Langfuse / LiteLLM 분할 원칙 (박제됨)

**이 디렉토리는 Langfuse SDK를 import하지 않습니다.** LLM-level trace(프롬프트, 토큰, 모델 응답)는 소비자가 LiteLLM의 `success_callback = ["langfuse"]`로 구성하고, orchestration-level trace(역할 경계, 파이프라인 step, 툴 호출)만 이 Observer 프로토콜이 담당합니다. 두 층은 공통 `trace_id`로 Langfuse에서 연결됩니다.

자세한 근거: `docs/design/05_reference_topologies.md` §2, `docs/design/04_open_questions.md` K4(OBSOLETE).

소비자가 orchestration 이벤트를 Langfuse로 보내고 싶다면 **자기 리포에서** `LangfuseOrchestrationObserver`를 구현해 Observer 프로토콜을 만족시키면 됩니다 — 라이브러리는 훅 지점만 제공합니다.

## 백엔드 선택 가이드

- `NullObserver` — CLI 일회성 실행, HITL 없는 CI 파이프라인.
- `CollectingObserver` — 테스트. `events.names()`로 이벤트 시퀀스 assertion.
- `StructlogObserver` — 로컬 개발·운영에서 로그 파일/stdout으로 흘리기.
- `CompositeObserver(*observers)` — 위 셋을 섞어 쓰기. 개별 백엔드의 실패는 삼켜져서 파이프라인이 절대 깨지지 않습니다.

## 불변 규칙

1. **Observer는 예외를 Orchestrator로 올려보내면 안 됩니다.** `CompositeObserver`가 try/except로 감싸는 이유이며, 새 백엔드도 같은 규칙을 따라야 합니다.
2. **이벤트 payload는 직렬화 가능해야 합니다.** `metadata` dict에 dataclass 인스턴스를 통째로 넣지 말고 `.model_dump()` 또는 기본 타입으로 변환해서 넣습니다.
3. **이벤트 이름은 `orchestrator.<subject>.<action>` 스키마**를 유지합니다. 다른 네임스페이스(예: 소비자의 `apt_legal.*`)가 필요하면 소비자가 자기 Observer 안에서 자기 이름을 씁니다.
