"""Builder pattern for CycleResult to reduce construction duplication."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from config.constants import CycleState, PositionSide
from core.funding import FundingAnalysisResult
from utils.timing import CycleTimer

from .atomic import ExecutionResult


class CycleResultBuilder:
    """
    Builder for constructing CycleResult objects.

    Reduces code duplication by accumulating cycle data incrementally
    and providing a single build() method that produces the final result.

    Usage:
        result = (
            CycleResultBuilder(cycle_id, start_time)
            .with_params(token, equity_usage, leverage, hold_duration)
            .with_positions(extended_side, tradexyz_side, size, value)
            .with_funding(analysis)
            .with_error("Something failed", CycleState.ERROR)
            .build(timer)
        )
    """

    def __init__(self, cycle_id: str, start_time: datetime):
        """
        Initialize builder with required cycle identifiers.

        Args:
            cycle_id: Unique cycle identifier
            start_time: When the cycle started
        """
        self._cycle_id = cycle_id
        self._start_time = start_time

        # Parameters (set via with_params)
        self._token: str = "UNKNOWN"
        self._equity_usage: float = 0.0
        self._leverage: int = 0
        self._hold_duration: int = 0

        # Positions (set via with_positions)
        self._extended_side: Optional[PositionSide] = None
        self._tradexyz_side: Optional[PositionSide] = None
        self._position_size: float = 0.0
        self._position_value: float = 0.0

        # Funding (set via with_funding)
        self._funding_analysis: Optional[FundingAnalysisResult] = None
        self._funding_earned: float = 0.0

        # Execution (set via with_execution)
        self._open_result: Optional[ExecutionResult] = None
        self._close_result: Optional[ExecutionResult] = None

        # State (set via with_error or build)
        self._success: bool = True
        self._state: CycleState = CycleState.IDLE
        self._error_message: Optional[str] = None

    def with_params(
        self,
        token: str,
        equity_usage: float,
        leverage: int,
        hold_duration: int,
    ) -> CycleResultBuilder:
        """
        Set cycle parameters.

        Args:
            token: Trading token symbol
            equity_usage: Fraction of equity used
            leverage: Leverage multiplier
            hold_duration: Hold duration in seconds
        """
        self._token = token
        self._equity_usage = equity_usage
        self._leverage = leverage
        self._hold_duration = hold_duration
        return self

    def with_positions(
        self,
        extended_side: Optional[PositionSide],
        tradexyz_side: Optional[PositionSide],
        size: float,
        value: float,
    ) -> CycleResultBuilder:
        """
        Set position information.

        Args:
            extended_side: Position side on Extended
            tradexyz_side: Position side on TradeXYZ
            size: Position size in base asset
            value: Position value in USD
        """
        self._extended_side = extended_side
        self._tradexyz_side = tradexyz_side
        self._position_size = size
        self._position_value = value
        return self

    def with_funding(
        self,
        analysis: Optional[FundingAnalysisResult],
        earned: float = 0.0,
    ) -> CycleResultBuilder:
        """
        Set funding information.

        Args:
            analysis: Funding analysis result
            earned: Actual/estimated funding earned
        """
        self._funding_analysis = analysis
        self._funding_earned = earned
        return self

    def with_execution(
        self,
        open_result: Optional[ExecutionResult],
        close_result: Optional[ExecutionResult] = None,
    ) -> CycleResultBuilder:
        """
        Set execution results.

        Args:
            open_result: Result of opening positions
            close_result: Result of closing positions
        """
        self._open_result = open_result
        self._close_result = close_result
        return self

    def with_error(
        self,
        message: str,
        state: CycleState = CycleState.ERROR,
    ) -> CycleResultBuilder:
        """
        Mark cycle as failed with error.

        Args:
            message: Error message
            state: Final cycle state (ERROR, EMERGENCY, etc.)
        """
        self._success = False
        self._state = state
        self._error_message = message
        return self

    def with_success(
        self,
        state: CycleState = CycleState.COOLDOWN,
        funding_earned: float = 0.0,
    ) -> CycleResultBuilder:
        """
        Mark cycle as successful.

        Args:
            state: Final cycle state (typically COOLDOWN)
            funding_earned: Funding earned during cycle
        """
        self._success = True
        self._state = state
        self._funding_earned = funding_earned
        return self

    def build(self, timer: CycleTimer) -> "CycleResult":
        """
        Build the final CycleResult.

        Args:
            timer: Cycle timer for duration calculation

        Returns:
            Fully constructed CycleResult
        """
        # Import here to avoid circular dependency
        from .manager import CycleResult

        return CycleResult(
            cycle_id=self._cycle_id,
            success=self._success,
            state=self._state,
            token=self._token,
            equity_usage=self._equity_usage,
            leverage=self._leverage,
            hold_duration=self._hold_duration,
            extended_side=self._extended_side,
            tradexyz_side=self._tradexyz_side,
            position_size=self._position_size,
            position_value=self._position_value,
            funding_analysis=self._funding_analysis,
            funding_earned=self._funding_earned,
            start_time=self._start_time,
            end_time=datetime.now(timezone.utc),
            total_duration_seconds=timer.get_elapsed(),
            open_result=self._open_result,
            close_result=self._close_result,
            error_message=self._error_message,
        )
