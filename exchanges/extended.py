"""Extended Exchange implementation."""

import asyncio
from typing import Any, Dict, List, Optional

import httpx

from config.constants import (
    ExchangeName,
    PositionSide,
    OrderType,
    OrderStatus,
    TimeInForce,
    EXTENDED_MARKETS,
)
from config.settings import ExtendedSettings
from utils.logging import get_logger
from utils.timing import get_current_timestamp, get_expiration_timestamp
from utils.retry import exchange_retry
from core.randomizer import CryptoRandomizer

from .base import (
    BaseExchange,
    MarketInfo,
    OrderInfo,
    PositionInfo,
    TradeResult,
    BalanceResult,
)


logger = get_logger(__name__)


class ExtendedExchange(BaseExchange):
    """Extended Exchange API implementation."""

    def __init__(
        self,
        settings: ExtendedSettings,
        simulation: bool = True,
    ):
        super().__init__(ExchangeName.EXTENDED, simulation)

        self._settings = settings
        self._base_url = settings.base_url
        # Keep as SecretStr - only extract at point of use
        self._api_key = settings.api_key
        self._stark_private_key = settings.stark_private_key
        self._l2_key = settings.l2_key
        self._vault = settings.vault
        self._account_id = settings.account_id

        self._client: Optional[httpx.AsyncClient] = None
        self._market_cache: Dict[str, MarketInfo] = {}
        self._cache_timestamp: int = 0
        self._cache_ttl: int = 5000

    def __repr__(self) -> str:
        """Safe representation that hides sensitive data."""
        return (
            f"ExtendedExchange("
            f"account_id={self._account_id}, "
            f"simulation={self._simulation}, "
            f"connected={self._connected})"
        )

    async def connect(self) -> bool:
        try:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "X-Api-Key": self._api_key.get_secret_value(),
                    "User-Agent": "DeltaNeutralBot/1.0",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
            
            response = await self._client.get("/api/v1/user/account/info")
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "OK":
                    logger.info("Connected to Extended Exchange", account_id=self._account_id)
                    self._connected = True
                    return True
            
            logger.error("Failed to connect to Extended", status=response.status_code)
            return False
            
        except Exception as e:
            logger.error("Extended connection error", error=str(e))
            return False

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        logger.info("Disconnected from Extended Exchange")

    @exchange_retry
    async def get_market_info(self, symbol: str) -> MarketInfo:
        market_symbol = self.get_market_symbol(symbol) if "-" not in symbol else symbol
        
        now = get_current_timestamp()
        if market_symbol in self._market_cache and (now - self._cache_timestamp) < self._cache_ttl:
            return self._market_cache[market_symbol]
        
        response = await self._request("GET", f"/api/v1/info/markets?market={market_symbol}")
        
        if response.get("status") != "OK" or not response.get("data"):
            raise ValueError(f"Failed to get market info for {market_symbol}")
        
        market_data = response["data"][0]
        stats = market_data.get("marketStats", {})
        config = market_data.get("tradingConfig", {})
        
        # Convert all numeric fields properly (API returns strings)
        info = MarketInfo(
            symbol=market_data["name"],
            base_asset=market_data["assetName"],
            quote_asset=market_data["collateralAssetName"],
            mark_price=float(stats.get("markPrice", 0)),
            index_price=float(stats.get("indexPrice", 0)),
            last_price=float(stats.get("lastPrice", 0)),
            bid_price=float(stats.get("bidPrice", 0)),
            ask_price=float(stats.get("askPrice", 0)),
            funding_rate=float(stats.get("fundingRate", 0)),
            next_funding_time=int(stats.get("nextFundingRate", 0)),
            min_order_size=float(config.get("minOrderSize", 0.001)),
            min_order_size_change=float(config.get("minOrderSizeChange", 0.001)),
            min_price_change=float(config.get("minPriceChange", 0.001)),
            max_leverage=int(float(config.get("maxLeverage", 50))),  # FIX: Convert string "50.00" -> float -> int
            is_active=market_data.get("active", False),
            status=market_data.get("status", "UNKNOWN"),
        )
        
        self._market_cache[market_symbol] = info
        self._cache_timestamp = now
        
        return info

    async def get_funding_rate(self, symbol: str) -> float:
        market_info = await self.get_market_info(symbol)
        return market_info.funding_rate

    async def get_mark_price(self, symbol: str) -> float:
        market_info = await self.get_market_info(symbol)
        return market_info.mark_price

    @exchange_retry
    async def get_balance(self) -> BalanceResult:
        response = await self._request("GET", "/api/v1/user/balance")
        
        if response.get("status") != "OK":
            raise ValueError("Failed to get balance from Extended")
        
        data = response.get("data", {})
        
        return BalanceResult(
            exchange=ExchangeName.EXTENDED,
            balance=float(data.get("balance", 0)),
            equity=float(data.get("equity", 0)),
            available_for_trade=float(data.get("availableForTrade", 0)),
            available_for_withdrawal=float(data.get("availableForWithdrawal", 0)),
            unrealized_pnl=float(data.get("unrealisedPnl", 0)),
            initial_margin=float(data.get("initialMargin", 0)),
            margin_ratio=float(data.get("marginRatio", 0)) if data.get("marginRatio") else None,
            exposure=float(data.get("exposure", 0)),
            leverage=float(data.get("leverage", 0)),
            currency=data.get("collateralName", "USD"),
            updated_time=int(data.get("updatedTime", 0)),
        )

    @exchange_retry
    async def get_positions(self, symbol: Optional[str] = None) -> List[PositionInfo]:
        url = "/api/v1/user/positions"
        if symbol:
            market_symbol = self.get_market_symbol(symbol) if "-" not in symbol else symbol
            url += f"?market={market_symbol}"
        
        response = await self._request("GET", url)
        
        if response.get("status") != "OK":
            return []
        
        positions = []
        for pos in response.get("data", []):
            positions.append(PositionInfo(
                position_id=str(pos.get("id", "")),
                exchange=ExchangeName.EXTENDED,
                symbol=pos.get("market", ""),
                side=PositionSide(pos.get("side", "LONG")),
                size=float(pos.get("size", 0)),
                value=float(pos.get("value", 0)),
                entry_price=float(pos.get("openPrice", 0)),
                mark_price=float(pos.get("markPrice", 0)),
                liquidation_price=float(pos.get("liquidationPrice", 0)) if pos.get("liquidationPrice") else None,
                unrealized_pnl=float(pos.get("unrealisedPnl", 0)),
                realized_pnl=float(pos.get("realisedPnl", 0)),
                leverage=int(float(pos.get("leverage", 1))),
                margin=float(pos.get("margin", 0)),
                created_time=int(pos.get("createdTime", 0)),
                updated_time=int(pos.get("updatedTime", 0)),
                raw_data=pos,
            ))
        
        return positions

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderInfo]:
        url = "/api/v1/user/orders"
        if symbol:
            market_symbol = self.get_market_symbol(symbol) if "-" not in symbol else symbol
            url += f"?market={market_symbol}"
        
        response = await self._request("GET", url)
        
        if response.get("status") != "OK":
            return []
        
        orders = []
        for order in response.get("data", []):
            orders.append(self._parse_order(order))
        
        return orders

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
        if self._simulation:
            logger.info(
                "SIMULATION: Would place order on Extended",
                symbol=symbol,
                side=side.value,
                quantity=quantity,
                order_type=order_type.value,
            )
            return TradeResult(
                success=True,
                order_id=f"sim_{CryptoRandomizer.generate_external_id()}",
                external_id=external_id,
                error_message=None,
                error_code=None,
            )
        
        # Real order placement would go here
        return TradeResult(
            success=False,
            order_id=None,
            external_id=external_id,
            error_message="Live trading not implemented",
            error_code="NOT_IMPLEMENTED",
        )

    async def cancel_order(self, order_id: str) -> bool:
        if self._simulation:
            logger.info("SIMULATION: Would cancel order", order_id=order_id)
            return True
        return False

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        if self._simulation:
            logger.info("SIMULATION: Would cancel all orders", symbol=symbol)
            return 0
        return 0

    async def close_position(self, symbol: str, quantity: Optional[float] = None) -> TradeResult:
        if self._simulation:
            logger.info("SIMULATION: Would close position", symbol=symbol)
            return TradeResult(
                success=True,
                order_id=None,
                external_id=None,
                error_message=None,
                error_code=None,
            )
        return TradeResult(
            success=False,
            order_id=None,
            external_id=None,
            error_message="Live trading not implemented",
            error_code="NOT_IMPLEMENTED",
        )

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        if self._simulation:
            logger.info("SIMULATION: Would set leverage", symbol=symbol, leverage=leverage)
            return True
        return False

    async def get_leverage(self, symbol: str) -> int:
        market_symbol = self.get_market_symbol(symbol) if "-" not in symbol else symbol
        response = await self._request("GET", f"/api/v1/user/leverage?market={market_symbol}")
        
        if response.get("status") == "OK" and response.get("data"):
            return int(float(response["data"][0].get("leverage", 1)))
        return 1

    def get_market_symbol(self, token: str) -> str:
        return EXTENDED_MARKETS.get(token.upper(), f"{token.upper()}-USD")

    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        if not self._client:
            raise RuntimeError("Not connected to Extended")

        # Apply rate limiting
        await self._rate_limiter.acquire()

        try:
            response = await self._client.request(method, endpoint, **kwargs)
            return response.json()
        except Exception as e:
            logger.error("Extended API request failed", endpoint=endpoint, error=str(e))
            return {"status": "ERROR", "error": {"message": str(e)}}

    def _parse_order(self, data: Dict[str, Any]) -> OrderInfo:
        status_map = {
            "NEW": OrderStatus.NEW,
            "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
            "FILLED": OrderStatus.FILLED,
            "CANCELLED": OrderStatus.CANCELLED,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.EXPIRED,
        }
        
        side_str = data.get("side", "BUY")
        side = PositionSide.LONG if side_str == "BUY" else PositionSide.SHORT
        
        qty = float(data.get("qty", 0))
        filled = float(data.get("filledQty", 0))
        
        return OrderInfo(
            order_id=str(data.get("id", "")),
            external_id=data.get("externalId"),
            exchange=ExchangeName.EXTENDED,
            symbol=data.get("market", ""),
            side=side,
            order_type=OrderType.LIMIT,
            status=status_map.get(data.get("status", ""), OrderStatus.NEW),
            quantity=qty,
            filled_quantity=filled,
            remaining_quantity=qty - filled,
            price=float(data.get("price", 0)) if data.get("price") else None,
            average_price=float(data.get("averagePrice", 0)) if data.get("averagePrice") else None,
            fee_paid=float(data.get("payedFee", 0)),
            created_time=int(data.get("createdTime", 0)),
            updated_time=int(data.get("updatedTime", 0)),
            reduce_only=data.get("reduceOnly", False),
            post_only=data.get("postOnly", False),
            raw_data=data,
        )
