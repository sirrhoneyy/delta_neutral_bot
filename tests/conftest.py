"""Shared test fixtures for delta-neutral bot tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from pydantic import SecretStr

from config.constants import ExchangeName, PositionSide, OrderStatus
from config.settings import Settings, ExtendedSettings, TradeXYZSettings, RiskSettings
from exchanges.base import (
    MarketInfo,
    PositionInfo,
    BalanceResult,
    TradeResult,
    OrderInfo,
)


@pytest.fixture
def mock_market_info() -> MarketInfo:
    """Create mock market info for BTC."""
    return MarketInfo(
        symbol="BTC-USD",
        base_asset="BTC",
        quote_asset="USD",
        mark_price=50000.0,
        index_price=50000.0,
        last_price=50000.0,
        bid_price=49990.0,
        ask_price=50010.0,
        funding_rate=0.0001,
        next_funding_time=0,
        min_order_size=0.001,
        min_order_size_change=0.001,
        min_price_change=0.1,
        max_leverage=50,
        is_active=True,
        status="ACTIVE",
    )


@pytest.fixture
def mock_balance_result() -> BalanceResult:
    """Create mock balance result."""
    return BalanceResult(
        exchange=ExchangeName.EXTENDED,
        balance=10000.0,
        equity=10000.0,
        available_for_trade=9000.0,
        available_for_withdrawal=8000.0,
        unrealized_pnl=0.0,
        initial_margin=1000.0,
        margin_ratio=0.1,
        exposure=5000.0,
        leverage=5.0,
        currency="USD",
        updated_time=0,
    )


@pytest.fixture
def mock_position_info() -> PositionInfo:
    """Create mock position info."""
    return PositionInfo(
        position_id="test_pos_1",
        exchange=ExchangeName.EXTENDED,
        symbol="BTC-USD",
        side=PositionSide.LONG,
        size=0.1,
        value=5000.0,
        entry_price=50000.0,
        mark_price=50100.0,
        liquidation_price=40000.0,
        unrealized_pnl=10.0,
        realized_pnl=0.0,
        leverage=10,
        margin=500.0,
        created_time=0,
        updated_time=0,
    )


@pytest.fixture
def mock_trade_result_success() -> TradeResult:
    """Create successful trade result."""
    return TradeResult(
        success=True,
        order_id="order_123",
        external_id="ext_456",
        error_message=None,
        error_code=None,
        filled_quantity=0.1,
        average_price=50000.0,
        fee_paid=5.0,
    )


@pytest.fixture
def mock_trade_result_failure() -> TradeResult:
    """Create failed trade result."""
    return TradeResult(
        success=False,
        order_id=None,
        external_id=None,
        error_message="Insufficient margin",
        error_code="INSUFFICIENT_MARGIN",
    )


@pytest.fixture
def mock_extended_exchange(
    mock_market_info,
    mock_balance_result,
    mock_position_info,
    mock_trade_result_success,
):
    """Create mock Extended exchange."""
    exchange = AsyncMock()
    exchange.name = ExchangeName.EXTENDED
    exchange._simulation = True
    exchange._connected = True

    # Configure async methods
    exchange.connect = AsyncMock(return_value=True)
    exchange.disconnect = AsyncMock()
    exchange.get_market_info = AsyncMock(return_value=mock_market_info)
    exchange.get_balance = AsyncMock(return_value=mock_balance_result)
    exchange.get_positions = AsyncMock(return_value=[mock_position_info])
    exchange.place_order = AsyncMock(return_value=mock_trade_result_success)
    exchange.close_position = AsyncMock(return_value=mock_trade_result_success)
    exchange.set_leverage = AsyncMock(return_value=True)
    exchange.get_market_symbol = MagicMock(return_value="BTC-USD")

    return exchange


@pytest.fixture
def mock_tradexyz_exchange(
    mock_market_info,
    mock_balance_result,
    mock_position_info,
    mock_trade_result_success,
):
    """Create mock TradeXYZ exchange."""
    exchange = AsyncMock()
    exchange.name = ExchangeName.TRADEXYZ
    exchange._simulation = True
    exchange._connected = True

    # Configure async methods
    exchange.connect = AsyncMock(return_value=True)
    exchange.disconnect = AsyncMock()
    exchange.get_market_info = AsyncMock(return_value=mock_market_info)
    exchange.get_balance = AsyncMock(return_value=mock_balance_result)
    exchange.get_positions = AsyncMock(return_value=[mock_position_info])
    exchange.place_order = AsyncMock(return_value=mock_trade_result_success)
    exchange.close_position = AsyncMock(return_value=mock_trade_result_success)
    exchange.set_leverage = AsyncMock(return_value=True)
    exchange.get_market_symbol = MagicMock(return_value="BTC")

    return exchange


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings in simulation mode."""
    return Settings(
        simulation_mode=True,
        simulation_balance_usd=10000.0,
        log_level="DEBUG",
        extended=ExtendedSettings(
            base_url="https://api.test.extended.exchange",
            api_key=SecretStr("test_api_key"),
            stark_private_key=SecretStr("0x1234567890abcdef"),
            l2_key="test_l2_key",
            vault="test_vault",
            account_id="test_account",
        ),
        tradexyz=TradeXYZSettings(
            base_url="https://api.test.tradexyz.exchange",
            wallet_address="0x1234567890123456789012345678901234567890",
            api_secret=SecretStr("0x" + "a" * 64),
        ),
        risk=RiskSettings(
            min_balance_usd=100.0,
            max_position_value_usd=50000.0,
            max_consecutive_failures=3,
            max_slippage_percent=0.5,
        ),
    )


@pytest.fixture
def cycle_start_time() -> datetime:
    """Create a cycle start time."""
    return datetime.now(timezone.utc)
