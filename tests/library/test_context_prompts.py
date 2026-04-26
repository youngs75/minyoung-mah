"""prompts.py — extract_summary_text 와 build helper."""

from __future__ import annotations

from minyoung_mah.context import (
    BASE_COMPACT_PROMPT,
    NO_TOOLS_PREAMBLE,
    PARTIAL_COMPACT_FROM_PROMPT,
    PARTIAL_COMPACT_UP_TO_PROMPT,
)
from minyoung_mah.context.prompts import (
    extract_summary_text,
    get_compact_prompt,
    get_partial_compact_prompt,
)


# ── Constants ────────────────────────────────────────────────────────────────


def test_no_tools_preamble_forbids_tools():
    assert "Do NOT call any tools" in NO_TOOLS_PREAMBLE
    assert "TEXT ONLY" in NO_TOOLS_PREAMBLE


def test_base_prompt_has_seven_plus_sections():
    # 7 (claude-code 의 9개) 섹션 모두 포함
    sections = [
        "1. Primary Request and Intent",
        "2. Key Technical Concepts",
        "3. Files and Code Sections",
        "4. Errors and fixes",
        "5. Problem Solving",
        "6. All user messages",
        "7. Pending Tasks",
        "8. Current Work",
        "9. Optional Next Step",
    ]
    for s in sections:
        assert s in BASE_COMPACT_PROMPT


def test_partial_from_prompt_focuses_on_recent():
    assert "RECENT portion of the conversation" in PARTIAL_COMPACT_FROM_PROMPT
    assert "do NOT need to be summarized" in PARTIAL_COMPACT_FROM_PROMPT


def test_partial_up_to_prompt_focuses_on_continuation():
    assert "Work Completed" in PARTIAL_COMPACT_UP_TO_PROMPT
    assert "Context for Continuing Work" in PARTIAL_COMPACT_UP_TO_PROMPT


# ── get_compact_prompt builder ──────────────────────────────────────────────


def test_get_compact_prompt_includes_preamble_and_base():
    p = get_compact_prompt()
    assert NO_TOOLS_PREAMBLE in p
    assert "1. Primary Request and Intent" in p
    assert "REMINDER: Do NOT call any tools" in p


def test_get_compact_prompt_with_custom_instructions():
    p = get_compact_prompt(custom_instructions="focus on python only")
    assert "Additional Instructions:" in p
    assert "focus on python only" in p


def test_get_compact_prompt_ignores_blank_custom():
    p_blank = get_compact_prompt(custom_instructions="   ")
    p_none = get_compact_prompt()
    assert "Additional Instructions:" not in p_blank
    assert p_blank == p_none


def test_get_partial_compact_prompt_from_direction():
    p = get_partial_compact_prompt(direction="from")
    assert "RECENT portion" in p
    assert "Work Completed" not in p


def test_get_partial_compact_prompt_up_to_direction():
    p = get_partial_compact_prompt(direction="up_to")
    assert "Work Completed" in p
    assert "Context for Continuing Work" in p


# ── extract_summary_text ────────────────────────────────────────────────────


def test_extract_summary_text_strips_analysis():
    raw = (
        "<analysis>\nthinking through it\n</analysis>\n"
        "<summary>\nthe actual summary\n</summary>"
    )
    extracted = extract_summary_text(raw)
    assert extracted == "the actual summary"


def test_extract_summary_text_handles_only_summary_tag():
    raw = "<summary>just summary</summary>"
    assert extract_summary_text(raw) == "just summary"


def test_extract_summary_text_handles_missing_tags():
    raw = "no tags at all, just plain text body"
    assert extract_summary_text(raw) == raw


def test_extract_summary_text_strips_analysis_when_no_summary_tag():
    raw = "<analysis>thinking</analysis>\nplain summary text after"
    extracted = extract_summary_text(raw)
    assert "<analysis>" not in extracted
    assert "plain summary text after" in extracted


def test_extract_summary_text_multiline_summary():
    raw = """<summary>
1. Section one
2. Section two
3. Section three
</summary>"""
    extracted = extract_summary_text(raw)
    assert "1. Section one" in extracted
    assert "3. Section three" in extracted
