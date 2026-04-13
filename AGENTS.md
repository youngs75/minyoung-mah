# Repository Guidelines — minyoung-mah

## 프로젝트 개요

**minyoung-mah** — Multi-Agent Harness by Youngsuk × Minji (Claude).

범용 Multi-Agent Harness 라이브러리. 사용자(Youngsuk)와 Claude(Minji)의 페어 작업으로 코딩 에이전트(`ax_advanced_coding_ai_agent`)를 구축하면서 정립된 5책임 철학(Safety / Detection / Clarity / Context / Observation)을 라이브러리화하여, 코딩 에이전트뿐 아니라 다른 vertical agent(첫 검증 대상: `apt-legal-agent`)에서도 재사용할 수 있게 만드는 것이 목표.

## 프로젝트 구조

```
minyoung-mah/
├── AGENTS.md                       # 이 파일 — AI와 기여자가 따를 규칙
├── README.md                       # 프로젝트 소개 + Phase 로드맵
├── pyproject.toml                  # name = "minyoung-mah"
├── .gitignore
├── minyoung_mah/                   # library 패키지 (아직 ax coding agent 코드의 사본 상태)
│   ├── core/                       # Orchestrator, state, tool binding
│   ├── subagents/                  # SubAgent 상태 머신
│   ├── memory/                     # SQLite + FTS5 메모리 스토어
│   ├── resilience/                 # watchdog/retry/progress_guard/safe_stop
│   ├── tools/                      # (Phase 2에서 examples로 이동 예정)
│   ├── cli/                        # (Phase 2에서 examples로 이동 예정)
│   ├── utils/
│   ├── config.py
│   ├── models.py
│   └── logging_config.py
├── examples/                       # 도메인별 reference application (Phase 2~3에서 채움)
│   └── (coding_agent/, apt_legal_agent/ — 예정)
├── tests/                          # 235개 테스트 (원본 그대로, Phase 2에서 library/application 분리)
├── docs/
│   ├── design/                     # 설계 스케치 4 문서 (Phase 1 완료)
│   │   ├── 01_core_abstractions.md
│   │   ├── 02_coding_agent_mapping.md
│   │   ├── 03_apt_legal_mapping.md
│   │   └── 04_open_questions.md
│   └── origin/                     # 전신 프로젝트(ax coding agent)의 설계 맥락
│       ├── README.md
│       ├── session-2026-04-12-0005.md   # 8차 (핫픽스 4건)
│       ├── session-2026-04-12-0006.md   # 9차 (35분 완주 실증, §10 메타 분석)
│       ├── EVIDENCE.md
│       └── AGENTS.origin.md
└── .ai/
    └── sessions/                   # 세션 핸드오프 문서
```

## 관련 프로젝트

- **`../ax_advanced_coding_ai_agent/`** — 전신 프로젝트. 2026-04-12 과제 제출 완료, 동결 상태. 9차 세션까지의 설계 서사가 `docs/origin/`에 보존되어 있음. minyoung-mah가 안정화되면 이 코딩 에이전트를 minyoung-mah API로 재배선(Phase 4).
- **`../apt-legal-mcp/`** — 첫 두 번째 검증 대상. 현재는 `docs/`에 3개 spec 문서만 있고 코드는 없음. minyoung-mah 위에서 처음부터 구현 예정 (Phase 3).

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

## 현재 Phase 상태 (2026-04-13 기준)

- **Phase 1 — Bootstrap & Design Sketch** ✅ 완료
  - 폴더 구조 + git 초기화 + 원본 코드 import (commit `361e072`)
  - Design sketch 4 문서 작성 (commit `4e71d2c`, 총 2200 라인)
- **Phase 2a — Library 뼈대 구축** ⏸️ 다음 세션 예정
  - `minyoung_mah/` 아래 6 protocol 정의 + opinionated default 구현
  - `examples/coding_agent/` 분리는 Phase 4에서
- **Phase 3 — apt-legal-agent 구축** ⏸️ Phase 2a 완료 후
  - `examples/apt_legal_agent/`에 greenfield 구현
- **Phase 4 — coding agent 이식** ⏸️ Phase 3 완료 후
  - 원본 `coding_agent/` 코드를 minyoung-mah API로 재배선

자세한 내용은 `docs/design/04_open_questions.md` §J1 참조.

## 5책임 철학 (라이브러리 경계의 기준)

원본 프로젝트의 7~9차 E2E 실증을 통해 정립된 철학. minyoung-mah는 이 5가지만 책임지고, 그 외 결정(역할 프롬프트, 도구 선택, 산출물 형식, 4-tier 모델 정의, 분쟁 유형 분류 등)은 application이 결정한다.

1. **Safety** — 권한 경계, 안전 중단, 무한 루프 방지
2. **Detection** — 장애·정체·반복 감지 (ProgressGuard, Watchdog)
3. **Clarity** — 관찰 가능한 로그와 trace
4. **Context** — SubAgent 간 context 전달 규칙
5. **Observation** — Langfuse 통합, timing 계측

이 철학에 어긋나는 것을 라이브러리에 추가하려면 **반드시 정당화 근거**가 필요합니다. 더 자세한 맥락은 `docs/origin/session-2026-04-12-0005.md`(8차 세션) 참조.

## 6 Core Protocols (Phase 1 design sketch 결과)

minyoung-mah가 외부로 노출할 protocol. 자세한 시그니처와 근거는 `docs/design/01_core_abstractions.md` 참조.

| # | Protocol | 책임 |
|---|---|---|
| 1 | `SubAgentRole` | "이 역할은 무엇을 하는가" — 역할 정의 (데이터) |
| 2 | `ToolAdapter` | "이 도구는 어떻게 호출하는가" — 외부 세계 접점 |
| 3 | `Orchestrator` | "역할들을 어떤 순서로 실행하는가" — `run_pipeline`(static) + `run_loop`(dynamic) + `invoke_role`(원자) |
| 4 | `ModelRouter` | "이 역할/tier에 어떤 모델을 쓰는가" |
| 5 | `MemoryStore` | "이 정보를 기억하고 꺼낸다" — tier 이름 configurable |
| 6 | `HITLChannel` | "사용자에게 묻고 응답을 받는다" — 채널 독립 |

## 개발 및 검증

### 환경 설정 (현재는 원본과 동일, Phase 2a에서 분리 예정)

```bash
pip install -e .
```

### 테스트

```bash
pytest                            # 235개 테스트 (원본 그대로 유지)
```

### 주의

- **원본 `../ax_advanced_coding_ai_agent/`는 절대 수정하지 않습니다**. 제출 완료 상태로 동결.
- minyoung-mah/minyoung_mah/는 현재 원본의 사본 상태이며, Phase 2a에서 본격적으로 리팩토링됩니다.
- 235개 테스트는 Phase 2a 동안 회귀 안전망 역할을 합니다. 라이브러리 분리 과정에서 테스트가 깨지면 라이브러리 분리 자체를 의심하세요.

## 디렉토리별 AGENTS.md

상위 디렉토리(`../ax_advanced_coding_ai_agent/`)는 모든 주요 디렉토리에 `AGENTS.md`를 두는 관례를 따랐습니다. minyoung-mah도 동일한 관례를 따르되, **Phase 2a에서 라이브러리 분리가 완료된 후** 디렉토리별 AGENTS.md를 작성합니다. 지금은 구조가 유동적이라 작성 비용 대비 수명이 짧습니다.

## 커밋 규칙

Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:` 등.
`.env`, `.db`, `.claude/`, `__pycache__/`는 커밋하지 않습니다.

## 참고

이 문서는 minyoung-mah 자체의 규칙이며, 원본의 AGENTS.md(동결)와는 별개로 진화합니다. 원본 규칙은 `docs/origin/AGENTS.origin.md`에 보존되어 있습니다.
