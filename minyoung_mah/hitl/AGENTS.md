# `minyoung_mah/hitl/` — Human-in-the-Loop 채널

`HITLChannel` 프로토콜(→ `core/protocols.py`)의 세 가지 기본 구현이 들어 있습니다. 이 디렉토리의 코드는 "사용자에게 묻고 응답을 받는다"라는 단일 책임만 집행하며, **응답 해석·역할별 분기·권한 체크는 하지 않습니다** (그건 호출자의 책임).

## 들어 있는 채널

| 클래스 | 용도 | 특징 |
|---|---|---|
| `NullHITLChannel` | CI, 자동화, 테스트, HITL이 트리거되지 않는 것이 **보장된** 파이프라인 | `ask()`가 항상 동일한 `default_choice`를 즉시 반환. `notify()`는 no-op. 블로킹 없음. |
| `TerminalHITLChannel` | 로컬 대화형 개발 | 표준 입출력으로 사용자에게 질문/선택지를 표시하고 답을 읽어옵니다. |
| `QueueHITLChannel` | 외부 전달(A2A SSE, 웹훅, 테스트 상호작용) | `asyncio.Queue` 기반. 질문을 큐에 넣고 응답을 기다립니다. 바깥쪽 transport는 임의. |

## 규칙

1. **`ask()`는 블로킹 async.** 어떻게 블로킹할지는 구현의 자유(터미널 readline, SSE long-poll, Queue.get). 그러나 Orchestrator에서 볼 때는 항상 `await hitl.ask(...)`입니다.
2. **`notify()`는 비파괴적이어야 합니다.** 실패하더라도 Orchestrator로 예외가 올라가면 안 됩니다. 기본 구현처럼 no-op 또는 best-effort로 처리합니다.
3. **채널은 도메인을 모릅니다.** "어떤 질문을 할지"는 역할 또는 애플리케이션이 결정하고, 채널은 그대로 전달만 합니다. 질문 템플릿 파일 같은 것은 여기에 두지 않습니다.
4. **새 채널을 추가할 때**는 `HITLChannel` 프로토콜을 duck-type하면 되며, 클래스 상속은 필요 없습니다.

## 테스트

HITL 로직은 파이프라인 동작과 얽혀 있어 전용 테스트 파일이 아직 없습니다. 새 채널을 추가하면 `tests/library/test_hitl_*.py`를 만들고 `QueueHITLChannel`을 포함한 케이스를 추가하는 것이 다음 품질 개선 백로그 항목입니다.
