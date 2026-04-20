"""Skill loader — static injection of procedural knowledge into SubAgent runs.
스킬 로더 — SubAgent 실행에 절차적 지식을 정적으로 주입.

Skills separate **procedure** from **identity**. The role system prompt stays
an identity contract ("you are a verifier") while edit-friendly SKILL.md files
hold the how-to steps. Consumers choose the injection policy — the library
only provides the loader + a renderer.

스킬은 **절차**와 **정체성**을 분리한다. role system prompt 는 "당신은 검증자다"
같은 정체성 계약으로 두고, 편집하기 쉬운 SKILL.md 파일에 how-to 단계를 둔다.
주입 정책은 컨슈머가 결정 — 라이브러리는 로더와 렌더러만 제공한다.

## Phase 1 — static injection / 정적 주입

At role build time the consumer calls ``SkillStore(root).for_role(name)`` and
attaches the returned tuple to the role. ``render_skill_block(skills)`` is then
appended to every invocation's user message.

역할 구성 시점에 컨슈머가 ``SkillStore(root).for_role(name)`` 을 호출해 반환
튜플을 역할에 붙인다. 그 다음 ``render_skill_block(skills)`` 의 결과가 매
호출의 user message 에 덧붙는다.

The loader intentionally distinguishes ``summary`` and ``body`` so Phase 2
(progressive disclosure — summary only in prompt, body loaded on demand via a
``load_skill`` tool) can reuse the same data shape.

로더는 ``summary`` 와 ``body`` 를 의도적으로 분리한다. Phase 2(점진적 공개 —
프롬프트에는 summary 만, body 는 ``load_skill`` 도구로 on-demand 로딩)가
같은 데이터 형태를 재사용할 수 있도록.

## Consumer usage / 컨슈머 사용법

    from minyoung_mah import SkillStore, render_skill_block

    store = SkillStore(Path("coding_agent/skills"))
    planner_skills = store.for_role("planner")
    user_message = render_skill_block(planner_skills) + "\\n\\n" + task_summary

The library does **not** expose a module-level singleton — the root path is
consumer-specific and binding it here would leak one app's filesystem layout
into library state.

라이브러리는 module-level 싱글톤을 **노출하지 않는다** — root 경로는 컨슈머
특화이며, 여기에 묶어두면 한 앱의 파일시스템 배치가 라이브러리 상태로
누설되기 때문이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    name: str
    summary: str
    applies_to: tuple[str, ...]
    body: str
    path: Path


def parse_frontmatter(raw: str) -> dict[str, object]:
    """Minimal ``key: value`` parser for the SKILL.md frontmatter subset.
    SKILL.md frontmatter 부분집합을 위한 미니멀 ``key: value`` 파서.

    Supported forms::
    지원 형태::

        key: scalar
        key: [a, b, c]   # flow-style list on a single line / 한 줄 flow-style 리스트

    A full YAML dependency is avoided deliberately — the frontmatter schema is
    tiny and fixed, and pulling pyyaml into the library for three keys would
    be a bad trade. Consumers that want richer metadata can subclass
    :class:`SkillStore` and override ``_parse_skill``.

    완전한 YAML 의존성은 의도적으로 피한다 — frontmatter 스키마는 작고 고정이며,
    키 3개를 위해 pyyaml 을 라이브러리에 끌어들이는 건 나쁜 트레이드오프. 더
    풍부한 메타데이터가 필요한 컨슈머는 :class:`SkillStore` 를 서브클래싱해
    ``_parse_skill`` 을 오버라이드하면 된다.
    """
    meta: dict[str, object] = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1]
            items = [p.strip() for p in inner.split(",") if p.strip()]
            meta[key] = items
        else:
            meta[key] = value
    return meta


def _parse_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"Skill {path} missing YAML frontmatter")
    _, frontmatter_raw, body = text.split("---", 2)
    meta = parse_frontmatter(frontmatter_raw)
    name = str(meta.get("name") or path.stem)
    summary = str(meta.get("summary") or "")
    applies_raw = meta.get("applies_to") or []
    if isinstance(applies_raw, str):
        applies_raw = [applies_raw]
    applies_to = tuple(str(r) for r in applies_raw)
    return Skill(
        name=name,
        summary=summary,
        applies_to=applies_to,
        body=body.lstrip("\n"),
        path=path,
    )


class SkillStore:
    """Eagerly loads every ``*.md`` under ``root`` as a :class:`Skill`.
    ``root`` 아래 모든 ``*.md`` 를 :class:`Skill` 로 즉시(eager) 로드.

    Bodies are kept in memory so lookups inside the hot SubAgent invocation
    path avoid disk I/O. Total size is tiny (few KB for typical projects),
    so eager load is the right trade.

    body 는 메모리에 보관되어 hot SubAgent 호출 경로에서 디스크 I/O 를 피한다.
    총 크기가 작으므로(일반 프로젝트에서 수 KB) eager load 가 적절한 트레이드오프.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._by_name: dict[str, Skill] = {}
        self._by_role: dict[str, list[Skill]] = {}
        self._load()

    def _load(self) -> None:
        for md_path in sorted(self._root.rglob("*.md")):
            skill = _parse_skill(md_path)
            self._by_name[skill.name] = skill
            for role in skill.applies_to:
                self._by_role.setdefault(role, []).append(skill)

    def get(self, name: str) -> Skill | None:
        return self._by_name.get(name)

    def for_role(self, role_name: str) -> list[Skill]:
        return list(self._by_role.get(role_name, []))

    def all(self) -> list[Skill]:
        return list(self._by_name.values())


def render_skill_block(skills: list[Skill]) -> str:
    """Format skill bodies for inclusion in a SubAgent user message.
    스킬 본문들을 SubAgent user message 삽입용으로 포맷한다."""
    if not skills:
        return ""
    parts = ["## Skills (procedural playbooks)"]
    for s in skills:
        parts.append(f"### Skill: {s.name}")
        if s.summary:
            parts.append(f"_Summary: {s.summary}_")
        parts.append(s.body.rstrip())
    return "\n\n".join(parts)


__all__ = [
    "Skill",
    "SkillStore",
    "parse_frontmatter",
    "render_skill_block",
]
