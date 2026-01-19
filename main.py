#!/usr/bin/env python3
"""
Delta-Neutral Perpetual Futures Trading Bot

Entry point for the automated trading system that executes
delta-neutral strategies across Extended and TradeXYZ exchanges.

Usage:
    python main.py                  # Run continuously
    python main.py --single-cycle   # Run one cycle only
    python main.py --dry-run        # Simulation mode (default)
    python main.py --live           # Live trading mode

Environment:
    Set SIMULATION_MODE=false in .env for live trading

WARNING: Live trading involves real financial risk.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import get_settings, Settings
from config.constants import SUPPORTED_TOKENS
from exchanges.extended import ExtendedExchange
from exchanges.tradexyz import TradeXYZExchange
from execution.manager import TradeManager
from execution.safety import EmergencyReason
from utils.logging import setup_logging, get_logger, trading_logger


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Delta-Neutral Perpetual Futures Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main.py                  # Run in simulation mode
    python main.py --live           # Run with real funds
    python main.py --single-cycle   # Execute one cycle only
    
Environment Variables:
    SIMULATION_MODE     Set to 'false' for live trading
    LOG_LEVEL           DEBUG, INFO, WARNING, ERROR
    
See .env.example for full configuration options.
        """,
    )
    
    parser.add_argument(
        "--single-cycle",
        action="store_true",
        help="Execute only one trading cycle",
    )
    
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live trading (overrides SIMULATION_MODE)",
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Force simulation mode (default)",
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Override logging level",
    )
    
    return parser.parse_args()


async def run_bot(
    settings: Settings,
    single_cycle: bool = False,
) -> int:
    """
    Run the trading bot.
    
    Args:
        settings: Application settings
        single_cycle: If True, run only one cycle
        
    Returns:
        Exit code (0 for success)
    """
    logger = get_logger(__name__)
    
    # Display startup banner
    print_banner(settings.simulation_mode)
    
    # Create exchange adapters
    extended = ExtendedExchange(
        settings=settings.extended,
        simulation=settings.simulation_mode,
    )
    
    tradexyz = TradeXYZExchange(
        settings=settings.tradexyz,
        simulation=settings.simulation_mode,
    )
    
    # Create trade manager
    manager = TradeManager(
        extended_exchange=extended,
        tradexyz_exchange=tradexyz,
        settings=settings,
    )
    
    try:
        # Start the manager
        await manager.start()
        
        if single_cycle:
            # Run single cycle
            logger.info("Executing single trading cycle")
            result = await manager.run_cycle()
            
            if result.success:
                logger.info(
                    "Cycle completed successfully",
                    cycle_id=result.cycle_id,
                    token=result.token,
                    position_value=f"${result.position_value:,.2f}",
                )
                return 0
            else:
                logger.error(
                    "Cycle failed",
                    cycle_id=result.cycle_id,
                    error=result.error_message,
                )
                return 1
        else:
            # Run continuous
            logger.info("Starting continuous trading operation")
            await manager.run_continuous()
            return 0
            
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
        return 0
        
    except Exception as e:
        logger.error("Fatal error", error=str(e))
        return 1
        
    finally:
        # Clean shutdown
        await manager.stop()


def print_banner(simulation: bool) -> None:
    """Print startup banner."""
    mode = "SIMULATION" if simulation else "LIVE TRADING"
    mode_color = "\033[92m" if simulation else "\033[91m"  # Green/Red
    reset = "\033[0m"
    
    banner = f"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║       Delta-Neutral Perpetual Futures Trading Bot            ║
║                                                              ║
║       Mode: {mode_color}{mode:^20}{reset}                       ║
║                                                              ║
║       Exchanges: Extended + TradeXYZ (Hyperliquid)           ║
║       Tokens: {', '.join(SUPPORTED_TOKENS):^40} ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)
    
    if not simulation:
        print(f"{mode_color}⚠️  WARNING: LIVE TRADING MODE - REAL FUNDS AT RISK{reset}")
        print()


def main() -> int:
    """Main entry point."""
    args = parse_args()
    
    try:
        # Load settings
        settings = get_settings()
        
        # Apply command line overrides
        if args.live:
            settings.simulation_mode = False
        elif args.dry_run:
            settings.simulation_mode = True
        
        if args.log_level:
            settings.log_level = args.log_level
        
        # Setup logging
        setup_logging(settings.log_level)
        
        # Run the bot
        return asyncio.run(run_bot(
            settings=settings,
            single_cycle=args.single_cycle,
        ))
        
    except KeyboardInterrupt:
        print("\nShutdown requested")
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
