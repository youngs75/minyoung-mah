# `minyoung_mah/` — 라이브러리 패키지

이 디렉토리는 minyoung-mah의 **전체 퍼블릭 API**입니다. 이 트리 밖의 코드(`tests/`, `docs/`)는 이 API를 검증하고 설명할 뿐, 기능을 추가하지 않습니다.

## 구성 원칙

- 이 디렉토리에 들어올 수 있는 것은 **6 Core Protocols 중 하나를 확장·구현**하거나, **5책임(Safety / Detection / Clarity / Context / Observation)** 중 하나를 강화하는 코드뿐입니다.
- vertical agent 특화 로직(도메인 역할, 프롬프트, MCP 토폴로지)은 이 트리 안에 들어오지 않습니다. 유혹이 들면 멈추고 `../AGENTS.md`의 "경계" 절을 다시 읽습니다.
- 0.1.0부터 런타임 의존성은 **`pydantic` + `structlog` + `langchain-core`** 셋입니다. `_invoke_structured` / `_invoke_loop`가 `BaseChatModel` 인터페이스(`ainvoke`/`bind_tools`/`with_structured_output`)를 직접 호출하기 때문에, "langchain은 optional"이라는 초기 가정은 소비자에게 거짓말이었습니다. Langfuse SDK 같은 *진짜* 선택 의존(예: 추후 Langfuse adapter)만 함수 내부 lazy import로 유지합니다.

## 서브모듈 지도

| 디렉토리 | 책임 | 대표 심볼 |
|---|---|---|
| `core/` | 6 protocols, `Orchestrator`, 파이프라인 실행, 레지스트리, 공통 타입 | `SubAgentRole`, `Orchestrator`, `StaticPipeline`, `ExecuteToolsStep` |
| `hitl/` | HITLChannel 기본 구현 | `NullHITLChannel`, `TerminalHITLChannel`, `QueueHITLChannel` |
| `memory/` | MemoryStore 기본 구현 | `SqliteMemoryStore`, `NullMemoryStore` |
| `model/` | ModelRouter 기본 구현 | `SingleModelRouter`, `TieredModelRouter` |
| `observer/` | Observer 기본 구현 + canonical event 이름 | `NullObserver`, `CollectingObserver`, `StructlogObserver`, `CompositeObserver`, `EVENT_NAMES` |
| `resilience/` | Watchdog timeout + ProgressGuard 정책 | `ResiliencePolicy`, `ProgressGuard`, `default_resilience()` |

각 서브모듈의 내부 규칙은 해당 디렉토리의 `AGENTS.md`를 참조하세요.

## 추가/수정 시 체크리스트

1. 변경이 6 protocol 시그니처에 영향을 주는가? → `docs/design/01_core_abstractions.md`를 같은 커밋에서 갱신.
2. 새 파일이 하드 의존성을 추가하는가? → `pyproject.toml`의 runtime deps와 충돌하지 않는지 확인. 진짜 선택 의존만 함수 내부 import.
3. Observer 이벤트 이름을 추가/변경했는가? → `observer/events.py::EVENT_NAMES`에 등록하고, `docs/ARCHITECTURE.md`의 이벤트 표도 갱신.
4. `tests/library/`에서 43개 기존 테스트가 통과하는가? 새 동작이면 테스트도 함께 추가.
5. 공개 API(타입, 시그니처) 변경이 소비자에 영향을 주는가? → `__version__` bump + `examples/apt_legal_minimal.py`에서 같은 패턴이 여전히 컴파일되는지 확인.
6. 소비자(`../apt-legal-agent/`, `../ax_advanced_coding_ai_agent/`)의 코드를 **이 리포 안에서** 수정하지 않았는가? — atomic 2-리포 커밋은 금지.
