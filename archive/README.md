# archive/

이 디렉토리는 minyoung-mah 라이브러리가 "소비자 코드도 같이 들고 있어야 하나"를 고민하던 초기 단계의 co-design 산출물을 보존합니다. **현재는 아무 것도 active하지 않습니다** — 빌드, 테스트, import 경로 어디에도 참여하지 않습니다.

## 경계 재정의 (2026-04-15)

minyoung-mah는 순수 multi-agent harness 라이브러리로 범위를 좁혔습니다. 소비자(`ax-coding-agent`, `apt-legal-agent`)는 각자 별도 리포에서 minyoung-mah를 editable install로 소비합니다. 따라서 이 리포는:

- **library 코드**(`minyoung_mah/`)와
- **library 자체 테스트**(`tests/library/`),
- **library-facing 설계 문서**(`docs/design/01_core_abstractions.md`, `docs/design/04_open_questions.md`)

만 적극적으로 관리합니다. 소비자 매핑 문서나 소비자 애플리케이션 예시는 여기 `archive/`에 묶어 보존합니다.

## 내용물

### `apt_legal_agent_demo/`

2026-04-14~15 세션에 "library와 apt-legal 예제를 한 리포에서 co-design"한다는 가정으로 작성된 레퍼런스 애플리케이션. 당시 가정한 MCP 토폴로지는 **단일 `apt-legal-mcp` 서버 + 6 tool**(search_law, get_law_article, search_precedent, get_precedent_detail, search_interpretation, compare_laws)이었고, 역할 구성은 **classifier → retrieval_planner → ExecuteToolsStep → responder** 4-step static pipeline + A2A (FastAPI + SSE) 레이어입니다.

그 후 실제 `apt-legal-agent` 리포의 아키텍처가 **두 MCP 서버**(`kor-legal-mcp` 법령 공통 + `apt-domain-mcp` 단지별 관리규약/회의록/위키)와 **router + legal_lookup + domain_lookup + synthesizer** 4-role 구성으로 재정립되면서, 이 데모의 shape은 실제 소비자와 맞지 않게 되었습니다. 실제 구현은 `../apt-legal-agent/` 리포(별도)에서 Phase 2에 착수 예정.

다만 co-design 과정에서 library에 흡수된 것이 하나 있습니다 — **`ExecuteToolsStep`** (LLM 없이 priority 그룹별 병렬 tool 디스패치). 이건 `minyoung_mah/core/`에 남아 있고 테스트도 `tests/library/test_execute_tools_step.py`에서 계속 돌아갑니다. 나머지 데모 코드(A2A layer, FastAPI app, roles/prompts/models, MCP proxy adapter, fake test fixture)는 이 archive에서만 열람 가능.

### `docs/02_coding_agent_mapping.md`

ax-coding-agent를 minyoung-mah 위에 어떻게 올릴지 설명한 Phase 1 설계 스케치. 소비자 매핑 문서라 경계 재정의 후 library 문서에서 빠짐.

### `docs/03_apt_legal_mapping.md`

위 `apt_legal_agent_demo/`의 설계 근거 문서. 단일 `apt-legal-mcp` 가정 기반이라 현재 `apt-legal-agent` 리포 설계와는 불일치.

## 다시 들여다 볼 가치가 있는 상황

- minyoung-mah 위에 새 vertical agent를 설계할 때 "어떤 shape이 가능한가"의 레퍼런스로.
- `ExecuteToolsStep` + static pipeline + A2A/SSE 연동을 한 번에 보고 싶을 때.
- 실제 `apt-legal-agent` 리포가 Phase 2에 들어가면, FakeChatModel / FakeMCPClient 테스트 구성이나 HITL/Observer→SSE 브릿지는 새 shape에 맞게 복사해 쓸 수 있습니다.

단, 여기 있는 코드를 다시 active 경로로 되살리지는 마세요. 되살릴 가치가 있다면 library에 흡수하거나(`ExecuteToolsStep`처럼) 소비자 리포에 재구현하는 것이 경계에 맞습니다.
