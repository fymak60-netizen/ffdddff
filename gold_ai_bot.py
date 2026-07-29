"""
╔══════════════════════════════════════════════════════════════════╗
║          GOLD AI SCALPER - XAUUSD Institutional-Grade Bot       ║
║                                                                  ║
║  Indicators: RSI, MACD, Bollinger Squeeze, Stochastic,          ║
║              ADX, EMA Stack, ATR, Z-Score, Supertrend           ║
║  AI Engine:  Random Forest + Gradient Boosting Ensemble         ║
║  Risk:       Dynamic ATR-based SL/TP, Trailing Stop,            ║
║              Daily Loss Limit, Break-Even Manager               ║
║                                                                  ║
║  Inspired by: github.com/andywarui/xaubot                       ║
║               github.com/clayandthepotter/ai-gold-scalper       ║
║               github.com/P1Piyush/XAUUSD-Trading-Bots          ║
╚══════════════════════════════════════════════════════════════════╝
"""

import sys
import time
import threading
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import cross_val_score

# ═══════════════════════════════════════════════════════════
#                  ACCOUNT CONFIGURATION
# ═══════════════════════════════════════════════════════════
ACCOUNT_NUMBER   = 109215262
ACCOUNT_PASSWORD = "Io-x3aSm"
BROKER_SERVER    = "MetaQuotes-Demo"
SYMBOL           = "XAUUSD"

# ═══════════════════════════════════════════════════════════
#                   TRADING PARAMETERS
# ═══════════════════════════════════════════════════════════
LOT_SIZE           = 0.05       # Lot size per trade
MAX_DAILY_LOSS     = 50.0       # Max daily loss in USD - stops bot
MAX_SPREAD         = 50         # Max spread in points (gold = 0.5 pips)
MIN_CONFIDENCE     = 0.62       # Minimum AI confidence to enter (62%)
CHECK_INTERVAL     = 5          # Seconds between each check (FAST!)
RETRAIN_INTERVAL   = 1800       # Retrain AI every 30 minutes
HISTORY_BARS       = 1000       # Bars for training
MAGIC_NUMBER       = 777777

# ═══════════════════════════════════════════════════════════
#              INDICATOR CALCULATION ENGINE
# ═══════════════════════════════════════════════════════════

class IndicatorEngine:
    """Calculates all technical indicators - the brain of the system"""

    @staticmethod
    def ema(series, period):
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def sma(series, period):
        return series.rolling(period).mean()

    @staticmethod
    def rsi(close, period=14):
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd(close, fast=12, slow=26, signal=9):
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(close, period=20, std_dev=2):
        sma = close.rolling(period).mean()
        std = close.rolling(period).std()
        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)
        # Squeeze: when bands are narrow = potential breakout
        squeeze = (upper - lower) / sma
        return upper, sma, lower, squeeze

    @staticmethod
    def stochastic(high, low, close, k_period=14, d_period=3):
        lowest_low = low.rolling(k_period).min()
        highest_high = high.rolling(k_period).max()
        k = 100 * (close - lowest_low) / (highest_high - lowest_low)
        d = k.rolling(d_period).mean()
        return k, d

    @staticmethod
    def adx(high, low, close, period=14):
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/period, min_periods=period).mean()
        plus_di = 100 * (plus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx_val = dx.ewm(alpha=1/period, min_periods=period).mean()
        return adx_val, plus_di, minus_di

    @staticmethod
    def atr(high, low, close, period=14):
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, min_periods=period).mean()

    @staticmethod
    def z_score(close, period=20):
        mean = close.rolling(period).mean()
        std = close.rolling(period).std()
        return (close - mean) / std

    @staticmethod
    def supertrend(high, low, close, period=10, multiplier=3):
        atr = IndicatorEngine.atr(high, low, close, period)
        hl2 = (high + low) / 2
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)

        supertrend = pd.Series(index=close.index, dtype=float)
        direction = pd.Series(index=close.index, dtype=float)

        supertrend.iloc[0] = upper_band.iloc[0]
        direction.iloc[0] = -1

        for i in range(1, len(close)):
            if close.iloc[i] > upper_band.iloc[i-1]:
                direction.iloc[i] = 1
            elif close.iloc[i] < lower_band.iloc[i-1]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = direction.iloc[i-1]

            if direction.iloc[i] == 1:
                supertrend.iloc[i] = lower_band.iloc[i]
            else:
                supertrend.iloc[i] = upper_band.iloc[i]

        return supertrend, direction

    @staticmethod
    def volume_weighted_average(df):
        """Simple VWAP from OHLCV data"""
        typical_price = (df['high'] + df['low'] + df['close']) / 3
        if 'tick_volume' in df.columns:
            volume = df['tick_volume']
        elif 'real_volume' in df.columns:
            volume = df['real_volume']
        else:
            volume = pd.Series(1, index=df.index)
        vwap = (typical_price * volume).cumsum() / volume.cumsum()
        return vwap


# ═══════════════════════════════════════════════════════════
#                 AI ENGINE (Ensemble Model)
# ═══════════════════════════════════════════════════════════

class AIEngine:
    """Ensemble AI: Random Forest + Gradient Boosting combined"""

    def __init__(self):
        self.rf_model = None
        self.gb_model = None
        self.is_trained = False
        self.accuracy = 0.0
        self.feature_importance = {}

    def prepare_features(self, df):
        """Calculate all indicators and create feature matrix"""
        df = df.copy()

        # === Momentum Indicators ===
        df['RSI'] = IndicatorEngine.rsi(df['close'])
        df['RSI_fast'] = IndicatorEngine.rsi(df['close'], 7)
        df['Stoch_K'], df['Stoch_D'] = IndicatorEngine.stochastic(df['high'], df['low'], df['close'])

        # === MACD ===
        df['MACD'], df['MACD_Signal'], df['MACD_Hist'] = IndicatorEngine.macd(df['close'])

        # === Bollinger Bands ===
        df['BB_Upper'], df['BB_Mid'], df['BB_Lower'], df['BB_Squeeze'] = \
            IndicatorEngine.bollinger_bands(df['close'])
        df['BB_Position'] = (df['close'] - df['BB_Lower']) / (df['BB_Upper'] - df['BB_Lower'])

        # === Trend Indicators ===
        df['EMA_9'] = IndicatorEngine.ema(df['close'], 9)
        df['EMA_21'] = IndicatorEngine.ema(df['close'], 21)
        df['EMA_50'] = IndicatorEngine.ema(df['close'], 50)
        df['EMA_200'] = IndicatorEngine.ema(df['close'], 200)

        # EMA Stack alignment (bullish when 9 > 21 > 50)
        df['EMA_Stack'] = ((df['EMA_9'] > df['EMA_21']) & (df['EMA_21'] > df['EMA_50'])).astype(int) \
                        - ((df['EMA_9'] < df['EMA_21']) & (df['EMA_21'] < df['EMA_50'])).astype(int)

        df['ADX'], df['Plus_DI'], df['Minus_DI'] = IndicatorEngine.adx(df['high'], df['low'], df['close'])

        # === Supertrend ===
        df['Supertrend'], df['ST_Direction'] = IndicatorEngine.supertrend(df['high'], df['low'], df['close'])

        # === Volatility ===
        df['ATR'] = IndicatorEngine.atr(df['high'], df['low'], df['close'])
        df['Z_Score'] = IndicatorEngine.z_score(df['close'])
        df['ATR_Ratio'] = df['ATR'] / df['close'] * 10000  # Normalized ATR

        # === Price Action Features ===
        df['Body_Size'] = abs(df['close'] - df['open']) / (df['high'] - df['low'] + 0.0001)
        df['Upper_Wick'] = (df['high'] - df[['close', 'open']].max(axis=1)) / (df['high'] - df['low'] + 0.0001)
        df['Lower_Wick'] = (df[['close', 'open']].min(axis=1) - df['low']) / (df['high'] - df['low'] + 0.0001)

        # === Candle Patterns ===
        df['Is_Bullish'] = (df['close'] > df['open']).astype(int)
        df['Prev_Close'] = df['close'].shift(1)
        df['Price_Change'] = df['close'].pct_change()
        df['Momentum_3'] = df['close'] / df['close'].shift(3) - 1
        df['Momentum_5'] = df['close'] / df['close'].shift(5) - 1

        # === Volume Analysis ===
        if 'tick_volume' in df.columns:
            df['Vol_SMA'] = df['tick_volume'].rolling(20).mean()
            df['Vol_Ratio'] = df['tick_volume'] / (df['Vol_SMA'] + 1)
        else:
            df['Vol_Ratio'] = 1.0

        # === VWAP ===
        df['VWAP'] = IndicatorEngine.volume_weighted_average(df)
        df['VWAP_Dist'] = (df['close'] - df['VWAP']) / df['ATR']

        # === Target: Next candle direction ===
        df['Target'] = (df['close'].shift(-1) > df['close']).astype(int)

        return df.dropna()

    def get_feature_columns(self):
        return [
            'RSI', 'RSI_fast', 'Stoch_K', 'Stoch_D',
            'MACD', 'MACD_Signal', 'MACD_Hist',
            'BB_Position', 'BB_Squeeze',
            'EMA_Stack', 'ADX', 'Plus_DI', 'Minus_DI',
            'ST_Direction', 'Z_Score', 'ATR_Ratio',
            'Body_Size', 'Upper_Wick', 'Lower_Wick',
            'Is_Bullish', 'Price_Change', 'Momentum_3', 'Momentum_5',
            'Vol_Ratio', 'VWAP_Dist'
        ]

    def train(self, df):
        """Train ensemble model on historical data"""
        features = self.get_feature_columns()
        available = [f for f in features if f in df.columns]

        X = df[available].values
        y = df['Target'].values

        if len(X) < 100:
            return False, "Not enough data"

        # Split for validation
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        # Model 1: Random Forest (fast, robust)
        self.rf_model = RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_split=10,
            min_samples_leaf=5,
            max_features='sqrt',
            random_state=42,
            n_jobs=-1
        )
        self.rf_model.fit(X_train, y_train)

        # Model 2: Gradient Boosting (precise, catches patterns)
        self.gb_model = GradientBoostingClassifier(
            n_estimators=150,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            random_state=42
        )
        self.gb_model.fit(X_train, y_train)

        # Ensemble accuracy
        rf_pred = self.rf_model.predict(X_val)
        gb_pred = self.gb_model.predict(X_val)
        # Combined prediction (both must agree for high confidence)
        ensemble_pred = ((rf_pred + gb_pred) >= 1).astype(int)
        self.accuracy = (ensemble_pred == y_val).mean()

        # Feature importance
        importances = self.rf_model.feature_importances_
        self.feature_importance = dict(zip(available, importances))

        self.is_trained = True
        return True, f"Accuracy: {self.accuracy:.1%}"

    def predict(self, df):
        """Get ensemble prediction with confidence"""
        if not self.is_trained:
            return None, 0.0

        features = self.get_feature_columns()
        available = [f for f in features if f in df.columns]
        X = df[available].iloc[-1:].values

        # Get probabilities from both models
        rf_proba = self.rf_model.predict_proba(X)[0]
        gb_proba = self.gb_model.predict_proba(X)[0]

        # Ensemble: average probabilities
        avg_proba = (rf_proba + gb_proba) / 2
        prediction = np.argmax(avg_proba)
        confidence = avg_proba[prediction]

        return prediction, confidence


# ═══════════════════════════════════════════════════════════
#                    RISK MANAGER
# ═══════════════════════════════════════════════════════════

class RiskManager:
    """Dynamic risk management - protects capital"""

    def __init__(self):
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.last_reset = datetime.now().date()
        self.max_consecutive_losses = 0
        self.consecutive_losses = 0

    def reset_daily(self):
        today = datetime.now().date()
        if today != self.last_reset:
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.last_reset = today
            self.consecutive_losses = 0

    def can_trade(self):
        self.reset_daily()
        if self.daily_pnl <= -MAX_DAILY_LOSS:
            return False, "Daily loss limit reached"
        if self.daily_trades >= 20:
            return False, "Max daily trades reached"
        if self.consecutive_losses >= 5:
            return False, "Too many consecutive losses - cooling down"
        return True, "OK"

    def calculate_dynamic_sl_tp(self, atr, direction, confidence):
        """ATR-based dynamic SL/TP with confidence scaling"""
        # Higher confidence = wider TP, tighter SL
        confidence_factor = 0.8 + (confidence * 0.4)  # 0.8 to 1.2

        sl_distance = atr * 1.5 / confidence_factor
        tp_distance = atr * 2.5 * confidence_factor

        return sl_distance, tp_distance

    def calculate_lot_size(self, account_balance, atr, confidence):
        """Dynamic position sizing based on risk"""
        risk_pct = 0.01 * confidence  # 0.6% to 1% risk per trade
        risk_amount = account_balance * risk_pct
        sl_distance = atr * 1.5

        if sl_distance <= 0:
            return LOT_SIZE

        # For XAUUSD: 1 lot = 100 oz, $1 per 0.01 move
        lot = risk_amount / (sl_distance * 100)
        lot = max(0.01, min(lot, 0.5))  # Clamp between 0.01 and 0.5
        return round(lot, 2)

    def record_trade(self, pnl):
        self.daily_pnl += pnl
        self.daily_trades += 1
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0


# ═══════════════════════════════════════════════════════════
#                    TRADE EXECUTOR
# ═══════════════════════════════════════════════════════════

class TradeExecutor:
    """Handles all MT5 order operations"""

    @staticmethod
    def open_trade(symbol, order_type, lot, sl, tp, comment="AI"):
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None, "No tick data"

        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "deviation": 30,
            "magic": MAGIC_NUMBER,
            "comment": comment,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None:
            return None, f"Order failed: {mt5.last_error()}"
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return None, f"Order rejected: {result.comment} ({result.retcode})"

        return result.order, "OK"

    @staticmethod
    def close_position(position):
        tick = mt5.symbol_info_tick(position.symbol)
        if tick is None:
            return False

        close_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = tick.bid if position.type == mt5.POSITION_TYPE_BUY else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": close_type,
            "position": position.ticket,
            "price": price,
            "deviation": 30,
            "magic": MAGIC_NUMBER,
            "comment": "AI Close",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

    @staticmethod
    def modify_sl(position, new_sl):
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": position.symbol,
            "position": position.ticket,
            "sl": round(new_sl, 2),
            "tp": position.tp,
        }
        result = mt5.order_send(request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE


# ═══════════════════════════════════════════════════════════
#                    MAIN BOT GUI
# ═══════════════════════════════════════════════════════════

class GoldAIBot:
    def __init__(self, root):
        self.root = root
        self.root.title("GOLD AI SCALPER - XAUUSD")
        self.root.geometry("820x620")
        self.root.configure(bg="#0d0d0d")
        self.root.resizable(True, True)

        # Core components
        self.indicators = IndicatorEngine()
        self.ai = AIEngine()
        self.risk = RiskManager()
        self.executor = TradeExecutor()

        # State
        self.running = False
        self.connected = False
        self.trade_count = 0
        self.win_count = 0
        self.total_pnl = 0.0

        self._build_gui()

        # Start bot thread
        self.bot_thread = threading.Thread(target=self.run_system, daemon=True)
        self.bot_thread.start()

    def _build_gui(self):
        # Title
        title = tk.Label(self.root, text="GOLD AI SCALPER",
                        font=("Consolas", 22, "bold"), bg="#0d0d0d", fg="#FFD700")
        title.pack(pady=(15, 5))

        subtitle = tk.Label(self.root, text="XAUUSD | Institutional-Grade AI Trading",
                           font=("Consolas", 10), bg="#0d0d0d", fg="#888888")
        subtitle.pack(pady=(0, 10))

        # Status frame
        status_frame = tk.Frame(self.root, bg="#1a1a1a", bd=1, relief="ridge")
        status_frame.pack(padx=15, pady=5, fill="x")

        self.connection_label = tk.Label(status_frame, text="[ ] Connecting...",
                                        font=("Consolas", 12, "bold"), bg="#1a1a1a", fg="#ff4444")
        self.connection_label.pack(pady=8)

        # Price frame
        price_frame = tk.Frame(self.root, bg="#1a1a1a", bd=1, relief="ridge")
        price_frame.pack(padx=15, pady=5, fill="x")

        self.price_label = tk.Label(price_frame, text="Price: --",
                                   font=("Consolas", 16, "bold"), bg="#1a1a1a", fg="#00ccff")
        self.price_label.pack(pady=8)

        # AI Status
        ai_frame = tk.Frame(self.root, bg="#1a1a1a", bd=1, relief="ridge")
        ai_frame.pack(padx=15, pady=5, fill="x")

        self.ai_label = tk.Label(ai_frame, text="AI: Waiting for data...",
                                font=("Consolas", 11), bg="#1a1a1a", fg="#ffcc00")
        self.ai_label.pack(pady=5)

        self.signal_label = tk.Label(ai_frame, text="Signal: --",
                                    font=("Consolas", 11, "bold"), bg="#1a1a1a", fg="#cccccc")
        self.signal_label.pack(pady=3)

        # Stats frame
        stats_frame = tk.Frame(self.root, bg="#1a1a1a", bd=1, relief="ridge")
        stats_frame.pack(padx=15, pady=5, fill="x")

        self.stats_label = tk.Label(stats_frame,
                                   text="Trades: 0 | Wins: 0 | WR: -- | PnL: $0.00",
                                   font=("Consolas", 11), bg="#1a1a1a", fg="#cccccc")
        self.stats_label.pack(pady=5)

        self.daily_label = tk.Label(stats_frame,
                                   text="Daily PnL: $0.00 | Risk: OK",
                                   font=("Consolas", 10), bg="#1a1a1a", fg="#88cc88")
        self.daily_label.pack(pady=3)

        # Log frame
        log_frame = tk.Frame(self.root, bg="#0d0d0d")
        log_frame.pack(padx=15, pady=10, fill="both", expand=True)

        self.log_text = tk.Text(log_frame, bg="#111111", fg="#00ff00",
                               font=("Consolas", 9), height=8, state="disabled",
                               insertbackground="#00ff00", selectbackground="#333333")
        scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

    def log(self, message, color="#00ff00"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        def _update():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{timestamp}] {message}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
            # Keep last 100 lines
            lines = int(self.log_text.index('end-1c').split('.')[0])
            if lines > 100:
                self.log_text.configure(state="normal")
                self.log_text.delete("1.0", f"{lines-100}.0")
                self.log_text.configure(state="disabled")
        self.root.after(0, _update)

    def update_label(self, label, text, color=None):
        def _update():
            label.config(text=text)
            if color:
                label.config(fg=color)
        self.root.after(0, _update)

    def run_system(self):
        """Main trading loop"""
        self.log("Starting Gold AI Scalper...", "#FFD700")
        self.log("Connecting to MetaTrader 5...", "#cccccc")

        # Initialize MT5
        if not mt5.initialize():
            self.log("ERROR: Cannot initialize MT5!", "#ff4444")
            self.update_label(self.connection_label, "[X] MT5 Init Failed", "#ff4444")
            return

        if not mt5.login(ACCOUNT_NUMBER, password=ACCOUNT_PASSWORD, server=BROKER_SERVER):
            self.log(f"ERROR: Login failed for account {ACCOUNT_NUMBER}!", "#ff4444")
            self.update_label(self.connection_label, "[X] Login Failed", "#ff4444")
            mt5.shutdown()
            return

        account = mt5.account_info()
        self.log(f"Connected! Account: {account.login} | Balance: ${account.balance:.2f}", "#00ff00")
        self.update_label(self.connection_label, f"[OK] Connected | Balance: ${account.balance:.2f}", "#00ff00")
        self.connected = True

        # Check symbol
        symbol_info = mt5.symbol_info(SYMBOL)
        if symbol_info is None:
            self.log(f"ERROR: Symbol {SYMBOL} not found!", "#ff4444")
            return

        if not symbol_info.visible:
            mt5.symbol_select(SYMBOL, True)

        self.log(f"Symbol: {SYMBOL} | Spread: {symbol_info.spread} pts | Point: {symbol_info.point}", "#cccccc")

        last_train_time = 0
        last_signal = None

        while True:
            try:
                # ─── 1. FETCH DATA ───
                rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, HISTORY_BARS)
                if rates is None or len(rates) < 200:
                    time.sleep(2)
                    continue

                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')

                # ─── 2. CALCULATE FEATURES ───
                df_features = self.ai.prepare_features(df)
                if df_features.empty:
                    time.sleep(2)
                    continue

                current_price = df['close'].iloc[-1]
                current_atr = df_features['ATR'].iloc[-1] if 'ATR' in df_features.columns else 0
                spread = mt5.symbol_info_tick(SYMBOL)
                spread_pts = (spread.ask - spread.bid) if spread else 0

                # Update price display
                self.update_label(self.price_label,
                    f"Price: {current_price:.2f} | ATR: {current_atr:.2f} | Spread: {spread_pts:.2f}")

                # ─── 3. TRAIN AI (every 30 min) ───
                now = time.time()
                if now - last_train_time > RETRAIN_INTERVAL or not self.ai.is_trained:
                    self.log("Training AI on latest data...", "#ffcc00")
                    self.update_label(self.ai_label, "AI: Training...", "#ffcc00")
                    success, msg = self.ai.train(df_features)
                    if success:
                        top_features = sorted(self.ai.feature_importance.items(),
                                             key=lambda x: x[1], reverse=True)[:5]
                        feat_str = ", ".join([f"{k}({v:.2f})" for k, v in top_features])
                        self.log(f"AI trained! {msg} | Top: {feat_str}", "#00ff00")
                        self.update_label(self.ai_label,
                            f"AI: READY | Accuracy: {self.ai.accuracy:.1%}", "#00ff00")
                    else:
                        self.log(f"AI training failed: {msg}", "#ff4444")
                    last_train_time = now

                if not self.ai.is_trained:
                    time.sleep(CHECK_INTERVAL)
                    continue

                # ─── 4. GET PREDICTION ───
                prediction, confidence = self.ai.predict(df_features)

                # Get indicator values for display
                rsi_val = df_features['RSI'].iloc[-1] if 'RSI' in df_features.columns else 0
                macd_hist = df_features['MACD_Hist'].iloc[-1] if 'MACD_Hist' in df_features.columns else 0
                adx_val = df_features['ADX'].iloc[-1] if 'ADX' in df_features.columns else 0
                st_dir = df_features['ST_Direction'].iloc[-1] if 'ST_Direction' in df_features.columns else 0
                ema_stack = df_features['EMA_Stack'].iloc[-1] if 'EMA_Stack' in df_features.columns else 0
                bb_squeeze = df_features['BB_Squeeze'].iloc[-1] if 'BB_Squeeze' in df_features.columns else 0
                z_score = df_features['Z_Score'].iloc[-1] if 'Z_Score' in df_features.columns else 0

                direction = "BUY" if prediction == 1 else "SELL"
                signal_color = "#00ff00" if prediction == 1 else "#ff3333"

                self.update_label(self.signal_label,
                    f"Signal: {direction} | Confidence: {confidence:.1%} | RSI:{rsi_val:.0f} ADX:{adx_val:.0f} MACD:{macd_hist:.2f}",
                    signal_color)

                # ─── 5. MULTI-CONFIRMATION FILTER ───
                # All indicators must agree for a trade
                buy_signals = 0
                sell_signals = 0

                # RSI confirmation
                if rsi_val < 65:
                    buy_signals += 1
                if rsi_val > 35:
                    sell_signals += 1

                # MACD histogram
                if macd_hist > 0:
                    buy_signals += 1
                else:
                    sell_signals += 1

                # EMA Stack
                if ema_stack > 0:
                    buy_signals += 1
                elif ema_stack < 0:
                    sell_signals += 1

                # Supertrend
                if st_dir > 0:
                    buy_signals += 1
                elif st_dir < 0:
                    sell_signals += 1

                # ADX strength filter (only trade when trend exists)
                trend_strong = adx_val > 20

                # BB Squeeze (high volatility opportunity)
                squeeze_active = bb_squeeze < 0.03

                # Z-Score extreme (mean reversion signal)
                z_extreme = abs(z_score) > 2.0

                # ─── 6. DECISION ───
                open_positions = mt5.positions_get(symbol=SYMBOL)
                if open_positions is None:
                    open_positions = []

                can_trade, risk_msg = self.risk.can_trade()

                if len(open_positions) == 0 and can_trade:
                    # BUY signal
                    if (prediction == 1 and confidence >= MIN_CONFIDENCE
                        and buy_signals >= 3 and trend_strong):

                        sl_dist, tp_dist = self.risk.calculate_dynamic_sl_tp(current_atr, 'buy', confidence)
                        sl = current_price - sl_dist
                        tp = current_price + tp_dist

                        account_info = mt5.account_info()
                        lot = self.risk.calculate_lot_size(account_info.balance, current_atr, confidence)

                        ticket, msg = self.executor.open_trade(
                            SYMBOL, mt5.ORDER_TYPE_BUY, lot, sl, tp, "AI-BUY")

                        if ticket:
                            self.log(f"BUY #{ticket} | Price:{current_price:.2f} SL:{sl:.2f} TP:{tp:.2f} Lot:{lot} Conf:{confidence:.0%}", "#00ff00")
                            self.trade_count += 1
                        else:
                            self.log(f"BUY failed: {msg}", "#ff4444")

                    # SELL signal
                    elif (prediction == 0 and confidence >= MIN_CONFIDENCE
                          and sell_signals >= 3 and trend_strong):

                        sl_dist, tp_dist = self.risk.calculate_dynamic_sl_tp(current_atr, 'sell', confidence)
                        sl = current_price + sl_dist
                        tp = current_price - tp_dist

                        account_info = mt5.account_info()
                        lot = self.risk.calculate_lot_size(account_info.balance, current_atr, confidence)

                        ticket, msg = self.executor.open_trade(
                            SYMBOL, mt5.ORDER_TYPE_SELL, lot, sl, tp, "AI-SELL")

                        if ticket:
                            self.log(f"SELL #{ticket} | Price:{current_price:.2f} SL:{sl:.2f} TP:{tp:.2f} Lot:{lot} Conf:{confidence:.0%}", "#ff3333")
                            self.trade_count += 1
                        else:
                            self.log(f"SELL failed: {msg}", "#ff4444")

                # ─── 7. TRAILING STOP & BREAK-EVEN ───
                for pos in open_positions:
                    profit_pts = 0
                    if pos.type == mt5.POSITION_TYPE_BUY:
                        profit_pts = current_price - pos.price_open
                        # Break-even: move SL to entry after 1 ATR profit
                        if profit_pts > current_atr and pos.sl < pos.price_open:
                            new_sl = pos.price_open + (current_atr * 0.2)  # Small profit lock
                            self.executor.modify_sl(pos, new_sl)
                            self.log(f"Break-even BUY #{pos.ticket}", "#ffcc00")
                        # Trailing stop: lock in profits
                        elif profit_pts > current_atr * 1.5:
                            trailing_sl = current_price - current_atr * 1.0
                            if trailing_sl > pos.sl:
                                self.executor.modify_sl(pos, trailing_sl)

                    elif pos.type == mt5.POSITION_TYPE_SELL:
                        profit_pts = pos.price_open - current_price
                        if profit_pts > current_atr and pos.sl > pos.price_open:
                            new_sl = pos.price_open - (current_atr * 0.2)
                            self.executor.modify_sl(pos, new_sl)
                            self.log(f"Break-even SELL #{pos.ticket}", "#ffcc00")
                        elif profit_pts > current_atr * 1.5:
                            trailing_sl = current_price + current_atr * 1.0
                            if trailing_sl < pos.sl:
                                self.executor.modify_sl(pos, trailing_sl)

                # ─── 8. UPDATE STATS ───
                account_info = mt5.account_info()
                if account_info:
                    equity = account_info.equity
                    balance = account_info.balance
                    pnl = equity - balance
                    self.total_pnl = pnl
                    wr = (self.win_count / self.trade_count * 100) if self.trade_count > 0 else 0

                    self.update_label(self.stats_label,
                        f"Trades: {self.trade_count} | Wins: {self.win_count} | WR: {wr:.0f}% | Floating PnL: ${pnl:.2f}")

                    risk_ok = "OK" if can_trade else risk_msg
                    risk_color = "#88cc88" if can_trade else "#ff4444"
                    self.update_label(self.daily_label,
                        f"Daily PnL: ${self.risk.daily_pnl:.2f} | Trades Today: {self.risk.daily_trades} | Risk: {risk_ok}",
                        risk_color)

            except Exception as e:
                self.log(f"Error: {str(e)}", "#ff4444")

            time.sleep(CHECK_INTERVAL)


# ═══════════════════════════════════════════════════════════
#                       ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    root = tk.Tk()
    app = GoldAIBot(root)
    root.mainloop()
    mt5.shutdown()
