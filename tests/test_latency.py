"""
Latency Regression Tests

RULE: No delay in FAST mode. All delays from latency_controller. First token never delayed.
       Build fails if violated.
"""

import pytest
import asyncio
import inspect
from unittest.mock import patch, MagicMock
from runtime.latency_controller import (
    LatencyController,
    LatencyProfile,
    LatencyBudget,
    new_controller,
    get_controller,
)


class TestLatencyControllerBasics:
    """Basic latency controller functionality."""
    
    def test_controller_creation(self):
        """Controller should initialize with profile."""
        controller = LatencyController(profile=LatencyProfile.FAST)
        assert controller.profile == LatencyProfile.FAST
        assert controller.elapsed_ms() >= 0
    
    def test_checkpoint_logging(self):
        """Checkpoints should be logged with elapsed time."""
        controller = LatencyController()
        controller.log_checkpoint("intent_classified")
        
        assert "intent_classified" in controller._checkpoints
        assert controller._checkpoints["intent_classified"] >= 0
    
    def test_budget_by_profile(self):
        """Each profile should have correct budget."""
        fast_budget = LatencyBudget.default(LatencyProfile.FAST)
        assert fast_budget.stream_chunk_delay_ms == 0
        assert fast_budget.first_token_max_ms == 2000
        assert fast_budget.total_response_max_ms == 6000
        
        argo_budget = LatencyBudget.default(LatencyProfile.ARGO)
        assert argo_budget.stream_chunk_delay_ms == 200
        assert argo_budget.total_response_max_ms == 10000
        
        voice_budget = LatencyBudget.default(LatencyProfile.VOICE)
        assert voice_budget.stream_chunk_delay_ms == 300
        assert voice_budget.total_response_max_ms == 15000


class TestFastModeContract:
    """FAST mode must have zero intentional delays."""
    
    def test_fast_mode_zero_delay(self):
        """FAST mode should have zero stream chunk delay."""
        fast = LatencyController(profile=LatencyProfile.FAST)
        assert fast.budget.stream_chunk_delay_ms == 0
    
    @pytest.mark.asyncio
    async def test_fast_mode_no_stream_delay(self):
        """Stream delay should be skipped in FAST mode."""
        fast = LatencyController(profile=LatencyProfile.FAST)
        
        # Record time before
        before = fast.elapsed_ms()
        
        # Apply stream delay (should be no-op)
        await fast.apply_stream_delay()
        
        # Record time after
        after = fast.elapsed_ms()
        
        # Should take minimal time (< 50ms for test overhead)
        assert (after - before) < 50, "FAST mode applied unexpected delay"
    
    def test_fast_mode_first_token_budget(self):
        """FAST mode first token budget should be 2 seconds max."""
        fast = LatencyController(profile=LatencyProfile.FAST)
        assert fast.budget.first_token_max_ms == 2000


class TestDelayOriginControl:
    """All delays must originate from latency_controller."""
    
    @pytest.mark.asyncio
    async def test_intentional_delay_logged(self):
        """Intentional delays should be logged."""
        controller = LatencyController()
        
        with patch("runtime.latency_controller.logger") as mock_logger:
            await controller.apply_intentional_delay("tool_execution", 100)
            
            # Should have logged the delay
            assert mock_logger.info.called
            call_args = str(mock_logger.info.call_args)
            assert "tool_execution" in call_args
    
    @pytest.mark.asyncio
    async def test_delay_skipped_if_exceeds_budget(self):
        """Delay should be skipped if it would exceed total budget."""
        controller = LatencyController(profile=LatencyProfile.FAST)
        budget = controller.budget
        
        # Simulate being very close to budget
        controller._start_time = asyncio.get_event_loop().time() - (budget.total_response_max_ms - 100) / 1000
        
        with patch("runtime.latency_controller.logger") as mock_logger:
            await controller.apply_intentional_delay("tool", 200)
            
            # Should warn about skipping
            assert mock_logger.warning.called


class TestFirstTokenTiming:
    """First token should never be delayed."""
    
    def test_check_first_token_under_budget(self):
        """Should not warn if first token is under budget."""
        controller = LatencyController(profile=LatencyProfile.FAST)
        controller._checkpoints["first_token_received"] = 1500  # Under 2000ms budget
        
        with patch("runtime.latency_controller.logger") as mock_logger:
            controller.check_first_token_latency()
            
            # Should not warn
            assert not mock_logger.warning.called
    
    def test_check_first_token_exceeds_budget(self):
        """Should warn if first token exceeds budget."""
        controller = LatencyController(profile=LatencyProfile.FAST)
        controller._checkpoints["first_token_received"] = 2500  # Over 2000ms budget
        
        with patch("runtime.latency_controller.logger") as mock_logger:
            controller.check_first_token_latency()
            
            # Should warn
            assert mock_logger.warning.called
            call_args = str(mock_logger.warning.call_args)
            assert "First token" in call_args


class TestStatusEmission:
    """Should emit status for long operations."""
    
    def test_should_emit_status_over_3s(self):
        """Should emit status if processing > 3 seconds."""
        controller = LatencyController()
        
        # Simulate long operation
        import time
        controller._start_time = time.monotonic() - 4.0
        
        assert controller.should_emit_status() is True
    
    def test_should_not_emit_status_under_3s(self):
        """Should not emit status if processing < 3 seconds."""
        controller = LatencyController()
        # Start time is recent
        assert controller.should_emit_status() is False


class TestReporting:
    """Latency reports should be structured."""
    
    def test_report_structure(self):
        """Report should have required fields."""
        controller = LatencyController(profile=LatencyProfile.ARGO)
        controller.log_checkpoint("intent_classified")
        
        report = controller.report()
        
        assert "profile" in report
        assert "elapsed_ms" in report
        assert "checkpoints" in report
        assert "had_intentional_delays" in report
        assert "exceeded_budget" in report
        
        assert report["profile"] == "ARGO"
        assert "intent_classified" in report["checkpoints"]


class TestGlobalController:
    """Global controller instance management."""
    
    def test_set_and_get_controller(self):
        """Should set and retrieve global controller."""
        from runtime.latency_controller import set_controller, get_controller
        
        controller = LatencyController(profile=LatencyProfile.FAST)
        set_controller(controller)
        
        retrieved = get_controller()
        assert retrieved is controller
        assert retrieved.profile == LatencyProfile.FAST


class TestNoInlineSleeps:
    """Ensure no inline sleeps in codebase."""
    
    def test_no_time_sleep_in_main_code(self):
        """Main code should not use time.sleep()."""
        import time
        import inspect
        
        # Check latency_controller itself
        source = inspect.getsource(LatencyController)
        
        # Should not have direct time.sleep calls
        assert "time.sleep(" not in source, "Found inline time.sleep() in LatencyController"
    
    @pytest.mark.asyncio
    async def test_stream_delay_uses_async_sleep(self):
        """Stream delay should use async sleep, not blocking sleep."""
        controller = LatencyController(profile=LatencyProfile.ARGO)
        
        # Should be awaitable (async)
        delay_coro = controller.apply_stream_delay()
        assert inspect.iscoroutine(delay_coro)
        await delay_coro


class TestBudgetExceedance:
    """Should handle budget exceedance gracefully."""
    
    def test_report_when_budget_exceeded(self):
        """Report should indicate if budget was exceeded."""
        controller = LatencyController(profile=LatencyProfile.FAST)
        
        # Simulate operation taking longer than budget
        import time
        controller._start_time = time.monotonic() - 7.0
        
        report = controller.report()
        assert report["exceeded_budget"] is True
    
    def test_report_when_budget_ok(self):
        """Report should indicate when budget is met."""
        controller = LatencyController(profile=LatencyProfile.FAST)
        # Just created, elapsed time is near 0
        
        report = controller.report()
        assert report["exceeded_budget"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
