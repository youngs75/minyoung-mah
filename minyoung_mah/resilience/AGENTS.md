# `minyoung_mah/resilience/` — 타임아웃과 정체 감지

5책임 중 **Safety / Detection**의 집행 지점. watchdog timeout, progress guard(반복 감지), role-level retry 상한이 여기에 모입니다. tool-level 전이 오류 retry는 여기가 아니라 `core/tool_invocation.py`에 있습니다(C2 결정).

## 파일

- `policy.py` — `ResiliencePolicy` dataclass + `default_resilience()` 팩토리.
- `progress_guard.py` — `ProgressGuard`. 동일 액션/툴 호출 반복 감지, 최대 반복 상한.

## ResiliencePolicy

```python
@dataclass
class ResiliencePolicy:
    role_timeouts: dict[str, float]        # 역할별 wall-clock timeout(초)
    fallback_timeout_s: float = 90.0       # role_timeouts에 없는 역할 기본값
    role_max_retries: dict[str, int]       # 역할별 semantic retry 상한
    fallback_max_retries: int = 1          # 기본 semantic retry 상한
    progress_guard: ProgressGuard          # 기본은 disabled()
```

두 가지 조회 API: `timeout_for(role)`, `max_retries_for(role)`.

## `default_resilience()` 기본값의 근거

- `fallback_timeout_s=180` — apt-legal 실소비자 경험(2026-04-15)에서 도출. 90초 기본값은 15-tool MCP 카탈로그를 자율 탐색하는 `legal_lookup` 같은 역할에 턱없이 부족했고, 즉시 watchdog abort가 터졌습니다. 180초는 단일 역할 예산을 대부분 provider의 request timeout 내로 유지하면서 multi-tool deliberation 여유를 남깁니다.
- `fallback_max_retries=1` — semantic retry는 한 번까지. 그 이상은 escalate.
- `progress_guard` **기본 disabled** — 정적 파이프라인은 반복이 구성 시점에 이미 bounded입니다. 소비자가 `invoke_role` 위에서 동적 driver-role loop를 조립할 때만 `default_resilience(enable_progress_guard=True)`로 활성화하세요.

### apt-legal 실측 예시 (권장 per-role override)

```python
default_resilience(
    role_timeouts={
        "router": 30.0,          # structured fast path, 1 LLM call
        "domain_lookup": 240.0,  # 8-tool MCP, up to 10 iterations
        "legal_lookup": 300.0,   # 15-tool MCP, up to 10 iterations
        "synthesizer": 120.0,    # 1 LLM call over accumulated state
    },
)
```

## 두 retry 레이어 구분 (중요)

| 레이어 | 어디에 | 무엇을 | 어떻게 결정 |
|---|---|---|---|
| **tool-level** | `core/tool_invocation.py::ToolRetryPolicy` | 전이 오류(`TIMEOUT`, `RATE_LIMIT`, `NETWORK`)만 | 자동, exponential backoff |
| **role-level** | `resilience/policy.py::role_max_retries` | semantic 실패(역할이 판단) | 역할이 자기 판단으로 재호출; 정책은 **상한만** 노출 |

이 구분을 섞으면 "네트워크 오류인데 역할 로직이 다시 돌면서 프롬프트가 오염되는" 클래스의 버그가 재발합니다(8차 세션 근거). tool-level에서 이미 처리된 오류를 role-level이 모르게 감추지 마세요.

## 불변 규칙

1. `ResiliencePolicy` 필드를 늘릴 때는 **기본값을 반드시 제공**해서 기존 소비자의 생성자 호출을 깨뜨리지 않습니다.
2. watchdog timeout은 **`Orchestrator.invoke_role`에서 `asyncio.wait_for`로 강제**됩니다. 역할 내부에서 자체 timeout을 또 걸면 경쟁 상태가 생깁니다 — 걸지 마세요.
3. `ProgressGuard`는 상태를 가지며 역할마다 격리되지 않습니다(현재는 Orchestrator 공유). 동적 loop에서 재사용할 때는 초기화 시점을 명확히 합니다.

## 테스트

`tests/library/test_progress_guard.py` — 반복 감지, 최대 반복 상한, disabled 모드.
