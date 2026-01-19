# Delta-Neutral Perpetual Futures Trading Bot

A production-ready automated trading system executing delta-neutral strategies across **Extended Exchange** and **TradeXYZ** (Hyperliquid API).

## Strategy Overview

The bot maintains **strict delta neutrality** by simultaneously opening opposing positions:
- One **LONG** position on one exchange
- One **SHORT** position on the other exchange
- Net market exposure: **Zero**

### Key Features

- **Funding Rate Optimization**: Probabilistic bias toward favorable funding rates
- **Capital-Aware Sizing**: All positions sized against minimum available balance
- **Cryptographically Secure Randomization**: Non-predictable behavior across all parameters
- **Atomic Position Management**: Rollback capabilities for failed executions
- **Comprehensive Risk Controls**: Pre-execution validation and safety checks

## Supported Tokens

- BTC (Bitcoin)
- ETH (Ethereum)  
- SOL (Solana)
- HYPE (Hyperliquid native token)

## Architecture

```
delta_neutral_bot/
├── config/
│   ├── __init__.py
│   ├── settings.py          # Environment configuration
│   └── constants.py         # Trading parameters
├── exchanges/
│   ├── __init__.py
│   ├── base.py              # Abstract exchange interface
│   ├── extended.py          # Extended Exchange implementation
│   └── tradexyz.py          # TradeXYZ (Hyperliquid) implementation
├── core/
│   ├── __init__.py
│   ├── funding.py           # Funding rate analysis
│   ├── sizing.py            # Position sizing logic
│   ├── randomizer.py        # Cryptographic randomization
│   └── risk.py              # Risk management
├── execution/
│   ├── __init__.py
│   ├── manager.py           # Trade lifecycle management
│   ├── atomic.py            # Atomic operations with rollback
│   └── safety.py            # Emergency procedures
├── utils/
│   ├── __init__.py
│   ├── logging.py           # Structured logging
│   └── timing.py            # Timing utilities
├── main.py                  # Entry point
├── requirements.txt
└── .env.example
```

## Installation

```bash
# Clone repository
git clone https://github.com/yourusername/delta-neutral-bot.git
cd delta-neutral-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API credentials
```

## Configuration

### Environment Variables

```env
# Extended Exchange
EXTENDED_API_KEY=your_extended_api_key
EXTENDED_STARK_PRIVATE_KEY=your_stark_private_key
EXTENDED_L2_KEY=your_l2_key
EXTENDED_VAULT=your_vault_number

# TradeXYZ (Hyperliquid)
TRADEXYZ_API_SECRET=your_hyperliquid_secret
TRADEXYZ_WALLET_ADDRESS=your_wallet_address

# Mode
SIMULATION_MODE=true  # Set false for live trading
LOG_LEVEL=INFO
```

## Risk Parameters

| Parameter | Min | Max | Description |
|-----------|-----|-----|-------------|
| Equity Usage | 40% | 80% | Per-cycle capital allocation |
| Leverage | 10x | 20x | Position leverage |
| Hold Duration | 20 min | 2 hours | Position holding time |
| Cooldown | 10 min | 60 min | Between-cycle wait |

## Safety Features

1. **Pre-Execution Validation**
   - Balance verification on both exchanges
   - Margin requirement checks
   - Liquidation price analysis

2. **Atomic Execution**
   - Simultaneous position opening
   - Automatic rollback on partial failure
   - No unhedged exposure guarantee

3. **Emergency Procedures**
   - Kill switch functionality
   - Graceful shutdown handling
   - Position reconciliation

## Funding Rate Bias

The bot applies **soft probabilistic bias** based on funding rate differentials:

| Funding Difference | Bias Strength |
|-------------------|---------------|
| < 0.001% | ~50/50 (near random) |
| 0.001% - 0.01% | ~60/40 (mild bias) |
| > 0.01% | ~75/25 (strong bias) |

**Important**: Funding bias never fully overrides randomness.

## Usage

### Simulation Mode (Recommended First)

```bash
# Run with simulation enabled
SIMULATION_MODE=true python main.py
```

### Live Trading

```bash
# CAUTION: Real funds at risk
SIMULATION_MODE=false python main.py
```

### Single Cycle Test

```bash
python -m pytest tests/ -v
```

## Monitoring

The bot provides real-time logging:

```
2024-01-15 10:30:00 | INFO | Cycle Start | Token: BTC
2024-01-15 10:30:01 | INFO | Funding | Extended: 0.0001% | TradeXYZ: -0.0003%
2024-01-15 10:30:01 | INFO | Assignment | Extended: SHORT | TradeXYZ: LONG
2024-01-15 10:30:02 | INFO | Sizing | Equity: 65% | Leverage: 15x | Size: 0.5 BTC
2024-01-15 10:30:03 | INFO | Execution | Opening positions...
2024-01-15 10:30:04 | INFO | Success | Both legs confirmed
2024-01-15 11:45:00 | INFO | Closing | Hold time: 75 minutes
2024-01-15 11:45:02 | INFO | Cycle Complete | PnL: +$12.50 (funding)
```

## Disclaimer

**THIS SOFTWARE IS FOR EDUCATIONAL PURPOSES ONLY.**

Trading cryptocurrencies and derivatives involves substantial risk of loss. This bot:
- Does NOT guarantee profits
- May experience losses due to execution slippage
- Is subject to exchange API limitations
- Requires proper risk management

**Use at your own risk. Never trade with funds you cannot afford to lose.**

## License

MIT License - See LICENSE file for details.
