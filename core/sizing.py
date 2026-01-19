"""Position sizing logic for delta-neutral strategy."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Tuple

from config.constants import InternalParams


@dataclass
class BalanceInfo:
    """
    Balance information for an exchange.
    
    Attributes:
        available: Available balance for trading
        equity: Total account equity
        margin_used: Currently used margin
        currency: Balance currency (usually USD/USDC)
    """
    available: float
    equity: float
    margin_used: float
    currency: str = "USD"


@dataclass
class SizingResult:
    """
    Result of position sizing calculation.
    
    Contains all sizing parameters for a delta-neutral position pair.
    """
    # Common parameters
    token: str
    position_size: float  # In base asset (e.g., BTC)
    position_value_usd: float  # Notional value in USD
    
    # Margin requirements
    margin_required_per_leg: float  # Per exchange
    total_margin_required: float  # Both legs combined
    
    # Parameters used
    equity_usage: float  # As decimal (e.g., 0.65)
    leverage: int
    
    # Effective values
    effective_leverage: float  # Actual leverage after sizing
    available_balance_used: float  # USD amount from available
    
    # Validation info
    fits_constraints: bool
    constraint_notes: list[str]


class PositionSizer:
    """
    Calculates position sizes for delta-neutral strategy.
    
    Key Principles:
    1. Size based on MINIMUM available balance across exchanges
    2. Both legs must be openable with available capital
    3. Joint validation of leverage and size to prevent margin exhaustion
    4. Conservative sizing with safety buffer
    """
    
    def __init__(
        self,
        safety_buffer: float = InternalParams.SAFETY_BUFFER,
        min_position_usd: float = 10.0,
        max_position_usd: float = 100_000.0,
    ):
        """
        Initialize position sizer.
        
        Args:
            safety_buffer: Multiply final size by this for safety
            min_position_usd: Minimum position value
            max_position_usd: Maximum position value per leg
        """
        self._safety_buffer = safety_buffer
        self._min_position = min_position_usd
        self._max_position = max_position_usd
    
    # IMPORTANT:
    # This function must never return a SizingResult with:
    # - position_size == 0 AND fits_constraints == True
    # Downstream execution assumes non-zero margins.
    def calculate_size(
        self,
        token: str,
        token_price: float,
        extended_balance: BalanceInfo,
        tradexyz_balance: BalanceInfo,
        equity_usage: float,
        leverage: int,
        min_order_size: float = 0.0001,
        size_precision: int = 6,
    ) -> SizingResult:
        """
        Calculate position size for delta-neutral pair.
        
        Args:
            token: Token symbol (e.g., "BTC")
            token_price: Current token price in USD
            extended_balance: Extended exchange balance info
            tradexyz_balance: TradeXYZ balance info
            equity_usage: Fraction of equity to use (0.4-0.8)
            leverage: Leverage multiplier (10-20)
            min_order_size: Minimum order size for token
            size_precision: Decimal places for position size
            
        Returns:
            SizingResult with calculated sizes and validation
        """
        notes: list[str] = []
        
        # Step 1: Determine constraining balance
        min_available = min(
            extended_balance.available,
            tradexyz_balance.available
        )
        
        if min_available <= 0:
            return SizingResult(
                token=token,
                position_size=0,
                position_value_usd=0,
                margin_required_per_leg=0,
                total_margin_required=0,
                equity_usage=equity_usage,
                leverage=leverage,
                effective_leverage=0,
                available_balance_used=0,
                fits_constraints=False,
                constraint_notes=["Insufficient available balance on one or both exchanges"],
            )
        
        # Step 2: Calculate capital allocation per leg
        # Each leg gets (equity_usage * min_available)
        capital_per_leg = min_available * equity_usage
        
        # Step 3: Calculate position value based on leverage
        # position_value = margin * leverage
        position_value = capital_per_leg * leverage
        
        # Step 4: Apply position value limits
        if position_value < self._min_position:
            notes.append(f"Position value ${position_value:.2f} below minimum ${self._min_position:.2f}")
            position_value = 0
        
        if position_value > self._max_position:
            notes.append(f"Position value capped from ${position_value:.2f} to ${self._max_position:.2f}")
            position_value = self._max_position
        
        # Step 5: Calculate position size in base asset
        if token_price <= 0:
            return SizingResult(
                token=token,
                position_size=0,
                position_value_usd=0,
                margin_required_per_leg=0,
                total_margin_required=0,
                equity_usage=equity_usage,
                leverage=leverage,
                effective_leverage=0,
                available_balance_used=0,
                fits_constraints=False,
                constraint_notes=["Invalid token price"],
            )
        
        raw_size = position_value / token_price
        
        # Step 6: Apply safety buffer and precision
        buffered_size = raw_size * self._safety_buffer
        
        # Round down to respect precision limits
        position_size = self._round_down(buffered_size, size_precision)
        
        # Ensure meets minimum order size
        if position_size < min_order_size:
            notes.append(f"Position size {position_size} below minimum {min_order_size}")
            return SizingResult(
                token=token,
                position_size=0,
                position_value_usd=0,
                margin_required_per_leg=0,
                total_margin_required=0,
                equity_usage=equity_usage,
                leverage=leverage,
                effective_leverage=0,
                available_balance_used=0,
                fits_constraints=False,
                constraint_notes=notes,
            )

        if position_size <= 0 or leverage <= 0:
            return SizingResult(
                token=token,
                position_size=0,
                position_value_usd=0,
                margin_required_per_leg=0,
                total_margin_required=0,
                equity_usage=equity_usage,
                leverage=leverage,
                effective_leverage=0,
                available_balance_used=0,
                fits_constraints=False,
                constraint_notes=notes + ["Invalid position size or leverage"],
            )

        
        # Step 7: Recalculate actual values after rounding
        actual_value = position_size * token_price
        actual_margin_per_leg = actual_value / leverage
        total_margin = actual_margin_per_leg * 2  # Both legs
        
        # Step 8: Verify we can still afford both legs
        fits = True
        if actual_margin_per_leg > extended_balance.available:
            fits = False
            notes.append("Insufficient margin on Extended after sizing")
        if actual_margin_per_leg > tradexyz_balance.available:
            fits = False
            notes.append("Insufficient margin on TradeXYZ after sizing")
        
        if position_size == 0:
            fits = False
        
        return SizingResult(
            token=token,
            position_size=position_size,
            position_value_usd=actual_value,
            margin_required_per_leg=actual_margin_per_leg,
            total_margin_required=total_margin,
            equity_usage=equity_usage,
            leverage=leverage,
            effective_leverage=leverage if actual_margin_per_leg > 0 else 0,
            available_balance_used=actual_margin_per_leg,
            fits_constraints=fits,
            constraint_notes=notes,
        )
    
    def calculate_with_max_leverage_for_size(
        self,
        token: str,
        token_price: float,
        target_position_size: float,
        extended_balance: BalanceInfo,
        tradexyz_balance: BalanceInfo,
        max_leverage: int = 20,
    ) -> Tuple[SizingResult, int]:
        """
        Calculate minimum leverage needed for a target size.
        
        Useful for determining if a desired position is achievable
        within leverage constraints.
        
        Args:
            token: Token symbol
            token_price: Current price
            target_position_size: Desired position size in base asset
            extended_balance: Extended balance info
            tradexyz_balance: TradeXYZ balance info
            max_leverage: Maximum allowed leverage
            
        Returns:
            Tuple of (SizingResult, required_leverage)
        """
        target_value = target_position_size * token_price
        min_available = min(extended_balance.available, tradexyz_balance.available)
        
        # Calculate required margin and leverage
        required_margin = target_value  # Without leverage
        required_leverage = int(target_value / min_available) + 1
        
        if required_leverage > max_leverage:
            # Can't achieve target size within leverage limits
            # Return what's achievable at max leverage
            achievable_equity_usage = min_available / target_value
            return self.calculate_size(
                token=token,
                token_price=token_price,
                extended_balance=extended_balance,
                tradexyz_balance=tradexyz_balance,
                equity_usage=min(0.8, achievable_equity_usage),
                leverage=max_leverage,
            ), max_leverage
        
        # Target is achievable
        equity_usage = target_value / (min_available * required_leverage)
        return self.calculate_size(
            token=token,
            token_price=token_price,
            extended_balance=extended_balance,
            tradexyz_balance=tradexyz_balance,
            equity_usage=equity_usage,
            leverage=required_leverage,
        ), required_leverage
    
    def validate_sizing(
        self,
        sizing: SizingResult,
        extended_balance: BalanceInfo,
        tradexyz_balance: BalanceInfo,
    ) -> Tuple[bool, list[str]]:
        """
        Validate a sizing result against current balances.
        
        Performs comprehensive checks to ensure positions can be opened.
        
        Args:
            sizing: SizingResult to validate
            extended_balance: Current Extended balance
            tradexyz_balance: Current TradeXYZ balance
            
        Returns:
            Tuple of (is_valid, list of issues)
        """
        issues: list[str] = []
        
        # Check position size is positive
        if sizing.position_size <= 0:
            issues.append("Position size must be positive")
        
        # Check margin requirements
        margin_per_leg = sizing.margin_required_per_leg
        
        if margin_per_leg > extended_balance.available:
            deficit = margin_per_leg - extended_balance.available
            issues.append(f"Extended: need ${margin_per_leg:.2f}, have ${extended_balance.available:.2f} (deficit: ${deficit:.2f})")
        
        if margin_per_leg > tradexyz_balance.available:
            deficit = margin_per_leg - tradexyz_balance.available
            issues.append(f"TradeXYZ: need ${margin_per_leg:.2f}, have ${tradexyz_balance.available:.2f} (deficit: ${deficit:.2f})")
        
        # Check total doesn't exceed combined available
        total_available = extended_balance.available + tradexyz_balance.available
        if sizing.total_margin_required > total_available:
            issues.append(f"Total margin ${sizing.total_margin_required:.2f} exceeds combined available ${total_available:.2f}")
        
        # Check position value limits
        if sizing.position_value_usd < self._min_position:
            issues.append(f"Position value ${sizing.position_value_usd:.2f} below minimum ${self._min_position:.2f}")
        
        if sizing.position_value_usd > self._max_position:
            issues.append(f"Position value ${sizing.position_value_usd:.2f} exceeds maximum ${self._max_position:.2f}")
        
        return len(issues) == 0, issues
    
    @staticmethod
    def _round_down(value: float, decimals: int) -> float:
        """
        Round down to specified decimal places.
        
        Uses Decimal for precision.
        
        Args:
            value: Value to round
            decimals: Number of decimal places
            
        Returns:
            Rounded value
        """
        d = Decimal(str(value))
        factor = Decimal(10) ** decimals
        rounded = (d * factor).to_integral_value(ROUND_DOWN) / factor
        return float(rounded)
