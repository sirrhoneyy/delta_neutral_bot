"""Risk management and validation for trading operations."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from config.constants import ExchangeName, PositionSide
from .sizing import SizingResult, BalanceInfo


class RiskLevel(str, Enum):
    """Risk assessment levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskCheckResult:
    """
    Result of a risk validation check.
    
    Attributes:
        passed: Whether the check passed
        risk_level: Assessed risk level
        check_name: Name of the check
        message: Human-readable description
        details: Additional details
    """
    passed: bool
    risk_level: RiskLevel
    check_name: str
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class RiskAssessment:
    """
    Complete risk assessment for a trading cycle.
    
    Aggregates all individual risk checks into a single result.
    """
    checks: List[RiskCheckResult]
    overall_passed: bool
    overall_risk_level: RiskLevel
    blocking_issues: List[str]
    warnings: List[str]
    
    @property
    def can_proceed(self) -> bool:
        """Whether trading can proceed."""
        return self.overall_passed and self.overall_risk_level != RiskLevel.CRITICAL


class RiskValidator:
    """
    Validates trading parameters against risk constraints.
    
    Performs comprehensive pre-trade validation including:
    - Balance sufficiency
    - Margin requirements
    - Liquidation risk
    - Position limits
    - Exchange constraints
    """
    
    def __init__(
        self,
        max_position_value: float = 100_000.0,
        min_balance_required: float = 100.0,
        max_slippage_percent: float = 0.5,
        min_margin_ratio: float = 0.2,
    ):
        """
        Initialize risk validator.
        
        Args:
            max_position_value: Maximum position value per leg
            min_balance_required: Minimum balance to trade
            max_slippage_percent: Maximum allowed slippage
            min_margin_ratio: Minimum margin buffer above maintenance
        """
        self._max_position = max_position_value
        self._min_balance = min_balance_required
        self._max_slippage = max_slippage_percent
        self._min_margin_ratio = min_margin_ratio
    
    def validate_pre_trade(
        self,
        sizing: SizingResult,
        extended_balance: BalanceInfo,
        tradexyz_balance: BalanceInfo,
        current_price: float,
        extended_maintenance_margin: float = 0.005,
        tradexyz_maintenance_margin: float = 0.005,
    ) -> RiskAssessment:
        """
        Perform comprehensive pre-trade risk validation.
        
        Args:
            sizing: Calculated position sizing
            extended_balance: Extended exchange balance
            tradexyz_balance: TradeXYZ exchange balance
            current_price: Current token price
            extended_maintenance_margin: Extended maintenance margin rate
            tradexyz_maintenance_margin: TradeXYZ maintenance margin rate
            
        Returns:
            Complete RiskAssessment
        """
        checks: List[RiskCheckResult] = []
        
        # Check 1: Minimum balance
        checks.append(self._check_minimum_balance(
            extended_balance,
            tradexyz_balance,
        ))
        
        # Check 2: Position size limits
        checks.append(self._check_position_limits(sizing))
        
        # Check 3: Margin sufficiency
        checks.append(self._check_margin_sufficiency(
            sizing,
            extended_balance,
            tradexyz_balance,
        ))
        
        # Check 4: Liquidation distance
        checks.append(self._check_liquidation_risk(
            sizing,
            current_price,
            extended_maintenance_margin,
            tradexyz_maintenance_margin,
        ))
        
        # Check 5: Leverage appropriateness
        checks.append(self._check_leverage(sizing))
        
        # Aggregate results
        return self._aggregate_results(checks)
    
    def _check_minimum_balance(
        self,
        extended_balance: BalanceInfo,
        tradexyz_balance: BalanceInfo,
    ) -> RiskCheckResult:
        """Check minimum balance requirements."""
        min_available = min(extended_balance.available, tradexyz_balance.available)
        
        if min_available < self._min_balance:
            return RiskCheckResult(
                passed=False,
                risk_level=RiskLevel.CRITICAL,
                check_name="minimum_balance",
                message=f"Available balance ${min_available:.2f} below minimum ${self._min_balance:.2f}",
                details={
                    "extended_available": extended_balance.available,
                    "tradexyz_available": tradexyz_balance.available,
                    "minimum_required": self._min_balance,
                },
            )
        
        if min_available < self._min_balance * 2:
            return RiskCheckResult(
                passed=True,
                risk_level=RiskLevel.MEDIUM,
                check_name="minimum_balance",
                message=f"Balance ${min_available:.2f} is low but acceptable",
                details={
                    "extended_available": extended_balance.available,
                    "tradexyz_available": tradexyz_balance.available,
                },
            )
        
        return RiskCheckResult(
            passed=True,
            risk_level=RiskLevel.LOW,
            check_name="minimum_balance",
            message="Balance check passed",
            details={
                "extended_available": extended_balance.available,
                "tradexyz_available": tradexyz_balance.available,
            },
        )
    
    def _check_position_limits(self, sizing: SizingResult) -> RiskCheckResult:
        """Check position size against limits."""
        if sizing.position_value_usd > self._max_position:
            return RiskCheckResult(
                passed=False,
                risk_level=RiskLevel.HIGH,
                check_name="position_limits",
                message=f"Position value ${sizing.position_value_usd:.2f} exceeds max ${self._max_position:.2f}",
                details={
                    "position_value": sizing.position_value_usd,
                    "max_allowed": self._max_position,
                },
            )
        
        if sizing.position_size <= 0:
            return RiskCheckResult(
                passed=False,
                risk_level=RiskLevel.CRITICAL,
                check_name="position_limits",
                message="Position size is zero or negative",
                details={"position_size": sizing.position_size},
            )
        
        return RiskCheckResult(
            passed=True,
            risk_level=RiskLevel.LOW,
            check_name="position_limits",
            message="Position limits check passed",
            details={
                "position_value": sizing.position_value_usd,
                "max_allowed": self._max_position,
            },
        )
    
    def _check_margin_sufficiency(
        self,
        sizing: SizingResult,
        extended_balance: BalanceInfo,
        tradexyz_balance: BalanceInfo,
    ) -> RiskCheckResult:
        """Check margin is sufficient with buffer."""
        required_with_buffer = sizing.margin_required_per_leg * (1 + self._min_margin_ratio)
        
        extended_ok = extended_balance.available >= required_with_buffer
        tradexyz_ok = tradexyz_balance.available >= required_with_buffer
        
        if not extended_ok or not tradexyz_ok:
            issues = []
            if not extended_ok:
                issues.append(f"Extended: ${extended_balance.available:.2f} < ${required_with_buffer:.2f}")
            if not tradexyz_ok:
                issues.append(f"TradeXYZ: ${tradexyz_balance.available:.2f} < ${required_with_buffer:.2f}")
            
            return RiskCheckResult(
                passed=False,
                risk_level=RiskLevel.HIGH,
                check_name="margin_sufficiency",
                message=f"Insufficient margin with buffer: {'; '.join(issues)}",
                details={
                    "required_with_buffer": required_with_buffer,
                    "extended_available": extended_balance.available,
                    "tradexyz_available": tradexyz_balance.available,
                    "buffer_ratio": self._min_margin_ratio,
                },
            )
        
        extended_util = sizing.margin_required_per_leg / extended_balance.available
        tradexyz_util = sizing.margin_required_per_leg / tradexyz_balance.available
        max_util = max(extended_util, tradexyz_util)
        
        risk_level = RiskLevel.MEDIUM if max_util > 0.9 else RiskLevel.LOW
        
        return RiskCheckResult(
            passed=True,
            risk_level=risk_level,
            check_name="margin_sufficiency",
            message=f"Margin check passed (max utilization: {max_util:.1%})",
            details={
                "extended_utilization": extended_util,
                "tradexyz_utilization": tradexyz_util,
            },
        )
    
    def _check_liquidation_risk(
        self,
        sizing: SizingResult,
        current_price: float,
        extended_mm: float,
        tradexyz_mm: float,
    ) -> RiskCheckResult:
        """Check liquidation price distance."""
        if sizing.leverage <= 0 or current_price <= 0:
            return RiskCheckResult(
                passed=False,
                risk_level=RiskLevel.CRITICAL,
                check_name="liquidation_risk",
                message="Invalid leverage or price for liquidation calculation",
                details={},
            )
        
        leverage = sizing.leverage
        
        long_liq_distance = (1 / leverage) - extended_mm
        long_liq_price = current_price * (1 - long_liq_distance)
        
        short_liq_distance = (1 / leverage) - tradexyz_mm
        short_liq_price = current_price * (1 + short_liq_distance)
        
        min_safe_distance = 0.03
        
        long_distance_pct = abs(current_price - long_liq_price) / current_price
        short_distance_pct = abs(short_liq_price - current_price) / current_price
        
        if long_distance_pct < min_safe_distance or short_distance_pct < min_safe_distance:
            return RiskCheckResult(
                passed=False,
                risk_level=RiskLevel.HIGH,
                check_name="liquidation_risk",
                message=f"Liquidation too close: long {long_distance_pct:.1%}, short {short_distance_pct:.1%}",
                details={
                    "current_price": current_price,
                    "long_liq_price": long_liq_price,
                    "short_liq_price": short_liq_price,
                    "long_distance_pct": long_distance_pct,
                    "short_distance_pct": short_distance_pct,
                },
            )
        
        risk_level = RiskLevel.MEDIUM if min(long_distance_pct, short_distance_pct) < 0.05 else RiskLevel.LOW
        
        return RiskCheckResult(
            passed=True,
            risk_level=risk_level,
            check_name="liquidation_risk",
            message=f"Liquidation distance OK (long: {long_distance_pct:.1%}, short: {short_distance_pct:.1%})",
            details={
                "long_liq_price": long_liq_price,
                "short_liq_price": short_liq_price,
            },
        )
    
    def _check_leverage(self, sizing: SizingResult) -> RiskCheckResult:
        """Check leverage is within safe bounds."""
        leverage = sizing.leverage
        
        if leverage > 20:
            return RiskCheckResult(
                passed=False,
                risk_level=RiskLevel.HIGH,
                check_name="leverage",
                message=f"Leverage {leverage}x exceeds maximum 20x",
                details={"leverage": leverage, "max_allowed": 20},
            )
        
        if leverage < 10:
            return RiskCheckResult(
                passed=True,
                risk_level=RiskLevel.LOW,
                check_name="leverage",
                message=f"Leverage {leverage}x is below target range (10-20x)",
                details={"leverage": leverage},
            )
        
        risk_level = RiskLevel.LOW if leverage <= 15 else RiskLevel.MEDIUM
        
        return RiskCheckResult(
            passed=True,
            risk_level=risk_level,
            check_name="leverage",
            message=f"Leverage {leverage}x within acceptable range",
            details={"leverage": leverage},
        )
    
    def _aggregate_results(self, checks: List[RiskCheckResult]) -> RiskAssessment:
        """Aggregate individual checks into overall assessment."""
        blocking: List[str] = []
        warnings: List[str] = []
        
        overall_passed = all(c.passed for c in checks)
        
        for check in checks:
            if not check.passed:
                blocking.append(f"{check.check_name}: {check.message}")
            elif check.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH):
                warnings.append(f"{check.check_name}: {check.message}")
        
        risk_levels = [c.risk_level for c in checks]
        if RiskLevel.CRITICAL in risk_levels:
            overall_risk = RiskLevel.CRITICAL
        elif RiskLevel.HIGH in risk_levels:
            overall_risk = RiskLevel.HIGH
        elif RiskLevel.MEDIUM in risk_levels:
            overall_risk = RiskLevel.MEDIUM
        else:
            overall_risk = RiskLevel.LOW
        
        return RiskAssessment(
            checks=checks,
            overall_passed=overall_passed,
            overall_risk_level=overall_risk,
            blocking_issues=blocking,
            warnings=warnings,
        )
