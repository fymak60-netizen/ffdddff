# GOLD AI SCALPER - XAUUSD

Institutional-Grade AI Trading Bot for Gold (XAUUSD) on MetaTrader 5.

## Features

### Strong Indicators (not weak ones!)
- **RSI** (14 & 7 period) - Momentum + Oversold/Overbought
- **MACD** (12/26/9) - Trend + Histogram divergence
- **Bollinger Bands Squeeze** - Breakout detection
- **Stochastic** (14/3) - Reversal signals
- **ADX + DI** (14) - Trend strength filter (only trades when trend > 20)
- **EMA Stack** (9/21/50/200) - Multi-MA alignment
- **ATR** (14) - Dynamic SL/TP sizing
- **Z-Score** (20) - Statistical mean reversion
- **Supertrend** (10/3) - Trend direction filter
- **VWAP** - Volume-weighted price level

### AI Engine (Ensemble)
- **Random Forest** (200 trees) - Fast pattern recognition
- **Gradient Boosting** (150 trees) - Precise signal detection
- Combined ensemble prediction with confidence scoring
- 25 engineered features from price, volume, and indicators
- Auto-retrains every 30 minutes on latest data

### Risk Management
- Dynamic ATR-based Stop Loss / Take Profit
- Break-even management (moves SL to entry after 1 ATR profit)
- Trailing stop (locks profits after 1.5 ATR)
- Maximum daily loss limit ($50 default)
- Maximum 20 trades per day
- 5 consecutive loss cooldown
- Dynamic position sizing based on account risk
- Spread filter (max 50 points)

## Setup

1. Install Python 3.8+
2. Install MetaTrader 5 (Windows)
3. Run setup: `pip install -r requirements.txt`
4. Configure account in `gold_ai_bot.py`
5. Run: `python gold_ai_bot.py`

## Configuration

Edit the top of `gold_ai_bot.py`:
- `ACCOUNT_NUMBER` - Your MT5 account
- `ACCOUNT_PASSWORD` - Your MT5 password
- `BROKER_SERVER` - Your broker server
- `LOT_SIZE` - Trade size (default 0.05)
- `MAX_DAILY_LOSS` - Max loss per day ($50)
- `MIN_CONFIDENCE` - AI confidence threshold (62%)
- `CHECK_INTERVAL` - Scan interval (5 seconds)

## How It Works

1. **Every 5 seconds**: Fetches latest M1 candle data (1000 bars)
2. **Calculates 25 indicators** across momentum, trend, volatility, and volume
3. **AI predicts** next candle direction with confidence score
4. **Multi-confirmation**: At least 3/4 indicators must agree + ADX > 20
5. **Dynamic risk**: SL/TP calculated from ATR, lot size from account risk %
6. **Management**: Trailing stop, break-even, daily loss limits

## Inspired By
- [andywarui/xaubot](https://github.com/andywarui/xaubot) - Multi-timeframe XAUUSD pipeline
- [clayandthepotter/ai-gold-scalper](https://github.com/clayandthepotter/ai-gold-scalper) - Enterprise AI gold system
- [P1Piyush/XAUUSD-Trading-Bots](https://github.com/P1Piyush/XAUUSD-Trading-Bots) - Institutional strategies
- [zero-was-here/tradingbot](https://github.com/zero-was-here/tradingbot) - DRL trading system

## Risk Disclaimer
Trading involves substantial risk. Past performance does not guarantee future results.
This is for educational purposes. Always test on a demo account first.
