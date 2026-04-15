# Repository Guidelines — minyoung-mah

## 프로젝트 개요

**minyoung-mah** — Multi-Agent Harness by Youngsuk × Minji (Claude).

범용 Multi-Agent Harness **라이브러리**. 사용자(Youngsuk)와 Claude(Minji)의 페어 작업으로 코딩 에이전트(`ax_advanced_coding_ai_agent`)를 구축하면서 정립된 5책임 철학(Safety / Detection / Clarity / Context / Observation)을 라이브러리화하여, 코딩 에이전트뿐 아니라 다른 vertical agent(첫 소비자: `apt-legal-agent`)에서도 재사용할 수 있게 만드는 것이 목표.

## 경계 (중요)

이 리포는 **순수 라이브러리**다. 소비자 애플리케이션 코드는 이 리포에 들어오지 않는다.

- ✅ 들어오는 것: 6 protocols, Orchestrator, StaticPipeline/ExecuteToolsStep, 기본 구현(Null/Terminal/Queue HITL, Sqlite/Null Memory, Single/Tiered ModelRouter, Null/Collecting/Structlog Observer), resilience 기본값, library 자체 테스트.
- ❌ 들어오지 않는 것: vertical agent 역할 정의, 도메인 프롬프트, MCP 토폴로지, FastAPI/A2A 레이어, 소비자별 bootstrap/배포 구성.
- 소비자(`ax-coding-agent`, `apt-legal-agent`)는 각자 별도 리포에서 `pip install -e ../minyoung-mah`로 editable install 후 소비한다. library에서 부족한 게 있으면 별도 리포에서 이슈/PR로 피드백해서 library에 흡수한다 (co-design은 리포 경계를 넘지 않고 PR 흐름으로).

초기 세션들에서 "library와 apt-legal 예제를 한 리포에서 co-design" 가정으로 작성된 레퍼런스 애플리케이션과 소비자 매핑 문서는 `archive/`에 보존되어 있으며 active 경로에 참여하지 않는다. 자세한 배경은 `archive/README.md` 참조.

## 프로젝트 구조

```
minyoung-mah/
├── AGENTS.md                       # 이 파일 — AI와 기여자가 따를 규칙
├── README.md                       # 프로젝트 소개 + Phase 로드맵
├── pyproject.toml                  # name = "minyoung-mah"
├── .gitignore
├── minyoung_mah/                   # library 패키지 (전부 active)
│   ├── core/                       # 6 protocols, Orchestrator, ExecuteToolsStep, registries
│   ├── hitl/                       # Null/Terminal/Queue HITL channels
│   ├── memory/                     # SqliteMemoryStore + NullMemoryStore
│   ├── model/                      # Single/Tiered ModelRouter
│   ├── observer/                   # Null/Collecting/Structlog/Composite observer
│   └── resilience/                 # ResiliencePolicy + ProgressGuard
├── tests/
│   └── library/                    # library 단위 테스트 (33개, active)
├── docs/
│   ├── design/                     # library-facing 설계 문서
│   │   ├── 01_core_abstractions.md
│   │   ├── 04_open_questions.md
│   │   └── 05_reference_topologies.md  # Deep Insight 등 참고 패턴 박제
│   └── origin/                     # 전신 프로젝트(ax coding agent)의 설계 맥락
│       ├── README.md
│       ├── session-2026-04-12-0005.md   # 8차 (핫픽스 4건)
│       ├── session-2026-04-12-0006.md   # 9차 (35분 완주 실증, §10 메타 분석)
│       ├── EVIDENCE.md
│       └── AGENTS.origin.md
├── archive/                        # inactive: 초기 co-design 산출물 보존 (README 참조)
│   ├── README.md
│   ├── apt_legal_agent_demo/       # 구 단일-MCP 가정의 레퍼런스 애플리케이션
│   └── docs/
│       ├── 02_coding_agent_mapping.md
│       └── 03_apt_legal_mapping.md
└── .ai/
    └── sessions/                   # 세션 핸드오프 문서
```

## 관련 프로젝트 (전부 별도 리포)

- **`../ax_advanced_coding_ai_agent/`** — 전신 프로젝트. 2026-04-12 과제 제출 완료, 동결 상태. 9차 세션까지의 설계 서사가 `docs/origin/`에 보존되어 있음. 이 리포에서 아무 것도 수정하지 않음.
- **`../apt-legal-agent/`** — Vertical AI Agent (공동주택 법률 도우미). Phase 0 완료(문서 허브 + 스캐폴드), 코드 구현은 Phase 2 예정. minyoung-mah의 **first real consumer**. MCP 토폴로지는 `kor-legal-mcp`(법령 공통) + `apt-domain-mcp`(단지별 도메인)의 2개 서버. minyoung-mah는 이 리포의 shape에 관여하지 않고 library API만 제공한다.
- **`../kor-legal-mcp/`**, **`../apt-domain-mcp/`** — apt-legal-agent가 소비하는 MCP 서버들. library 범위 밖.

## 커뮤니케이션 규칙

사용자와의 모든 소통은 항상 한국어로 진행합니다. 코드 주석은 영어를 기본으로 하되, 사용자 facing 메시지(에러, 진행, 문서)는 한국어를 사용합니다.

## 세션 파일 명명 규칙

세션 파일은 `.ai/sessions/session-YYYY-MM-DD-NNNN.md` 형식을 사용합니다.

- `YYYY-MM-DD`: 세션 당일 날짜
- `NNNN`: 같은 날짜 내 순번 (`0001`부터 시작)
- 같은 날짜 파일이 있으면 가장 큰 번호에 `+1`을 적용합니다.

## Resume 규칙

사용자가 `resume` 또는 `이어서`라고 요청하면 가장 최근 세션 파일을 찾아 이어서 작업합니다.

- `.ai/sessions/`에서 명명 규칙에 맞는 파일만 후보로 봅니다.
- 가장 최신 날짜를 우선 선택하고, 같은 날짜면 가장 큰 순번을 선택합니다.
- 초기 컨텍스트에 파일이 없어 보여도 실제 파일 시스템을 다시 확인합니다.
- 세션 파일 조회 또는 읽기가 샌드박스 제한으로 실패하면, `.ai/sessions/` 확인과 대상 파일 읽기에 필요한 최소 범위에서 권한 상승을 요청한 뒤 즉시 재시도합니다.
- 선택한 세션 파일은 전체를 읽습니다.
- 사용자에게 이전 작업 내용과 다음 할 일을 한국어로 간단히 브리핑합니다.

## Handoff 규칙

새 세션 파일은 사용자가 명시적으로 종료를 요청한 경우에만 생성합니다. 허용 트리거 예시는 `handoff`, `정리해줘`, `세션 저장`, `종료하자`, `세션 종료`입니다.

- 저장 위치는 항상 `.ai/sessions/`입니다.
- 기존 `session-*.md` 파일은 절대 수정하지 않습니다.
- 자동 저장이나 단계별 저장은 하지 않습니다.
- 새 파일에는 프로젝트 개요, 최근 작업 내역, 현재 상태, 다음 단계, 중요 참고사항을 포함합니다.
- 저장 후 사용자에게 생성된 파일 경로를 알립니다.

## 현재 Phase 상태 (2026-04-15 기준)

- **Phase 1 — Bootstrap & Design Sketch** ✅ 완료
- **Phase 2a — Library 뼈대 구축** ✅ 완료 — 6 protocol + default 구현 + `ExecuteToolsStep` + 33 tests
- **경계 재정의** ✅ 완료 — co-design 산출물을 `archive/`로 이동, library-only scope 확정
- **Phase 2b — 제자리 클린업** ✅ 완료 (2026-04-15)
  - `minyoung_mah/{subagents,tools,cli,utils}` 디렉토리 전체 삭제 (broken 코딩 에이전트 사본)
  - `minyoung_mah/{config,models,logging_config}.py` 삭제
  - `minyoung_mah/memory/{extractor,middleware,schema}.py` 삭제
  - `minyoung_mah/resilience/{error_handler,retry_policy,watchdog,safe_stop}.py` 삭제
  - `tests/` 최상위 broken 파일 11개 삭제 (`tests/library/`만 남김)
  - `datetime.utcnow()` deprecation 4곳 수정
  - `docs/design/05_reference_topologies.md` 추가 — Deep Insight 3-tier 패턴 박제
  - `tests/library/` 33/33 통과
- **0.1.0 — 소비자 피드백 반영** ✅ 완료 (2026-04-15)
  - `StaticPipeline.shared_state` — pipeline-wide 상수 (apt-legal의 `complex_id` 4회 복사 해소)
  - `PipelineStepResult.payload` / `payload_as(cls)` — 이중 `.output.output` 해소, typed 접근
  - `RoleInvocationResult.has_usable_output` / `output_text` / `format_for_llm` — INCOMPLETE 배너로 synthesizer 환각 함정 완화
  - `run_loop` / `LoopState` / `LoopResult` 전면 삭제 (죽은 shape 정리)
  - `langchain-core`를 required dependency로 정직화, `ModelHandle = BaseChatModel`
  - `default_resilience` `fallback_timeout_s 90 → 180` + docstring에 apt-legal 실측 예시
  - `py.typed` marker + `examples/apt_legal_minimal.py`
  - 43 tests (기존 33 + 신규 10)
- **선택적 확장** ⏸️ 필요할 때
  - `QueueObserver` — streaming 이벤트를 `asyncio.Queue`로 forward (Deep Insight 패턴 참고)
  - `Orchestrator.max_iterations` 하드 스톱 추가 (ProgressGuard와 직교하는 총 실행 횟수 상한)
  - Contract test suite — 6 protocol 각각의 "이걸 구현하면 통과" 재사용 테스트
  - 소비자 리포에서 gap이 관찰될 때만 착수. library 경계에 부합하는지 먼저 점검.

## 5책임 철학 (라이브러리 경계의 기준)

원본 프로젝트의 7~9차 E2E 실증을 통해 정립된 철학. minyoung-mah는 이 5가지만 책임지고, 그 외 결정(역할 프롬프트, 도구 선택, 산출물 형식, 4-tier 모델 정의, 분쟁 유형 분류 등)은 application이 결정한다.

1. **Safety** — 권한 경계, 안전 중단, 무한 루프 방지
2. **Detection** — 장애·정체·반복 감지 (ProgressGuard, Watchdog)
3. **Clarity** — 관찰 가능한 로그와 trace
4. **Context** — SubAgent 간 context 전달 규칙
5. **Observation** — canonical event vocabulary + observer hook 지점 (LLM-level trace는 소비자가 LiteLLM 뒷단 Langfuse로 구성; 자세한 분할은 `docs/design/05_reference_topologies.md` §2)

이 철학에 어긋나는 것을 라이브러리에 추가하려면 **반드시 정당화 근거**가 필요합니다. 더 자세한 맥락은 `docs/origin/session-2026-04-12-0005.md`(8차 세션) 참조.

## 6 Core Protocols

minyoung-mah가 외부로 노출할 protocol. 자세한 시그니처와 근거는 `docs/design/01_core_abstractions.md` 참조.

| # | Protocol | 책임 |
|---|---|---|
| 1 | `SubAgentRole` | "이 역할은 무엇을 하는가" — 역할 정의 (데이터) |
| 2 | `ToolAdapter` | "이 도구는 어떻게 호출하는가" — 외부 세계 접점 |
| 3 | `Orchestrator` | "역할들을 어떤 순서로 실행하는가" — `run_pipeline`(static DAG) + `invoke_role`(원자). 동적 driver-role loop는 소비자가 `invoke_role` 위에서 직접 조립 |
| 4 | `ModelRouter` | "이 역할/tier에 어떤 모델을 쓰는가" |
| 5 | `MemoryStore` | "이 정보를 기억하고 꺼낸다" — tier 이름 configurable |
| 6 | `HITLChannel` | "사용자에게 묻고 응답을 받는다" — 채널 독립 |

## 개발 및 검증

### 환경 설정

```bash
pip install -e .
```

### 테스트

```bash
pytest tests/library/             # library 단위 테스트 (33개, 전부 네트워크 없이 초 단위 완주)
```

`tests/` 최상위에 남아 있는 구 파일들은 `coding_agent.*` import에 의존해 broken이다. Phase 2b에서 삭제 또는 재작성 대상.

### 주의

- **원본 `../ax_advanced_coding_ai_agent/`는 절대 수정하지 않는다**. 제출 완료 상태로 동결.
- `archive/`의 코드/문서는 **건드리지 않는다**. 재참조만 가능. 되살릴 가치가 있는 조각이 있으면 library에 흡수하거나 소비자 리포에 복사해 쓴다.
- `minyoung_mah/` 하위는 이제 전부 active하다 (Phase 2b에서 broken 사본 모듈을 모두 제거함). 새로 뭔가 추가할 때도 이 상태가 깨지지 않도록 한다.
- 경계 원칙: 이 리포 안에서 "특정 vertical agent를 위한 코드를 추가하는" 유혹이 들면 멈추고, library로 추상화 가능한지 먼저 점검한다. 추상화가 어색하면 그건 소비자 리포에 있어야 할 코드다. 참고 패턴은 `docs/design/05_reference_topologies.md`에 박제되어 있지만, 문서일 뿐 강제 구현이 아니다.

## 디렉토리별 AGENTS.md

상위 디렉토리(`../ax_advanced_coding_ai_agent/`)는 모든 주요 디렉토리에 `AGENTS.md`를 두는 관례를 따랐습니다. minyoung-mah도 동일한 관례를 따르되, **Phase 2b에서 broken 사본 모듈 정리가 끝난 후** 디렉토리별 AGENTS.md를 작성합니다. 지금은 구조가 유동적이라 작성 비용 대비 수명이 짧습니다.

## 커밋 규칙

Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:` 등.
`.env`, `.db`, `.claude/`, `__pycache__/`는 커밋하지 않습니다.

## 참고

이 문서는 minyoung-mah 자체의 규칙이며, 원본의 AGENTS.md(동결)와는 별개로 진화합니다. 원본 규칙은 `docs/origin/AGENTS.origin.md`에 보존되어 있습니다.
