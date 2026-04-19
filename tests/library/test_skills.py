"""Unit tests for ``minyoung_mah.skills``.

Covers frontmatter parsing, multi-role indexing, and the render pipeline.
The store intentionally does not ship a singleton — tests construct it with
a temporary root to avoid cross-test leakage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from minyoung_mah import Skill, SkillStore, parse_frontmatter, render_skill_block


SKILL_DOC = """\
---
name: planning-workflow
summary: Read request, ask planner HITL if ambiguous, decompose tasks
applies_to: [planner]
---

## Steps

1. Read the request.
2. If ambiguous, ask the user.
3. Decompose into atomic tasks.
"""


SHARED_SKILL_DOC = """\
---
name: shared-discipline
summary: Shared discipline for planner + verifier
applies_to: [planner, verifier]
---

Be concise. Cite paths.
"""


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_parse_frontmatter_handles_scalars_and_flow_lists():
    meta = parse_frontmatter(
        """
        name: demo
        summary: A short line
        applies_to: [planner, coder, verifier]
        # comment ignored
        ignored_without_colon
        """
    )
    assert meta["name"] == "demo"
    assert meta["summary"] == "A short line"
    assert meta["applies_to"] == ["planner", "coder", "verifier"]
    assert "ignored_without_colon" not in meta


def test_skill_store_indexes_by_name_and_role(tmp_path: Path):
    _write(tmp_path, "planner/workflow.md", SKILL_DOC)
    _write(tmp_path, "shared/discipline.md", SHARED_SKILL_DOC)

    store = SkillStore(tmp_path)

    assert isinstance(store.get("planning-workflow"), Skill)
    planner_skills = store.for_role("planner")
    verifier_skills = store.for_role("verifier")

    assert {s.name for s in planner_skills} == {"planning-workflow", "shared-discipline"}
    assert [s.name for s in verifier_skills] == ["shared-discipline"]
    assert len(store.all()) == 2


def test_skill_store_rejects_file_without_frontmatter(tmp_path: Path):
    _write(tmp_path, "bad.md", "no frontmatter here")
    with pytest.raises(ValueError, match="missing YAML frontmatter"):
        SkillStore(tmp_path)


def test_render_skill_block_emits_header_and_bodies(tmp_path: Path):
    _write(tmp_path, "planner/workflow.md", SKILL_DOC)
    store = SkillStore(tmp_path)

    rendered = render_skill_block(store.for_role("planner"))

    assert rendered.startswith("## Skills (procedural playbooks)")
    assert "### Skill: planning-workflow" in rendered
    assert "_Summary: Read request" in rendered
    assert "Decompose into atomic tasks." in rendered


def test_render_skill_block_empty_returns_empty_string():
    assert render_skill_block([]) == ""
