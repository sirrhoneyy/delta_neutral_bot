"""TradeXYZ (Hyperliquid) Exchange implementation."""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional
from decimal import Decimal

import httpx
from eth_account import Account
import eth_utils
from hyperliquid.utils.signing import sign_l1_action, get_timestamp_ms

from config.constants import (
    ExchangeName,
    PositionSide,
    OrderType,
    OrderStatus,
    TimeInForce,
    TRADEXYZ_MARKETS,
)
from config.settings import TradeXYZSettings
from utils.logging import get_logger
from utils.timing import get_current_timestamp
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


class TradeXYZExchange(BaseExchange):
    """
    TradeXYZ (Hyperliquid) Exchange API implementation.
    
    TradeXYZ uses Hyperliquid's API infrastructure. This implementation
    wraps the Hyperliquid API with the standard BaseExchange interface.
    
    Key Features:
    - EIP-712 signing for order management
    - REST API with POST-based actions
    - WebSocket support for real-time updates
    """
    
    def __init__(
        self,
        settings: TradeXYZSettings,
        simulation: bool = True,
    ):
        """
        Initialize TradeXYZ exchange adapter.

        Args:
            settings: TradeXYZ-specific settings
            simulation: If True, don't execute real trades
        """
        super().__init__(ExchangeName.TRADEXYZ, simulation)

        self._settings = settings
        self._base_url = settings.base_url
        self._wallet_address = settings.wallet_address
        # Main wallet for balance/position queries (your actual Hyperliquid account)
        self._balance_wallet = settings.balance_wallet
        # Keep as SecretStr - only extract at point of use
        self._api_secret = settings.api_secret

        # HTTP client
        self._client: Optional[httpx.AsyncClient] = None

        # Account instance for signing
        self._account: Optional[Account] = None

        # Market metadata cache
        self._meta_cache: Dict[str, Any] = {}
        self._asset_index_map: Dict[str, int] = {}
        self._cache_timestamp: int = 0
        self._cache_ttl: int = 60000  # 60 seconds

        # Network configuration (mainnet vs testnet)
        self._is_mainnet = "mainnet" in self._base_url or "hyperliquid.xyz" in self._base_url

    def __repr__(self) -> str:
        """Safe representation that hides sensitive data."""
        wallet_preview = self._wallet_address[:10] + "..." if self._wallet_address else "None"
        return (
            f"TradeXYZExchange("
            f"wallet={wallet_preview}, "
            f"simulation={self._simulation}, "
            f"connected={self._connected})"
        )
    
    # =========================================================================
    # Connection Management
    # =========================================================================
    
    async def connect(self) -> bool:
        """Establish connection to TradeXYZ/Hyperliquid."""
        try:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
            
            # Initialize account for signing - extract secret at point of use
            self._account = Account.from_key(self._api_secret.get_secret_value())

            derived_address = eth_utils.to_checksum_address(self._account.address)
            configured_address = eth_utils.to_checksum_address(self._wallet_address)

            logger.warning(
                "TRADEXYZ SIGNING CHECK",
                configured_wallet=configured_address,
                derived_wallet=derived_address,
                match=(configured_address == derived_address),
            )
            
            logger.warning(
                "TRADEXYZ API WALLET",
                main_wallet=configured_address,
                api_wallet=derived_address,
            )


            # Verify connection by fetching meta
            await self._refresh_meta()
            
            logger.info(
                "Connected to TradeXYZ (Hyperliquid)",
                wallet=self._wallet_address[:10] + "..."
            )
            self._connected = True
            return True
            
        except Exception as e:
            logger.error("TradeXYZ connection error", error=str(e))
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from TradeXYZ."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        self._account = None
        logger.info("Disconnected from TradeXYZ")
    
    async def _refresh_meta(self) -> None:
        """Refresh market metadata from API."""
        response = await self._info_request({"type": "meta"})
        
        if response and "universe" in response:
            self._meta_cache = response
            self._asset_index_map = {
                asset["name"]: idx
                for idx, asset in enumerate(response["universe"])
            }
            self._cache_timestamp = get_current_timestamp()
    
    # =========================================================================
    # Market Data
    # =========================================================================
    
    @exchange_retry
    async def get_market_info(self, symbol: str) -> MarketInfo:
        """Get market information for a trading pair."""
        asset = self.get_market_symbol(symbol)
        
        # Ensure we have fresh meta
        now = get_current_timestamp()
        if not self._meta_cache or (now - self._cache_timestamp) > self._cache_ttl:
            await self._refresh_meta()
        
        # Get asset info from meta
        asset_idx = self._asset_index_map.get(asset)
        if asset_idx is None:
            raise ValueError(f"Unknown asset: {asset}")
        
        asset_info = self._meta_cache["universe"][asset_idx]
        
        # Get current market data
        all_mids = await self._info_request({"type": "allMids"})
        mid_price = float(all_mids.get(asset, 0)) if all_mids else 0
        
        # Get funding info
        funding_response = await self._info_request({
            "type": "metaAndAssetCtxs"
        })
        
        funding_rate = 0.0
        next_funding = 0
        if funding_response and len(funding_response) > 1:
            asset_ctxs = funding_response[1]
            if asset_idx < len(asset_ctxs):
                ctx = asset_ctxs[asset_idx]
                funding_rate = float(ctx.get("funding", 0))
        
        return MarketInfo(
            symbol=asset,
            base_asset=asset,
            quote_asset="USD",
            mark_price=mid_price,
            index_price=mid_price,  # Hyperliquid uses same
            last_price=mid_price,
            bid_price=mid_price * 0.999,  # Approximate
            ask_price=mid_price * 1.001,
            funding_rate=funding_rate,
            next_funding_time=next_funding,
            min_order_size=float(asset_info.get("szDecimals", 3)) ** -1,
            min_order_size_change=10 ** -int(asset_info.get("szDecimals", 3)),
            min_price_change=10 ** -int(asset_info.get("pxDecimals", 2)),
            max_leverage=int(asset_info.get("maxLeverage", 50)),
            is_active=True,
            status="ACTIVE",
        )
    
    async def get_funding_rate(self, symbol: str) -> float:
        """Get current funding rate."""
        market_info = await self.get_market_info(symbol)
        return market_info.funding_rate
    
    async def get_mark_price(self, symbol: str) -> float:
        """Get current mark price."""
        asset = self.get_market_symbol(symbol)
        all_mids = await self._info_request({"type": "allMids"})
        return float(all_mids.get(asset, 0)) if all_mids else 0
    
    # =========================================================================
    # Account Data
    # =========================================================================
    
    @exchange_retry
    async def get_balance(self) -> BalanceResult:
        """Get account balance information."""
        response = await self._info_request({
            "type": "clearinghouseState",
            "user": self._balance_wallet,  # Use main wallet for balance queries
        })
        
        if not response:
            raise ValueError("Failed to get balance from TradeXYZ")
        
        margin_summary = response.get("marginSummary", {})
        
        return BalanceResult(
            exchange=ExchangeName.TRADEXYZ,
            balance=float(margin_summary.get("accountValue", 0)),
            equity=float(margin_summary.get("accountValue", 0)),
            available_for_trade=float(margin_summary.get("totalRawUsd", 0)),
            available_for_withdrawal=float(response.get("withdrawable", 0)),
            unrealized_pnl=float(margin_summary.get("totalNtlPos", 0)) - float(margin_summary.get("accountValue", 0)),
            initial_margin=float(margin_summary.get("totalMarginUsed", 0)),
            margin_ratio=None,
            exposure=float(margin_summary.get("totalNtlPos", 0)),
            leverage=0,  # Calculated per position
            currency="USD",
            updated_time=get_current_timestamp(),
        )
    
    @exchange_retry
    async def get_positions(self, symbol: Optional[str] = None) -> List[PositionInfo]:
        """Get open positions."""
        response = await self._info_request({
            "type": "clearinghouseState",
            "user": self._balance_wallet,  # Use main wallet for position queries
        })

        if not response:
            return []

        positions = []
        asset_positions = response.get("assetPositions", [])
        
        for pos_wrapper in asset_positions:
            pos = pos_wrapper.get("position", {})
            
            if symbol:
                asset = self.get_market_symbol(symbol)
                if pos.get("coin") != asset:
                    continue
            
            szi = float(pos.get("szi", 0))
            if abs(szi) < 1e-10:  # No position
                continue
            
            entry_px = float(pos.get("entryPx", 0))
            
            positions.append(PositionInfo(
                position_id=f"{pos.get('coin')}_{self._wallet_address}",
                exchange=ExchangeName.TRADEXYZ,
                symbol=pos.get("coin", ""),
                side=PositionSide.LONG if szi > 0 else PositionSide.SHORT,
                size=abs(szi),
                value=abs(szi) * entry_px,
                entry_price=entry_px,
                mark_price=entry_px,  # Would need to fetch current
                liquidation_price=float(pos.get("liquidationPx")) if pos.get("liquidationPx") else None,
                unrealized_pnl=float(pos.get("unrealizedPnl", 0)),
                realized_pnl=float(pos.get("returnOnEquity", 0)),
                leverage=int(float(pos.get("leverage", {}).get("value", 1))),
                margin=float(pos.get("marginUsed", 0)),
                created_time=0,
                updated_time=get_current_timestamp(),
                raw_data=pos,
            ))
        
        return positions
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderInfo]:
        """Get open orders."""
        response = await self._info_request({
            "type": "openOrders",
            "user": self._wallet_address,
        })
        
        if not response:
            return []
        
        orders = []
        for order in response:
            if symbol:
                asset = self.get_market_symbol(symbol)
                if order.get("coin") != asset:
                    continue
            
            orders.append(self._parse_order(order))
        
        return orders
    
    # =========================================================================
    # Order Management
    # =========================================================================
    
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
        """Place an order on TradeXYZ/Hyperliquid."""
        if self._simulation:
            logger.info(
                "SIMULATION: Would place order on TradeXYZ",
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
        
        asset = self.get_market_symbol(symbol)
        
        # Get asset index
        asset_idx = self._asset_index_map.get(asset)
        if asset_idx is None:
            await self._refresh_meta()
            asset_idx = self._asset_index_map.get(asset)
            if asset_idx is None:
                return TradeResult(
                    success=False,
                    order_id=None,
                    external_id=external_id,
                    error_message=f"Unknown asset: {asset}",
                    error_code="UNKNOWN_ASSET",
                )
        
        # Set leverage if specified
        if leverage:
            await self.set_leverage(symbol, leverage)
        
        # For market orders, get current price and add slippage
        if order_type == OrderType.MARKET or price is None:
            mark_price = await self.get_mark_price(symbol)
            if side == PositionSide.LONG:
                price = mark_price * 1.01  # 1% slippage buffer
            else:
                price = mark_price * 0.99
        
        # Build order
        is_buy = side == PositionSide.LONG

        # Round to appropriate decimals based on Hyperliquid's requirements
        asset_info = self._meta_cache["universe"][asset_idx]
        sz_decimals = int(asset_info.get("szDecimals", 3))

        # Hyperliquid uses 5 significant figures for price
        # Price must be rounded to tick size (varies by asset)
        # For BTC, typical tick is 1.0, for smaller assets it's smaller
        rounded_size = round(quantity, sz_decimals)

        # Format price with appropriate precision
        # Hyperliquid requires prices to be multiples of the tick size
        # For BTC this is typically $1, so we round to whole numbers
        if asset in ["BTC"]:
            rounded_price = round(price, 0)  # Round to nearest dollar for BTC
        elif asset in ["ETH"]:
            rounded_price = round(price, 1)  # Round to $0.1 for ETH
        else:
            rounded_price = round(price, 2)  # Default to cents

        logger.info(
            "TradeXYZ order params",
            asset=asset,
            is_buy=is_buy,
            size=rounded_size,
            price=rounded_price,
            sz_decimals=sz_decimals,
        )

        order_spec = {
            "a": asset_idx,
            "b": is_buy,
            "p": str(rounded_price),
            "s": str(rounded_size),
            "r": reduce_only,
            "t": {
                "limit": {
                    "tif": "Ioc" if time_in_force == TimeInForce.IOC else "Gtc"
                }
            },
        }
        
        if external_id:
            order_spec["c"] = int(external_id, 16) if external_id.startswith("0x") else hash(external_id) % (10 ** 16)
        
        # Build action
        action = {
            "type": "order",
            "orders": [order_spec],
            "grouping": "na",
        }
        
        # Sign and send
        nonce = get_current_timestamp()
        signature = self._sign_action(action, nonce)
        
        payload = {
            "action": action,
            "nonce": nonce,
            "signature": signature,
        }
        
        response = await self._exchange_request(payload)
        
        if response and response.get("status") == "ok":
            statuses = response.get("response", {}).get("data", {}).get("statuses", [])
            if statuses and statuses[0].get("resting"):
                resting = statuses[0]["resting"]
                return TradeResult(
                    success=True,
                    order_id=str(resting.get("oid", "")),
                    external_id=external_id,
                    error_message=None,
                    error_code=None,
                    raw_response=response,
                )
            elif statuses and statuses[0].get("filled"):
                filled = statuses[0]["filled"]
                return TradeResult(
                    success=True,
                    order_id=str(filled.get("oid", "")),
                    external_id=external_id,
                    error_message=None,
                    error_code=None,
                    filled_quantity=float(filled.get("totalSz", 0)),
                    average_price=float(filled.get("avgPx", 0)),
                    raw_response=response,
                )
            elif statuses and statuses[0].get("error"):
                return TradeResult(
                    success=False,
                    order_id=None,
                    external_id=external_id,
                    error_message=statuses[0]["error"],
                    error_code="ORDER_ERROR",
                    raw_response=response,
                )
        
        return TradeResult(
            success=False,
            order_id=None,
            external_id=external_id,
            error_message=str(response) if response else "No response",
            error_code="UNKNOWN",
            raw_response=response or {},
        )
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID."""
        if self._simulation:
            logger.info("SIMULATION: Would cancel order on TradeXYZ", order_id=order_id)
            return True
        
        # Need to find the asset for this order
        orders = await self.get_open_orders()
        target_order = None
        for order in orders:
            if order.order_id == order_id:
                target_order = order
                break
        
        if not target_order:
            return False
        
        asset_idx = self._asset_index_map.get(target_order.symbol)
        if asset_idx is None:
            return False
        
        action = {
            "type": "cancel",
            "cancels": [{
                "a": asset_idx,
                "o": int(order_id),
            }],
        }
        
        nonce = get_current_timestamp()
        signature = self._sign_action(action, nonce)
        
        response = await self._exchange_request({
            "action": action,
            "nonce": nonce,
            "signature": signature,
        })
        
        return response and response.get("status") == "ok"
    
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all open orders."""
        if self._simulation:
            logger.info("SIMULATION: Would cancel all orders on TradeXYZ", symbol=symbol)
            return 0
        
        orders = await self.get_open_orders(symbol)
        
        if not orders:
            return 0
        
        cancels = []
        for order in orders:
            asset_idx = self._asset_index_map.get(order.symbol)
            if asset_idx is not None:
                cancels.append({
                    "a": asset_idx,
                    "o": int(order.order_id),
                })
        
        if not cancels:
            return 0
        
        action = {
            "type": "cancel",
            "cancels": cancels,
        }
        
        nonce = get_current_timestamp()
        signature = self._sign_action(action, nonce)
        
        response = await self._exchange_request({
            "action": action,
            "nonce": nonce,
            "signature": signature,
        })
        
        return len(cancels) if response and response.get("status") == "ok" else 0
    
    # =========================================================================
    # Position Management
    # =========================================================================
    
    async def close_position(
        self,
        symbol: str,
        quantity: Optional[float] = None,
    ) -> TradeResult:
        """Close a position."""
        positions = await self.get_positions(symbol)
        
        if not positions:
            return TradeResult(
                success=True,
                order_id=None,
                external_id=None,
                error_message="No position to close",
                error_code=None,
            )
        
        position = positions[0]
        close_qty = quantity or position.size
        
        # Close by placing opposite order
        close_side = PositionSide.SHORT if position.side == PositionSide.LONG else PositionSide.LONG
        
        return await self.place_order(
            symbol=symbol,
            side=close_side,
            quantity=close_qty,
            order_type=OrderType.MARKET,
            reduce_only=True,
        )
    
    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a market."""
        if self._simulation:
            logger.info("SIMULATION: Would set leverage on TradeXYZ", symbol=symbol, leverage=leverage)
            return True
        
        asset = self.get_market_symbol(symbol)
        asset_idx = self._asset_index_map.get(asset)
        
        if asset_idx is None:
            return False
        
        action = {
            "type": "updateLeverage",
            "asset": asset_idx,
            "isCross": True,
            "leverage": leverage,
        }
        
        nonce = get_current_timestamp()
        signature = self._sign_action(action, nonce)
        
        response = await self._exchange_request({
            "action": action,
            "nonce": nonce,
            "signature": signature,
        })
        
        return response and response.get("status") == "ok"
    
    async def get_leverage(self, symbol: str) -> int:
        """Get current leverage for a market."""
        positions = await self.get_positions(symbol)
        
        if positions:
            return positions[0].leverage
        
        # Default leverage
        return 1
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def get_market_symbol(self, token: str) -> str:
        """Convert token to TradeXYZ/Hyperliquid market symbol."""
        return TRADEXYZ_MARKETS.get(token.upper(), token.upper())
    
    async def _info_request(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Make info request to Hyperliquid API."""
        if not self._client:
            raise RuntimeError("Not connected to TradeXYZ")

        # Apply rate limiting
        await self._rate_limiter.acquire()

        try:
            response = await self._client.post("/info", json=data)
            return response.json()
        except Exception as e:
            logger.error("TradeXYZ info request failed", error=str(e))
            return None

    async def _exchange_request(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Make exchange request to Hyperliquid API."""
        if not self._client:
            raise RuntimeError("Not connected to TradeXYZ")

        # Apply rate limiting
        await self._rate_limiter.acquire()

        try:
            response = await self._client.post("/exchange", json=data)
            return response.json()
        except Exception as e:
            logger.error("TradeXYZ exchange request failed", error=str(e))
            return None
    
    def _sign_action(self, action: Dict[str, Any], nonce: int) -> Dict[str, str]:
        """
        Sign an action using Hyperliquid's EIP-712 signing scheme.

        Uses the official hyperliquid-python-sdk for proper signature generation.
        """
        if not self._account:
            raise RuntimeError("Account not initialized")

        # Use official Hyperliquid SDK signing
        # active_pool=None means no vault, expires_after=None means no expiry
        signature = sign_l1_action(
            wallet=self._account,
            action=action,
            active_pool=None,
            nonce=nonce,
            expires_after=None,
            is_mainnet=self._is_mainnet,
        )

        return signature
    
    def _parse_order(self, data: Dict[str, Any]) -> OrderInfo:
        """Parse order data from API response."""
        side_str = data.get("side", "B")
        side = PositionSide.LONG if side_str in ("B", "buy") else PositionSide.SHORT
        
        return OrderInfo(
            order_id=str(data.get("oid", "")),
            external_id=str(data.get("cloid")) if data.get("cloid") else None,
            exchange=ExchangeName.TRADEXYZ,
            symbol=data.get("coin", ""),
            side=side,
            order_type=OrderType.LIMIT,
            status=OrderStatus.NEW,  # Open orders are always new/resting
            quantity=float(data.get("sz", 0)),
            filled_quantity=0,  # Would need trade history
            remaining_quantity=float(data.get("sz", 0)),
            price=float(data.get("limitPx", 0)),
            average_price=None,
            fee_paid=0,
            created_time=int(data.get("timestamp", 0)),
            updated_time=int(data.get("timestamp", 0)),
            reduce_only=data.get("reduceOnly", False),
            post_only=False,
            raw_data=data,
        )
