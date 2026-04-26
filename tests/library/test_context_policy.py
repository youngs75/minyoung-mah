"""CompactPolicy + get_context_window 단위 테스트."""

from __future__ import annotations

import pytest

from minyoung_mah.context import CompactPolicy, default_policy, get_context_window


# ── get_context_window ────────────────────────────────────────────────────────


def test_known_claude_models():
    assert get_context_window("claude-opus-4-7") == 200_000
    assert get_context_window("claude-sonnet-4-6") == 200_000
    assert get_context_window("claude-haiku-4-5") == 200_000


def test_known_deepseek_models():
    assert get_context_window("deepseek-v4-pro") == 128_000
    assert get_context_window("deepseek-v4-flash") == 128_000


def test_dated_variant_uses_longest_prefix():
    # claude-opus-4-7-20240520 같은 dated suffix 도 prefix 매칭
    assert get_context_window("claude-opus-4-7-20240520") == 200_000


def test_unknown_model_returns_default():
    assert get_context_window("totally-unknown-model") == 128_000
    assert get_context_window("totally-unknown-model", default=64_000) == 64_000


def test_empty_model_name_returns_default():
    assert get_context_window("") == 128_000


def test_env_var_override(monkeypatch):
    monkeypatch.setenv(
        "MINYOUNG_CONTEXT_WINDOW_CLAUDE_OPUS_4_7", "500000"
    )
    assert get_context_window("claude-opus-4-7") == 500_000


def test_env_var_override_invalid_falls_back(monkeypatch):
    monkeypatch.setenv(
        "MINYOUNG_CONTEXT_WINDOW_CLAUDE_OPUS_4_7", "not-a-number"
    )
    # 잘못된 값은 무시 → 기본 매핑 사용
    assert get_context_window("claude-opus-4-7") == 200_000


def test_basechatmodel_object_resolves_via_attr(monkeypatch):
    class _FakeModel:
        model_name = "claude-opus-4-7"

    assert get_context_window(_FakeModel()) == 200_000


def test_basechatmodel_with_model_field():
    class _FakeModel:
        model = "deepseek-v4-pro"

    assert get_context_window(_FakeModel()) == 128_000


# ── CompactPolicy threshold 계산 ─────────────────────────────────────────────


def test_default_policy_ratios():
    p = default_policy()
    assert p.auto_compact_ratio == 0.85
    assert p.warning_ratio == 0.75
    assert p.blocking_ratio == 0.95
    assert p.output_reserve_tokens == 20_000
    assert p.max_consecutive_failures == 3
    assert p.enabled is True


def test_threshold_calculation():
    p = CompactPolicy(
        auto_compact_ratio=0.85,
        warning_ratio=0.75,
        blocking_ratio=0.95,
        output_reserve_tokens=20_000,
        enabled_env=None,
        ratio_override_env=None,
        blocking_override_env=None,
    )
    # context window 200K, output reserve 20K → usable 180K
    # auto = 180K * 0.85 = 153K
    assert p.auto_threshold_tokens(200_000) == 153_000
    assert p.warning_threshold_tokens(200_000) == 135_000
    assert p.blocking_threshold_tokens(200_000) == 171_000


def test_env_disable(monkeypatch):
    monkeypatch.setenv("MINYOUNG_AUTO_COMPACT", "0")
    p = CompactPolicy()
    assert p.enabled is False


def test_env_disable_false_string(monkeypatch):
    monkeypatch.setenv("MINYOUNG_AUTO_COMPACT", "false")
    p = CompactPolicy()
    assert p.enabled is False


def test_env_enable_explicit(monkeypatch):
    monkeypatch.setenv("MINYOUNG_AUTO_COMPACT", "1")
    p = CompactPolicy()
    assert p.enabled is True


def test_env_ratio_override(monkeypatch):
    monkeypatch.setenv("MINYOUNG_COMPACT_RATIO", "0.5")
    p = CompactPolicy()
    assert p.auto_compact_ratio == 0.5


def test_env_blocking_override(monkeypatch):
    monkeypatch.setenv("MINYOUNG_COMPACT_BLOCKING_LIMIT", "1000000")
    p = CompactPolicy()
    # 환경변수 절대값 사용 (200K context 무관)
    assert p.blocking_threshold_tokens(200_000) == 1_000_000
