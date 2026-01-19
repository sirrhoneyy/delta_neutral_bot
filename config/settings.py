"""Settings management using Pydantic."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Find and load .env file from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

from .constants import DefaultParams


class ExtendedSettings(BaseSettings):
    """Extended Exchange credentials and configuration."""
    
    model_config = SettingsConfigDict(
        env_prefix="EXTENDED_",
        extra="ignore"
    )
    
    api_key: SecretStr = Field(default=SecretStr(os.getenv("EXTENDED_API_KEY", "dummy")))
    stark_private_key: SecretStr = Field(default=SecretStr(os.getenv("EXTENDED_STARK_PRIVATE_KEY", "0x0")))
    l2_key: str = Field(default=os.getenv("EXTENDED_L2_KEY", "0x0"))
    vault: int = Field(default=int(os.getenv("EXTENDED_VAULT", "0")))
    account_id: int = Field(default=int(os.getenv("EXTENDED_ACCOUNT_ID", "0")))
    network: Literal["mainnet", "testnet"] = Field(default="mainnet")
    
    @property
    def base_url(self) -> str:
        if self.network == "testnet":
            return "https://api.starknet.sepolia.extended.exchange"
        return "https://api.starknet.extended.exchange"
    
    @property
    def ws_url(self) -> str:
        if self.network == "testnet":
            return "wss://starknet.sepolia.extended.exchange/stream.extended.exchange/v1"
        return "wss://api.starknet.extended.exchange/stream.extended.exchange/v1"


class TradeXYZSettings(BaseSettings):
    """TradeXYZ (Hyperliquid) credentials and configuration."""
    
    model_config = SettingsConfigDict(
        env_prefix="TRADEXYZ_",
        extra="ignore"
    )
    
    wallet_address: str = Field(default=os.getenv("TRADEXYZ_WALLET_ADDRESS", "0x0"))
    api_secret: SecretStr = Field(default=SecretStr(os.getenv("TRADEXYZ_API_SECRET", "0x0")))
    network: Literal["mainnet", "testnet"] = Field(default="mainnet")
    
    @property
    def base_url(self) -> str:
        if self.network == "testnet":
            return "https://api.hyperliquid-testnet.xyz"
        return "https://api.hyperliquid.xyz"


class RiskSettings(BaseSettings):
    """Risk management parameters."""
    
    model_config = SettingsConfigDict(extra="ignore")
    
    min_equity_usage: float = Field(default=0.40)
    max_equity_usage: float = Field(default=0.80)
    min_leverage: int = Field(default=10)
    max_leverage: int = Field(default=20)
    min_hold_duration: int = Field(default=1200)
    max_hold_duration: int = Field(default=7200)
    min_cooldown: int = Field(default=600)
    max_cooldown: int = Field(default=3600)
    max_position_value_usd: float = Field(default=100000.0)
    min_balance_usd: float = Field(default=25.0)
    max_consecutive_failures: int = Field(default=3)
    max_slippage_percent: float = Field(default=0.5)


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        extra="ignore"
    )

    simulation_mode: bool = Field(default=os.getenv("SIMULATION_MODE", "true").lower() == "true")
    simulation_balance_usd: float = Field(default=10_000.0)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    api_timeout: int = Field(default=30)
    order_timeout: int = Field(default=60)
    ws_reconnect_attempts: int = Field(default=5)

    extended: ExtendedSettings = Field(default_factory=ExtendedSettings)
    tradexyz: TradeXYZSettings = Field(default_factory=TradeXYZSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)

    @model_validator(mode="after")
    def validate_live_mode_credentials(self) -> "Settings":
        """Reject dummy/placeholder credentials when running in live mode."""
        if self.simulation_mode:
            return self

        # Check Extended credentials
        dummy_indicators = {"dummy", "0x0", "placeholder", "test", "example"}
        extended_api_key = self.extended.api_key.get_secret_value().lower()
        extended_stark_key = self.extended.stark_private_key.get_secret_value().lower()

        if any(ind in extended_api_key for ind in dummy_indicators):
            raise ValueError(
                "Live mode requires valid Extended API key. "
                "Found placeholder value in EXTENDED_API_KEY."
            )

        if extended_stark_key in dummy_indicators or extended_stark_key == "0x0":
            raise ValueError(
                "Live mode requires valid Extended Stark private key. "
                "Found placeholder value in EXTENDED_STARK_PRIVATE_KEY."
            )

        # Check TradeXYZ credentials
        tradexyz_wallet = self.tradexyz.wallet_address.lower()
        tradexyz_secret = self.tradexyz.api_secret.get_secret_value().lower()

        if tradexyz_wallet in dummy_indicators or tradexyz_wallet == "0x0":
            raise ValueError(
                "Live mode requires valid TradeXYZ wallet address. "
                "Found placeholder value in TRADEXYZ_WALLET_ADDRESS."
            )

        if tradexyz_secret in dummy_indicators or tradexyz_secret == "0x0":
            raise ValueError(
                "Live mode requires valid TradeXYZ API secret. "
                "Found placeholder value in TRADEXYZ_API_SECRET."
            )

        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
