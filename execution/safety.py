"""Safety monitoring and emergency procedures."""

import asyncio
import signal
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional, Set

from config.constants import ExchangeName, CycleState, InternalParams
from exchanges.base import BaseExchange, PositionInfo
from utils.logging import get_logger, trading_logger


logger = get_logger(__name__)


class EmergencyReason(str, Enum):
    """Reasons for triggering emergency procedures."""
    USER_INTERRUPT = "user_interrupt"
    CONSECUTIVE_FAILURES = "consecutive_failures"
    UNHEDGED_EXPOSURE = "unhedged_exposure"
    MARGIN_CALL = "margin_call"
    CONNECTION_LOST = "connection_lost"
    SYSTEM_ERROR = "system_error"
    MANUAL_TRIGGER = "manual_trigger"


@dataclass
class EmergencyAction:
    """
    Record of an emergency action taken.
    """
    reason: EmergencyReason
    timestamp: int
    positions_closed: List[str]
    orders_cancelled: int
    success: bool
    details: str


class SafetyMonitor:
    """
    Monitors trading safety and executes emergency procedures.
    
    Responsibilities:
    1. Track consecutive failures
    2. Monitor for unhedged exposure
    3. Handle system signals (Ctrl+C)
    4. Execute emergency shutdowns
    5. Verify position reconciliation
    
    Emergency Procedures:
    1. Cancel all pending orders
    2. Close all positions
    3. Log emergency details
    4. Notify (if configured)
    """
    
    def __init__(
        self,
        extended_exchange: BaseExchange,
        tradexyz_exchange: BaseExchange,
        max_consecutive_failures: int = 3,
        check_interval: float = 5.0,
    ):
        """
        Initialize safety monitor.
        
        Args:
            extended_exchange: Extended exchange adapter
            tradexyz_exchange: TradeXYZ exchange adapter
            max_consecutive_failures: Failures before emergency
            check_interval: Seconds between safety checks
        """
        self._extended = extended_exchange
        self._tradexyz = tradexyz_exchange
        self._max_failures = max_consecutive_failures
        self._check_interval = check_interval
        
        # State tracking
        self._consecutive_failures = 0
        self._emergency_triggered = False
        self._shutdown_requested = False
        self._monitored_tokens: Set[str] = set()
        
        # Callbacks
        self._on_emergency: Optional[Callable[[EmergencyAction], None]] = None
        
        # Signal handling
        self._original_sigint = None
        self._original_sigterm = None
    
    def start(self) -> None:
        """Start safety monitoring."""
        # Install signal handlers
        self._original_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        self._original_sigterm = signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("Safety monitor started")
    
    def stop(self) -> None:
        """Stop safety monitoring."""
        # Restore original signal handlers
        if self._original_sigint:
            signal.signal(signal.SIGINT, self._original_sigint)
        if self._original_sigterm:
            signal.signal(signal.SIGTERM, self._original_sigterm)
        
        logger.info("Safety monitor stopped")
    
    def _signal_handler(self, signum: int, frame) -> None:
        """Handle system signals."""
        sig_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        logger.warning(f"Received {sig_name} - initiating graceful shutdown")
        
        self._shutdown_requested = True
        
        # If already in emergency, force exit
        if self._emergency_triggered:
            logger.warning("Emergency already in progress - forcing exit")
            raise SystemExit(1)
    
    @property
    def shutdown_requested(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_requested
    
    @property
    def emergency_triggered(self) -> bool:
        """Check if emergency has been triggered."""
        return self._emergency_triggered
    
    def set_emergency_callback(
        self,
        callback: Callable[[EmergencyAction], None]
    ) -> None:
        """Set callback for emergency events."""
        self._on_emergency = callback
    
    def record_failure(self) -> bool:
        """
        Record a cycle failure.
        
        Returns:
            True if max failures reached (emergency triggered)
        """
        self._consecutive_failures += 1
        
        logger.warning(
            "Cycle failure recorded",
            count=self._consecutive_failures,
            max=self._max_failures,
        )
        
        if self._consecutive_failures >= self._max_failures:
            logger.error("Maximum consecutive failures reached")
            return True
        
        return False
    
    def record_success(self) -> None:
        """Record a cycle success (resets failure counter)."""
        self._consecutive_failures = 0
    
    def add_monitored_token(self, token: str) -> None:
        """Add token to monitoring list."""
        self._monitored_tokens.add(token)
    
    def remove_monitored_token(self, token: str) -> None:
        """Remove token from monitoring list."""
        self._monitored_tokens.discard(token)
    
    async def check_exposure(self) -> bool:
        """
        Check for unhedged exposure across exchanges.
        
        Returns:
            True if exposure is balanced (safe)
        """
        try:
            # Get all positions from both exchanges
            ext_positions = await self._extended.get_positions()
            xyz_positions = await self._tradexyz.get_positions()
            
            # Build position maps
            ext_map = {p.symbol.split("-")[0]: p for p in ext_positions}
            xyz_map = {p.symbol: p for p in xyz_positions}
            
            # Check each monitored token
            for token in self._monitored_tokens:
                ext_pos = ext_map.get(token)
                xyz_pos = xyz_map.get(token)
                
                # Both should have positions or neither
                if bool(ext_pos) != bool(xyz_pos):
                    logger.error(
                        "Unhedged exposure detected",
                        token=token,
                        extended=bool(ext_pos),
                        tradexyz=bool(xyz_pos),
                    )
                    return False
                
                if ext_pos and xyz_pos:
                    # Should be opposite sides
                    if ext_pos.side == xyz_pos.side:
                        logger.error(
                            "Same-side exposure detected",
                            token=token,
                            side=ext_pos.side.value,
                        )
                        return False
                    
                    # Sizes should be approximately equal
                    size_diff = abs(ext_pos.size - xyz_pos.size)
                    max_size = max(ext_pos.size, xyz_pos.size)

                    if max_size > 0 and size_diff / max_size > InternalParams.SIZE_IMBALANCE_TOLERANCE:
                        logger.warning(
                            "Size imbalance detected",
                            token=token,
                            extended_size=ext_pos.size,
                            tradexyz_size=xyz_pos.size,
                        )
                        # Warning but not critical
            
            return True
            
        except Exception as e:
            logger.error("Exposure check failed", error=str(e))
            return False
    
    async def execute_emergency(
        self,
        reason: EmergencyReason,
    ) -> EmergencyAction:
        """
        Execute emergency procedures.
        
        1. Cancel all orders on both exchanges
        2. Close all positions on both exchanges
        3. Record and log the action
        
        Args:
            reason: Why emergency was triggered
            
        Returns:
            EmergencyAction with results
        """
        self._emergency_triggered = True
        
        trading_logger.emergency(
            "Emergency shutdown initiated",
            reason=reason.value,
        )
        
        import time
        timestamp = int(time.time() * 1000)
        
        positions_closed: List[str] = []
        orders_cancelled = 0
        success = True
        details_parts: List[str] = []
        
        # Cancel all orders
        try:
            ext_cancelled = await self._extended.cancel_all_orders()
            orders_cancelled += ext_cancelled
            details_parts.append(f"Extended: cancelled {ext_cancelled} orders")
        except Exception as e:
            logger.error("Failed to cancel Extended orders", error=str(e))
            success = False
            details_parts.append(f"Extended order cancel failed: {e}")
        
        try:
            xyz_cancelled = await self._tradexyz.cancel_all_orders()
            orders_cancelled += xyz_cancelled
            details_parts.append(f"TradeXYZ: cancelled {xyz_cancelled} orders")
        except Exception as e:
            logger.error("Failed to cancel TradeXYZ orders", error=str(e))
            success = False
            details_parts.append(f"TradeXYZ order cancel failed: {e}")
        
        # Close all positions
        try:
            ext_positions = await self._extended.get_positions()
            for pos in ext_positions:
                try:
                    await self._extended.close_position(pos.symbol)
                    positions_closed.append(f"Extended:{pos.symbol}")
                except Exception as e:
                    logger.error(
                        "Failed to close Extended position",
                        symbol=pos.symbol,
                        error=str(e),
                    )
                    success = False
        except Exception as e:
            logger.error("Failed to get Extended positions", error=str(e))
            success = False
        
        try:
            xyz_positions = await self._tradexyz.get_positions()
            for pos in xyz_positions:
                try:
                    await self._tradexyz.close_position(pos.symbol)
                    positions_closed.append(f"TradeXYZ:{pos.symbol}")
                except Exception as e:
                    logger.error(
                        "Failed to close TradeXYZ position",
                        symbol=pos.symbol,
                        error=str(e),
                    )
                    success = False
        except Exception as e:
            logger.error("Failed to get TradeXYZ positions", error=str(e))
            success = False
        
        action = EmergencyAction(
            reason=reason,
            timestamp=timestamp,
            positions_closed=positions_closed,
            orders_cancelled=orders_cancelled,
            success=success,
            details="; ".join(details_parts),
        )
        
        if self._on_emergency:
            try:
                self._on_emergency(action)
            except Exception as e:
                logger.error("Emergency callback failed", error=str(e))
        
        trading_logger.emergency(
            "Emergency shutdown complete",
            reason=reason.value,
            positions_closed=len(positions_closed),
            orders_cancelled=orders_cancelled,
            success=success,
        )
        
        return action
    
    async def verify_all_closed(self) -> bool:
        """
        Verify all positions are closed.
        
        Returns:
            True if no open positions exist
        """
        try:
            ext_positions = await self._extended.get_positions()
            xyz_positions = await self._tradexyz.get_positions()
            
            if ext_positions:
                logger.warning(
                    "Extended still has positions",
                    count=len(ext_positions),
                )
                return False
            
            if xyz_positions:
                logger.warning(
                    "TradeXYZ still has positions",
                    count=len(xyz_positions),
                )
                return False
            
            return True
            
        except Exception as e:
            logger.error("Position verification failed", error=str(e))
            return False
    
    async def run_safety_loop(self) -> None:
        """
        Run continuous safety check loop.
        
        Checks exposure and connection health periodically.
        """
        while not self._shutdown_requested and not self._emergency_triggered:
            try:
                # Check exposure balance
                if self._monitored_tokens:
                    balanced = await self.check_exposure()
                    if not balanced:
                        await self.execute_emergency(EmergencyReason.UNHEDGED_EXPOSURE)
                        break
                
                # Check exchange connections
                if not self._extended.is_connected:
                    logger.error("Extended connection lost")
                    await self.execute_emergency(EmergencyReason.CONNECTION_LOST)
                    break
                
                if not self._tradexyz.is_connected:
                    logger.error("TradeXYZ connection lost")
                    await self.execute_emergency(EmergencyReason.CONNECTION_LOST)
                    break
                
            except Exception as e:
                logger.error("Safety check error", error=str(e))
            
            await asyncio.sleep(self._check_interval)
