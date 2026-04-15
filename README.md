# minyoung-mah

**Multi-Agent Harness by Youngsuk × Minji (Claude).**

`minyoung-mah`는 범용 Multi-Agent Harness **라이브러리**입니다. 특정 도메인이나 프레임워크에 결합되지 않고, 소비자(vertical agent)가 가져다 쓸 수 있는 **프로토콜 + 기본 구현**만 제공합니다.

## 경계

이 리포는 **순수 라이브러리**입니다. 소비자 애플리케이션 코드는 이 리포에 들어오지 않습니다.

- ✅ **들어오는 것**: 6 protocols, `Orchestrator`, `StaticPipeline` + `ExecuteToolsStep`, 기본 구현(Null/Terminal/Queue HITL, Sqlite/Null Memory, Single/Tiered ModelRouter, Null/Collecting/Structlog/Composite Observer), `ResiliencePolicy` + `ProgressGuard`, library 자체 테스트
- ❌ **들어오지 않는 것**: vertical agent 역할 정의, 도메인 프롬프트, MCP 토폴로지, FastAPI/A2A 레이어, 소비자별 bootstrap/배포 구성

소비자는 별도 리포에서 `pip install -e ../minyoung-mah`로 editable install하여 소비합니다.

## 5책임 철학

Harness는 결과물의 형식이나 역할 구조를 강제하지 않습니다. 오직 다음 5가지만 책임집니다:

1. **Safety** — 권한 경계, 안전 중단, 무한 루프 방지
2. **Detection** — 장애·정체·반복 감지 (`ProgressGuard`)
3. **Clarity** — 관찰 가능한 로그와 trace (canonical observer event names)
4. **Context** — SubAgent 간 context 전달 규칙 (`InvocationContext`)
5. **Observation** — timing 계측 + observer hook 포인트

역할 프롬프트, 도구 선택, 산출물 형식, topology는 **소비자가** 결정합니다. 이 철학은 원본 프로젝트(`ax_advanced_coding_ai_agent`)의 7~9차 E2E 실증을 통해 정립되었고, `docs/origin/`에 그 서사가 보존되어 있습니다.

## 6 Core Protocols

| # | Protocol | 책임 |
|---|---|---|
| 1 | `SubAgentRole` | "이 역할은 무엇을 하는가" — 역할 정의 (데이터) |
| 2 | `ToolAdapter` | "이 도구는 어떻게 호출하는가" — 외부 세계 접점 |
| 3 | `Orchestrator` | "역할들을 어떤 순서로 실행하는가" — `run_pipeline`(static) + `invoke_role`(원자) |
| 4 | `ModelRouter` | "이 역할/tier에 어떤 모델을 쓰는가" |
| 5 | `MemoryStore` | "이 정보를 기억하고 꺼낸다" — tier 이름 configurable |
| 6 | `HITLChannel` | "사용자에게 묻고 응답을 받는다" — 채널 독립 |

전체 그림(실행 경로, 데이터 흐름, canonical event, retry 레이어 분할 등)은 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)에서 한 번에 볼 수 있습니다. 개별 프로토콜 시그니처의 설계 근거는 [`docs/design/01_core_abstractions.md`](docs/design/01_core_abstractions.md), 참고용 topology 패턴(Deep Insight 3-tier 등)은 [`docs/design/05_reference_topologies.md`](docs/design/05_reference_topologies.md) 참조.

## 설치 및 사용

```bash
# 소비자 리포에서
pip install -e ../minyoung-mah
```

라이브러리 자체 개발:

```bash
pip install -e .
pytest tests/library/     # 33 tests, 초 단위 완주, 네트워크 없음
```

Runtime 의존성은 `pydantic`과 `structlog` 둘뿐입니다. langchain 메시지 호환은 optional extra로 제공됩니다 (`pip install minyoung-mah[langchain]`). **Langfuse 통합은 라이브러리가 직접 제공하지 않습니다** — LLM-level trace는 소비자가 LiteLLM의 `success_callback = ["langfuse"]`로 구성하고, orchestration-level trace는 `Observer` 프로토콜을 자기 리포에서 구현합니다. 근거는 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §6.

## Phase 상태

- **Phase 1 — Bootstrap & Design Sketch** ✅ 완료
- **Phase 2a — Library 뼈대 구축** ✅ 완료 (6 protocol + `ExecuteToolsStep` + 33 tests)
- **경계 재정의** ✅ 완료 (2026-04-15) — co-design 산출물을 `archive/`로 이동, library-only scope 확정
- **Phase 2b — 제자리 클린업** ✅ 완료 (2026-04-15) — 원본 coding agent 사본 모듈 전부 제거, 의존성 11개 → 2개
- **Phase 2c — 선택적 확장** ⏸️ 소비자 요구 시 — `run_loop` 설계, `QueueObserver`, `Orchestrator.max_iterations` 하드 스톱

## 관련 프로젝트 (전부 별도 리포)

- [`../ax_advanced_coding_ai_agent/`](../ax_advanced_coding_ai_agent) — 전신 프로젝트. 2026-04-12 과제 제출 후 동결. 9차 세션까지의 설계 서사가 `docs/origin/`에 보존됨.
- [`../apt-legal-agent/`](../apt-legal-agent) — Vertical AI Agent (공동주택 법률 도우미). minyoung-mah의 first real consumer. Phase 0 완료, 코드 구현은 Phase 2 예정. 2-MCP 서버 토폴로지 (`kor-legal-mcp` + `apt-domain-mcp`).

## 문서 지도

| 문서 | 언제 읽나 |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 라이브러리의 전체 그림을 처음 볼 때. 실행 경로, 데이터 흐름, canonical event, retry 분할, fast/general path를 한 번에. |
| [`AGENTS.md`](AGENTS.md) | 리포 전체 규칙, Phase 상태, 커밋·세션 규칙. |
| [`minyoung_mah/AGENTS.md`](minyoung_mah/AGENTS.md) 및 각 서브모듈의 `AGENTS.md` | 패키지 내부에 코드를 추가·수정할 때. 서브모듈(`core/`, `hitl/`, `memory/`, `model/`, `observer/`, `resilience/`)마다 규칙을 따로 둡니다. |
| [`docs/design/01_core_abstractions.md`](docs/design/01_core_abstractions.md) | 6 protocol 시그니처의 설계 근거. |
| [`docs/design/04_open_questions.md`](docs/design/04_open_questions.md) | 미결·OBSOLETE 결정 이력. |
| [`docs/design/05_reference_topologies.md`](docs/design/05_reference_topologies.md) | 소비자가 참고할 수 있는 토폴로지 패턴 박제 (강제 아님). |
| [`docs/origin/`](docs/origin/) | 원본 프로젝트(`ax_advanced_coding_ai_agent`)의 7~9차 세션 서사. 읽기 전용. |

## 기여 가이드

[`AGENTS.md`](AGENTS.md) 참조. 소비자 특화 코드를 이 리포에 추가하려는 충동이 들면 멈추고, library로 추상화 가능한지 먼저 점검합니다. 추상화가 어색하면 그건 소비자 리포에 있어야 할 코드입니다.

## 라이선스

TBD
