"""Tests for core trading functionality."""

import pytest
import secrets
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.constants import ExchangeName, PositionSide, SUPPORTED_TOKENS
from core.randomizer import CryptoRandomizer, RandomParams
from core.funding import FundingAnalyzer, FundingBias
from core.sizing import PositionSizer, SizingResult, BalanceInfo
from core.risk import RiskValidator, RiskLevel


class TestCryptoRandomizer:
    """Tests for CryptoRandomizer."""
    
    def test_token_selection_within_supported(self):
        """Token selection should only return supported tokens."""
        randomizer = CryptoRandomizer()
        
        for _ in range(100):
            token = randomizer.select_token()
            assert token in SUPPORTED_TOKENS
    
    def test_equity_usage_within_bounds(self):
        """Equity usage should be within configured bounds."""
        randomizer = CryptoRandomizer(
            min_equity=0.40,
            max_equity=0.80,
        )
        
        for _ in range(100):
            equity = randomizer.generate_equity_usage()
            assert 0.40 <= equity <= 0.80
    
    def test_leverage_within_bounds(self):
        """Leverage should be within configured bounds."""
        randomizer = CryptoRandomizer(
            min_leverage=10,
            max_leverage=20,
        )
        
        for _ in range(100):
            leverage = randomizer.generate_leverage()
            assert 10 <= leverage <= 20
    
    def test_hold_duration_within_bounds(self):
        """Hold duration should be within bounds."""
        randomizer = CryptoRandomizer(
            min_hold=1200,
            max_hold=7200,
        )
        
        for _ in range(100):
            duration = randomizer.generate_hold_duration()
            assert 1200 <= duration <= 7200
    
    def test_cooldown_within_bounds(self):
        """Cooldown should be within bounds."""
        randomizer = CryptoRandomizer(
            min_cooldown=600,
            max_cooldown=3600,
        )
        
        for _ in range(100):
            cooldown = randomizer.generate_cooldown()
            assert 600 <= cooldown <= 3600
    
    def test_random_side_assignment_balanced(self):
        """Random assignment should be roughly balanced."""
        randomizer = CryptoRandomizer()
        
        extended_long_count = 0
        total = 1000
        
        for _ in range(total):
            assignments = randomizer.assign_exchange_sides_random()
            if assignments[0][1] == PositionSide.LONG:
                extended_long_count += 1
        
        # Should be roughly 50/50 (allow 45-55%)
        ratio = extended_long_count / total
        assert 0.45 <= ratio <= 0.55
    
    def test_funding_bias_affects_assignment(self):
        """Large funding difference should bias assignment."""
        randomizer = CryptoRandomizer()
        
        # Large positive funding on Extended (should bias toward short on Extended)
        extended_short_count = 0
        total = 1000
        
        for _ in range(total):
            assignments = randomizer.assign_exchange_sides_with_bias(
                extended_funding=0.001,  # High positive (shorts collect)
                tradexyz_funding=-0.0001,  # Negative
            )
            if assignments[0][1] == PositionSide.SHORT:
                extended_short_count += 1
        
        # Should be biased toward short on Extended (expect >60%)
        ratio = extended_short_count / total
        assert ratio > 0.60
    
    def test_cycle_params_immutable(self):
        """RandomParams should be immutable."""
        randomizer = CryptoRandomizer()
        params = randomizer.generate_cycle_params()
        
        with pytest.raises(Exception):
            params.token = "NEW_TOKEN"  # type: ignore


class TestFundingAnalyzer:
    """Tests for FundingAnalyzer."""
    
    def test_bias_strength_small(self):
        """Small rate difference should give small bias."""
        analyzer = FundingAnalyzer()
        
        result = analyzer.analyze(
            extended_rate=0.0001,
            tradexyz_rate=0.0001,
            token="BTC",
        )
        
        assert result.bias_strength in (FundingBias.NONE, FundingBias.SMALL)
    
    def test_bias_strength_large(self):
        """Large rate difference should give large bias."""
        analyzer = FundingAnalyzer()
        
        result = analyzer.analyze(
            extended_rate=0.001,
            tradexyz_rate=-0.001,
            token="BTC",
        )
        
        assert result.bias_strength == FundingBias.LARGE
    
    def test_recommendation_favors_short_on_high_positive(self):
        """Should recommend short on exchange with higher positive funding."""
        analyzer = FundingAnalyzer()
        
        result = analyzer.analyze(
            extended_rate=0.001,  # High positive
            tradexyz_rate=0.0001,  # Low positive
            token="BTC",
        )
        
        assert result.recommended_short_exchange == ExchangeName.EXTENDED
    
    def test_recommendation_favors_long_on_negative(self):
        """Should recommend long on exchange with more negative funding."""
        analyzer = FundingAnalyzer()
        
        result = analyzer.analyze(
            extended_rate=-0.001,  # Negative
            tradexyz_rate=0.0001,  # Positive
            token="BTC",
        )
        
        assert result.recommended_long_exchange == ExchangeName.EXTENDED


class TestPositionSizer:
    """Tests for PositionSizer."""
    
    def test_size_based_on_minimum_balance(self):
        """Should size based on minimum available balance."""
        sizer = PositionSizer()
        
        # Extended has more balance
        extended_balance = BalanceInfo(
            available=10000,
            equity=10000,
            margin_used=0,
        )
        
        # TradeXYZ has less balance
        tradexyz_balance = BalanceInfo(
            available=5000,
            equity=5000,
            margin_used=0,
        )
        
        result = sizer.calculate_size(
            token="BTC",
            token_price=50000,
            extended_balance=extended_balance,
            tradexyz_balance=tradexyz_balance,
            equity_usage=0.5,
            leverage=10,
        )
        
        # Should be based on TradeXYZ's 5000, not Extended's 10000
        # 5000 * 0.5 * 10 = 25000 max position value
        assert result.position_value_usd <= 25000 * 0.95  # With safety buffer
    
    def test_insufficient_balance_returns_zero(self):
        """Should return zero size when balance insufficient."""
        sizer = PositionSizer(min_position_usd=100)
        
        extended_balance = BalanceInfo(
            available=0,
            equity=0,
            margin_used=0,
        )
        
        tradexyz_balance = BalanceInfo(
            available=1000,
            equity=1000,
            margin_used=0,
        )
        
        result = sizer.calculate_size(
            token="BTC",
            token_price=50000,
            extended_balance=extended_balance,
            tradexyz_balance=tradexyz_balance,
            equity_usage=0.5,
            leverage=10,
        )
        
        assert result.position_size == 0
        assert not result.fits_constraints
    
    def test_respects_max_position_limit(self):
        """Should cap position at maximum value."""
        sizer = PositionSizer(max_position_usd=10000)
        
        balance = BalanceInfo(
            available=100000,
            equity=100000,
            margin_used=0,
        )
        
        result = sizer.calculate_size(
            token="BTC",
            token_price=50000,
            extended_balance=balance,
            tradexyz_balance=balance,
            equity_usage=0.8,
            leverage=20,
        )
        
        # Would calculate to 100000 * 0.8 * 20 = 1,600,000
        # Should be capped at 10,000
        assert result.position_value_usd <= 10000


class TestRiskValidator:
    """Tests for RiskValidator."""
    
    def test_passes_when_all_checks_pass(self):
        """Should pass when all risk checks are satisfied."""
        validator = RiskValidator(
            min_balance_required=100,
            max_position_value=100000,
        )
        
        sizing = SizingResult(
            token="BTC",
            position_size=0.1,
            position_value_usd=5000,
            margin_required_per_leg=500,
            total_margin_required=1000,
            equity_usage=0.5,
            leverage=10,
            effective_leverage=10,
            available_balance_used=500,
            fits_constraints=True,
            constraint_notes=[],
        )
        
        ext_balance = BalanceInfo(available=10000, equity=10000, margin_used=0)
        xyz_balance = BalanceInfo(available=10000, equity=10000, margin_used=0)
        
        result = validator.validate_pre_trade(
            sizing=sizing,
            extended_balance=ext_balance,
            tradexyz_balance=xyz_balance,
            current_price=50000,
        )
        
        assert result.overall_passed
        assert result.can_proceed
    
    def test_fails_on_insufficient_balance(self):
        """Should fail when balance below minimum."""
        validator = RiskValidator(min_balance_required=1000)
        
        sizing = SizingResult(
            token="BTC",
            position_size=0.1,
            position_value_usd=5000,
            margin_required_per_leg=500,
            total_margin_required=1000,
            equity_usage=0.5,
            leverage=10,
            effective_leverage=10,
            available_balance_used=500,
            fits_constraints=True,
            constraint_notes=[],
        )
        
        ext_balance = BalanceInfo(available=500, equity=500, margin_used=0)  # Below min
        xyz_balance = BalanceInfo(available=10000, equity=10000, margin_used=0)
        
        result = validator.validate_pre_trade(
            sizing=sizing,
            extended_balance=ext_balance,
            tradexyz_balance=xyz_balance,
            current_price=50000,
        )
        
        assert not result.overall_passed
        assert result.overall_risk_level == RiskLevel.CRITICAL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
