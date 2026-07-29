# -*- coding: utf-8 -*-
"""
==============================================================
  مؤشرات فنية — تنفيذ نظيف بـ pandas/numpy فقط (بدون مكتبات خارجية)
  كل الحسابات سببية (Causal): لا تنظر للمستقبل إطلاقاً
==============================================================
"""
import numpy as np
import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """متوسط المدى الحقيقي (تنعيم Wilder)"""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """متوسط متحرك أسي"""
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """مؤشر القوة النسبية (تنعيم Wilder)"""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    # عندما يكون avg_loss = 0 ⇒ RSI = 100
    out = out.where(avg_loss != 0, 100.0)
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD → (الخط، خط الإشارة، الهيستوجرام)"""
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def bollinger(close: pd.Series, period: int = 20, mult: float = 2.0):
    """بولنجر باند → (العلوي، الأوسط، السفلي)"""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    return mid + mult * std, mid, mid - mult * std


def highest(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).max()


def lowest(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).min()
