"""Funding rate analysis for delta-neutral strategy optimization."""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from config.constants import (
    ExchangeName,
    PositionSide,
    FUNDING_BIAS_THRESHOLDS,
)


class FundingBias(str, Enum):
    """Funding rate bias strength categories."""
    NONE = "none"           # No meaningful difference
    SMALL = "small"         # < 0.01% - near random
    MODERATE = "moderate"   # 0.01% - 0.05% - mild bias
    LARGE = "large"         # > 0.05% - strong bias


@dataclass
class FundingRateInfo:
    """
    Funding rate information for a single exchange.
    
    Attributes:
        exchange: Exchange name
        rate: Current funding rate (as decimal, e.g., 0.0001 = 0.01%)
        next_funding_time: Unix timestamp of next funding
        token: Token/market symbol
    """
    exchange: ExchangeName
    rate: float
    next_funding_time: int
    token: str
    
    @property
    def rate_percent(self) -> float:
        """Get rate as percentage."""
        return self.rate * 100
    
    @property
    def is_positive(self) -> bool:
        """Check if longs pay shorts."""
        return self.rate > 0
    
    @property
    def is_negative(self) -> bool:
        """Check if shorts pay longs."""
        return self.rate < 0


@dataclass
class FundingAnalysisResult:
    """
    Result of funding rate analysis.
    
    Contains the analysis results and recommended exchange
    assignments based on funding rate optimization.
    """
    extended_rate: FundingRateInfo
    tradexyz_rate: FundingRateInfo
    
    # Analysis results
    rate_difference: float
    bias_strength: FundingBias
    
    # Recommendation (subject to probabilistic override)
    recommended_short_exchange: ExchangeName
    recommended_long_exchange: ExchangeName
    
    # Expected funding outcome
    expected_hourly_funding_income: float  # Positive = earning, negative = paying
    
    @property
    def favorable_for_optimization(self) -> bool:
        """Check if funding difference is significant enough to matter."""
        return self.bias_strength != FundingBias.NONE


class FundingAnalyzer:
    """
    Analyzes funding rates to optimize delta-neutral positions.
    
    Funding Rate Economics:
    - Positive rate: Longs pay shorts → prefer SHORT position
    - Negative rate: Shorts pay longs → prefer LONG position
    
    The analyzer determines optimal exchange assignments but
    does NOT enforce them - the randomizer applies probabilistic
    bias based on these recommendations.
    """
    
    def __init__(self, min_meaningful_diff: float = 0.00001):
        """
        Initialize funding analyzer.
        
        Args:
            min_meaningful_diff: Minimum rate difference to consider meaningful
                                (default: 0.001% = 0.00001)
        """
        self._min_diff = min_meaningful_diff
    
    def analyze(
        self,
        extended_rate: float,
        tradexyz_rate: float,
        token: str,
        extended_next_funding: int = 0,
        tradexyz_next_funding: int = 0,
        position_value_usd: float = 0,
    ) -> FundingAnalysisResult:
        """
        Analyze funding rates and determine optimal assignments.
        
        Args:
            extended_rate: Extended exchange funding rate
            tradexyz_rate: TradeXYZ funding rate
            token: Token being traded
            extended_next_funding: Next funding time on Extended
            tradexyz_next_funding: Next funding time on TradeXYZ
            position_value_usd: Position value for income calculation
            
        Returns:
            FundingAnalysisResult with analysis and recommendations
        """
        # Create rate info objects
        extended_info = FundingRateInfo(
            exchange=ExchangeName.EXTENDED,
            rate=extended_rate,
            next_funding_time=extended_next_funding,
            token=token,
        )
        
        tradexyz_info = FundingRateInfo(
            exchange=ExchangeName.TRADEXYZ,
            rate=tradexyz_rate,
            next_funding_time=tradexyz_next_funding,
            token=token,
        )
        
        # Calculate difference
        rate_difference = abs(extended_rate - tradexyz_rate)
        
        # Determine bias strength
        bias_strength = self._determine_bias_strength(rate_difference)
        
        # Determine optimal assignments
        # Higher rate = better to be short (collect from longs)
        if extended_rate > tradexyz_rate:
            recommended_short = ExchangeName.EXTENDED
            recommended_long = ExchangeName.TRADEXYZ
        else:
            recommended_short = ExchangeName.TRADEXYZ
            recommended_long = ExchangeName.EXTENDED
        
        # Calculate expected funding income
        # Income = (short_position_rate - long_position_rate) * position_value
        # When short on higher-rate exchange: positive income
        expected_income = self._calculate_expected_income(
            extended_rate=extended_rate,
            tradexyz_rate=tradexyz_rate,
            recommended_short=recommended_short,
            position_value=position_value_usd,
        )
        
        return FundingAnalysisResult(
            extended_rate=extended_info,
            tradexyz_rate=tradexyz_info,
            rate_difference=rate_difference,
            bias_strength=bias_strength,
            recommended_short_exchange=recommended_short,
            recommended_long_exchange=recommended_long,
            expected_hourly_funding_income=expected_income,
        )
    
    def _determine_bias_strength(self, rate_difference: float) -> FundingBias:
        """
        Determine bias strength category based on rate difference.
        
        Args:
            rate_difference: Absolute difference between rates
            
        Returns:
            FundingBias category
        """
        if rate_difference < self._min_diff:
            return FundingBias.NONE
        
        for category, (low, high) in FUNDING_BIAS_THRESHOLDS.items():
            if low <= rate_difference < high:
                return FundingBias(category.lower())
        
        return FundingBias.LARGE
    
    def _calculate_expected_income(
        self,
        extended_rate: float,
        tradexyz_rate: float,
        recommended_short: ExchangeName,
        position_value: float,
    ) -> float:
        """
        Calculate expected hourly funding income.
        
        For delta-neutral positions:
        - Short position: receives funding when rate is positive
        - Long position: pays funding when rate is positive
        
        Net income = short_receive - long_pay
        
        Args:
            extended_rate: Extended funding rate
            tradexyz_rate: TradeXYZ funding rate
            recommended_short: Which exchange to short
            position_value: Position size in USD
            
        Returns:
            Expected hourly income (positive = earning)
        """
        if position_value <= 0:
            return 0.0
        
        if recommended_short == ExchangeName.EXTENDED:
            # Short on Extended, Long on TradeXYZ
            short_rate = extended_rate
            long_rate = tradexyz_rate
        else:
            # Short on TradeXYZ, Long on Extended
            short_rate = tradexyz_rate
            long_rate = extended_rate
        
        # Short position income (positive rate = receive funding)
        short_income = position_value * short_rate
        
        # Long position cost (positive rate = pay funding)
        long_cost = position_value * long_rate
        
        # Net funding income
        return short_income - long_cost
    
    def compare_assignment_outcomes(
        self,
        extended_rate: float,
        tradexyz_rate: float,
        position_value: float,
    ) -> Tuple[float, float]:
        """
        Compare funding outcomes for both possible assignments.
        
        Args:
            extended_rate: Extended funding rate
            tradexyz_rate: TradeXYZ funding rate
            position_value: Position value in USD
            
        Returns:
            Tuple of (income_if_short_extended, income_if_short_tradexyz)
        """
        # Scenario 1: Short Extended, Long TradeXYZ
        income_short_extended = (
            position_value * extended_rate  # Receive on short
            - position_value * tradexyz_rate  # Pay on long
        )
        
        # Scenario 2: Short TradeXYZ, Long Extended
        income_short_tradexyz = (
            position_value * tradexyz_rate  # Receive on short
            - position_value * extended_rate  # Pay on long
        )
        
        return (income_short_extended, income_short_tradexyz)
    
    @staticmethod
    def format_rate(rate: float) -> str:
        """
        Format funding rate for display.
        
        Args:
            rate: Rate as decimal
            
        Returns:
            Formatted string (e.g., "+0.0100%" or "-0.0050%")
        """
        percentage = rate * 100
        sign = "+" if percentage >= 0 else ""
        return f"{sign}{percentage:.4f}%"
