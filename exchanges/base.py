"""Abstract base class for exchange implementations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable, TypeVar, Awaitable
from enum import Enum

from config.constants import (
    ExchangeName,
    PositionSide,
    OrderType,
    OrderStatus,
    TimeInForce,
)
from utils.timing import RateLimiter

# Type variable for generic async functions
T = TypeVar("T")


@dataclass
class MarketInfo:
    """
    Market/trading pair information.
    
    Provides essential market parameters needed for order placement.
    """
    symbol: str
    base_asset: str
    quote_asset: str
    
    # Price info
    mark_price: float
    index_price: float
    last_price: float
    bid_price: float
    ask_price: float
    
    # Funding
    funding_rate: float
    next_funding_time: int
    
    # Trading config
    min_order_size: float
    min_order_size_change: float
    min_price_change: float
    max_leverage: int
    
    # Status
    is_active: bool
    status: str


@dataclass
class OrderInfo:
    """
    Order information.
    
    Represents an order at any stage of its lifecycle.
    """
    order_id: str
    external_id: Optional[str]
    exchange: ExchangeName
    
    symbol: str
    side: PositionSide
    order_type: OrderType
    status: OrderStatus
    
    # Quantities
    quantity: float
    filled_quantity: float
    remaining_quantity: float
    
    # Prices
    price: Optional[float]
    average_price: Optional[float]
    
    # Fees
    fee_paid: float
    
    # Timing
    created_time: int
    updated_time: int
    
    # Additional
    reduce_only: bool = False
    post_only: bool = False
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionInfo:
    """
    Position information.
    
    Represents an open position on an exchange.
    """
    position_id: str
    exchange: ExchangeName
    
    symbol: str
    side: PositionSide
    
    # Size and value
    size: float
    value: float
    
    # Prices
    entry_price: float
    mark_price: float
    liquidation_price: Optional[float]
    
    # P&L
    unrealized_pnl: float
    realized_pnl: float
    
    # Margin
    leverage: int
    margin: float
    
    # Timing
    created_time: int
    updated_time: int
    
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeResult:
    """
    Result of a trade execution.
    
    Returned after placing an order.
    """
    success: bool
    order_id: Optional[str]
    external_id: Optional[str]
    error_message: Optional[str]
    error_code: Optional[str]
    
    # Fill info (may be partial or zero for async APIs)
    filled_quantity: float = 0.0
    average_price: float = 0.0
    fee_paid: float = 0.0
    
    raw_response: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BalanceResult:
    """Exchange balance information."""
    exchange: ExchangeName
    
    # Core balances
    balance: float  # Account balance
    equity: float  # Balance + unrealized P&L
    available_for_trade: float
    available_for_withdrawal: float
    
    # Margin info
    unrealized_pnl: float
    initial_margin: float
    margin_ratio: Optional[float]
    
    # Position info
    exposure: float
    leverage: float
    
    currency: str = "USD"
    updated_time: int = 0


class BaseExchange(ABC):
    """
    Abstract base class for exchange implementations.

    Defines the common interface that all exchange adapters must implement.
    This allows the trading logic to be exchange-agnostic.
    """

    def __init__(
        self,
        exchange_name: ExchangeName,
        simulation: bool = True,
        requests_per_minute: int = 600,
    ):
        """
        Initialize exchange adapter.

        Args:
            exchange_name: Exchange identifier
            simulation: If True, don't execute real trades
            requests_per_minute: Rate limit for API calls
        """
        self._name = exchange_name
        self._simulation = simulation
        self._connected = False
        self._rate_limiter = RateLimiter(requests_per_minute=requests_per_minute)
    
    @property
    def name(self) -> ExchangeName:
        """Get exchange name."""
        return self._name
    
    @property
    def is_simulation(self) -> bool:
        """Check if running in simulation mode."""
        return self._simulation
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to exchange."""
        return self._connected
    
    # =========================================================================
    # Connection Management
    # =========================================================================
    
    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to exchange.
        
        Returns:
            True if connection successful
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from exchange."""
        pass
    
    # =========================================================================
    # Market Data
    # =========================================================================
    
    @abstractmethod
    async def get_market_info(self, symbol: str) -> MarketInfo:
        """
        Get market information for a trading pair.
        
        Args:
            symbol: Market symbol (e.g., "BTC-USD" or "BTC")
            
        Returns:
            MarketInfo with current market data
        """
        pass
    
    @abstractmethod
    async def get_funding_rate(self, symbol: str) -> float:
        """
        Get current funding rate for a market.
        
        Args:
            symbol: Market symbol
            
        Returns:
            Current funding rate as decimal
        """
        pass
    
    @abstractmethod
    async def get_mark_price(self, symbol: str) -> float:
        """
        Get current mark price.
        
        Args:
            symbol: Market symbol
            
        Returns:
            Current mark price
        """
        pass
    
    # =========================================================================
    # Account Data
    # =========================================================================
    
    @abstractmethod
    async def get_balance(self) -> BalanceResult:
        """
        Get account balance information.
        
        Returns:
            BalanceResult with current balances
        """
        pass
    
    @abstractmethod
    async def get_positions(self, symbol: Optional[str] = None) -> List[PositionInfo]:
        """
        Get open positions.
        
        Args:
            symbol: Optional filter by symbol
            
        Returns:
            List of open positions
        """
        pass
    
    @abstractmethod
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderInfo]:
        """
        Get open orders.
        
        Args:
            symbol: Optional filter by symbol
            
        Returns:
            List of open orders
        """
        pass
    
    # =========================================================================
    # Order Management
    # =========================================================================
    
    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: PositionSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        leverage: Optional[int] = None,
        reduce_only: bool = False,
        post_only: bool = False,
        time_in_force: TimeInForce = TimeInForce.IOC,
        external_id: Optional[str] = None,
    ) -> TradeResult:
        """
        Place an order.
        
        Args:
            symbol: Market symbol
            side: LONG or SHORT
            quantity: Order quantity in base asset
            order_type: MARKET or LIMIT
            price: Limit price (required for LIMIT orders)
            leverage: Position leverage (uses current if not specified)
            reduce_only: If True, only reduces existing position
            post_only: If True, order must be maker
            time_in_force: Order time in force
            external_id: Optional client order ID
            
        Returns:
            TradeResult with execution details
        """
        pass
    
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if cancellation successful
        """
        pass
    
    @abstractmethod
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """
        Cancel all open orders.
        
        Args:
            symbol: Optional filter by symbol
            
        Returns:
            Number of orders cancelled
        """
        pass
    
    # =========================================================================
    # Position Management
    # =========================================================================
    
    @abstractmethod
    async def close_position(
        self,
        symbol: str,
        quantity: Optional[float] = None,
    ) -> TradeResult:
        """
        Close a position.
        
        Args:
            symbol: Market symbol
            quantity: Quantity to close (closes full position if not specified)
            
        Returns:
            TradeResult with execution details
        """
        pass
    
    @abstractmethod
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """
        Set leverage for a market.
        
        Args:
            symbol: Market symbol
            leverage: Desired leverage
            
        Returns:
            True if successful
        """
        pass
    
    @abstractmethod
    async def get_leverage(self, symbol: str) -> int:
        """
        Get current leverage for a market.
        
        Args:
            symbol: Market symbol
            
        Returns:
            Current leverage multiplier
        """
        pass
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    @abstractmethod
    def get_market_symbol(self, token: str) -> str:
        """
        Convert token to exchange-specific market symbol.
        
        Args:
            token: Token symbol (e.g., "BTC")
            
        Returns:
            Exchange market symbol (e.g., "BTC-USD" or "BTC")
        """
        pass
    
    async def get_order_status(self, order_id: str) -> Optional[OrderInfo]:
        """
        Get status of a specific order.

        Args:
            order_id: Order ID to check

        Returns:
            OrderInfo if found, None otherwise
        """
        # Default implementation - subclasses may override
        orders = await self.get_open_orders()
        for order in orders:
            if order.order_id == order_id:
                return order
        return None

    async def _rate_limited_call(
        self,
        func: Callable[..., Awaitable[T]],
        *args,
        **kwargs,
    ) -> T:
        """
        Execute an async function with rate limiting.

        Acquires a rate limit token before executing the function.
        Use this wrapper for all API calls that count against rate limits.

        Args:
            func: Async function to call
            *args: Positional arguments to pass to func
            **kwargs: Keyword arguments to pass to func

        Returns:
            Result of the function call
        """
        await self._rate_limiter.acquire()
        return await func(*args, **kwargs)
