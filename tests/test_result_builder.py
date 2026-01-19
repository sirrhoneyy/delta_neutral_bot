"""Tests for CycleResultBuilder."""

import pytest
from datetime import datetime, timezone

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.constants import CycleState, PositionSide
from execution.result_builder import CycleResultBuilder
from utils.timing import CycleTimer


class TestCycleResultBuilder:
    """Tests for CycleResultBuilder."""

    def test_build_minimal_result(self, cycle_start_time):
        """Builder should create result with minimal data."""
        timer = CycleTimer()
        timer.start()

        result = (
            CycleResultBuilder("cycle_001", cycle_start_time)
            .build(timer)
        )

        assert result.cycle_id == "cycle_001"
        assert result.start_time == cycle_start_time
        assert result.success is True  # Default
        assert result.state == CycleState.IDLE  # Default

    def test_build_with_params(self, cycle_start_time):
        """Builder should set params correctly."""
        timer = CycleTimer()
        timer.start()

        result = (
            CycleResultBuilder("cycle_002", cycle_start_time)
            .with_params("BTC", 0.5, 10, 3600)
            .build(timer)
        )

        assert result.token == "BTC"
        assert result.equity_usage == 0.5
        assert result.leverage == 10
        assert result.hold_duration == 3600

    def test_build_with_positions(self, cycle_start_time):
        """Builder should set position data correctly."""
        timer = CycleTimer()
        timer.start()

        result = (
            CycleResultBuilder("cycle_003", cycle_start_time)
            .with_positions(
                PositionSide.LONG,
                PositionSide.SHORT,
                0.1,
                5000.0,
            )
            .build(timer)
        )

        assert result.extended_side == PositionSide.LONG
        assert result.tradexyz_side == PositionSide.SHORT
        assert result.position_size == 0.1
        assert result.position_value == 5000.0

    def test_build_with_error(self, cycle_start_time):
        """Builder should mark failure with error."""
        timer = CycleTimer()
        timer.start()

        result = (
            CycleResultBuilder("cycle_004", cycle_start_time)
            .with_error("Something went wrong", CycleState.ERROR)
            .build(timer)
        )

        assert result.success is False
        assert result.state == CycleState.ERROR
        assert result.error_message == "Something went wrong"

    def test_build_with_success(self, cycle_start_time):
        """Builder should mark success correctly."""
        timer = CycleTimer()
        timer.start()

        result = (
            CycleResultBuilder("cycle_005", cycle_start_time)
            .with_params("ETH", 0.6, 15, 1800)
            .with_positions(PositionSide.SHORT, PositionSide.LONG, 1.0, 3000.0)
            .with_success(CycleState.COOLDOWN, 25.0)
            .build(timer)
        )

        assert result.success is True
        assert result.state == CycleState.COOLDOWN
        assert result.funding_earned == 25.0

    def test_build_complete_cycle(self, cycle_start_time):
        """Builder should handle complete cycle with all data."""
        timer = CycleTimer()
        timer.start()

        result = (
            CycleResultBuilder("cycle_006", cycle_start_time)
            .with_params("SOL", 0.7, 20, 7200)
            .with_positions(PositionSide.LONG, PositionSide.SHORT, 100.0, 10000.0)
            .with_funding(None, 50.0)
            .with_success(CycleState.COOLDOWN, 50.0)
            .build(timer)
        )

        assert result.cycle_id == "cycle_006"
        assert result.success is True
        assert result.token == "SOL"
        assert result.leverage == 20
        assert result.position_size == 100.0
        assert result.funding_earned == 50.0
        assert result.end_time is not None
        assert result.total_duration_seconds >= 0

    def test_builder_is_chainable(self, cycle_start_time):
        """All builder methods should return self for chaining."""
        timer = CycleTimer()
        timer.start()

        builder = CycleResultBuilder("cycle_007", cycle_start_time)

        # Each method should return the builder
        assert builder.with_params("BTC", 0.5, 10, 3600) is builder
        assert builder.with_positions(PositionSide.LONG, PositionSide.SHORT, 0.1, 5000.0) is builder
        assert builder.with_funding(None) is builder
        assert builder.with_execution(None) is builder
        assert builder.with_error("test") is builder

    def test_emergency_state(self, cycle_start_time):
        """Builder should handle emergency state."""
        timer = CycleTimer()
        timer.start()

        result = (
            CycleResultBuilder("cycle_008", cycle_start_time)
            .with_params("BTC", 0.5, 10, 3600)
            .with_error("Emergency triggered", CycleState.EMERGENCY)
            .build(timer)
        )

        assert result.success is False
        assert result.state == CycleState.EMERGENCY


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
