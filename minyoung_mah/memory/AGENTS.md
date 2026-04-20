# `minyoung_mah/memory/` — MemoryStore 기본 구현

`MemoryStore` 프로토콜(→ `core/protocols.py`)의 두 가지 기본 구현.

| 클래스 | 용도 |
|---|---|
| `SqliteMemoryStore` | 기본값. SQLite + FTS5 전문 검색, `(tier, scope, key)` unique 제약. |
| `NullMemoryStore` | 모든 쓰기를 버립니다. 개인정보 제약으로 **메모리를 남기면 안 되는 소비자**를 위한 안전 기본값. |

## 핵심 개념

- **`tier`**: 애플리케이션이 정의하는 문자열. 라이브러리는 `"short_term"`, `"semantic"` 같은 이름을 강제하지 않습니다. 코딩 에이전트는 자기 tier 세트를, apt-legal은 다른 세트를 씁니다.
- **`scope`**: tier 안의 부분 집합을 가리키는 선택적 문자열(프로젝트 id, 사용자 id, 세션 id). `search(scope=None)`은 모든 scope를 검색합니다.
- **스키마는 의도적으로 원본 coding agent와 호환되지 않습니다** (decision D1). `layer → tier`, `project_id → scope` 리네임이 이유. 마이그레이션 도구는 제공하지 않습니다.

## 회수 경로 — `search` vs `list_by_scope`

두 가지 회수 API가 제공됩니다. tier 성격에 맞는 쪽을 고르세요.

| API | 인덱스 | 적합한 tier |
|---|---|---|
| `search(tier, query, scope, limit)` | FTS5 전문 검색 | `semantic`, `preference` 같이 **키워드 매치가 의미 있는** tier |
| `list_by_scope(tier, scope, limit, order)` | 없음 (직접 SELECT + ORDER BY) | `short_term` 같이 **"최근 N개"가 유효 회수** 인 tier |

0.1.6에서 `list_by_scope`가 추가됐습니다. 도입 계기는 apt-legal-agent의 실측 사례 — 한국어 답변이 저장된 `short_term` tier를 영문 query로 `search` 호출하면 FTS 매치 0건. short_term은 "무엇이 저장됐나"를 쿼리로 찾는 게 아니라 "직전 N개"를 시간순으로 보는 게 본래 용도라, 전용 API를 분리했습니다. FTS tokenizer를 CJK 친화로 바꾸는 옵션도 후보였지만, 그 변경은 `semantic`/`preference`에는 이득이 없고 부작용만 있어 **검색 경로 자체를 분리**하는 게 합리적이었습니다.

## 규칙

1. **라이브러리는 tier/scope 이름의 의미를 검사하지 않습니다.** 빈 문자열이 아니면 통과. 의미는 소비자 책임.
2. **`MemoryExtractor`는 여기 살지 않습니다.** Orchestrator가 파이프라인 종료 후 선택적으로 호출하는 애플리케이션 훅이며, 기본 구현을 제공하지 않습니다 (privacy opt-in).
3. **새 백엔드를 추가할 때** (예: Redis, Postgres)는 `MemoryStore` protocol을 duck-type하고, `asyncio`를 블로킹하지 않도록 `asyncio.to_thread` 또는 native async 드라이버를 사용합니다. `SqliteMemoryStore`가 `to_thread` 패턴의 참고가 됩니다.
4. **스키마 마이그레이션**은 이 파일에서 하지 않습니다. 소비자가 자기 리포에서 자기 DB를 관리합니다.

## 테스트

`tests/library/test_memory_store.py` — `SqliteMemoryStore`의 tier/scope 격리, FTS5 검색, 업서트 동작을 커버합니다. `NullMemoryStore`는 no-op이라 별도 테스트가 불필요.
