# `tests/library/` — 라이브러리 단위 테스트

이 트리는 `minyoung_mah/` 패키지의 **유일한 active 테스트 스위트**입니다. 33개 테스트, 네트워크 없음, 초 단위 완주.

## 실행

```bash
pytest tests/library/
```

`tests/` 최상위에는 과거 coding agent에서 가져온 broken 파일이 없습니다 (Phase 2b에서 전부 삭제). 새 테스트는 반드시 `tests/library/` 아래에 둡니다.

## 파일 매핑

| 파일 | 커버하는 모듈 |
|---|---|
| `test_orchestrator_structured.py` | `Orchestrator._invoke_structured` (fast path, `with_structured_output`) |
| `test_orchestrator_tool_loop.py` | `Orchestrator._invoke_loop` (일반 tool-call 루프, iteration 상한, allowlist 위반) |
| `test_pipeline.py` | `StaticPipeline` 조립, `fan_out`, `condition`, `on_step_failure` 모드(`abort`/`continue`/`escalate_hitl`) |
| `test_execute_tools_step.py` | `ExecuteToolsStep` LLM-less 툴 디스패치, 우선순위 그룹, `continue_on_failure` |
| `test_tool_invocation.py` | `ToolInvocationEngine` tool-level retry, `TRANSIENT_ERRORS` 분류 |
| `test_registry.py` | `RoleRegistry` / `ToolRegistry` 이름 충돌, allowlist 필터 |
| `test_memory_store.py` | `SqliteMemoryStore` tier/scope 격리, FTS5 검색 |
| `test_observer_events.py` | `EVENT_NAMES` canonical 세트, `CollectingObserver` 시퀀스 |
| `test_progress_guard.py` | `ProgressGuard` 반복 감지, 최대 반복 상한 |

## 작성 원칙

1. **네트워크 금지.** LLM은 `conftest.py`의 fake/fixture로 대체합니다. 새 테스트에서 실제 HTTP 호출이 필요하면 설계가 틀린 것입니다.
2. **fixture로 fake ModelHandle·Observer·HITL을 재사용하세요** — `conftest.py`를 먼저 확인.
3. **한 파일은 한 모듈의 책임 하나에 집중.** 파이프라인 테스트 안에서 registry 충돌까지 검사하지 마세요. 파일이 커지면 쪼갭니다.
4. **새 Observer 이벤트를 추가**했다면 `test_observer_events.py`의 canonical 세트 assertion이 먼저 업데이트되어야 합니다.
5. **비동기 테스트는 `pytest-asyncio` 없이 이미 동작**하도록 conftest가 구성되어 있습니다. 기존 패턴을 따르세요.

## 다음 확장 후보 (세션 0003 P1 백로그)

- `QueueHITLChannel` — 블로킹/해제 경로
- `CompositeObserver` — 부분 실패가 삼켜지는지
- `Orchestrator` `fan_out` 병렬성
- `SingleModelRouter` 기본 경로 스모크
