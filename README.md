# minyoung-mah

**Multi-Agent Harness by Youngsuk × Minji (Claude).**

`minyoung-mah`는 범용 Multi-Agent Harness 라이브러리입니다.
도메인 특화 agent(예: coding agent)를 만들 때 재사용할 수 있도록
다음 4가지 축을 분리된 모듈로 제공합니다.

1. **Agentic Loop Core** (`minyoung_mah/core/`) — LangGraph 기반 상태 그래프, orchestrator, tool adapter interface
2. **Dynamic SubAgents** (`minyoung_mah/subagents/`) — 런타임 역할/모델/도구 결정, CREATED → ASSIGNED → RUNNING → COMPLETED → DESTROYED 상태 머신
3. **Resilience** (`minyoung_mah/resilience/`) — watchdog, retry, progress guard, safe stop (7가지 장애 유형 대응)
4. **3-Tier Memory** (`minyoung_mah/memory/`) — user / project / domain 계층, SQLite + FTS5

## 설계 철학 — Harness의 5가지 책임만 남긴다

Harness는 결과물의 형식을 강제하지 않습니다. 오직 다음 5가지만 책임집니다:

1. **Safety** — 권한 경계, 안전 중단
2. **Detection** — 장애·정체·반복 감지
3. **Clarity** — 관찰 가능한 로그·trace
4. **Context** — SubAgent 간 컨텍스트 전달 규칙
5. **Observation** — Langfuse 통합, timing.subagent.invoke 계측

역할 프롬프트, 도구 선택, 산출물 형식은 **사용자(상위 application)가** 결정합니다.
이 철학은 원본 프로젝트(`ax_advanced_coding_ai_agent`)의 7~9차 E2E 실증을 통해
정립되었으며, `docs/origin/`에 그 서사가 보존되어 있습니다.

## 현황

- **Phase 1 (진행 중)**: 원본 `ax_advanced_coding_ai_agent`에서 코드 import + 골격 세팅
- **Phase 2 (예정)**: coding-specific 코드를 `examples/coding_agent/`로 분리, `minyoung_mah` 라이브러리는 도메인 중립 코어만 남김
- **Phase 3 (예정)**: 라이브러리 API 안정화, 레퍼런스 예시로 coding agent 재빌드 후 회귀 검증

## 관련 프로젝트

- [`ax_advanced_coding_ai_agent`](../ax_advanced_coding_ai_agent) — 원본 coding agent (2026-04-12 과제 제출 완료). 9차 E2E까지의 설계 서사와 실증 데이터 보유.

## 라이선스

TBD
