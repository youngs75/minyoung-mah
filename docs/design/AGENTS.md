# `docs/design/` — library-facing 설계 문서

라이브러리 자체의 **설계 근거**를 박제하는 곳입니다. 운영 매뉴얼(README), 아키텍처 투어(`docs/ARCHITECTURE.md`), 원본 서사(`docs/origin/`)와는 역할이 다릅니다.

## 파일

| 파일 | 무엇을 담나 | 언제 갱신하나 |
|---|---|---|
| `01_core_abstractions.md` | 6 Core Protocol의 시그니처·책임·근거 | protocol 시그니처 변경 시. 이 문서가 계약의 서술적 소스입니다. |
| `04_open_questions.md` | 결정 대기 중이거나 OBSOLETE된 설계 질문들. K1~K5 | 질문이 결정되거나, 기존 결정이 뒤집히거나, 새로운 질문이 드러났을 때. |
| `05_reference_topologies.md` | 참고용 패턴 박제 (Deep Insight 3-tier, Observability 분할 등). **구현 강제가 아님** | 소비자에서 새로 드러난 패턴이 라이브러리 경계 안에 흡수할 가치가 있을 때. |

`02_coding_agent_mapping.md`와 `03_apt_legal_mapping.md`는 경계 재정의(2026-04-15 세션 0001)에서 `archive/docs/`로 이동했습니다. 이 디렉토리에 다시 넣지 마세요 — library 리포는 소비자 매핑을 품지 않습니다.

## 규칙

1. **문서 번호는 한 번 부여되면 재활용하지 않습니다.** 02/03이 archive로 이동했어도 새 문서는 06 이후로 붙입니다.
2. **`04_open_questions.md`의 항목을 삭제하지 마세요.** 해결된 항목은 본문을 `[RESOLVED — YYYY-MM-DD]` 또는 `[OBSOLETE — YYYY-MM-DD]`로 전환하고 근거를 남깁니다. 결정의 이유를 잃으면 나중에 같은 논의를 다시 합니다.
3. **`05_reference_topologies.md`는 문서일 뿐 구현을 강제하지 않습니다.** "이런 패턴이 있더라"를 박제해서 소비자가 참고하도록 하는 것이 목적. Deep Insight 3-tier를 라이브러리가 강제하면 경계가 무너집니다.
4. **origin 문서 링크**(`docs/origin/session-*.md`)는 읽기 전용입니다. 새 세션 핸드오프는 `docs/origin/`이 아니라 `.ai/sessions/`로 갑니다.

## 관련 문서

- **운영·설치 관점**: `../../README.md`
- **아키텍처 투어(전체 그림)**: `../ARCHITECTURE.md`
- **원본 프로젝트 서사**: `../origin/` (읽기 전용)
- **리포 전체 규칙**: `../../AGENTS.md`
