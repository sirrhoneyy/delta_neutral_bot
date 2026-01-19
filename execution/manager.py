"""Trade lifecycle management for delta-neutral strategy."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from config.constants import (
    ExchangeName,
    PositionSide,
    CycleState,
    SUPPORTED_TOKENS,
    InternalParams,
)
from config.settings import Settings
from exchanges.base import BaseExchange
from core.randomizer import CryptoRandomizer, RandomParams
from core.funding import FundingAnalyzer, FundingAnalysisResult
from core.sizing import PositionSizer, SizingResult, BalanceInfo
from core.risk import RiskValidator, RiskAssessment
# PnLCalculator available in core.pnl for live trading P&L calculation
from utils.logging import get_logger, trading_logger
from utils.timing import async_sleep_random, CycleTimer

from .atomic import AtomicExecutor, ExecutionResult
from .safety import SafetyMonitor, EmergencyReason
from .result_builder import CycleResultBuilder


logger = get_logger(__name__)


@dataclass
class CycleResult:
    """
    Result of a complete trading cycle.
    """
    cycle_id: str
    success: bool
    state: CycleState
    
    # Cycle parameters
    token: str
    equity_usage: float
    leverage: int
    hold_duration: int
    
    # Positions
    extended_side: Optional[PositionSide]
    tradexyz_side: Optional[PositionSide]
    position_size: float
    position_value: float
    
    # Funding
    funding_analysis: Optional[FundingAnalysisResult]
    funding_earned: float
    
    # Timing
    start_time: datetime
    end_time: Optional[datetime]
    total_duration_seconds: float
    
    # Execution
    open_result: Optional[ExecutionResult]
    close_result: Optional[ExecutionResult]
    
    # Errors
    error_message: Optional[str]
    
    # Details
    details: Dict[str, Any] = field(default_factory=dict)


class TradeManager:
    """
    Manages the complete trading cycle lifecycle.
    
    Cycle Flow:
    1. Generate random parameters
    2. Fetch funding rates
    3. Assign exchange sides with funding bias
    4. Calculate position size
    5. Validate risk parameters
    6. Execute atomic position opening
    7. Hold for random duration
    8. Execute atomic position closing
    9. Wait for cooldown
    10. Repeat
    
    Coordinates all components:
    - CryptoRandomizer for non-predictable behavior
    - FundingAnalyzer for optimization
    - PositionSizer for capital management
    - RiskValidator for safety checks
    - AtomicExecutor for position management
    - SafetyMonitor for emergency handling
    """
    
    def __init__(
        self,
        extended_exchange: BaseExchange,
        tradexyz_exchange: BaseExchange,
        settings: Settings,
    ):
        """
        Initialize trade manager.
        
        Args:
            extended_exchange: Extended exchange adapter
            tradexyz_exchange: TradeXYZ exchange adapter
            settings: Application settings
        """
        self._extended = extended_exchange
        self._tradexyz = tradexyz_exchange
        self._settings = settings
        
        # Components
        self._randomizer = CryptoRandomizer(
            min_equity=settings.risk.min_equity_usage,
            max_equity=settings.risk.max_equity_usage,
            min_leverage=settings.risk.min_leverage,
            max_leverage=settings.risk.max_leverage,
            min_hold=settings.risk.min_hold_duration,
            max_hold=settings.risk.max_hold_duration,
            min_cooldown=settings.risk.min_cooldown,
            max_cooldown=settings.risk.max_cooldown,
        )
        
        self._funding_analyzer = FundingAnalyzer()
        
        self._sizer = PositionSizer(
            max_position_usd=settings.risk.max_position_value_usd,
            min_position_usd=settings.risk.min_balance_usd,
        )
        
        self._risk_validator = RiskValidator(
            max_position_value=settings.risk.max_position_value_usd,
            min_balance_required=settings.risk.min_balance_usd,
            max_slippage_percent=settings.risk.max_slippage_percent,
        )
        
        self._executor = AtomicExecutor(
            extended_exchange=extended_exchange,
            tradexyz_exchange=tradexyz_exchange,
            max_execution_time=settings.order_timeout,
        )
        
        self._safety = SafetyMonitor(
            extended_exchange=extended_exchange,
            tradexyz_exchange=tradexyz_exchange,
            max_consecutive_failures=settings.risk.max_consecutive_failures,
        )

        # State
        self._current_state = CycleState.IDLE
        self._running = False
        self._current_cycle_id: Optional[str] = None
        self._cycle_timer = CycleTimer()
    
    @property
    def is_running(self) -> bool:
        """Check if manager is running."""
        return self._running
    
    @property
    def current_state(self) -> CycleState:
        """Get current cycle state."""
        return self._current_state
    
    async def start(self) -> None:
        """Start the trade manager."""
        logger.info("Starting trade manager")

        if not self._settings.simulation_mode:
            logger.warning("LIVE MODE ENABLED")

            # Phase-based protection
            if self._settings.risk.max_leverage > 10:
                raise RuntimeError(
                    "Live leverage too high. Start with <=3x and scale gradually."
                )

            if self._settings.risk.max_equity_usage > 0.50:
                raise RuntimeError(
                    "Live equity usage too high. Start with <=10%."
                )        

            logger.warning(
                "LIVE CONFIG",
                leverage_range=f"{self._settings.risk.min_leverage}-{self._settings.risk.max_leverage}",
                equity_range=f"{self._settings.risk.min_equity_usage:.0%}-{self._settings.risk.max_equity_usage:.0%}",
            )

        # Connect to exchanges
        ext_connected = await self._extended.connect()
        xyz_connected = await self._tradexyz.connect()
        
        if not ext_connected or not xyz_connected:
            raise RuntimeError("Failed to connect to one or more exchanges")
        
        # Start safety monitor
        self._safety.start()
        
        self._running = True
        logger.info("Trade manager started")
    
    async def stop(self) -> None:
        """Stop the trade manager gracefully."""
        logger.info("Stopping trade manager")
        
        self._running = False
        
        # Stop safety monitor
        self._safety.stop()
        
        # Disconnect from exchanges
        await self._extended.disconnect()
        await self._tradexyz.disconnect()
        
        logger.info("Trade manager stopped")
    
    async def run_cycle(self) -> CycleResult:
        """
        Execute a complete trading cycle.
        
        Returns:
            CycleResult with cycle outcome
        """
        cycle_id = str(uuid.uuid4())[:8]
        self._current_cycle_id = cycle_id
        self._cycle_timer.start()
        
        start_time = datetime.now(timezone.utc)
        
        trading_logger.cycle_start(
            cycle_id=cycle_id,
            token="TBD",
        )
        
        try:
            # Phase 1: Generate random parameters
            self._current_state = CycleState.IDLE
            params = self._randomizer.generate_cycle_params(SUPPORTED_TOKENS)
            
            trading_logger.debug(
                "Cycle parameters generated",
                cycle_id=cycle_id,
                token=params.token,
                equity_usage=f"{params.equity_usage:.1%}",
                leverage=f"{params.leverage}x",
                hold_duration=f"{params.hold_duration_seconds}s",
            )
            
            # Phase 2: Fetch current data
            ext_balance = await self._extended.get_balance()
            xyz_balance = await self._tradexyz.get_balance()

            logger.info(
                "Account balances",
                extended_available=f"${ext_balance.available_for_trade:.2f}",
                extended_equity=f"${ext_balance.equity:.2f}",
                tradexyz_available=f"${xyz_balance.available_for_trade:.2f}",
                tradexyz_equity=f"${xyz_balance.equity:.2f}",
            )
            
            ext_market = await self._extended.get_market_info(params.token)
            xyz_market = await self._tradexyz.get_market_info(params.token)
            
            # Phase 3: Analyze funding rates
            funding_analysis = self._funding_analyzer.analyze(
                extended_rate=ext_market.funding_rate,
                tradexyz_rate=xyz_market.funding_rate,
                token=params.token,
                extended_next_funding=ext_market.next_funding_time,
                tradexyz_next_funding=xyz_market.next_funding_time,
            )
            
            trading_logger.funding_rates(
                token=params.token,
                extended_rate=ext_market.funding_rate,
                tradexyz_rate=xyz_market.funding_rate,
                bias_result=funding_analysis.bias_strength.value,
            )
            
            # Phase 4: Assign sides with funding bias
            (ext_assignment, xyz_assignment) = self._randomizer.assign_exchange_sides_with_bias(
                extended_funding=ext_market.funding_rate,
                tradexyz_funding=xyz_market.funding_rate,
            )
            
            extended_side = ext_assignment[1]
            tradexyz_side = xyz_assignment[1]
            
            trading_logger.position_assignment(
                extended_side=extended_side.value,
                tradexyz_side=tradexyz_side.value,
                funding_favored=(
                    funding_analysis.recommended_short_exchange == ExchangeName.EXTENDED
                    and extended_side == PositionSide.SHORT
                ),
            )
            
            # Phase 5: Calculate position size
            ext_balance_info = BalanceInfo(
                available=ext_balance.available_for_trade,
                equity=ext_balance.equity,
                margin_used=ext_balance.initial_margin,
            )
            
            xyz_balance_info = BalanceInfo(
                available=xyz_balance.available_for_trade,
                equity=xyz_balance.equity,
                margin_used=xyz_balance.initial_margin,
            )
            
            # 🔹 SIMULATION balance injection
            if self._settings.simulation_mode:
                sim_balance = self._settings.simulation_balance_usd
                ext_balance_info.available = sim_balance
                ext_balance_info.equity = sim_balance
                ext_balance_info.margin_used = 0

                xyz_balance_info.available = sim_balance
                xyz_balance_info.equity = sim_balance
                xyz_balance_info.margin_used = 0

            sizing = self._sizer.calculate_size(
                token=params.token,
                token_price=ext_market.mark_price,
                extended_balance=ext_balance_info,
                tradexyz_balance=xyz_balance_info,
                equity_usage=params.equity_usage,
                leverage=params.leverage,
                min_order_size=ext_market.min_order_size,
            )

            if not sizing.fits_constraints:
                trading_logger.warning(
                    "Sizing rejected — skipping cycle",
                    cycle_id=cycle_id,
                    token=params.token,
                    notes=sizing.constraint_notes,
                )

                self._safety.record_failure()

                return (
                    CycleResultBuilder(cycle_id, start_time)
                    .with_params(params.token, params.equity_usage, params.leverage, params.hold_duration_seconds)
                    .with_positions(extended_side, tradexyz_side, 0, 0)
                    .with_funding(funding_analysis)
                    .with_error("Sizing rejected: " + "; ".join(sizing.constraint_notes))
                    .build(self._cycle_timer)
                )

            
            trading_logger.sizing_decision(
                equity_usage=params.equity_usage,
                leverage=params.leverage,
                position_size=sizing.position_size,
                position_value_usd=sizing.position_value_usd,
            )
            
            # Phase 6: Validate risk
            risk_assessment = self._risk_validator.validate_pre_trade(
                sizing=sizing,
                extended_balance=ext_balance_info,
                tradexyz_balance=xyz_balance_info,
                current_price=ext_market.mark_price,
            )
            
            if not risk_assessment.can_proceed:
                error_msg = "; ".join(risk_assessment.blocking_issues)
                trading_logger.warning(
                    "Risk validation failed",
                    cycle_id=cycle_id,
                    issues=error_msg,
                )

                self._safety.record_failure()

                return (
                    CycleResultBuilder(cycle_id, start_time)
                    .with_params(params.token, params.equity_usage, params.leverage, params.hold_duration_seconds)
                    .with_positions(extended_side, tradexyz_side, 0, 0)
                    .with_funding(funding_analysis)
                    .with_error(error_msg)
                    .build(self._cycle_timer)
                )
            
            # Phase 7: Open positions
            self._current_state = CycleState.OPENING
            self._safety.add_monitored_token(params.token)
            
            open_result = await self._executor.open_positions(
                token=params.token,
                size=sizing.position_size,
                extended_side=extended_side,
                tradexyz_side=tradexyz_side,
                leverage=params.leverage,
                price=ext_market.mark_price,
            )
            
            if not open_result.success:
                self._safety.record_failure()
                self._safety.remove_monitored_token(params.token)

                return (
                    CycleResultBuilder(cycle_id, start_time)
                    .with_params(params.token, params.equity_usage, params.leverage, params.hold_duration_seconds)
                    .with_positions(extended_side, tradexyz_side, 0, 0)
                    .with_funding(funding_analysis)
                    .with_execution(open_result)
                    .with_error(open_result.error_message or "Open failed")
                    .build(self._cycle_timer)
                )
            
            # Phase 8: Hold positions
            self._current_state = CycleState.HOLDING
            
            trading_logger.debug(
                "Holding positions",
                cycle_id=cycle_id,
                duration=params.hold_duration_seconds,
            )
            
            # Hold with periodic safety checks
            hold_duration = await self._hold_with_safety_checks(
                params.hold_duration_seconds
            )
            
            # Check if emergency was triggered
            if self._safety.emergency_triggered:
                return (
                    CycleResultBuilder(cycle_id, start_time)
                    .with_params(params.token, params.equity_usage, params.leverage, int(hold_duration))
                    .with_positions(extended_side, tradexyz_side, sizing.position_size, sizing.position_value_usd)
                    .with_funding(funding_analysis)
                    .with_execution(open_result)
                    .with_error("Emergency triggered during hold", CycleState.EMERGENCY)
                    .build(self._cycle_timer)
                )
            
            # Phase 9: Close positions
            self._current_state = CycleState.CLOSING

            close_result = await self._executor.close_positions(
                token=params.token,
            )

            self._safety.remove_monitored_token(params.token)

            if not close_result.success:
                self._safety.record_failure()

                return (
                    CycleResultBuilder(cycle_id, start_time)
                    .with_params(params.token, params.equity_usage, params.leverage, int(hold_duration))
                    .with_positions(extended_side, tradexyz_side, sizing.position_size, sizing.position_value_usd)
                    .with_funding(funding_analysis)
                    .with_execution(open_result, close_result)
                    .with_error(close_result.error_message or "Close failed")
                    .build(self._cycle_timer)
                )

            # Phase 10: Calculate funding earned
            # Note: In simulation mode, this is estimated from funding rates.
            # In live mode, actual funding would be fetched from exchange history.
            funding_earned = self._calculate_estimated_funding(
                funding_analysis=funding_analysis,
                position_value=sizing.position_value_usd,
                hold_duration_seconds=hold_duration,
            )
            
            end_time = datetime.now(timezone.utc)
            total_duration = self._cycle_timer.get_elapsed()
            
            # Record success
            self._safety.record_success()
            self._current_state = CycleState.COOLDOWN
            
            trading_logger.cycle_end(
                cycle_id=cycle_id,
                duration_seconds=total_duration,
                pnl=funding_earned,
            )

            return (
                CycleResultBuilder(cycle_id, start_time)
                .with_params(params.token, params.equity_usage, params.leverage, int(hold_duration))
                .with_positions(extended_side, tradexyz_side, sizing.position_size, sizing.position_value_usd)
                .with_funding(funding_analysis, funding_earned)
                .with_execution(open_result, close_result)
                .with_success(CycleState.COOLDOWN, funding_earned)
                .build(self._cycle_timer)
            )
            
        except Exception as e:
            logger.error("Cycle failed with exception", error=str(e))

            self._safety.record_failure()

            return (
                CycleResultBuilder(cycle_id, start_time)
                .with_error(str(e))
                .build(self._cycle_timer)
            )
    
    async def run_continuous(self) -> None:
        """
        Run continuous trading cycles.
        
        Executes cycles until stopped or emergency triggered.
        """
        while self._running and not self._safety.shutdown_requested:
            if self._safety.emergency_triggered:
                logger.warning("Emergency triggered - stopping continuous operation")
                break
            
            # Run a cycle
            result = await self.run_cycle()
            
            if not result.success:
                logger.warning(
                    "Cycle failed",
                    cycle_id=result.cycle_id,
                    error=result.error_message,
                )
            
            # Wait for cooldown
            if self._running and not self._safety.emergency_triggered:
                self._current_state = CycleState.COOLDOWN
                
                cooldown = self._randomizer.generate_cooldown()
                
                trading_logger.debug(
                    "Entering cooldown",
                    duration=cooldown,
                )
                
                await async_sleep_random(cooldown, cooldown + 60)
        
        logger.info("Continuous operation ended")
    
    async def _hold_with_safety_checks(
        self,
        total_duration: int,
    ) -> float:
        """
        Hold positions with periodic safety checks.

        Args:
            total_duration: Total hold duration in seconds

        Returns:
            Actual hold duration
        """
        check_interval = InternalParams.SAFETY_CHECK_INTERVAL_SECONDS
        elapsed = 0.0

        while elapsed < total_duration:
            # Check for shutdown/emergency
            if self._safety.shutdown_requested or self._safety.emergency_triggered:
                break

            # Sleep for interval or remaining time
            sleep_time = min(check_interval, total_duration - elapsed)
            await asyncio.sleep(sleep_time)
            elapsed += sleep_time

        return elapsed

    def _calculate_estimated_funding(
        self,
        funding_analysis: Optional[FundingAnalysisResult],
        position_value: float,
        hold_duration_seconds: float,
    ) -> float:
        """
        Estimate funding earned during a cycle.

        This is an approximation based on current funding rates.
        Actual funding depends on funding intervals and rate changes.

        Args:
            funding_analysis: Funding rate analysis from cycle start
            position_value: Position notional value in USD
            hold_duration_seconds: How long position was held

        Returns:
            Estimated funding earned in USD (positive = earned, negative = paid)
        """
        if funding_analysis is None:
            return 0.0

        # Funding is typically paid every 8 hours
        # Pro-rate based on actual hold duration
        funding_interval = float(InternalParams.FUNDING_INTERVAL_SECONDS)
        funding_periods = hold_duration_seconds / funding_interval

        # Net funding rate (favorable short rate - unfavorable long rate)
        # Delta-neutral strategy should be net positive if properly aligned
        net_rate = funding_analysis.rate_difference

        # Estimated funding = position_value * net_rate * periods
        # Note: This assumes rates stay constant (approximation)
        estimated_funding = position_value * net_rate * funding_periods

        return estimated_funding
