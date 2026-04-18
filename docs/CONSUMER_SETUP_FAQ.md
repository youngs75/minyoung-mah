# Consumer Setup FAQ

minyoung-mah 를 소비하는 프로젝트에서 자주 부딪히는 설정/사용 이슈. 실제 소비자(prime-jennie-runtime, apt-legal-agent) 가 마주친 사례 기반.

라이브러리 자체 설계는 [`ARCHITECTURE.md`](./ARCHITECTURE.md), 역할 정의는 [`design/01_core_abstractions.md`](./design/01_core_abstractions.md) 참고.

---

## Q1. `pip install -e` 가 `uv.lock` 을 건드리지 않는데, 왜 CI 에서 버전이 다르지?

**증상**: 로컬에서 `uv pip install -e ../minyoung-mah` 로 0.1.2 로 개발 중인데 CI / 배포 결과물은 여전히 0.1.1 (또는 `pyproject.toml` 의 git+tag 버전).

**원인**: editable install 은 현재 venv 의 site-packages 만 심볼릭 링크로 교체. `uv.lock` 은 변하지 않음. CI / 배포는 `uv.lock` 에 잠긴 git+tag 또는 PyPI 버전을 resolve.

**해결**:
```bash
# CI 직전에 uv.lock 을 실 소비 버전으로 강제 업데이트
uv sync --reinstall-package minyoung-mah

# 또는 pyproject.toml 의 버전 핀 자체를 올리고 lock 재생성
# (pyproject.toml)
# dependencies = ["minyoung-mah>=0.1.2"]
uv lock --upgrade-package minyoung-mah
```

**권장 워크플로**:
- 로컬 기능 개발: editable install 로 빠른 iteration
- 기능 안정화 후: minyoung-mah master 에 커밋 + tag (또는 PyPI publish)
- 소비자 repo 에서 `uv.lock` 업데이트 → commit → CI/배포

**예시 (prime-jennie-runtime)**:
- `pyproject.toml`: `minyoung-mah>=0.1.0` 로 하위 호환 유지
- 2026-04-18 현재 minyoung-mah 0.1.2 master push 완료, PyPI publish 대기. publish 되면 다음 `docker compose build` 에서 자동 승격 (코드 수정 불필요).

---

## Q2. `shared_state` 는 언제 쓰고 언제 안 쓰나?

**상황**: StaticPipeline 에서 모든 step 이 같은 데이터(예: `complex_id`) 에 접근해야 할 때.

**apt-legal 의 패턴** (pipeline-wide 상수):
```python
StaticPipeline(
    shared_state={"complex_id": "01HXXSOL..."},  # 모든 step 가 읽기만
    steps=[
        PipelineStep(name="router", ...),
        PipelineStep(name="legal_lookup", ...),  # shared_state.complex_id 접근
        PipelineStep(name="domain_lookup", ...), # 동일
        PipelineStep(name="synthesizer", ...),   # 동일
    ],
)
```
각 `role.build_user_message(invocation)` 에서 `(invocation.shared_state or {}).get("complex_id")` 로 읽음.

**안 쓸 때 (prime-jennie-runtime 의 경우)**:
- Scout / Macro 는 결정론적 후처리 위주 → step 간 context 공유 필요 없음
- 대신 `InvocationContext.metadata` 에 `scout_context`, `macro_context` 같은 step 별 입력을 pipeline 조립 단계에서 직접 주입

**선택 기준**:
- "모든 step 이 같은 값을 **읽기만**" 하는가? → YES 면 `shared_state`
- step 별로 **다른 입력** 이 필요한가? → NO, 각 step 의 `InvocationContext.metadata` 에 주입
- step 이 **쓰기** 해야 하는가? → 대안은 `parent_outputs` 로 상위 step 결과 참조

**주의**: shared_state 는 pipeline 전체 immutable. 쓰기는 parent_outputs 경유.

---

## Q3. `metadata['usage']` 가 `None` 이면 어떻게 하나?

**상황**: 0.1.1 이하 또는 mock 모델 사용 시 `RoleInvocationResult.metadata` 에 `usage` 키 없음 또는 `None`.

**3-priority fallback 패턴** (prime-jennie-runtime `persistence._resolve_cost`):
```python
def _resolve_cost(meta: dict, model: str, prompt_chars: int, output_chars: int) -> float:
    # 1순위: 명시적 cost_usd (누가 미리 계산했다면)
    if (cost := meta.get("cost_usd")) is not None:
        return float(cost)

    # 2순위: metadata.usage 실측 (0.1.2+ provider)
    usage = meta.get("usage")
    if isinstance(usage, dict) and {"input_tokens", "output_tokens"} <= usage.keys():
        return _real_cost(model, usage)   # usage × pricing 표

    # 3순위: char 기반 추정 (±20% 오차)
    return _estimate_cost(model, prompt_chars, output_chars)
```

**0.1.2 업그레이드 이점**:
- LangChain `AIMessage.usage_metadata` → `RoleInvocationResult.metadata['usage']` 자동 전파
- Anthropic / OpenAI / DeepSeek 모두 표준 usage 필드 제공 → 추정 대신 실측
- mock provider (LangChain `FakeListLLM` 등) 는 usage 없음 → char 추정 fallback

**소비자 권장**:
- 비용 추적이 중요하면 `minyoung-mah>=0.1.2` 명시 + 실 provider 사용
- mock 으로 테스트할 땐 `cost_usd=None` 으로 돌리고 fallback 만 검증

---

## Q4. `output_schema` + `max_iterations=1` + `tool_allowlist=[]` 조합은 왜 중요한가?

**Orchestrator 의 structured output fast path** (LLM `with_structured_output` 직접 사용) 는 3 조건 **모두** 충족 시에만 활성:

1. `output_schema is not None` (Pydantic BaseModel)
2. `tool_allowlist == []` (도구 호출 불가)
3. `max_iterations == 1` (LLM 단 1회)

하나라도 부족하면 일반 tool-calling loop 로 빠져서 최종 prompt 에서 JSON 을 직접 뽑아 파싱하게 됨 → 파싱 실패 시 recovery 부담.

**fast path 예시** (prime-jennie-runtime Scout):
```python
@dataclass(frozen=True)
class ScoutRole:
    name: str = "scout"
    system_prompt: str = SCOUT_SYSTEM_PROMPT
    tool_allowlist: list[str] = field(default_factory=list)  # ✓ 빈 리스트
    model_tier: str = "strong"
    output_schema: type[BaseModel] | None = ScoutOutput      # ✓ Pydantic
    max_iterations: int = 1                                  # ✓ 1회

    def build_user_message(self, invocation): ...
```
→ structured fast path 작동. `ScoutOutput` Pydantic 스키마로 안전하게 파싱.

**일반 loop 예시** (apt-legal legal_lookup):
```python
StaticRole(
    name="legal_lookup",
    output_schema=None,                     # 구조화 X
    tool_allowlist=["search_legal"],        # 도구 호출 필요
    max_iterations=10,                      # 반복 검색 가능
)
```
→ tool-calling loop 로 최종 자연어 결과 생성.

**교훈**: "구조화 JSON 이 꼭 필요한가?" 라고 묻고, YES 면 3 조건 모두 맞춤. NO 면 최종 자연어 + downstream 소비자에서 파싱.

---

## Q5. `PipelineStepResult.format_for_llm()` 이 `INCOMPLETE` 도 노출하는 이유?

**실제 사례 (apt-legal scenario-3)**: synthesizer 가 legal_lookup 의 결과를 읽을 때, legal_lookup 이 timeout 으로 INCOMPLETE 상태.

**0.1.0 이전**: INCOMPLETE 결과를 조용히 필터 → synthesizer 가 "법령 자료 없음" 으로 잘못 판단 → "해당 조항 없음" 답변 생성 (hallucination).

**0.1.0 개선**: `format_for_llm()` 기본값 `include_incomplete=True` — status banner 포함:
```
[role=legal_lookup status=INCOMPLETE iterations=10] error=timeout
(partial tool results if any)
```

**효과**: synthesizer 가 "이 자료는 불완전함" 을 알고 답변에 조심스러워질 수 있음.

**사용 예**:
```python
# roles.py 의 synthesizer.build_user_message:
for step_name, step_result in (invocation.parent_outputs or {}).items():
    if isinstance(step_result, PipelineStepResult):
        block = step_result.format_for_llm()   # include_incomplete=True (default)
        parts.append(f"\n[{step_name}]\n{block}")
```

**override (비권장)**: `step_result.format_for_llm(include_incomplete=False)` — INCOMPLETE/FAILED/ABORTED 는 빈 문자열. 상류 실패가 downstream 에 영향 주지 말아야 할 특수 경우에만.

---

## Q6. `invocation.metadata['key']` 로 context 를 주입하려는데 누가 넣어야 하나?

**Orchestrator 는 metadata 를 자동 주입하지 않는다.** `InvocationContext.metadata` 는 pipeline 조립 단계 — 즉 `PipelineStep.input_mapping` 함수 — 의 책임.

**prime-jennie-runtime Scout 예시**:
```python
PipelineStep(
    name="scout",
    role="scout",
    input_mapping=lambda state: InvocationContext(
        task_summary="stock screening",
        user_request="",
        metadata={"scout_context": ScoutContext(...)},  # ← 여기!
    ),
),
```

`ScoutRole.build_user_message(invocation)` 안에서:
```python
ctx = invocation.metadata.get("scout_context")
if ctx is None:
    raise ValueError("scout_context required in metadata")
return build_user_prompt(ctx)
```

**권장 패턴**:
- Role 문서에 "기대 metadata 키" 를 명시
- pipeline 조립 시 `input_mapping` 에서 해당 키를 명시적 주입
- 누락 시 Role 내부에서 명시적 ValueError (silent fail 방지)

---

## Q7. `TieredModelRouter` vs `SingleModelRouter` 는 언제 갈라서 쓰나?

**prime-jennie-runtime** (Tiered):
```python
TieredModelRouter({
    "strong": ChatLiteLLM(model="deepseek-chat"),
    "reasoning": ChatAnthropic(model="claude-opus-4-7"),
    "shadow_reasoning": ChatLiteLLM(model="deepseek-chat"),  # shadow 평가용
})
```
이유:
- Scout (빠른 추론 + 적은 비용) → DeepSeek `"strong"` tier
- Macro (깊은 분석 + 높은 정확도) → Claude Opus `"reasoning"` tier
- Macro shadow (병렬 평가 / 비교) → DeepSeek `"shadow_reasoning"` tier

**apt-legal-agent** (Single):
```python
SingleLiteLLMRouter(ChatLiteLLM(model="..."))
```
이유: router / legal_lookup / domain_lookup / synthesizer 모두 비슷한 자연어 처리 수준 → 같은 모델로 충분.

**기준**:
- tier 별 모델 분리가 의미 있는 비용/성능 차이를 만드는가?
- 개발 초기엔 Single 로 단순화, 병목/비용 issue 발생 시 Tiered 전환
- v3 의 Macro vs Scout 은 분리가 명확한 사례 — Opus 는 Macro 만

---

## Q8. 버전 업그레이드 (0.1.0 → 0.1.2) 시 주의점?

### 0.1.0 → 0.1.1 (2026-04-15)
- `format_for_llm()` 이 tool_results 도 노출 (INCOMPLETE 일 때 도구 결과가 있으면 fallback body)
- **Breaking 없음** — forward compatible

### 0.1.1 → 0.1.2 (2026-04-18)
- `RoleInvocationResult.metadata["usage"]` — LangChain `AIMessage.usage_metadata` 자동 전파 (Anthropic / OpenAI / DeepSeek 표준)
- consumer 는 metadata 키 추가만 — **Breaking 없음**
- prime-jennie-runtime 은 `_resolve_cost` 의 3-priority fallback 으로 승격 (코드 수정 0)
- apt-legal 은 비용 추적 안 해도 그만

### 소비자별 권장 버전 핀
- apt-legal-agent: `minyoung-mah>=0.1.0` (비용 추적 미사용)
- prime-jennie-runtime: `minyoung-mah>=0.1.2` (실측 토큰 비용)
- 신규 소비자: 최신 (`>=0.1.2`)

### PyPI publish 상태
- 0.1.2 는 2026-04-18 시점 master 커밋만 존재. PyPI publish 미수행 (사용자 액션 대기).
- publish 절차: `cd ~/projects/minyoung-mah && uv build && uv publish`
- publish 되면 소비자의 `uv.lock` 재생성 없이도 다음 rebuild 에서 자동 승격

---

## Q9. 테스트에서 Orchestrator 를 어떻게 mock 하나?

### minyoung-mah 제공 utility
- `tests/library/conftest.py` — mock ModelRouter, CollectingObserver, NullMemoryStore fixture 다수
- `NullObserver` — 관찰 이벤트 drop (production 기본은 emitter)

### 소비자 패턴 A (prime-jennie-runtime 실제 코드)
```python
# tests/slow_loop/test_pipeline_e2e.py
from minyoung_mah import Orchestrator, TieredModelRouter, NullMemoryStore, NullHITLChannel

def test_scout_e2e(mock_observer, mock_model_router, stub_feeders):
    orchestrator = Orchestrator(
        roles=role_registry,
        tools=tool_registry,
        model_router=mock_model_router,  # 미리 응답 스크립팅
        memory=NullMemoryStore(),
        hitl_channel=NullHITLChannel(),
        observer=mock_observer,
        resilience=default_resilience(fallback_timeout_s=5),
    )
    result = await orchestrator.run_pipeline(pipeline, ctx, mock_observer)
    assert result.steps["scout"].status == "SUCCESS"
```

`mock_model_router` 는 `TieredModelRouter({"strong": FakeListLLM(...)})` 같이 LangChain fake 모델 주입.

### 소비자 패턴 B (apt-legal 계획)
MCP adapter 를 mock `MCPSession` 으로 대체 + ToolAdapter 레벨에서 응답 스크립팅. 현재 E2E 테스트 미구현 (unit 테스트 위주).

### 권장 계층
1. **Unit**: Role 의 `build_user_message` 로직 (context 없이 호출해서 prompt 문자열 검증)
2. **Integration**: StaticPipeline 조립 + fake ModelRouter + fake ToolAdapter 로 end-to-end flow
3. **E2E** (선택): 실 LLM / MCP 호출. dev 환경에서만 (비용 고려)

---

## Q10. 문제가 생기면 어디를 먼저 보나?

| 증상 | 첫 확인 위치 |
|------|---------|
| `ImportError: cannot import name 'X' from minyoung_mah` | `minyoung_mah/__init__.py` 의 re-export 목록. 0.1.0 → 0.1.2 사이 제거된 심볼 확인 |
| Role 이 예상 prompt 를 생성 안 함 | Role 의 `build_user_message` 에서 `invocation.metadata.get("...")` 가 None 인지. input_mapping 주입 경로 재확인 |
| 구조화 출력이 JSON 파싱 실패 | Q4 — 3 조건 (output_schema + tool_allowlist=[] + max_iterations=1) 모두 충족했는가 |
| `metadata['usage']` 가 None | 0.1.1 이하 또는 mock 모델. Q3 3-priority fallback 으로 처리 |
| Synthesizer 가 상류 실패 무시 | Q5 — `format_for_llm(include_incomplete=True)` 기본값 유지했는지 |
| CI 에선 버전이 다름 | Q1 — `uv sync --reinstall-package minyoung-mah` |
| Pipeline step 간 상수 공유 필요 | Q2 — `shared_state` 또는 input_mapping 선택 |
| 비용 계산이 부정확 | 0.1.2+ 로 올리고 실 provider 사용. mock 에선 기대 못 함 |

여전히 해결 안 되면 `minyoung_mah/AGENTS.md` (repo 내부 규칙) + `docs/ARCHITECTURE.md` (설계 근거) 확인 후 issue.
