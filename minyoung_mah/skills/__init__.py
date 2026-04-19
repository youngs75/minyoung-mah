"""Skill loader — static injection of procedural knowledge into SubAgent runs.

Skills separate **procedure** from **identity**. The role system prompt stays
an identity contract ("you are a verifier") while edit-friendly SKILL.md files
hold the how-to steps. Consumers choose the injection policy — the library
only provides the loader + a renderer.

## Phase 1 — static injection

At role build time the consumer calls ``SkillStore(root).for_role(name)`` and
attaches the returned tuple to the role. ``render_skill_block(skills)`` is then
appended to every invocation's user message.

The loader intentionally distinguishes ``summary`` and ``body`` so Phase 2
(progressive disclosure — summary only in prompt, body loaded on demand via a
``load_skill`` tool) can reuse the same data shape.

## Consumer usage

    from minyoung_mah import SkillStore, render_skill_block

    store = SkillStore(Path("coding_agent/skills"))
    planner_skills = store.for_role("planner")
    user_message = render_skill_block(planner_skills) + "\\n\\n" + task_summary

The library does **not** expose a module-level singleton — the root path is
consumer-specific and binding it here would leak one app's filesystem layout
into library state.
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

    Supported forms::

        key: scalar
        key: [a, b, c]   # flow-style list on a single line

    A full YAML dependency is avoided deliberately — the frontmatter schema is
    tiny and fixed, and pulling pyyaml into the library for three keys would
    be a bad trade. Consumers that want richer metadata can subclass
    :class:`SkillStore` and override ``_parse_skill``.
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

    Bodies are kept in memory so lookups inside the hot SubAgent invocation
    path avoid disk I/O. Total size is tiny (few KB for typical projects),
    so eager load is the right trade.
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
    """Format skill bodies for inclusion in a SubAgent user message."""
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
