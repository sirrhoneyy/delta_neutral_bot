"""Trading constants and enumerations."""

from enum import Enum
from typing import Final


# =============================================================================
# SUPPORTED TOKENS
# =============================================================================
SUPPORTED_TOKENS: Final[list[str]] = ["BTC", "ETH", "SOL", "HYPE"]

# Token to market symbol mappings
EXTENDED_MARKETS: Final[dict[str, str]] = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "HYPE": "HYPE-USD",
}

TRADEXYZ_MARKETS: Final[dict[str, str]] = {
    "BTC": "BTC",
    "ETH": "ETH",
    "SOL": "SOL",
    "HYPE": "HYPE",
}


# =============================================================================
# ENUMERATIONS
# =============================================================================
class ExchangeName(str, Enum):
    """Supported exchanges."""
    EXTENDED = "extended"
    TRADEXYZ = "tradexyz"


class PositionSide(str, Enum):
    """Position direction."""
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(str, Enum):
    """Order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    CONDITIONAL = "CONDITIONAL"


class TimeInForce(str, Enum):
    """Time in force options."""
    GTC = "GTC"      # Good Till Cancel
    GTT = "GTT"      # Good Till Time
    IOC = "IOC"      # Immediate or Cancel
    FOK = "FOK"      # Fill or Kill


class OrderStatus(str, Enum):
    """Order execution status."""
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNTRIGGERED = "UNTRIGGERED"
    TRIGGERED = "TRIGGERED"
    PENDING = "PENDING"


class CycleState(str, Enum):
    """Trading cycle states."""
    IDLE = "IDLE"
    OPENING = "OPENING"
    HOLDING = "HOLDING"
    CLOSING = "CLOSING"
    COOLDOWN = "COOLDOWN"
    ERROR = "ERROR"
    EMERGENCY = "EMERGENCY"


# =============================================================================
# FUNDING RATE BIAS THRESHOLDS
# =============================================================================
# Funding rate difference thresholds for probabilistic bias
FUNDING_BIAS_THRESHOLDS: Final[dict[str, tuple[float, float]]] = {
    "SMALL": (0.0, 0.0001),       # < 0.01% difference -> ~50/50
    "MODERATE": (0.0001, 0.0005),  # 0.01% - 0.05% -> ~60/40
    "LARGE": (0.0005, float("inf")),  # > 0.05% -> ~75/25
}

# Corresponding probability weights (favorable exchange : other exchange)
FUNDING_BIAS_WEIGHTS: Final[dict[str, tuple[float, float]]] = {
    "SMALL": (0.50, 0.50),     # Near random
    "MODERATE": (0.60, 0.40),  # Mild bias
    "LARGE": (0.75, 0.25),     # Strong bias
}


# =============================================================================
# TRADING PARAMETERS (Defaults - can be overridden by env)
# =============================================================================
class DefaultParams:
    """Default trading parameters."""

    # Position sizing
    MIN_EQUITY_USAGE: float = 0.40   # 40% minimum
    MAX_EQUITY_USAGE: float = 0.80   # 80% maximum

    # Leverage
    MIN_LEVERAGE: int = 10
    MAX_LEVERAGE: int = 20

    # Timing (seconds)
    MIN_HOLD_DURATION: int = 1200    # 20 minutes
    MAX_HOLD_DURATION: int = 7200    # 2 hours
    MIN_COOLDOWN: int = 600          # 10 minutes
    MAX_COOLDOWN: int = 3600         # 60 minutes

    # Safety limits
    MAX_POSITION_VALUE_USD: float = 100_000.0
    MIN_BALANCE_USD: float = 100.0
    MAX_CONSECUTIVE_FAILURES: int = 3
    MAX_SLIPPAGE_PERCENT: float = 0.5

    # API timeouts (seconds)
    API_TIMEOUT: int = 30
    ORDER_TIMEOUT: int = 60
    WS_RECONNECT_ATTEMPTS: int = 5


class InternalParams:
    """Internal algorithm parameters (not user-configurable)."""

    # Position sizing applies 95% of calculated size for safety margin
    SAFETY_BUFFER: float = 0.95

    # Randomization uses 1000 discrete steps for sub-percent precision
    RANDOMIZATION_STEPS: int = 1000

    # Position size imbalance tolerance (1% difference allowed)
    SIZE_IMBALANCE_TOLERANCE: float = 0.01

    # Safety check interval during hold phase (seconds)
    SAFETY_CHECK_INTERVAL_SECONDS: int = 30

    # Funding interval for estimation (8 hours in seconds)
    FUNDING_INTERVAL_SECONDS: int = 28800


# =============================================================================
# API ENDPOINTS
# =============================================================================
class ExtendedEndpoints:
    """Extended Exchange API endpoints."""
    
    MAINNET_BASE = "https://api.starknet.extended.exchange"
    TESTNET_BASE = "https://api.starknet.sepolia.extended.exchange"
    
    MAINNET_WS = "wss://api.starknet.extended.exchange/stream.extended.exchange/v1"
    TESTNET_WS = "wss://starknet.sepolia.extended.exchange/stream.extended.exchange/v1"
    
    # API paths
    MARKETS = "/api/v1/info/markets"
    MARKET_STATS = "/api/v1/info/markets/{market}/stats"
    ORDERBOOK = "/api/v1/info/markets/{market}/orderbook"
    FUNDING = "/api/v1/info/{market}/funding"
    
    BALANCE = "/api/v1/user/balance"
    POSITIONS = "/api/v1/user/positions"
    ORDERS = "/api/v1/user/orders"
    ORDER = "/api/v1/user/order"
    LEVERAGE = "/api/v1/user/leverage"
    FEES = "/api/v1/user/fees"


class TradeXYZEndpoints:
    """TradeXYZ (Hyperliquid) API endpoints."""
    
    MAINNET_BASE = "https://api.hyperliquid.xyz"
    TESTNET_BASE = "https://api.hyperliquid-testnet.xyz"
    
    # API paths (Hyperliquid uses POST with action types)
    INFO = "/info"
    EXCHANGE = "/exchange"


# =============================================================================
# STARKNET CONSTANTS (for Extended signing)
# =============================================================================
class StarknetConstants:
    """Starknet-related constants for Extended."""
    
    MAINNET_CHAIN_ID = "SN_MAIN"
    TESTNET_CHAIN_ID = "SN_SEPOLIA"
    
    DOMAIN_NAME = "Perpetuals"
    DOMAIN_VERSION = "v0"
    DOMAIN_REVISION = "1"
    
    COLLATERAL_DECIMALS = 6  # USDC has 6 decimals
    COLLATERAL_ASSET_ID = "0x1"
