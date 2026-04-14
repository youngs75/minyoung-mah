"""Default :class:`ModelRouter` implementations.

The routers here are deliberately dumb — they take pre-constructed chat
model instances and hand them out by tier name. Building the models
themselves (API keys, base URLs, temperatures) is an application concern.
"""

from __future__ import annotations

from ..core.protocols import ModelHandle


class SingleModelRouter:
    """One model for every (tier, role) — the degenerate case.

    Use this when the application has no tiered routing (apt-legal uses a
    single ``gpt-4o`` for every role). The ``tier`` and ``role_name``
    arguments are accepted but ignored.
    """

    def __init__(self, model: ModelHandle) -> None:
        self._model = model

    def resolve(self, tier: str, role_name: str) -> ModelHandle:  # noqa: ARG002
        return self._model


class TieredModelRouter:
    """Tier-name → model lookup, with optional per-role overrides.

    ``tiers`` is the primary mapping (e.g. ``{"reasoning": qwen_max,
    "fast": qwen_flash}``). ``role_overrides`` lets a specific role bypass
    the tier — for example forcing ``classifier`` onto a cheaper model
    regardless of what tier the role declares.
    """

    def __init__(
        self,
        tiers: dict[str, ModelHandle],
        role_overrides: dict[str, ModelHandle] | None = None,
    ) -> None:
        if not tiers:
            raise ValueError("TieredModelRouter requires at least one tier")
        self._tiers = dict(tiers)
        self._role_overrides = dict(role_overrides or {})

    def resolve(self, tier: str, role_name: str) -> ModelHandle:
        if role_name in self._role_overrides:
            return self._role_overrides[role_name]
        try:
            return self._tiers[tier]
        except KeyError as exc:
            raise KeyError(
                f"Tier '{tier}' not registered in TieredModelRouter "
                f"(known tiers: {sorted(self._tiers)})"
            ) from exc
