"""Cryptographically secure randomization for trading parameters."""

import secrets
from dataclasses import dataclass
from typing import List, Tuple

from config.constants import (
    SUPPORTED_TOKENS,
    ExchangeName,
    PositionSide,
    FUNDING_BIAS_THRESHOLDS,
    FUNDING_BIAS_WEIGHTS,
    InternalParams,
)


@dataclass(frozen=True)
class RandomParams:
    """
    Randomized parameters for a trading cycle.
    
    All values are determined at cycle start and remain
    constant throughout the cycle.
    """
    token: str
    equity_usage: float  # 0.40 - 0.80
    leverage: int  # 10 - 20
    hold_duration_seconds: int  # 1200 - 7200
    cooldown_seconds: int  # 600 - 3600


class CryptoRandomizer:
    """
    Cryptographically secure randomization for trading operations.
    
    Uses Python's secrets module (backed by OS entropy) to ensure
    non-predictable, non-reproducible random values.
    
    This prevents:
    - Pattern detection by external observers
    - Timing attacks
    - Predictable behavior exploitation
    """
    
    def __init__(
        self,
        min_equity: float = 0.40,
        max_equity: float = 0.80,
        min_leverage: int = 10,
        max_leverage: int = 20,
        min_hold: int = 1200,
        max_hold: int = 7200,
        min_cooldown: int = 600,
        max_cooldown: int = 3600,
    ):
        """
        Initialize randomizer with bounds.
        
        Args:
            min_equity: Minimum equity usage percentage
            max_equity: Maximum equity usage percentage
            min_leverage: Minimum leverage multiplier
            max_leverage: Maximum leverage multiplier
            min_hold: Minimum hold duration in seconds
            max_hold: Maximum hold duration in seconds
            min_cooldown: Minimum cooldown in seconds
            max_cooldown: Maximum cooldown in seconds
        """
        self._min_equity = min_equity
        self._max_equity = max_equity
        self._min_leverage = min_leverage
        self._max_leverage = max_leverage
        self._min_hold = min_hold
        self._max_hold = max_hold
        self._min_cooldown = min_cooldown
        self._max_cooldown = max_cooldown
    
    def select_token(self, tokens: List[str] | None = None) -> str:
        """
        Randomly select a token to trade.
        
        Args:
            tokens: List of tokens to choose from (defaults to SUPPORTED_TOKENS)
            
        Returns:
            Selected token symbol
        """
        available = tokens or SUPPORTED_TOKENS
        if not available:
            raise ValueError("No tokens available for selection")
        
        index = secrets.randbelow(len(available))
        return available[index]
    
    def generate_equity_usage(self) -> float:
        """
        Generate random equity usage percentage.

        Uses discrete steps for precision while maintaining
        cryptographic randomness.

        Returns:
            Equity usage as decimal (e.g., 0.65 for 65%)
        """
        range_size = self._max_equity - self._min_equity
        steps = InternalParams.RANDOMIZATION_STEPS

        random_step = secrets.randbelow(steps + 1)
        return self._min_equity + (range_size * random_step / steps)
    
    def generate_leverage(self) -> int:
        """
        Generate random leverage multiplier.
        
        Returns:
            Leverage as integer (e.g., 15 for 15x)
        """
        range_size = self._max_leverage - self._min_leverage
        return self._min_leverage + secrets.randbelow(range_size + 1)
    
    def generate_hold_duration(self) -> int:
        """
        Generate random position hold duration.
        
        Returns:
            Hold duration in seconds
        """
        range_size = self._max_hold - self._min_hold
        return self._min_hold + secrets.randbelow(range_size + 1)
    
    def generate_cooldown(self) -> int:
        """
        Generate random cooldown duration.
        
        Returns:
            Cooldown duration in seconds
        """
        range_size = self._max_cooldown - self._min_cooldown
        return self._min_cooldown + secrets.randbelow(range_size + 1)
    
    def generate_cycle_params(self, tokens: List[str] | None = None) -> RandomParams:
        """
        Generate all random parameters for a trading cycle.
        
        Creates a complete, immutable set of parameters to be used
        throughout a single cycle.
        
        Args:
            tokens: Optional list of tokens to choose from
            
        Returns:
            RandomParams with all cycle parameters
        """
        return RandomParams(
            token=self.select_token(tokens),
            equity_usage=self.generate_equity_usage(),
            leverage=self.generate_leverage(),
            hold_duration_seconds=self.generate_hold_duration(),
            cooldown_seconds=self.generate_cooldown(),
        )
    
    def assign_exchange_sides_random(self) -> Tuple[Tuple[ExchangeName, PositionSide], Tuple[ExchangeName, PositionSide]]:
        """
        Randomly assign long/short sides to exchanges.
        
        Pure random assignment without funding rate consideration.
        
        Returns:
            Tuple of ((exchange1, side1), (exchange2, side2))
        """
        # Random coin flip using cryptographic randomness
        extended_is_long = secrets.randbelow(2) == 0
        
        if extended_is_long:
            return (
                (ExchangeName.EXTENDED, PositionSide.LONG),
                (ExchangeName.TRADEXYZ, PositionSide.SHORT),
            )
        else:
            return (
                (ExchangeName.EXTENDED, PositionSide.SHORT),
                (ExchangeName.TRADEXYZ, PositionSide.LONG),
            )
    
    def assign_exchange_sides_with_bias(
        self,
        extended_funding: float,
        tradexyz_funding: float,
    ) -> Tuple[Tuple[ExchangeName, PositionSide], Tuple[ExchangeName, PositionSide]]:
        """
        Assign exchange sides with probabilistic funding rate bias.
        
        Funding rate logic:
        - Positive funding = longs pay shorts → prefer SHORT
        - Negative funding = shorts pay longs → prefer LONG
        
        The bias is probabilistic, not deterministic:
        - Small difference: ~50/50 (near random)
        - Moderate difference: ~60/40 (mild bias)
        - Large difference: ~75/25 (strong bias)
        
        Args:
            extended_funding: Current funding rate on Extended
            tradexyz_funding: Current funding rate on TradeXYZ
            
        Returns:
            Tuple of ((exchange1, side1), (exchange2, side2))
        """
        # Calculate which exchange is more favorable for shorts
        # Higher positive funding = better to be short (collect funding)
        funding_diff = abs(extended_funding - tradexyz_funding)
        
        # Determine bias category
        bias_category = "SMALL"
        for category, (low, high) in FUNDING_BIAS_THRESHOLDS.items():
            if low <= funding_diff < high:
                bias_category = category
                break
        
        # Get probability weights
        favorable_weight, other_weight = FUNDING_BIAS_WEIGHTS[bias_category]
        
        # Determine which exchange is more favorable for shorts
        # (higher positive funding or less negative funding)
        extended_more_favorable_for_short = extended_funding > tradexyz_funding
        
        # Generate random threshold for comparison
        # Using discrete steps for precision
        threshold = int(favorable_weight * InternalParams.RANDOMIZATION_STEPS)
        random_value = secrets.randbelow(InternalParams.RANDOMIZATION_STEPS)
        
        # Apply probabilistic selection
        choose_favorable = random_value < threshold
        
        if extended_more_favorable_for_short:
            # Extended is better for shorts
            if choose_favorable:
                # Bias won: Short on Extended
                return (
                    (ExchangeName.EXTENDED, PositionSide.SHORT),
                    (ExchangeName.TRADEXYZ, PositionSide.LONG),
                )
            else:
                # Randomness won: Long on Extended
                return (
                    (ExchangeName.EXTENDED, PositionSide.LONG),
                    (ExchangeName.TRADEXYZ, PositionSide.SHORT),
                )
        else:
            # TradeXYZ is better for shorts
            if choose_favorable:
                # Bias won: Short on TradeXYZ
                return (
                    (ExchangeName.EXTENDED, PositionSide.LONG),
                    (ExchangeName.TRADEXYZ, PositionSide.SHORT),
                )
            else:
                # Randomness won: Long on TradeXYZ
                return (
                    (ExchangeName.EXTENDED, PositionSide.SHORT),
                    (ExchangeName.TRADEXYZ, PositionSide.LONG),
                )
    
    @staticmethod
    def generate_nonce() -> int:
        """
        Generate a cryptographically random nonce.
        
        Used for order signing and uniqueness.
        
        Returns:
            Random 64-bit integer
        """
        return secrets.randbits(64)
    
    @staticmethod
    def generate_external_id() -> str:
        """
        Generate a unique external order ID.
        
        Returns:
            Hex string suitable for order identification
        """
        return secrets.token_hex(16)
