"""Tests for SafetyMonitor."""

import pytest
from unittest.mock import AsyncMock

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.constants import ExchangeName, PositionSide
from execution.safety import SafetyMonitor, EmergencyReason


class TestSafetyMonitor:
    """Tests for SafetyMonitor failure tracking and emergency detection."""

    @pytest.fixture
    def safety_monitor(self, mock_extended_exchange, mock_tradexyz_exchange):
        """Create safety monitor with mocked exchanges."""
        return SafetyMonitor(
            extended_exchange=mock_extended_exchange,
            tradexyz_exchange=mock_tradexyz_exchange,
            max_consecutive_failures=3,
        )

    def test_initial_state(self, safety_monitor):
        """Monitor should start in safe state."""
        assert safety_monitor.consecutive_failures == 0
        assert safety_monitor.emergency_triggered is False
        assert safety_monitor.shutdown_requested is False

    def test_record_failure_increments_count(self, safety_monitor):
        """Recording failure should increment counter."""
        safety_monitor.record_failure()
        assert safety_monitor.consecutive_failures == 1

        safety_monitor.record_failure()
        assert safety_monitor.consecutive_failures == 2

    def test_record_success_resets_failures(self, safety_monitor):
        """Recording success should reset failure counter."""
        safety_monitor.record_failure()
        safety_monitor.record_failure()
        assert safety_monitor.consecutive_failures == 2

        safety_monitor.record_success()
        assert safety_monitor.consecutive_failures == 0

    def test_max_failures_triggers_emergency(self, safety_monitor):
        """Exceeding max failures should trigger emergency."""
        for _ in range(3):
            safety_monitor.record_failure()

        assert safety_monitor.emergency_triggered is True

    def test_add_monitored_token(self, safety_monitor):
        """Should track monitored tokens."""
        safety_monitor.add_monitored_token("BTC")
        safety_monitor.add_monitored_token("ETH")

        assert "BTC" in safety_monitor._monitored_tokens
        assert "ETH" in safety_monitor._monitored_tokens

    def test_remove_monitored_token(self, safety_monitor):
        """Should remove monitored tokens."""
        safety_monitor.add_monitored_token("BTC")
        safety_monitor.add_monitored_token("ETH")
        safety_monitor.remove_monitored_token("BTC")

        assert "BTC" not in safety_monitor._monitored_tokens
        assert "ETH" in safety_monitor._monitored_tokens

    @pytest.mark.asyncio
    async def test_check_exposure_no_positions(
        self,
        safety_monitor,
        mock_extended_exchange,
        mock_tradexyz_exchange,
    ):
        """Should pass with no monitored tokens."""
        mock_extended_exchange.get_positions = AsyncMock(return_value=[])
        mock_tradexyz_exchange.get_positions = AsyncMock(return_value=[])

        result = await safety_monitor.check_exposure()
        assert result is True

    @pytest.mark.asyncio
    async def test_check_exposure_balanced_positions(
        self,
        safety_monitor,
        mock_extended_exchange,
        mock_tradexyz_exchange,
        mock_position_info,
    ):
        """Should pass with balanced positions."""
        # Create opposing positions of same size
        ext_pos = mock_position_info
        ext_pos.side = PositionSide.LONG
        ext_pos.size = 0.1

        xyz_pos = mock_position_info
        xyz_pos.exchange = ExchangeName.TRADEXYZ
        xyz_pos.side = PositionSide.SHORT
        xyz_pos.size = 0.1

        mock_extended_exchange.get_positions = AsyncMock(return_value=[ext_pos])
        mock_tradexyz_exchange.get_positions = AsyncMock(return_value=[xyz_pos])

        safety_monitor.add_monitored_token("BTC")
        result = await safety_monitor.check_exposure()
        assert result is True

    def test_trigger_emergency_sets_flag(self, safety_monitor):
        """Triggering emergency should set flag."""
        safety_monitor.trigger_emergency(EmergencyReason.UNHEDGED_EXPOSURE)

        assert safety_monitor.emergency_triggered is True
        assert safety_monitor._emergency_reason == EmergencyReason.UNHEDGED_EXPOSURE

    def test_request_shutdown(self, safety_monitor):
        """Requesting shutdown should set flag."""
        safety_monitor.request_shutdown()

        assert safety_monitor.shutdown_requested is True

    def test_get_status_report(self, safety_monitor):
        """Should generate status report."""
        safety_monitor.record_failure()
        safety_monitor.add_monitored_token("BTC")

        status = safety_monitor.get_status()

        assert status["consecutive_failures"] == 1
        assert status["emergency_triggered"] is False
        assert "BTC" in status["monitored_tokens"]


class TestEmergencyReason:
    """Tests for EmergencyReason enum."""

    def test_all_reasons_have_values(self):
        """All emergency reasons should have string values."""
        for reason in EmergencyReason:
            assert isinstance(reason.value, str)
            assert len(reason.value) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
