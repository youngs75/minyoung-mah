"""Default :class:`ModelRouter` implementations.
:class:`ModelRouter` 기본 구현체들.

The routers here are deliberately dumb — they take pre-constructed chat
model instances and hand them out by tier name. Building the models
themselves (API keys, base URLs, temperatures) is an application concern.

여기 있는 router 들은 의도적으로 단순하다 — 미리 생성된 chat 모델 인스턴스를
받아 tier 이름으로 분배할 뿐이다. 모델 자체를 만드는 일(API 키, base URL,
temperature 등)은 애플리케이션의 책임이다.
"""

from __future__ import annotations

from ..core.protocols import ModelHandle


class SingleModelRouter:
    """One model for every (tier, role) — the degenerate case.
    모든 (tier, role) 에 대해 단일 모델 — degenerate case.

    Use this when the application has no tiered routing (apt-legal uses a
    single ``gpt-4o`` for every role). The ``tier`` and ``role_name``
    arguments are accepted but ignored.

    애플리케이션에 tier 라우팅이 없을 때 사용 (apt-legal 은 모든 역할에 단일
    ``gpt-4o`` 사용). ``tier`` 와 ``role_name`` 인자는 받지만 무시된다.
    """

    def __init__(self, model: ModelHandle) -> None:
        self._model = model

    def resolve(self, tier: str, role_name: str) -> ModelHandle:  # noqa: ARG002
        return self._model


class TieredModelRouter:
    """Tier-name → model lookup, with optional per-role overrides.
    Tier 이름 → 모델 조회. 역할별 override 도 선택적으로 지원.

    ``tiers`` is the primary mapping (e.g. ``{"reasoning": qwen_max,
    "fast": qwen_flash}``). ``role_overrides`` lets a specific role bypass
    the tier — for example forcing ``classifier`` onto a cheaper model
    regardless of what tier the role declares.

    ``tiers`` 가 기본 매핑(예: ``{"reasoning": qwen_max, "fast": qwen_flash}``).
    ``role_overrides`` 는 특정 역할이 tier 를 우회하도록 한다 — 예: 역할이
    어떤 tier 를 선언하든 ``classifier`` 는 더 저렴한 모델로 강제하는 식.
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
