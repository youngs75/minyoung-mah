"""The six core protocols of minyoung-mah.
minyoung-mah 의 6개 핵심 프로토콜.

These protocols define the **library's API surface**. Application code
(coding agent, apt-legal-agent, ...) implements them — or uses the
opinionated defaults the library ships — and composes them through the
:class:`minyoung_mah.core.orchestrator.Orchestrator`.

이 프로토콜들이 **라이브러리의 API 표면**을 정의한다. 애플리케이션 코드
(coding agent, apt-legal-agent 등)는 이를 구현하거나 라이브러리가 제공하는
opinionated 기본 구현을 사용하며, :class:`minyoung_mah.core.orchestrator.Orchestrator`
를 통해 조립한다.

Design rationale: docs/design/01_core_abstractions.md.
The six responsibilities this library takes on — Safety, Detection,
Clarity, Context, Observation — are enforced here and nowhere else.

설계 근거는 docs/design/01_core_abstractions.md 참조.
이 라이브러리가 책임지는 6가지 — Safety, Detection, Clarity, Context, Observation —
는 오직 여기에서만 강제된다.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from .types import (
    HITLEvent,
    HITLResponse,
    InvocationContext,
    MemoryEntry,
    ObserverEvent,
    ToolResult,
)


# ---------------------------------------------------------------------------
# 1. SubAgentRole — "this role is what" / "이 역할은 무엇을 하는가"
# ---------------------------------------------------------------------------


@runtime_checkable
class SubAgentRole(Protocol):
    """A role is a declarative bundle that tells the Orchestrator how to
    invoke a SubAgent for a specific purpose.
    역할(role)은 특정 목적의 SubAgent 를 어떻게 호출할지 Orchestrator 에게
    알려주는 선언적 묶음이다.

    Roles are *data*, not active objects. The Orchestrator owns execution.
    Applications typically declare roles as frozen dataclasses or
    ``SimpleNamespace`` instances that duck-type this protocol.

    역할은 *데이터*이지 능동 객체가 아니다. 실행 주체는 Orchestrator 다.
    애플리케이션은 보통 frozen dataclass 또는 ``SimpleNamespace`` 인스턴스로
    역할을 선언해 이 프로토콜에 대해 duck-type 한다.
    """

    name: str
    system_prompt: str
    tool_allowlist: list[str]
    model_tier: str
    output_schema: type[BaseModel] | None
    max_iterations: int

    def build_user_message(self, invocation: InvocationContext) -> str:
        """Construct the initial user message for this invocation.
        이번 호출의 초기 user 메시지를 구성한다."""
        ...


# ---------------------------------------------------------------------------
# 2. ToolAdapter — "this tool is how" / "이 도구는 어떻게 호출하는가"
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolAdapter(Protocol):
    """Unified contract for every tool the Orchestrator might call.
    Orchestrator 가 호출할 수 있는 모든 도구를 위한 통일된 계약.

    Internal implementations (shell, file I/O) and external proxies (MCP
    clients, HTTP APIs) look identical to the Orchestrator.

    내부 구현(shell, 파일 I/O)이든 외부 프록시(MCP 클라이언트, HTTP API)든
    Orchestrator 에서는 동일한 형태로 보인다.
    """

    name: str
    description: str
    arg_schema: type[BaseModel]

    async def call(self, args: BaseModel) -> ToolResult:
        """Execute the tool. Must not raise for expected failures — return
        ``ToolResult(ok=False, error=..., error_category=...)`` instead.

        도구를 실행한다. 예상되는 실패에 대해서는 raise 하지 말고 대신
        ``ToolResult(ok=False, error=..., error_category=...)`` 를 반환한다.
        """
        ...


# ---------------------------------------------------------------------------
# 3. ModelRouter — "which model for this tier/role"
#                  "이 tier/역할에 어떤 모델을 쓰는가"
# ---------------------------------------------------------------------------


# A ``ModelHandle`` is any object that satisfies the LangChain
# :class:`BaseChatModel` surface the Orchestrator uses:
# ``ainvoke``, ``bind_tools``, and ``with_structured_output``. We alias
# it to :class:`BaseChatModel` so consumers get real type checking —
# ``Any`` was a polite fiction that hid the actual requirement. Test
# fixtures that duck-type a subset of the interface still work at
# runtime because the Orchestrator only calls the subset it needs.
#
# ``ModelHandle`` 은 Orchestrator 가 사용하는 LangChain :class:`BaseChatModel`
# 표면(``ainvoke``, ``bind_tools``, ``with_structured_output``)을 만족하는 임의의
# 객체다. 컨슈머가 실제 타입 체크를 받을 수 있도록 :class:`BaseChatModel` 로
# alias 한다 — ``Any`` 로 두면 진짜 요구사항이 가려진다. 인터페이스의 일부만
# duck-type 한 테스트 픽스처도 Orchestrator 가 필요한 부분만 호출하므로
# 런타임에서는 그대로 동작한다.
ModelHandle = BaseChatModel


@runtime_checkable
class ModelRouter(Protocol):
    """Resolves a ``(tier, role_name)`` pair to a concrete chat model.
    ``(tier, role_name)`` 쌍을 구체적인 chat 모델로 해석한다.

    Tier names are strings chosen by the application (e.g. ``"reasoning"``,
    ``"fast"``, or just ``"default"``). Both arguments are passed so routers
    can override per-role when needed.

    tier 이름은 애플리케이션이 정하는 문자열(예: ``"reasoning"``, ``"fast"``,
    혹은 그냥 ``"default"``)이다. 두 인자를 모두 받으므로 router 가 필요할 때
    역할 단위로 override 할 수 있다.
    """

    def resolve(self, tier: str, role_name: str) -> ModelHandle: ...


# ---------------------------------------------------------------------------
# 4. MemoryStore — "remember and recall" / "기억하고 다시 꺼낸다"
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryStore(Protocol):
    """Async-first persistent memory.
    Async 우선 영속 메모리.

    Tiers are application-defined strings. ``scope`` further partitions
    entries within a tier (e.g. a project id, a user id, a session id).
    Passing ``scope=None`` to ``search`` matches all scopes.

    tier 는 애플리케이션이 정의한 문자열이다. ``scope`` 는 tier 내에서 항목을
    추가로 분할한다(예: 프로젝트 id, 사용자 id, 세션 id). ``search`` 에
    ``scope=None`` 을 넘기면 모든 scope 가 매칭된다.
    """

    async def write(
        self,
        tier: str,
        key: str,
        value: str,
        scope: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def read(
        self,
        tier: str,
        key: str,
        scope: str | None = None,
    ) -> MemoryEntry | None: ...

    async def search(
        self,
        tier: str,
        query: str,
        scope: str | None = None,
        limit: int = 5,
    ) -> list[MemoryEntry]: ...

    async def list_by_scope(
        self,
        tier: str,
        scope: str | None = None,
        limit: int = 10,
        order: str = "desc",
    ) -> list[MemoryEntry]:
        """List entries within ``(tier, scope)`` ordered by ``created_at``.
        ``(tier, scope)`` 범위의 항목을 ``created_at`` 기준으로 정렬해 반환.

        Unlike :meth:`search`, this does **not** consult the FTS index — it
        returns the most recent ``limit`` entries regardless of content.
        Intended for tiers whose useful recall is "the last N items" rather
        than keyword-matched (e.g. ``short_term`` conversation turns where
        the next-turn query rarely shares tokens with stored content,
        especially across CJK/English mixes).

        :meth:`search` 와 달리 FTS 인덱스를 **참조하지 않는다** — 내용과 무관하게
        가장 최근 ``limit`` 개 항목을 돌려준다. 유효 회수가 "가장 최근 N 개"인
        tier 에 적합하다(예: ``short_term`` 대화 turn 처럼 다음 turn 쿼리가
        저장 내용과 토큰이 겹치지 않는 경우. 특히 CJK/영문 혼재 환경).

        ``scope=None`` means "all scopes in this tier". ``order`` is
        ``"desc"`` (default, newest first) or ``"asc"``. Implementations must
        validate ``order`` and raise on other values.

        ``scope=None`` 은 "이 tier 의 모든 scope"를 의미한다. ``order`` 는
        ``"desc"``(기본값, 최신순) 또는 ``"asc"``. 구현체는 ``order`` 를
        검증하고 다른 값에 대해서는 예외를 던져야 한다.
        """
        ...

    async def list_tiers(self) -> list[str]: ...


# ---------------------------------------------------------------------------
# 5. HITLChannel — "ask the human, wait for a reply"
#                  "사람에게 묻고 응답을 기다린다"
# ---------------------------------------------------------------------------


@runtime_checkable
class HITLChannel(Protocol):
    """Bidirectional bridge between a running pipeline and a human user.
    실행 중인 파이프라인과 사람 사용자 사이의 양방향 다리.

    ``ask`` is a blocking async call. How the implementation blocks is up to
    the channel — a terminal prompt, an SSE long-poll, an in-memory queue.
    ``notify`` is non-blocking; channels may no-op it.

    ``ask`` 는 블로킹 async 호출이다. 어떻게 블로킹할지는 채널이 결정한다 —
    터미널 프롬프트, SSE long-poll, 인메모리 큐 등. ``notify`` 는 논블로킹이며
    채널이 no-op 으로 둬도 된다.
    """

    async def ask(
        self,
        question: str,
        options: list[str] | None = None,
        description: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> HITLResponse: ...

    async def notify(self, event: HITLEvent) -> None: ...


# ---------------------------------------------------------------------------
# 6. Observer — "what happened, when, how long"
#               "무엇이 언제 얼마나 오래 걸렸는가"
# ---------------------------------------------------------------------------


@runtime_checkable
class Observer(Protocol):
    """Receives standardized :class:`ObserverEvent` objects.
    표준화된 :class:`ObserverEvent` 객체를 수신한다.

    Implementations fan them out to Langfuse, structlog, OpenTelemetry, or
    a test collector. Events are fire-and-forget; observers must never
    raise back into the Orchestrator.

    구현체는 이를 Langfuse, structlog, OpenTelemetry, 테스트 collector 등으로
    fan-out 한다. 이벤트는 fire-and-forget 이며, observer 는 Orchestrator 쪽으로
    예외를 다시 던져서는 절대 안 된다.
    """

    async def emit(self, event: ObserverEvent) -> None: ...


# ---------------------------------------------------------------------------
# Optional: MemoryExtractor — application hook, not a core responsibility
# 선택: MemoryExtractor — 애플리케이션 훅, 코어 책임 아님
# ---------------------------------------------------------------------------


@runtime_checkable
class MemoryExtractor(Protocol):
    """Pulls memory-worthy facts out of a completed pipeline run.
    완료된 파이프라인 실행에서 기억할 가치가 있는 사실을 뽑아낸다.

    The library ships **no default implementation** (privacy-sensitive apps
    must opt in). Passing ``memory_extractor=None`` to the Orchestrator
    disables extraction entirely.

    라이브러리는 **기본 구현을 제공하지 않는다** (프라이버시에 민감한 앱은
    명시적으로 opt-in 해야 한다). Orchestrator 에 ``memory_extractor=None`` 을
    넘기면 추출이 완전히 비활성화된다.
    """

    async def extract(
        self,
        user_request: str,
        result: Any,
        memory: MemoryStore,
    ) -> None: ...
