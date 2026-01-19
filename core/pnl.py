"""P&L calculation for delta-neutral trading cycles."""

from dataclasses import dataclass
from typing import Optional

from exchanges.base import PositionInfo


@dataclass(frozen=True)
class CyclePnL:
    """
    P&L breakdown for a complete trading cycle.

    Captures all components of profit and loss from a delta-neutral
    position pair across both exchanges.
    """
    # Realized P&L from position closure (price difference)
    extended_realized_pnl: float
    tradexyz_realized_pnl: float

    # Funding payments received/paid during hold period
    extended_funding: float
    tradexyz_funding: float

    # Trading fees paid
    total_fees: float

    # Net P&L after all components
    net_pnl: float

    @property
    def gross_pnl(self) -> float:
        """Total P&L before fees."""
        return (
            self.extended_realized_pnl
            + self.tradexyz_realized_pnl
            + self.extended_funding
            + self.tradexyz_funding
        )

    @property
    def total_funding(self) -> float:
        """Combined funding from both exchanges."""
        return self.extended_funding + self.tradexyz_funding

    @property
    def total_realized_pnl(self) -> float:
        """Combined realized P&L from both exchanges."""
        return self.extended_realized_pnl + self.tradexyz_realized_pnl


@dataclass
class PositionSnapshot:
    """Snapshot of position state at a point in time."""
    exchange_name: str
    symbol: str
    size: float
    entry_price: float
    unrealized_pnl: float
    realized_pnl: float
    funding_accumulated: float = 0.0

    @classmethod
    def from_position_info(
        cls,
        position: PositionInfo,
        funding_accumulated: float = 0.0,
    ) -> "PositionSnapshot":
        """Create snapshot from PositionInfo."""
        return cls(
            exchange_name=position.exchange.value,
            symbol=position.symbol,
            size=position.size,
            entry_price=position.entry_price,
            unrealized_pnl=position.unrealized_pnl,
            realized_pnl=position.realized_pnl,
            funding_accumulated=funding_accumulated,
        )


class PnLCalculator:
    """
    Calculator for cycle P&L from position snapshots.

    Computes realized P&L, funding earned, and fees for a complete
    delta-neutral trading cycle.
    """

    def __init__(self, fee_rate: float = 0.0005):
        """
        Initialize P&L calculator.

        Args:
            fee_rate: Default fee rate as decimal (e.g., 0.0005 for 0.05%)
        """
        self._fee_rate = fee_rate

    def calculate_from_snapshots(
        self,
        extended_open: Optional[PositionSnapshot],
        extended_close: Optional[PositionSnapshot],
        tradexyz_open: Optional[PositionSnapshot],
        tradexyz_close: Optional[PositionSnapshot],
        open_fees: float = 0.0,
        close_fees: float = 0.0,
    ) -> CyclePnL:
        """
        Calculate cycle P&L from position snapshots.

        Args:
            extended_open: Extended position snapshot at cycle open
            extended_close: Extended position snapshot at cycle close
            tradexyz_open: TradeXYZ position snapshot at cycle open
            tradexyz_close: TradeXYZ position snapshot at cycle close
            open_fees: Fees paid during position opening
            close_fees: Fees paid during position closing

        Returns:
            CyclePnL with complete breakdown
        """
        # Calculate Extended realized P&L
        extended_realized = 0.0
        if extended_close and extended_open:
            extended_realized = (
                extended_close.realized_pnl - extended_open.realized_pnl
            )
        elif extended_close:
            extended_realized = extended_close.realized_pnl

        # Calculate TradeXYZ realized P&L
        tradexyz_realized = 0.0
        if tradexyz_close and tradexyz_open:
            tradexyz_realized = (
                tradexyz_close.realized_pnl - tradexyz_open.realized_pnl
            )
        elif tradexyz_close:
            tradexyz_realized = tradexyz_close.realized_pnl

        # Calculate funding earned/paid
        extended_funding = 0.0
        if extended_close:
            extended_funding = extended_close.funding_accumulated
        if extended_open:
            extended_funding -= extended_open.funding_accumulated

        tradexyz_funding = 0.0
        if tradexyz_close:
            tradexyz_funding = tradexyz_close.funding_accumulated
        if tradexyz_open:
            tradexyz_funding -= tradexyz_open.funding_accumulated

        # Total fees
        total_fees = open_fees + close_fees

        # Net P&L
        net_pnl = (
            extended_realized
            + tradexyz_realized
            + extended_funding
            + tradexyz_funding
            - total_fees
        )

        return CyclePnL(
            extended_realized_pnl=extended_realized,
            tradexyz_realized_pnl=tradexyz_realized,
            extended_funding=extended_funding,
            tradexyz_funding=tradexyz_funding,
            total_fees=total_fees,
            net_pnl=net_pnl,
        )

    def calculate_simple(
        self,
        position_value: float,
        extended_realized_pnl: float = 0.0,
        tradexyz_realized_pnl: float = 0.0,
        extended_funding: float = 0.0,
        tradexyz_funding: float = 0.0,
    ) -> CyclePnL:
        """
        Calculate cycle P&L from direct values.

        Simpler interface when position snapshots aren't available.
        Estimates fees based on position value and fee rate.

        Args:
            position_value: Total position value (used to estimate fees)
            extended_realized_pnl: Realized P&L from Extended
            tradexyz_realized_pnl: Realized P&L from TradeXYZ
            extended_funding: Funding earned on Extended
            tradexyz_funding: Funding earned on TradeXYZ

        Returns:
            CyclePnL with complete breakdown
        """
        # Estimate fees: 2 exchanges x 2 trades (open + close) x fee_rate
        estimated_fees = position_value * self._fee_rate * 4

        net_pnl = (
            extended_realized_pnl
            + tradexyz_realized_pnl
            + extended_funding
            + tradexyz_funding
            - estimated_fees
        )

        return CyclePnL(
            extended_realized_pnl=extended_realized_pnl,
            tradexyz_realized_pnl=tradexyz_realized_pnl,
            extended_funding=extended_funding,
            tradexyz_funding=tradexyz_funding,
            total_fees=estimated_fees,
            net_pnl=net_pnl,
        )
