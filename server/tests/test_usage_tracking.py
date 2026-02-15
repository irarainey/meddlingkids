"""Tests for src.utils.usage_tracking — LLM call and token tracking."""

from __future__ import annotations

from src.utils import usage_tracking


class TestUsageTracking:
    """Tests for the usage_tracking module."""

    def setup_method(self) -> None:
        """Reset usage counters before each test."""
        usage_tracking.reset()

    def test_reset_clears_counters(self) -> None:
        usage_tracking.record("TestAgent", input_tokens=100, output_tokens=50)
        usage_tracking.reset()
        usage = usage_tracking._get_usage()
        assert usage.total_calls == 0
        assert usage.total_tokens == 0

    def test_record_increments_calls(self) -> None:
        usage_tracking.record("Agent1")
        usage_tracking.record("Agent2")
        usage = usage_tracking._get_usage()
        assert usage.total_calls == 2

    def test_record_accumulates_tokens(self) -> None:
        usage_tracking.record("Agent1", input_tokens=100, output_tokens=50)
        usage_tracking.record("Agent2", input_tokens=200, output_tokens=100)
        usage = usage_tracking._get_usage()
        assert usage.total_input_tokens == 300
        assert usage.total_output_tokens == 150
        assert usage.total_tokens == 450

    def test_record_with_total_tokens_only(self) -> None:
        usage_tracking.record("Agent1", total_tokens=500)
        usage = usage_tracking._get_usage()
        assert usage.total_tokens == 500

    def test_record_with_no_tokens(self) -> None:
        usage_tracking.record("Agent1")
        usage = usage_tracking._get_usage()
        assert usage.total_calls == 1
        assert usage.total_tokens == 0

    def test_log_summary_with_no_calls(self) -> None:
        # Should not raise
        usage_tracking.log_summary()

    def test_log_summary_with_calls(self) -> None:
        usage_tracking.record("Agent1", input_tokens=100, output_tokens=50)
        # Should not raise
        usage_tracking.log_summary()
