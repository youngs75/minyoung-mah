# docs/origin — 원본 프로젝트의 설계 맥락

이 디렉토리는 `minyoung-mah`의 전신인 `ax_advanced_coding_ai_agent`에서
라이브러리 설계에 직접 영향을 준 문서만을 선별하여 보존합니다.

**원본 프로젝트 위치**: `../../../ax_advanced_coding_ai_agent/`
**원본 제출**: 2026-04-12 (SDS AX Advanced 2026-1 과제)

## 파일

| 파일 | 원본 경로 | 역할 |
|---|---|---|
| `session-2026-04-12-0005.md` | `.ai/sessions/` | 8차 세션 — Sub-B + Phase 3 A/B/C + 사후 핫픽스 4건. Harness 5책임 철학 정립 |
| `session-2026-04-12-0006.md` | `.ai/sessions/` | 9차 세션 — 핫픽스 4건 실증 (35분 완주, verifier 97% 감소) + §10 메타 분석 |
| `EVIDENCE.md` | 루트 | 전체 실증 데이터. 특히 §10 "과제 요구사항의 구조적 분석"이 라이브러리 설계 철학의 근간 |
| `AGENTS.origin.md` | `AGENTS.md` | 원본 프로젝트의 규칙 문서 (참고용, 파일명 충돌 방지 위해 rename) |

## 왜 이 문서들인가

`minyoung-mah`의 "Harness 5책임" 철학 —
**Safety / Detection / Clarity / Context / Observation만 책임지고, 역할·도구·산출물 형식은 사용자가 결정** —
은 원본 프로젝트의 7차~9차 E2E 실증 과정에서 정립되었습니다.

이 문서들이 없으면 라이브러리 API 설계 시 "왜 X를 강제하지 않는가?"라는 질문에
답할 수 없게 됩니다. 향후 Phase 2/3 리팩토링 과정에서 판단 근거로 참조하세요.
