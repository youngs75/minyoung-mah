"""The Orchestrator — static pipeline executor for Phase 2a.

Responsibilities
----------------
1. **Safety**: role allowlists, watchdog timeouts, max_iterations.
2. **Detection**: progress guard hook (disabled by default in static mode).
3. **Clarity**: standardized observer events on every boundary.
4. **Context**: build role-level ``InvocationContext`` from pipeline state.
5. **Observation**: timing + ok/error on every emit.

What this module is *not* responsible for: choosing which role to invoke
next (applications declare that via :class:`StaticPipeline`), domain
prompts, or tool implementations.

``run_loop`` is declared but raises ``NotImplementedError`` — dynamic mode
is deferred to Phase 4 per decision J1 and the Phase 2a scope vote (b).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from ..hitl.channels import NullHITLChannel
from ..observer.events import NullObserver
from ..resilience.policy import ResiliencePolicy, default_resilience
from .protocols import (
    HITLChannel,
    MemoryExtractor,
    MemoryStore,
    ModelRouter,
    Observer,
    SubAgentRole,
    ToolAdapter,
)
from .registry import RoleRegistry, ToolRegistry
from .tool_invocation import ToolInvocationEngine
from .types import (
    ExecuteToolsStep,
    InvocationContext,
    LoopResult,
    ObserverEvent,
    PipelineResult,
    PipelineState,
    PipelineStep,
    PipelineStepResult,
    RoleInvocationResult,
    RoleStatus,
    StaticPipeline,
    ToolCallRequest,
    ToolResult,
)


class OrchestratorError(Exception):
    """Raised when the Orchestrator cannot continue — e.g. unknown role."""


class Orchestrator:
    """Composes the six core protocols to run pipelines.

    See ``docs/design/01_core_abstractions.md`` §3 for the design rationale.
    The public surface is three methods: :meth:`run_pipeline` (static DAG),
    :meth:`invoke_role` (atomic unit), and :meth:`run_loop` (dynamic, Phase 4).
    """

    def __init__(
        self,
        role_registry: RoleRegistry,
        tool_registry: ToolRegistry,
        model_router: ModelRouter,
        memory: MemoryStore,
        hitl: HITLChannel | None = None,
        resilience: ResiliencePolicy | None = None,
        observer: Observer | None = None,
        memory_extractor: MemoryExtractor | None = None,
        tool_engine: ToolInvocationEngine | None = None,
    ) -> None:
        self.roles = role_registry
        self.tools = tool_registry
        self.model_router = model_router
        self.memory = memory
        self.hitl: HITLChannel = hitl or NullHITLChannel()
        self.resilience = resilience or default_resilience()
        self.observer: Observer = observer or NullObserver()
        self.memory_extractor = memory_extractor
        self.tool_engine = tool_engine or ToolInvocationEngine(self.observer)

    # ------------------------------------------------------------------
    # Public: static pipeline
    # ------------------------------------------------------------------

    async def run_pipeline(
        self,
        pipeline: StaticPipeline,
        user_request: str,
    ) -> PipelineResult:
        """Execute a static DAG of roles.

        Steps run in declaration order. Each step sees the accumulated
        ``PipelineState`` and builds its own ``InvocationContext`` via the
        step's ``input_mapping``. ``fan_out`` turns a step into N parallel
        invocations of the same role.
        """
        run_id = str(uuid.uuid4())
        start = time.monotonic()
        state: PipelineState = {}
        await self._emit(
            "orchestrator.run.start",
            metadata={"run_id": run_id, "pipeline_steps": len(pipeline.steps)},
        )

        try:
            for step in pipeline.steps:
                step_result = await self._run_step(step, state, user_request, run_id)
                state[step.name] = step_result

                if step_result.skipped:
                    continue

                step_failed = any(
                    r.status in (RoleStatus.FAILED, RoleStatus.ABORTED)
                    for r in step_result.outputs
                )
                if step_failed and pipeline.on_step_failure == "abort":
                    duration = int((time.monotonic() - start) * 1000)
                    await self._emit(
                        "orchestrator.run.end",
                        ok=False,
                        duration_ms=duration,
                        metadata={"run_id": run_id, "aborted_at": step.name},
                    )
                    return PipelineResult(
                        state=state,
                        completed=False,
                        aborted_at=step.name,
                        error=step_result.outputs[0].error if step_result.outputs else None,
                        duration_ms=duration,
                    )
                if step_failed and pipeline.on_step_failure == "escalate_hitl":
                    await self.hitl.notify(_hitl_event("error", {"step": step.name}))
        except Exception as exc:  # noqa: BLE001
            duration = int((time.monotonic() - start) * 1000)
            await self._emit(
                "orchestrator.run.end",
                ok=False,
                duration_ms=duration,
                metadata={"run_id": run_id, "error": f"{type(exc).__name__}: {exc}"},
            )
            raise

        duration = int((time.monotonic() - start) * 1000)
        await self._emit(
            "orchestrator.run.end",
            ok=True,
            duration_ms=duration,
            metadata={"run_id": run_id},
        )

        result = PipelineResult(state=state, completed=True, duration_ms=duration)

        if self.memory_extractor is not None:
            try:
                await self.memory_extractor.extract(
                    user_request=user_request,
                    result=result,
                    memory=self.memory,
                )
            except Exception:  # noqa: BLE001
                pass

        return result

    # ------------------------------------------------------------------
    # Public: atomic invocation
    # ------------------------------------------------------------------

    async def invoke_role(
        self,
        role_name: str,
        invocation: InvocationContext,
    ) -> RoleInvocationResult:
        """Run a single role once and return its outcome.

        Dispatches between the structured fast path (decision A4) and the
        general tool-calling loop. Wraps the whole thing in a watchdog
        timeout drawn from :class:`ResiliencePolicy`.
        """
        try:
            role = self.roles.get(role_name)
        except KeyError as exc:
            raise OrchestratorError(str(exc)) from exc

        timeout_s = self.resilience.timeout_for(role_name)
        start = time.monotonic()
        await self._emit(
            "orchestrator.role.invoke.start",
            role=role_name,
            metadata={"task_summary": invocation.task_summary},
        )

        try:
            result = await asyncio.wait_for(
                self._invoke_inner(role, invocation),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            duration = int((time.monotonic() - start) * 1000)
            await self._emit(
                "orchestrator.role.invoke.end",
                role=role_name,
                ok=False,
                duration_ms=duration,
                metadata={"error": "watchdog_timeout", "timeout_s": timeout_s},
            )
            return RoleInvocationResult(
                role_name=role_name,
                status=RoleStatus.ABORTED,
                output=None,
                duration_ms=duration,
                error=f"role '{role_name}' exceeded watchdog timeout of {timeout_s}s",
            )

        result.duration_ms = int((time.monotonic() - start) * 1000)
        await self._emit(
            "orchestrator.role.invoke.end",
            role=role_name,
            ok=result.status is RoleStatus.COMPLETED,
            duration_ms=result.duration_ms,
            metadata={"iterations": result.iterations, "status": result.status.name},
        )
        return result

    # ------------------------------------------------------------------
    # Public: dynamic loop (Phase 4)
    # ------------------------------------------------------------------

    async def run_loop(
        self,
        driver_role: str,
        user_request: str,
        stop_when: Callable[[Any], bool],
    ) -> LoopResult:
        """Deferred to Phase 4 per decision J1 and the Phase 2a scope vote.

        Phase 2a ships static pipelines only; apt-legal (Phase 3) does not
        need ``run_loop``. The coding agent (Phase 4) brings it back along
        with the ``delegate`` tool factory.
        """
        raise NotImplementedError(
            "run_loop is deferred to Phase 4 — use run_pipeline for now "
            "(see docs/design/04_open_questions.md §J1)."
        )

    # ------------------------------------------------------------------
    # Internal: single step execution (incl. fan_out)
    # ------------------------------------------------------------------

    async def _run_step(
        self,
        step: PipelineStep | ExecuteToolsStep,
        state: PipelineState,
        user_request: str,
        run_id: str,
    ) -> PipelineStepResult:
        if isinstance(step, ExecuteToolsStep):
            return await self._run_execute_tools_step(step, state, run_id)
        return await self._run_role_step(step, state, user_request, run_id)

    async def _run_role_step(
        self,
        step: PipelineStep,
        state: PipelineState,
        user_request: str,
        run_id: str,
    ) -> PipelineStepResult:
        if step.condition is not None and not step.condition(state):
            await self._emit(
                "orchestrator.pipeline.step.start",
                role=step.role,
                metadata={"step": step.name, "skipped": True, "run_id": run_id},
            )
            await self._emit(
                "orchestrator.pipeline.step.end",
                role=step.role,
                ok=True,
                metadata={"step": step.name, "skipped": True, "run_id": run_id},
            )
            return PipelineStepResult(
                step_name=step.name, role_name=step.role, outputs=[], skipped=True
            )

        await self._emit(
            "orchestrator.pipeline.step.start",
            role=step.role,
            metadata={"step": step.name, "run_id": run_id},
        )

        if step.fan_out is not None:
            contexts = step.fan_out(state)
            contexts = [self._ensure_user_request(c, user_request) for c in contexts]
            outputs = await asyncio.gather(
                *(self.invoke_role(step.role, c) for c in contexts)
            )
        else:
            ctx = step.input_mapping(state)
            ctx = self._ensure_user_request(ctx, user_request)
            outputs = [await self.invoke_role(step.role, ctx)]

        all_ok = all(o.status is RoleStatus.COMPLETED for o in outputs)
        await self._emit(
            "orchestrator.pipeline.step.end",
            role=step.role,
            ok=all_ok,
            metadata={"step": step.name, "fan_out": len(outputs), "run_id": run_id},
        )
        return PipelineStepResult(
            step_name=step.name, role_name=step.role, outputs=list(outputs)
        )

    async def _run_execute_tools_step(
        self,
        step: ExecuteToolsStep,
        state: PipelineState,
        run_id: str,
    ) -> PipelineStepResult:
        """Run an :class:`ExecuteToolsStep` — LLM-less parallel tool dispatch.

        Calls are grouped by priority (ascending). Each priority group runs
        in parallel via :meth:`ToolInvocationEngine.call_parallel`; groups
        run sequentially. Results are collected in the original plan order
        regardless of execution ordering.
        """
        if step.condition is not None and not step.condition(state):
            await self._emit(
                "orchestrator.pipeline.step.start",
                metadata={"step": step.name, "skipped": True, "run_id": run_id},
            )
            await self._emit(
                "orchestrator.pipeline.step.end",
                ok=True,
                metadata={"step": step.name, "skipped": True, "run_id": run_id},
            )
            return PipelineStepResult(
                step_name=step.name, role_name=None, outputs=[], skipped=True
            )

        await self._emit(
            "orchestrator.pipeline.step.start",
            metadata={"step": step.name, "run_id": run_id, "kind": "execute_tools"},
        )

        plan = step.tool_calls_from(state)
        # Preserve plan order for the final result list.
        order_by_call_id: dict[str, int] = {
            req.call_id: idx for idx, (req, _) in enumerate(plan)
        }
        results_by_call_id: dict[str, ToolResult] = {}

        # Group by priority (ascending: lower priority number runs first).
        priorities = sorted({prio for _, prio in plan})
        step_ok = True
        for priority in priorities:
            group = [req for req, prio in plan if prio == priority]
            pairs: list[tuple[Any, ToolCallRequest]] = []
            for request in group:
                try:
                    adapter = self.tools.get(request.tool_name)
                    pairs.append((adapter, request))
                except KeyError:
                    results_by_call_id[request.call_id] = ToolResult(
                        ok=False,
                        value=None,
                        error=f"tool '{request.tool_name}' not registered",
                    )
                    step_ok = False

            if pairs:
                group_results = await self.tool_engine.call_parallel(pairs)
                for (_, req), result in zip(pairs, group_results):
                    results_by_call_id[req.call_id] = result
                    if not result.ok:
                        step_ok = False

            if not step_ok and not step.continue_on_failure:
                break

        ordered_results = [
            results_by_call_id[req.call_id]
            for req, _ in plan
            if req.call_id in results_by_call_id
        ]

        await self._emit(
            "orchestrator.pipeline.step.end",
            ok=step_ok,
            metadata={
                "step": step.name,
                "run_id": run_id,
                "kind": "execute_tools",
                "tool_calls": len(plan),
                "ok_count": sum(1 for r in ordered_results if r.ok),
            },
        )

        # For continue_on_failure=True we want the pipeline to treat the
        # step as "completed" even if some tools failed — responder can
        # see individual failures via tool_results. For
        # continue_on_failure=False we synthesize a FAILED RoleInvocation
        # so the main abort/continue loop in run_pipeline picks it up.
        outputs: list[RoleInvocationResult] = []
        if not step_ok and not step.continue_on_failure:
            outputs = [
                RoleInvocationResult(
                    role_name="__execute_tools__",
                    status=RoleStatus.FAILED,
                    output=None,
                    tool_results=list(ordered_results),
                    error="one or more tool calls failed (continue_on_failure=False)",
                )
            ]

        return PipelineStepResult(
            step_name=step.name,
            role_name=None,
            outputs=outputs,
            tool_results=list(ordered_results),
        )

    # ------------------------------------------------------------------
    # Internal: role invocation — fast path dispatcher + general loop
    # ------------------------------------------------------------------

    async def _invoke_inner(
        self,
        role: SubAgentRole,
        invocation: InvocationContext,
    ) -> RoleInvocationResult:
        uses_fast_path = (
            role.output_schema is not None
            and role.max_iterations == 1
            and not role.tool_allowlist
        )
        if uses_fast_path:
            return await self._invoke_structured(role, invocation)
        return await self._invoke_loop(role, invocation)

    async def _invoke_structured(
        self,
        role: SubAgentRole,
        invocation: InvocationContext,
    ) -> RoleInvocationResult:
        """Fast path: ``with_structured_output`` — no tool loop."""
        from langchain_core.messages import HumanMessage, SystemMessage

        model = self.model_router.resolve(role.model_tier, role.name)
        if not hasattr(model, "with_structured_output"):
            return RoleInvocationResult(
                role_name=role.name,
                status=RoleStatus.FAILED,
                output=None,
                error="model does not support with_structured_output",
            )

        structured = model.with_structured_output(role.output_schema)
        messages = [
            SystemMessage(content=role.system_prompt),
            HumanMessage(content=role.build_user_message(invocation)),
        ]
        try:
            output = await _maybe_await(structured.ainvoke(messages))
        except Exception as exc:  # noqa: BLE001
            return RoleInvocationResult(
                role_name=role.name,
                status=RoleStatus.FAILED,
                output=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        return RoleInvocationResult(
            role_name=role.name,
            status=RoleStatus.COMPLETED,
            output=output,
            iterations=1,
        )

    async def _invoke_loop(
        self,
        role: SubAgentRole,
        invocation: InvocationContext,
    ) -> RoleInvocationResult:
        """General path: free-form LLM + tool-calling loop."""
        from langchain_core.messages import (
            AIMessage,
            HumanMessage,
            SystemMessage,
            ToolMessage,
        )

        model = self.model_router.resolve(role.model_tier, role.name)
        adapters = self.tools.filter(role.tool_allowlist)
        adapters_by_name: dict[str, ToolAdapter] = {a.name: a for a in adapters}

        if adapters and hasattr(model, "bind_tools"):
            bound = model.bind_tools([_tool_def(a) for a in adapters])
        else:
            bound = model

        messages: list[Any] = [
            SystemMessage(content=role.system_prompt),
            HumanMessage(content=role.build_user_message(invocation)),
        ]
        collected_requests: list[ToolCallRequest] = []
        collected_results: list[ToolResult] = []

        for iteration in range(1, role.max_iterations + 1):
            self.resilience.progress_guard.check(iteration)
            try:
                ai_msg: AIMessage = await _maybe_await(bound.ainvoke(messages))
            except Exception as exc:  # noqa: BLE001
                return RoleInvocationResult(
                    role_name=role.name,
                    status=RoleStatus.FAILED,
                    output=None,
                    iterations=iteration,
                    tool_calls=collected_requests,
                    tool_results=collected_results,
                    error=f"{type(exc).__name__}: {exc}",
                )
            messages.append(ai_msg)

            tool_calls = getattr(ai_msg, "tool_calls", None) or []
            if not tool_calls:
                return RoleInvocationResult(
                    role_name=role.name,
                    status=RoleStatus.COMPLETED,
                    output=_extract_text(ai_msg),
                    iterations=iteration,
                    tool_calls=collected_requests,
                    tool_results=collected_results,
                )

            for tc in tool_calls:
                request = ToolCallRequest(
                    call_id=tc.get("id") or str(uuid.uuid4()),
                    tool_name=tc["name"],
                    args=tc.get("args", {}) or {},
                )
                collected_requests.append(request)
                self.resilience.progress_guard.record_action(
                    request.tool_name, request.args
                )

                adapter = adapters_by_name.get(request.tool_name)
                if adapter is None:
                    result = ToolResult(
                        ok=False,
                        value=None,
                        error=f"tool '{request.tool_name}' not in allowlist",
                    )
                else:
                    result = await self.tool_engine.call_one(adapter, request)
                collected_results.append(result)

                messages.append(
                    ToolMessage(
                        content=_serialize_tool_value(result),
                        tool_call_id=request.call_id,
                    )
                )

        return RoleInvocationResult(
            role_name=role.name,
            status=RoleStatus.INCOMPLETE,
            output=None,
            iterations=role.max_iterations,
            tool_calls=collected_requests,
            tool_results=collected_results,
            error=f"role '{role.name}' exceeded max_iterations={role.max_iterations}",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_user_request(
        self,
        ctx: InvocationContext,
        user_request: str,
    ) -> InvocationContext:
        if ctx.user_request:
            return ctx
        return InvocationContext(
            task_summary=ctx.task_summary,
            user_request=user_request,
            parent_outputs=ctx.parent_outputs,
            shared_state=ctx.shared_state,
            memory_snippets=ctx.memory_snippets,
            metadata=ctx.metadata,
        )

    async def _emit(
        self,
        name: str,
        *,
        role: str | None = None,
        tool: str | None = None,
        ok: bool | None = None,
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            await self.observer.emit(
                ObserverEvent(
                    name=name,
                    timestamp=datetime.utcnow(),
                    role=role,
                    tool=tool,
                    ok=ok,
                    duration_ms=duration_ms,
                    metadata=metadata or {},
                )
            )
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _tool_def(adapter: ToolAdapter) -> dict[str, Any]:
    """OpenAI-function-style tool definition for ``bind_tools``."""
    return {
        "type": "function",
        "function": {
            "name": adapter.name,
            "description": adapter.description,
            "parameters": adapter.arg_schema.model_json_schema(),
        },
    }


def _serialize_tool_value(result: ToolResult) -> str:
    if not result.ok:
        return f"ERROR: {result.error or 'tool call failed'}"
    value = result.value
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


def _extract_text(ai_msg: Any) -> str:
    content = getattr(ai_msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


async def _maybe_await(value: Awaitable[Any] | Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    if hasattr(value, "__await__"):
        return await value  # type: ignore[func-returns-value]
    return value


def _hitl_event(kind: str, data: dict[str, Any]):
    from .types import HITLEvent

    return HITLEvent(kind=kind, data=data)  # type: ignore[arg-type]
