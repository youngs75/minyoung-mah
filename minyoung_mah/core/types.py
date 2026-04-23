"""Core data types shared across all minyoung-mah protocols.
모든 minyoung-mah 프로토콜에서 공유되는 코어 데이터 타입.

This module holds the **passive data structures** that flow between the
Orchestrator, roles, tool adapters, memory, and HITL channels. Protocols
themselves live in :mod:`minyoung_mah.core.protocols`.

이 모듈은 Orchestrator, 역할, 도구 adapter, memory, HITL 채널 사이를 흐르는
**수동 데이터 구조**를 담는다. 프로토콜 자체는
:mod:`minyoung_mah.core.protocols` 에 있다.

Everything here is either a ``dataclass`` or a plain ``Enum`` so that it is
cheap to construct, easy to serialize, and safe to pass across async
boundaries.

여기 정의된 모든 것은 ``dataclass`` 또는 평범한 ``Enum`` 이므로 구성 비용이
싸고, 직렬화가 쉬우며, async 경계를 가로질러 안전하게 전달 가능하다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Invocation context — what a role receives when it is invoked
# 호출 컨텍스트 — 역할이 호출될 때 전달받는 것
# ---------------------------------------------------------------------------


@dataclass
class InvocationContext:
    """Everything a role needs to run one invocation.
    역할이 한 번 실행하는 데 필요한 모든 것.

    The Orchestrator constructs this per ``invoke_role`` call. Roles treat it
    as read-only; any mutation belongs in the resulting ``RoleInvocationResult``.

    Orchestrator 가 ``invoke_role`` 호출마다 새로 만든다. 역할은 이를 read-only
    로 다뤄야 하며, 변경 사항은 결과인 ``RoleInvocationResult`` 에 담는다.
    """

    task_summary: str
    user_request: str
    parent_outputs: dict[str, Any] = field(default_factory=dict)
    shared_state: dict[str, Any] = field(default_factory=dict)
    memory_snippets: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tool invocation results — 도구 호출 결과
# ---------------------------------------------------------------------------


class ErrorCategory(Enum):
    """Library-level error taxonomy for tool-level retry decisions.
    도구 수준 재시도 판단을 위한 라이브러리 차원 오류 분류.

    Only the transient categories (``TIMEOUT``, ``RATE_LIMIT``, ``NETWORK``)
    are retried by the tool-level retry layer. ``AUTH`` is surfaced
    immediately because retrying usually cannot fix a credential problem.
    ``TOOL_ERROR`` and ``PARSE_ERROR`` are semantic failures — the library
    passes them through to the LLM so the role can decide what to do.

    일시적 카테고리(``TIMEOUT``, ``RATE_LIMIT``, ``NETWORK``)만 도구 수준
    재시도 계층에서 재시도된다. ``AUTH`` 는 자격 증명 문제를 재시도로 고칠 수
    없으므로 즉시 surface 된다. ``TOOL_ERROR`` 와 ``PARSE_ERROR`` 는 의미상
    실패로, 라이브러리가 LLM 에 그대로 전달해 역할이 어떻게 대응할지 결정하게 한다.
    """

    TIMEOUT = auto()
    RATE_LIMIT = auto()
    NETWORK = auto()
    AUTH = auto()
    TOOL_ERROR = auto()
    PARSE_ERROR = auto()
    UNKNOWN = auto()


TRANSIENT_ERRORS: frozenset[ErrorCategory] = frozenset(
    {ErrorCategory.TIMEOUT, ErrorCategory.RATE_LIMIT, ErrorCategory.NETWORK}
)


@dataclass
class ToolResult:
    """Structured outcome of a single tool call.
    단일 도구 호출의 구조화된 결과.

    ``value`` is constrained to ``str | BaseModel | dict`` per decision C1 so
    the Orchestrator knows exactly how to serialize the payload for the LLM.

    ``value`` 는 결정 C1 에 따라 ``str | BaseModel | dict`` 로 제한되어 있어,
    Orchestrator 가 LLM 에 페이로드를 어떻게 직렬화할지 정확히 알 수 있다.
    """

    ok: bool
    value: str | BaseModel | dict[str, Any] | None
    error: str | None = None
    error_category: ErrorCategory | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallRequest:
    """One tool call requested by an LLM turn.
    LLM 한 턴이 요청한 단일 도구 호출."""

    call_id: str
    tool_name: str
    args: dict[str, Any]


# ---------------------------------------------------------------------------
# Role invocation results — 역할 호출 결과
# ---------------------------------------------------------------------------


class RoleStatus(Enum):
    COMPLETED = auto()
    INCOMPLETE = auto()
    FAILED = auto()
    ABORTED = auto()


@dataclass
class RoleInvocationResult:
    """What a role invocation returns to the Orchestrator.
    역할 호출이 Orchestrator 에게 돌려주는 결과 묶음."""

    role_name: str
    status: RoleStatus
    output: str | BaseModel | dict[str, Any] | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    iterations: int = 0
    duration_ms: int = 0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_usable_output(self) -> bool:
        """True iff status is COMPLETED and ``output`` is not None.
        status 가 COMPLETED 이고 ``output`` 이 None 이 아닐 때만 True.

        Use this in ``build_user_message`` / synthesizer prompts to decide
        whether to feed a result downstream. A role that ran out of
        iterations (``INCOMPLETE``) may have a partial ``output`` but the
        consumer should treat it as unreliable.

        ``build_user_message`` 또는 synthesizer 프롬프트에서 결과를 downstream
        으로 흘려보낼지 판단할 때 사용한다. iteration 을 소진한 역할
        (``INCOMPLETE``)은 부분 ``output`` 을 가질 수 있지만 컨슈머는 신뢰할 수
        없는 값으로 다뤄야 한다.
        """
        return self.status is RoleStatus.COMPLETED and self.output is not None

    def output_text(self) -> str:
        """Serialize ``output`` to a string the LLM can read.
        ``output`` 을 LLM 이 읽을 수 있는 문자열로 직렬화한다.

        - ``None`` → empty string / 빈 문자열
        - ``str`` → as-is / 그대로
        - ``BaseModel`` → ``model_dump_json()``
        - ``dict`` → ``json.dumps(..., ensure_ascii=False)``
        - other / 그 외 → ``str(value)``
        """
        value = self.output
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, BaseModel):
            return value.model_dump_json()
        if isinstance(value, dict):
            try:
                return json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    def _successful_tool_results_text(self) -> str:
        """Serialize successful tool results as a fallback body.
        성공한 도구 결과들을 폴백 본문으로 직렬화한다.

        When a role exhausts ``max_iterations`` without producing a final
        text output, the successful tool results are still valuable data
        that downstream roles (e.g. synthesizer) should be able to use.

        역할이 최종 텍스트 출력 없이 ``max_iterations`` 를 소진해도 성공한
        도구 결과는 여전히 가치 있는 데이터이며, downstream 역할
        (예: synthesizer)이 활용할 수 있어야 한다.
        """
        successful = [r for r in self.tool_results if r.ok and r.value is not None]
        if not successful:
            return ""
        parts: list[str] = []
        for r in successful:
            if isinstance(r.value, str):
                parts.append(r.value)
            elif isinstance(r.value, BaseModel):
                parts.append(r.value.model_dump_json())
            elif isinstance(r.value, dict):
                try:
                    parts.append(json.dumps(r.value, ensure_ascii=False))
                except (TypeError, ValueError):
                    parts.append(str(r.value))
            else:
                parts.append(str(r.value))
        return "\n---\n".join(parts)

    def format_for_llm(self, *, include_incomplete: bool = True) -> str:
        """Return a labeled block suitable for inclusion in a downstream prompt.
        downstream 프롬프트에 삽입하기 좋은 라벨링된 블록을 반환한다.

        Shape::
        형태::

            [role=<name> status=<STATUS> iterations=<N>]
            <output_text or tool results or '(no output)'>

        If the role is not usable (``INCOMPLETE``/``FAILED``/``ABORTED``) and
        ``include_incomplete=False``, returns an empty string. The default
        ``True`` surfaces partial results with their status banner so the
        downstream LLM can treat them as suspect rather than silently
        trusting them (the apt-legal scenario-3 hallucination trap).

        역할이 사용 불가 상태(``INCOMPLETE``/``FAILED``/``ABORTED``)이고
        ``include_incomplete=False`` 면 빈 문자열을 반환한다. 기본값 ``True``
        는 부분 결과를 status 배너와 함께 surface 하여 downstream LLM 이 이를
        의심스럽게 다룰 수 있게 한다 — 무비판적으로 신뢰해서 환각이 생기는
        apt-legal 시나리오 3 함정을 피하기 위함.

        When a role is ``INCOMPLETE`` with no final LLM output but has
        successful tool results, those results are surfaced as the body
        so downstream consumers can work with the data that *was*
        collected.

        역할이 ``INCOMPLETE`` 이고 최종 LLM 출력이 없지만 성공한 도구 결과가
        있다면, 그 결과들을 본문으로 surface 하여 downstream 컨슈머가 *수집된*
        데이터로 작업할 수 있게 한다.
        """
        if not self.has_usable_output and not include_incomplete:
            return ""
        body = self.output_text()
        if not body:
            body = self._successful_tool_results_text() or "(no output)"
        header = (
            f"[role={self.role_name} status={self.status.name} "
            f"iterations={self.iterations}]"
        )
        if self.error and not self.has_usable_output:
            header += f" error={self.error}"
        return f"{header}\n{body}"


# ---------------------------------------------------------------------------
# Static pipeline definition — 정적 파이프라인 정의
# ---------------------------------------------------------------------------


PipelineState = dict[str, "PipelineStepResult"]


@dataclass
class PipelineStepResult:
    """Aggregated result of a single pipeline step.
    단일 파이프라인 스텝의 집계 결과.

    For role-based ``fan_out`` steps the ``outputs`` list holds all parallel
    role invocations. For :class:`ExecuteToolsStep` the ``outputs`` list is
    empty and ``tool_results`` holds the N parallel tool results in plan
    order. Role steps leave ``tool_results`` empty.

    역할 기반 ``fan_out`` 스텝에서는 ``outputs`` 리스트가 모든 병렬 역할 호출
    결과를 담는다. :class:`ExecuteToolsStep` 의 경우 ``outputs`` 는 비어 있고
    ``tool_results`` 가 plan 순서대로 N 개 병렬 도구 결과를 담는다. 역할 스텝은
    ``tool_results`` 를 비워둔다.
    """

    step_name: str
    role_name: str | None
    outputs: list[RoleInvocationResult]
    tool_results: list["ToolResult"] = field(default_factory=list)
    skipped: bool = False

    @property
    def output(self) -> RoleInvocationResult | None:
        """First role-invocation result, or ``None`` when the step was
        skipped / tool-only / fan_out empty.
        첫 번째 역할 호출 결과. 스텝이 skip/도구 전용/fan_out 비었음 일 때는 ``None``.

        Prefer :attr:`payload` or :meth:`payload_as` for the actual value
        produced by the role. Prefer :meth:`format_for_llm` when feeding
        downstream synthesizers.

        역할이 만든 실제 값에는 :attr:`payload` 또는 :meth:`payload_as` 를 쓰는
        것이 좋다. downstream synthesizer 에 넣을 때는 :meth:`format_for_llm`
        을 쓰는 것이 좋다.
        """
        return self.outputs[0] if self.outputs else None

    @property
    def payload(self) -> Any:
        """Return the first role invocation's ``.output`` payload.
        첫 번째 역할 호출의 ``.output`` 페이로드를 반환한다.

        Shortcut for the common ``state["step"].output.output`` access
        pattern — returns ``None`` if the step is skipped, empty, or the
        first output has no value.

        흔히 쓰는 ``state["step"].output.output`` 접근 패턴의 단축. 스텝이
        skip 됐거나 비어 있거나 첫 출력에 값이 없으면 ``None`` 을 반환한다.
        """
        out = self.output
        if out is None:
            return None
        return out.output

    def payload_as(self, cls: type[T]) -> T | None:
        """Return :attr:`payload` when it is an instance of ``cls``, else ``None``.
        :attr:`payload` 가 ``cls`` 의 인스턴스이면 그것을, 아니면 ``None`` 을 반환.

        Typed accessor for structured-output roles. Typical usage::
        구조화 출력 역할용 타입 보장 접근자. 일반적 사용::

            decision = state["route"].payload_as(RouterDecision)
            if decision and decision.need_legal:
                ...
        """
        payload = self.payload
        if isinstance(payload, cls):
            return payload
        return None

    def format_for_llm(self, *, include_incomplete: bool = True) -> str:
        """Concatenate every role invocation's ``format_for_llm`` output.
        모든 역할 호출의 ``format_for_llm`` 출력을 연결한다.

        ``fan_out`` steps produce N blocks separated by blank lines. Tool-
        only / skipped steps return an empty string. See
        :meth:`RoleInvocationResult.format_for_llm` for the shape of each
        block and the rationale for surfacing INCOMPLETE results.

        ``fan_out`` 스텝은 빈 줄로 구분된 N 블록을 만든다. 도구 전용/skip 된
        스텝은 빈 문자열을 반환. 각 블록의 형태와 INCOMPLETE 결과를 surface
        하는 근거는 :meth:`RoleInvocationResult.format_for_llm` 참조.
        """
        blocks = [
            out.format_for_llm(include_incomplete=include_incomplete)
            for out in self.outputs
        ]
        return "\n\n".join(b for b in blocks if b)


@dataclass
class PipelineStep:
    """One node in a StaticPipeline.
    StaticPipeline 의 노드 하나.

    ``input_mapping`` builds the ``InvocationContext`` from the accumulated
    pipeline state. ``condition`` lets a step be skipped based on upstream
    outputs. ``fan_out`` turns the step into N parallel invocations of the
    same role — each with its own context.

    ``input_mapping`` 은 누적된 pipeline state 로부터 ``InvocationContext`` 를
    구성한다. ``condition`` 으로 upstream 출력에 따라 스텝을 skip 시킬 수 있다.
    ``fan_out`` 을 지정하면 동일 역할을 각자 다른 컨텍스트로 N 회 병렬 호출한다.
    """

    name: str
    role: str
    input_mapping: Callable[[PipelineState], InvocationContext]
    condition: Callable[[PipelineState], bool] | None = None
    fan_out: Callable[[PipelineState], list[InvocationContext]] | None = None


@dataclass
class ExecuteToolsStep:
    """A pipeline step that runs tool calls without an LLM.
    LLM 없이 도구 호출을 실행하는 파이프라인 스텝.

    Use this when an upstream role has produced an execution plan and the
    next step is purely mechanical tool dispatch. The step pulls
    :class:`ToolCallRequest` instances out of the accumulated pipeline
    state via ``tool_calls_from`` and runs them through the shared
    :class:`ToolInvocationEngine`.

    upstream 역할이 실행 계획을 산출했고 다음 스텝이 순수하게 기계적인 도구
    디스패치일 때 사용한다. 스텝은 ``tool_calls_from`` 으로 누적된 pipeline
    state 에서 :class:`ToolCallRequest` 들을 꺼내 공유
    :class:`ToolInvocationEngine` 으로 실행한다.

    Parameters
    ----------
    name:
        Unique step name — becomes the key in ``PipelineState``.
        고유 스텝 이름 — ``PipelineState`` 의 키가 된다.
    tool_calls_from:
        Callable returning the list of tool calls to run. Each call may
        include a ``priority`` (1 = required, 2 = supplementary, 3 =
        optional). Calls with the same priority run in parallel; lower
        priority groups run first.
        실행할 도구 호출 리스트를 반환하는 callable. 각 호출은 ``priority``
        (1=필수, 2=보조, 3=선택)를 포함할 수 있다. 같은 priority 호출은
        병렬, priority 그룹 간에는 낮은 번호가 먼저 실행.
    condition:
        Optional skip predicate — same shape as :class:`PipelineStep`.
        선택적 skip predicate — :class:`PipelineStep` 과 동일한 형태.
    continue_on_failure:
        When True (default), a failed tool call does not abort the step.
        When False, the step surfaces the first failing priority group as
        a step failure and subsequent priority groups are skipped.
        True(기본)면 도구 호출 실패가 스텝을 중단시키지 않는다. False 면
        첫 실패 priority 그룹이 스텝 실패로 surface 되고 이후 priority 그룹은
        skip 된다.
    """

    name: str
    tool_calls_from: Callable[
        [PipelineState], list[tuple["ToolCallRequest", int]]
    ]
    condition: Callable[[PipelineState], bool] | None = None
    continue_on_failure: bool = True


@dataclass
class StaticPipeline:
    """Declaration of a sequential DAG of steps plus pipeline-wide context.
    스텝들의 순차적 DAG 선언 + 파이프라인 차원 공유 컨텍스트.

    ``shared_state`` is merged into every step's
    :class:`InvocationContext` before the role runs — per-step
    ``input_mapping`` values win on key conflicts. Use it for constants
    that every role needs to see (e.g. ``{"complex_id": "..."}``) so
    each ``input_mapping`` does not have to re-copy the same dict.

    ``shared_state`` 는 역할 실행 전에 모든 스텝의 :class:`InvocationContext`
    로 병합된다 — 키 충돌 시 스텝별 ``input_mapping`` 값이 이긴다. 모든 역할이
    봐야 하는 상수(예: ``{"complex_id": "..."}``)에 사용하면 각 ``input_mapping``
    이 같은 dict 를 복사할 필요가 없어진다.
    """

    steps: list[PipelineStep | ExecuteToolsStep]
    on_step_failure: Literal["abort", "continue", "escalate_hitl"] = "abort"
    shared_state: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    state: PipelineState
    completed: bool
    aborted_at: str | None = None
    error: str | None = None
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Memory — 메모리
# ---------------------------------------------------------------------------


@dataclass
class MemoryEntry:
    """A single memory record. Scoped by ``tier`` + optional ``scope``.
    단일 메모리 레코드. ``tier`` + 선택적 ``scope`` 로 분류된다."""

    tier: str
    key: str
    value: str
    scope: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# HITL — Human-in-the-Loop / 사람 개입
# ---------------------------------------------------------------------------


@dataclass
class HITLResponse:
    choice: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HITLEvent:
    # ``critic_escalate`` is emitted by application-side sufficiency loops
    # when the LLM critic verdict requests human review.
    # ``critic_escalate`` 는 sufficiency loop 의 LLM critic verdict 가
    # 사람 검토를 요청할 때 발화한다.
    kind: Literal[
        "role_start",
        "role_end",
        "tool_call",
        "progress",
        "error",
        "critic_escalate",
    ]
    data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Observer event — Observer 이벤트
# ---------------------------------------------------------------------------


@dataclass
class ObserverEvent:
    """Standardized observer event — see design doc 04 §G1.
    표준화된 observer 이벤트 — 설계 문서 04 §G1 참조.

    ``name`` uses dotted notation (e.g. ``"orchestrator.role.invoke.start"``).
    Backend adapters translate this into Langfuse spans, structlog entries,
    OTel traces, etc.

    ``name`` 은 점 표기법을 사용한다(예: ``"orchestrator.role.invoke.start"``).
    백엔드 adapter 가 이를 Langfuse span, structlog 엔트리, OTel trace 등으로
    번역한다.
    """

    name: str
    timestamp: datetime
    role: str | None = None
    tool: str | None = None
    duration_ms: int | None = None
    ok: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
