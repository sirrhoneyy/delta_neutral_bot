"""Structured logging configuration."""

import logging
import sys
from datetime import datetime, timezone
from typing import Any

import structlog
from rich.console import Console
from rich.logging import RichHandler


def setup_logging(level: str = "INFO") -> None:
    """
    Configure structured logging with rich output.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    # Configure standard library logging
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=Console(stderr=True),
                show_time=True,
                show_path=False,
                rich_tracebacks=True,
                tracebacks_show_locals=True,
            )
        ],
    )
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.
    
    Args:
        name: Logger name (typically module name)
        
    Returns:
        Configured structured logger
    """
    return structlog.get_logger(name)


class TradingLogger:
    """
    Specialized logger for trading operations.
    
    Provides standardized logging for trading events with
    consistent formatting and contextual information.
    """
    
    def __init__(self, name: str = "trading"):
        self._logger = get_logger(name)
        
    def cycle_start(
        self,
        cycle_id: str,
        token: str,
        **kwargs: Any
    ) -> None:
        """Log cycle start."""
        self._logger.info(
            "Cycle started",
            cycle_id=cycle_id,
            token=token,
            **kwargs
        )
    
    def cycle_end(
        self,
        cycle_id: str,
        duration_seconds: float,
        pnl: float | None = None,
        **kwargs: Any
    ) -> None:
        """Log cycle completion."""
        self._logger.info(
            "Cycle completed",
            cycle_id=cycle_id,
            duration_seconds=round(duration_seconds, 2),
            pnl=pnl,
            **kwargs
        )
    
    def funding_rates(
        self,
        token: str,
        extended_rate: float,
        tradexyz_rate: float,
        bias_result: str,
    ) -> None:
        """Log funding rate analysis."""
        self._logger.info(
            "Funding rates analyzed",
            token=token,
            extended_rate=f"{extended_rate:.6f}",
            tradexyz_rate=f"{tradexyz_rate:.6f}",
            rate_diff=f"{abs(extended_rate - tradexyz_rate):.6f}",
            bias=bias_result,
        )
    
    def position_assignment(
        self,
        extended_side: str,
        tradexyz_side: str,
        funding_favored: bool,
    ) -> None:
        """Log position side assignment."""
        self._logger.info(
            "Positions assigned",
            extended=extended_side,
            tradexyz=tradexyz_side,
            funding_optimized=funding_favored,
        )
    
    def sizing_decision(
        self,
        equity_usage: float,
        leverage: int,
        position_size: float,
        position_value_usd: float,
    ) -> None:
        """Log position sizing decision."""
        self._logger.info(
            "Position sized",
            equity_pct=f"{equity_usage * 100:.1f}%",
            leverage=f"{leverage}x",
            size=position_size,
            value_usd=f"${position_value_usd:,.2f}",
        )
    
    def order_placed(
        self,
        exchange: str,
        side: str,
        size: float,
        price: float | None = None,
        order_id: str | None = None,
    ) -> None:
        """Log order placement."""
        self._logger.info(
            "Order placed",
            exchange=exchange,
            side=side,
            size=size,
            price=price,
            order_id=order_id,
        )
    
    def order_filled(
        self,
        exchange: str,
        order_id: str,
        fill_price: float,
        fill_size: float,
    ) -> None:
        """Log order fill."""
        self._logger.info(
            "Order filled",
            exchange=exchange,
            order_id=order_id,
            fill_price=fill_price,
            fill_size=fill_size,
        )
    
    def position_opened(
        self,
        exchange: str,
        side: str,
        size: float,
        entry_price: float,
    ) -> None:
        """Log position opening."""
        self._logger.info(
            "Position opened",
            exchange=exchange,
            side=side,
            size=size,
            entry_price=entry_price,
        )
    
    def position_closed(
        self,
        exchange: str,
        side: str,
        size: float,
        exit_price: float,
        pnl: float,
    ) -> None:
        """Log position closing."""
        self._logger.info(
            "Position closed",
            exchange=exchange,
            side=side,
            size=size,
            exit_price=exit_price,
            realized_pnl=f"${pnl:,.2f}",
        )
    
    def error(
        self,
        message: str,
        error: Exception | None = None,
        **kwargs: Any
    ) -> None:
        """Log error with context."""
        self._logger.error(
            message,
            error=str(error) if error else None,
            error_type=type(error).__name__ if error else None,
            **kwargs
        )
    
    def warning(
        self,
        message: str,
        **kwargs: Any
    ) -> None:
        """Log warning."""
        self._logger.warning(message, **kwargs)
    
    def debug(
        self,
        message: str,
        **kwargs: Any
    ) -> None:
        """Log debug information."""
        self._logger.debug(message, **kwargs)
    
    def emergency(
        self,
        message: str,
        reason: str,
        **kwargs: Any
    ) -> None:
        """Log emergency event."""
        self._logger.critical(
            f"EMERGENCY: {message}",
            reason=reason,
            timestamp=datetime.now(timezone.utc).isoformat(),
            **kwargs
        )


# Create a global trading logger instance
trading_logger = TradingLogger()
