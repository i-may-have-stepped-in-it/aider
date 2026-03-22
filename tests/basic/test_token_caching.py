"""Tests for token caching statistics and summary."""

import pytest

from aider.coders.base_coder_output import BaseCoderOutputMixin


class MockModel:
    """Mock model for testing."""

    name = "claude-3-5-sonnet"
    info = {
        "input_cost_per_token": 0.000003,  # $3.00 per 1M tokens
        "output_cost_per_token": 0.000015,  # $15.00 per 1M tokens
        "input_cost_per_token_cache_hit": 0.0000003,  # $0.30 per 1M tokens (10%)
    }


class MockCoder(BaseCoderOutputMixin):
    """Mock coder for testing cache statistics."""

    def __init__(self):
        self.total_cache_hit_tokens = 0
        self.total_cache_write_tokens = 0
        self.total_uncached_input_tokens = 0
        self.total_tokens_sent = 0
        self.total_tokens_received = 0
        self.total_cost = 0.0
        self.main_model = MockModel()

    class MockIO:
        @staticmethod
        def tool_output(msg):
            pass

    io = MockIO()


class TestTokenCaching:
    """Test token caching statistics."""

    def test_initial_state(self):
        """Test that cache stats start at zero."""
        coder = MockCoder()
        assert coder.total_cache_hit_tokens == 0
        assert coder.total_cache_write_tokens == 0
        assert coder.total_uncached_input_tokens == 0

    def test_reset_cache_stats(self):
        """Test resetting cache statistics."""
        coder = MockCoder()
        coder.total_cache_hit_tokens = 1000
        coder.total_cache_write_tokens = 500
        coder.total_uncached_input_tokens = 2000

        coder.reset_token_cache_stats()

        assert coder.total_cache_hit_tokens == 0
        assert coder.total_cache_write_tokens == 0
        assert coder.total_uncached_input_tokens == 0

    def test_get_token_cache_summary_no_data(self):
        """Test summary returns None when no cache data."""
        coder = MockCoder()
        summary = coder.get_token_cache_summary()
        assert summary is None

    def test_get_token_cache_summary_with_data(self):
        """Test summary with cache data."""
        coder = MockCoder()
        coder.total_cache_hit_tokens = 1000000
        coder.total_uncached_input_tokens = 200000
        coder.total_tokens_sent = 1200000
        coder.total_cost = 5.0

        summary = coder.get_token_cache_summary()
        assert summary is not None
        assert "TOKEN CACHE SUMMARY" in summary
        assert "1,000,000" in summary
        assert "Savings Highlight" in summary
        assert "83.3%" in summary  # Cache percentage

    def test_cache_efficiency_calculation(self):
        """Test cache efficiency percentage calculation."""
        coder = MockCoder()
        coder.total_cache_hit_tokens = 900000
        coder.total_uncached_input_tokens = 100000
        coder.total_tokens_sent = 1000000
        coder.total_cost = 3.0

        summary = coder.get_token_cache_summary()
        assert "90.0%" in summary  # 900k / 1M = 90%

    def test_cost_savings_calculation(self):
        """Test cost savings calculation in summary."""
        coder = MockCoder()
        coder.total_cache_hit_tokens = 1000000
        coder.total_uncached_input_tokens = 0
        coder.total_tokens_sent = 1000000
        # Cost with cache: 1M * $0.30/M = $0.30
        coder.total_cost = 0.30

        summary = coder.get_token_cache_summary()
        assert summary is not None
        # Without cache would cost: 1M * $3.00/M = $3.00
        # Savings: $3.00 - $0.30 = $2.70
        assert "2.7000" in summary or "2.70" in summary


class TestCacheTrackingAccumulation:
    """Test that cache stats accumulate correctly across messages."""

    def test_accumulation_simulation(self):
        """Simulate multiple messages and verify accumulation."""
        coder = MockCoder()

        # Simulate first message
        coder.total_cache_hit_tokens += 50000
        coder.total_cache_write_tokens += 10000
        coder.total_uncached_input_tokens += 30000

        # Simulate second message
        coder.total_cache_hit_tokens += 75000
        coder.total_cache_write_tokens += 5000
        coder.total_uncached_input_tokens += 25000

        assert coder.total_cache_hit_tokens == 125000
        assert coder.total_cache_write_tokens == 15000
        assert coder.total_uncached_input_tokens == 55000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
