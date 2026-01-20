"""Atomic position execution with rollback capabilities."""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from config.constants import ExchangeName, PositionSide, OrderType
from exchanges.base import BaseExchange, TradeResult, PositionInfo
from utils.logging import get_logger, trading_logger
from utils.timing import CycleTimer


logger = get_logger(__name__)


class ExecutionState(str, Enum):
    """Atomic execution states."""
    PENDING = "pending"
    OPENING_FIRST = "opening_first"
    OPENING_SECOND = "opening_second"
    COMPLETE = "complete"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass
class LegResult:
    """Result for a single position leg."""
    exchange: ExchangeName
    side: PositionSide
    success: bool
    trade_result: Optional[TradeResult]
    position: Optional[PositionInfo]
    error: Optional[str]


@dataclass
class ExecutionResult:
    """
    Result of atomic position execution.
    
    Contains results for both legs and overall status.
    """
    success: bool
    state: ExecutionState
    
    # Leg results
    extended_leg: Optional[LegResult]
    tradexyz_leg: Optional[LegResult]
    
    # Execution metrics
    execution_time_ms: float
    
    # Error info
    error_message: Optional[str]
    rollback_performed: bool
    rollback_success: bool
    
    # Raw details
    details: Dict[str, Any] = field(default_factory=dict)


class AtomicExecutor:
    """
    Executes delta-neutral position pairs atomically.
    
    Ensures:
    1. Both legs open near-simultaneously
    2. Automatic rollback if one leg fails
    3. No unhedged exposure
    
    Execution Flow:
    1. Validate pre-conditions
    2. Open first leg
    3. Open second leg (as close to simultaneously as possible)
    4. If either fails, rollback successful leg
    5. Verify final state
    """
    
    def __init__(
        self,
        extended_exchange: BaseExchange,
        tradexyz_exchange: BaseExchange,
        max_execution_time: float = 30.0,  # seconds
        parallel_open: bool = True,
    ):
        """
        Initialize atomic executor.
        
        Args:
            extended_exchange: Extended exchange adapter
            tradexyz_exchange: TradeXYZ exchange adapter
            max_execution_time: Maximum allowed execution time
            parallel_open: If True, attempt parallel opening
        """
        self._extended = extended_exchange
        self._tradexyz = tradexyz_exchange
        self._max_time = max_execution_time
        self._parallel = parallel_open
        
        self._current_state = ExecutionState.PENDING
        self._timer = CycleTimer()
    
    async def open_positions(
        self,
        token: str,
        size: float,
        extended_side: PositionSide,
        tradexyz_side: PositionSide,
        leverage: int,
        price: float,
    ) -> ExecutionResult:
        """
        Open delta-neutral position pair atomically.
        
        Args:
            token: Token to trade (e.g., "BTC")
            size: Position size in base asset
            extended_side: Side for Extended position
            tradexyz_side: Side for TradeXYZ position
            leverage: Leverage to use
            price: Current market price (for limit order calculation)
            
        Returns:
            ExecutionResult with outcome details
        """
        self._timer.start()
        self._current_state = ExecutionState.PENDING
        
        trading_logger.debug(
            "Starting atomic position opening",
            token=token,
            size=size,
            extended_side=extended_side.value,
            tradexyz_side=tradexyz_side.value,
        )
        
        extended_result: Optional[LegResult] = None
        tradexyz_result: Optional[LegResult] = None
        
        try:
            # Set leverage on both exchanges
            await asyncio.gather(
                self._extended.set_leverage(token, leverage),
                self._tradexyz.set_leverage(token, leverage),
            )
            
            if self._parallel:
                # Attempt parallel opening for minimal timing difference
                extended_result, tradexyz_result = await self._open_parallel(
                    token, size, extended_side, tradexyz_side, price
                )
            else:
                # Sequential opening with quick rollback
                extended_result, tradexyz_result = await self._open_sequential(
                    token, size, extended_side, tradexyz_side, price
                )
            
            # Check if both succeeded
            if extended_result.success and tradexyz_result.success:
                self._current_state = ExecutionState.COMPLETE

                # Use actual fill prices from trade results, fallback to submitted price
                extended_fill_price = (
                    extended_result.trade_result.average_price
                    if extended_result.trade_result and extended_result.trade_result.average_price > 0
                    else price
                )
                tradexyz_fill_price = (
                    tradexyz_result.trade_result.average_price
                    if tradexyz_result.trade_result and tradexyz_result.trade_result.average_price > 0
                    else price
                )

                trading_logger.position_opened(
                    exchange="Extended",
                    side=extended_side.value,
                    size=size,
                    entry_price=extended_fill_price,
                )
                trading_logger.position_opened(
                    exchange="TradeXYZ",
                    side=tradexyz_side.value,
                    size=size,
                    entry_price=tradexyz_fill_price,
                )
                
                return ExecutionResult(
                    success=True,
                    state=ExecutionState.COMPLETE,
                    extended_leg=extended_result,
                    tradexyz_leg=tradexyz_result,
                    execution_time_ms=self._timer.get_elapsed() * 1000,
                    error_message=None,
                    rollback_performed=False,
                    rollback_success=True,
                )
            
            # One or both failed - need rollback
            return await self._handle_failure(
                extended_result,
                tradexyz_result,
                token,
            )
            
        except asyncio.TimeoutError:
            logger.error("Position opening timed out")
            
            # Attempt emergency rollback
            rollback_result = await self._emergency_rollback(token)
            
            return ExecutionResult(
                success=False,
                state=ExecutionState.FAILED,
                extended_leg=extended_result,
                tradexyz_leg=tradexyz_result,
                execution_time_ms=self._timer.get_elapsed() * 1000,
                error_message="Execution timeout",
                rollback_performed=True,
                rollback_success=rollback_result,
            )
            
        except Exception as e:
            logger.error("Position opening failed", error=str(e))
            
            rollback_result = await self._emergency_rollback(token)
            
            return ExecutionResult(
                success=False,
                state=ExecutionState.FAILED,
                extended_leg=extended_result,
                tradexyz_leg=tradexyz_result,
                execution_time_ms=self._timer.get_elapsed() * 1000,
                error_message=str(e),
                rollback_performed=True,
                rollback_success=rollback_result,
            )
    
    async def close_positions(
        self,
        token: str,
        extended_size: Optional[float] = None,
        tradexyz_size: Optional[float] = None,
    ) -> ExecutionResult:
        """
        Close delta-neutral position pair atomically.
        
        Args:
            token: Token to close
            extended_size: Size to close on Extended (None = full)
            tradexyz_size: Size to close on TradeXYZ (None = full)
            
        Returns:
            ExecutionResult with outcome details
        """
        self._timer.start()
        
        trading_logger.debug(
            "Starting atomic position closing",
            token=token,
        )
        
        try:
            # Close both positions simultaneously
            extended_task = self._extended.close_position(token, extended_size)
            tradexyz_task = self._tradexyz.close_position(token, tradexyz_size)
            
            ext_result, xyz_result = await asyncio.gather(
                extended_task, tradexyz_task, return_exceptions=True
            )
            
            # Process results
            ext_success = isinstance(ext_result, TradeResult) and ext_result.success
            xyz_success = isinstance(xyz_result, TradeResult) and xyz_result.success
            
            extended_leg = LegResult(
                exchange=ExchangeName.EXTENDED,
                side=PositionSide.LONG,  # Direction depends on original position
                success=ext_success,
                trade_result=ext_result if isinstance(ext_result, TradeResult) else None,
                position=None,
                error=str(ext_result) if isinstance(ext_result, Exception) else None,
            )
            
            tradexyz_leg = LegResult(
                exchange=ExchangeName.TRADEXYZ,
                side=PositionSide.SHORT,
                success=xyz_success,
                trade_result=xyz_result if isinstance(xyz_result, TradeResult) else None,
                position=None,
                error=str(xyz_result) if isinstance(xyz_result, Exception) else None,
            )
            
            both_success = ext_success and xyz_success
            
            if both_success:
                trading_logger.debug("Both positions closed successfully")
            elif ext_success:
                trading_logger.warning("Extended closed but TradeXYZ failed", error=tradexyz_leg.error)
            elif xyz_success:
                trading_logger.warning("TradeXYZ closed but Extended failed", error=extended_leg.error)
            else:
                trading_logger.error("Both position closes failed")
            
            return ExecutionResult(
                success=both_success,
                state=ExecutionState.COMPLETE if both_success else ExecutionState.FAILED,
                extended_leg=extended_leg,
                tradexyz_leg=tradexyz_leg,
                execution_time_ms=self._timer.get_elapsed() * 1000,
                error_message=None if both_success else "One or both closes failed",
                rollback_performed=False,
                rollback_success=True,
            )
            
        except Exception as e:
            logger.error("Position closing failed", error=str(e))
            
            return ExecutionResult(
                success=False,
                state=ExecutionState.FAILED,
                extended_leg=None,
                tradexyz_leg=None,
                execution_time_ms=self._timer.get_elapsed() * 1000,
                error_message=str(e),
                rollback_performed=False,
                rollback_success=False,
            )
    
    async def _open_parallel(
        self,
        token: str,
        size: float,
        extended_side: PositionSide,
        tradexyz_side: PositionSide,
        price: float,
    ) -> Tuple[LegResult, LegResult]:
        """Open both legs in parallel."""
        self._current_state = ExecutionState.OPENING_FIRST
        
        # Create tasks for parallel execution
        extended_task = self._extended.place_order(
            symbol=token,
            side=extended_side,
            quantity=size,
            order_type=OrderType.MARKET,
            price=price,
        )
        
        tradexyz_task = self._tradexyz.place_order(
            symbol=token,
            side=tradexyz_side,
            quantity=size,
            order_type=OrderType.MARKET,
            price=price,
        )
        
        # Execute with timeout
        results = await asyncio.wait_for(
            asyncio.gather(extended_task, tradexyz_task, return_exceptions=True),
            timeout=self._max_time,
        )
        
        ext_result, xyz_result = results
        
        # Build leg results
        extended_leg = self._build_leg_result(
            ExchangeName.EXTENDED,
            extended_side,
            ext_result,
        )
        
        tradexyz_leg = self._build_leg_result(
            ExchangeName.TRADEXYZ,
            tradexyz_side,
            xyz_result,
        )
        
        return extended_leg, tradexyz_leg
    
    async def _open_sequential(
        self,
        token: str,
        size: float,
        extended_side: PositionSide,
        tradexyz_side: PositionSide,
        price: float,
    ) -> Tuple[LegResult, LegResult]:
        """Open legs sequentially with immediate rollback on failure."""
        # Open Extended first
        self._current_state = ExecutionState.OPENING_FIRST
        
        ext_result = await self._extended.place_order(
            symbol=token,
            side=extended_side,
            quantity=size,
            order_type=OrderType.MARKET,
            price=price,
        )
        
        extended_leg = self._build_leg_result(
            ExchangeName.EXTENDED,
            extended_side,
            ext_result,
        )
        
        if not extended_leg.success:
            # First leg failed, nothing to rollback
            return extended_leg, LegResult(
                exchange=ExchangeName.TRADEXYZ,
                side=tradexyz_side,
                success=False,
                trade_result=None,
                position=None,
                error="Not attempted - first leg failed",
            )
        
        # Open TradeXYZ
        self._current_state = ExecutionState.OPENING_SECOND
        
        xyz_result = await self._tradexyz.place_order(
            symbol=token,
            side=tradexyz_side,
            quantity=size,
            order_type=OrderType.MARKET,
            price=price,
        )
        
        tradexyz_leg = self._build_leg_result(
            ExchangeName.TRADEXYZ,
            tradexyz_side,
            xyz_result,
        )
        
        return extended_leg, tradexyz_leg
    
    async def _handle_failure(
        self,
        extended_leg: LegResult,
        tradexyz_leg: LegResult,
        token: str,
    ) -> ExecutionResult:
        """Handle partial failure with rollback."""
        self._current_state = ExecutionState.ROLLING_BACK
        
        rollback_success = True
        
        # Rollback successful leg
        if extended_leg.success and not tradexyz_leg.success:
            logger.warning("Rolling back Extended position")
            try:
                await self._extended.close_position(token)
            except Exception as e:
                logger.error("Extended rollback failed", error=str(e))
                rollback_success = False
                
        elif tradexyz_leg.success and not extended_leg.success:
            logger.warning("Rolling back TradeXYZ position")
            try:
                await self._tradexyz.close_position(token)
            except Exception as e:
                logger.error("TradeXYZ rollback failed", error=str(e))
                rollback_success = False
        
        final_state = ExecutionState.ROLLED_BACK if rollback_success else ExecutionState.FAILED
        self._current_state = final_state
        
        # Construct error message
        errors = []
        if not extended_leg.success:
            errors.append(f"Extended: {extended_leg.error}")
        if not tradexyz_leg.success:
            errors.append(f"TradeXYZ: {tradexyz_leg.error}")
        
        return ExecutionResult(
            success=False,
            state=final_state,
            extended_leg=extended_leg,
            tradexyz_leg=tradexyz_leg,
            execution_time_ms=self._timer.get_elapsed() * 1000,
            error_message="; ".join(errors),
            rollback_performed=True,
            rollback_success=rollback_success,
        )
    
    async def _emergency_rollback(self, token: str) -> bool:
        """Perform emergency rollback of any open positions."""
        logger.warning("Performing emergency rollback", token=token)
        
        success = True
        
        # Cancel any pending orders
        try:
            await self._extended.cancel_all_orders(token)
        except Exception as e:
            logger.error("Failed to cancel Extended orders", error=str(e))
            success = False
        
        try:
            await self._tradexyz.cancel_all_orders(token)
        except Exception as e:
            logger.error("Failed to cancel TradeXYZ orders", error=str(e))
            success = False
        
        # Close any open positions
        try:
            await self._extended.close_position(token)
        except Exception as e:
            logger.error("Failed to close Extended position", error=str(e))
            success = False
        
        try:
            await self._tradexyz.close_position(token)
        except Exception as e:
            logger.error("Failed to close TradeXYZ position", error=str(e))
            success = False
        
        return success
    
    def _build_leg_result(
        self,
        exchange: ExchangeName,
        side: PositionSide,
        result: Any,
    ) -> LegResult:
        """Build LegResult from trade result or exception."""
        if isinstance(result, Exception):
            return LegResult(
                exchange=exchange,
                side=side,
                success=False,
                trade_result=None,
                position=None,
                error=str(result),
            )
        
        if isinstance(result, TradeResult):
            return LegResult(
                exchange=exchange,
                side=side,
                success=result.success,
                trade_result=result,
                position=None,
                error=result.error_message,
            )
        
        return LegResult(
            exchange=exchange,
            side=side,
            success=False,
            trade_result=None,
            position=None,
            error="Unknown result type",
        )
