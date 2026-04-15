# `minyoung_mah/model/` — ModelRouter 기본 구현

`ModelRouter` 프로토콜(→ `core/protocols.py`)의 두 가지 기본 구현. 라우터는 **사전에 구성된 chat model 인스턴스를 tier 이름으로 분배**할 뿐, 모델 자체를 만들지 않습니다.

| 클래스 | 용도 |
|---|---|
| `SingleModelRouter` | 모든 (tier, role)에 동일한 모델을 돌려줍니다. tiered routing이 불필요한 애플리케이션(예: apt-legal이 `gpt-4o` 하나로 모든 역할 처리)용. |
| `TieredModelRouter` | `{"reasoning": …, "fast": …}` 형태의 tier 매핑. 선택적으로 `role_overrides`로 특정 역할만 다른 모델로 강제할 수 있습니다 (예: classifier는 무조건 저비용). |

## 규칙

1. **API 키, base URL, temperature, 프로바이더 선택은 여기서 하지 않습니다.** 모델을 실제로 구성하는 것은 애플리케이션이 자기 bootstrap 코드에서 합니다. 라우터는 이미 만들어진 핸들을 받아 저장·반환만 합니다.
2. **`ModelHandle`은 `Any`로 선언되어 있습니다** (`core/protocols.py`). 런타임에 필요한 것은 Orchestrator가 호출하는 duck-type 메서드(`ainvoke`, `bind_tools`, `with_structured_output`)뿐입니다. 라이브러리가 langchain `BaseChatModel`에 하드 의존하지 않도록 이 느슨함을 유지합니다.
3. **tier 이름은 라이브러리가 검사하지 않습니다.** 애플리케이션이 `"default"` 하나만 써도 되고, `"nano"/"mini"/"standard"/"max"` 4단을 써도 됩니다. Deep Insight 3-tier 패턴은 `docs/design/05_reference_topologies.md` §1에 박제되어 있지만, 라이브러리가 강제하지 않습니다.
4. **새 라우터**(예: 부하 분산, A/B 라우팅)를 추가할 때는 `resolve(tier, role_name) -> ModelHandle` 시그니처만 만족시키면 됩니다.

## 테스트

기본 라우터의 커버리지 확장은 `session-2026-04-15-0003.md`의 P1 백로그 항목입니다 (`SingleModelRouter` 기본 경로 테스트 추가).
