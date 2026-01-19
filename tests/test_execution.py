"""Tests for AtomicExecutor."""

import pytest
from unittest.mock import AsyncMock

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.constants import ExchangeName, PositionSide
from execution.atomic import AtomicExecutor, ExecutionState
from exchanges.base import TradeResult


class TestAtomicExecutor:
    """Tests for AtomicExecutor."""

    @pytest.fixture
    def executor(self, mock_extended_exchange, mock_tradexyz_exchange):
        """Create executor with mocked exchanges."""
        return AtomicExecutor(
            extended_exchange=mock_extended_exchange,
            tradexyz_exchange=mock_tradexyz_exchange,
            max_execution_time=30.0,
            parallel_open=True,
        )

    @pytest.mark.asyncio
    async def test_open_positions_success(
        self,
        executor,
        mock_extended_exchange,
        mock_tradexyz_exchange,
    ):
        """Both legs should open successfully."""
        result = await executor.open_positions(
            token="BTC",
            size=0.1,
            extended_side=PositionSide.LONG,
            tradexyz_side=PositionSide.SHORT,
            leverage=10,
            price=50000.0,
        )

        assert result.success is True
        assert result.state == ExecutionState.COMPLETE
        assert result.extended_leg is not None
        assert result.tradexyz_leg is not None
        assert result.rollback_performed is False

    @pytest.mark.asyncio
    async def test_open_positions_extended_fails(
        self,
        executor,
        mock_extended_exchange,
        mock_tradexyz_exchange,
        mock_trade_result_failure,
    ):
        """Should handle failure on Extended leg."""
        mock_extended_exchange.place_order = AsyncMock(
            return_value=mock_trade_result_failure
        )

        result = await executor.open_positions(
            token="BTC",
            size=0.1,
            extended_side=PositionSide.LONG,
            tradexyz_side=PositionSide.SHORT,
            leverage=10,
            price=50000.0,
        )

        assert result.success is False
        assert result.extended_leg is not None
        assert result.extended_leg.success is False

    @pytest.mark.asyncio
    async def test_open_positions_tradexyz_fails_with_rollback(
        self,
        executor,
        mock_extended_exchange,
        mock_tradexyz_exchange,
        mock_trade_result_success,
        mock_trade_result_failure,
    ):
        """Should rollback Extended when TradeXYZ fails."""
        # Extended succeeds, TradeXYZ fails
        mock_extended_exchange.place_order = AsyncMock(
            return_value=mock_trade_result_success
        )
        mock_tradexyz_exchange.place_order = AsyncMock(
            return_value=mock_trade_result_failure
        )

        result = await executor.open_positions(
            token="BTC",
            size=0.1,
            extended_side=PositionSide.LONG,
            tradexyz_side=PositionSide.SHORT,
            leverage=10,
            price=50000.0,
        )

        assert result.success is False
        assert result.rollback_performed is True
        # Verify close_position was called on Extended for rollback
        mock_extended_exchange.close_position.assert_called()

    @pytest.mark.asyncio
    async def test_close_positions_success(
        self,
        executor,
        mock_extended_exchange,
        mock_tradexyz_exchange,
    ):
        """Both position closes should succeed."""
        result = await executor.close_positions(token="BTC")

        assert result.success is True
        assert result.state == ExecutionState.COMPLETE
        mock_extended_exchange.close_position.assert_called_with("BTC", None)
        mock_tradexyz_exchange.close_position.assert_called_with("BTC", None)

    @pytest.mark.asyncio
    async def test_close_positions_partial_failure(
        self,
        executor,
        mock_extended_exchange,
        mock_tradexyz_exchange,
        mock_trade_result_success,
        mock_trade_result_failure,
    ):
        """Should report failure if one close fails."""
        mock_extended_exchange.close_position = AsyncMock(
            return_value=mock_trade_result_success
        )
        mock_tradexyz_exchange.close_position = AsyncMock(
            return_value=mock_trade_result_failure
        )

        result = await executor.close_positions(token="BTC")

        assert result.success is False
        assert result.extended_leg.success is True
        assert result.tradexyz_leg.success is False

    @pytest.mark.asyncio
    async def test_leverage_set_before_open(
        self,
        executor,
        mock_extended_exchange,
        mock_tradexyz_exchange,
    ):
        """Leverage should be set on both exchanges before opening."""
        await executor.open_positions(
            token="BTC",
            size=0.1,
            extended_side=PositionSide.LONG,
            tradexyz_side=PositionSide.SHORT,
            leverage=15,
            price=50000.0,
        )

        mock_extended_exchange.set_leverage.assert_called_with("BTC", 15)
        mock_tradexyz_exchange.set_leverage.assert_called_with("BTC", 15)

    @pytest.mark.asyncio
    async def test_execution_time_tracked(
        self,
        executor,
        mock_extended_exchange,
        mock_tradexyz_exchange,
    ):
        """Execution time should be tracked."""
        result = await executor.open_positions(
            token="BTC",
            size=0.1,
            extended_side=PositionSide.LONG,
            tradexyz_side=PositionSide.SHORT,
            leverage=10,
            price=50000.0,
        )

        assert result.execution_time_ms >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
