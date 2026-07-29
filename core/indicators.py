"""
مكتبة المؤشرات — تنفيذ متجهي بـ NumPy مطابق لسلوك Pine Script.
"""

from __future__ import annotations

import numpy as np


def rma(src: np.ndarray, length: int) -> np.ndarray:
    """Wilder's smoothing — نفس ta.rma في Pine."""
    n = len(src)
    out = np.full(n, np.nan)
    if n == 0 or length <= 0:
        return out
    alpha = 1.0 / length
    acc = np.nan
    for i in range(n):
        v = src[i]
        if np.isnan(v):
            continue
        if np.isnan(acc):
            if i + 1 >= length:
                window = src[i - length + 1:i + 1]
                if not np.isnan(window).any():
                    acc = float(np.mean(window))
                    out[i] = acc
            continue
        acc = alpha * v + (1 - alpha) * acc
        out[i] = acc
    return out


def sma(src: np.ndarray, length: int) -> np.ndarray:
    n = len(src)
    out = np.full(n, np.nan)
    if length <= 0 or n < length:
        return out
    c = np.cumsum(np.insert(np.nan_to_num(src, nan=0.0), 0, 0.0))
    vals = (c[length:] - c[:-length]) / length
    out[length - 1:] = vals
    return out


def ema(src: np.ndarray, length: int) -> np.ndarray:
    n = len(src)
    out = np.full(n, np.nan)
    if n == 0 or length <= 0:
        return out
    k = 2.0 / (length + 1.0)
    acc = np.nan
    for i in range(n):
        v = src[i]
        if np.isnan(v):
            continue
        acc = v if np.isnan(acc) else (v - acc) * k + acc
        out[i] = acc
    return out


def stdev(src: np.ndarray, length: int) -> np.ndarray:
    n = len(src)
    out = np.full(n, np.nan)
    if length <= 1 or n < length:
        return out
    s = np.nan_to_num(src, nan=0.0)
    c1 = np.cumsum(np.insert(s, 0, 0.0))
    c2 = np.cumsum(np.insert(s * s, 0, 0.0))
    m = (c1[length:] - c1[:-length]) / length
    m2 = (c2[length:] - c2[:-length]) / length
    var = np.maximum(m2 - m * m, 0.0)
    out[length - 1:] = np.sqrt(var)
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev = np.roll(close, 1)
    prev[0] = close[0]
    return np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    return rma(true_range(high, low, close), length)


def rsi(close: np.ndarray, length: int = 14) -> np.ndarray:
    d = np.diff(close, prepend=close[0])
    up = rma(np.where(d > 0, d, 0.0), length)
    dn = rma(np.where(d < 0, -d, 0.0), length)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(dn == 0, np.inf, up / dn)
    return 100.0 - 100.0 / (1.0 + rs)


def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int = 14):
    up_move = np.diff(high, prepend=high[0])
    dn_move = -np.diff(low, prepend=low[0])
    plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
    tr = rma(true_range(high, low, close), length)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * rma(plus_dm, length) / tr
        minus_di = 100.0 * rma(minus_dm, length) / tr
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    return rma(np.nan_to_num(dx, nan=0.0), length), plus_di, minus_di


def pivot_high(high: np.ndarray, left: int, right: int) -> np.ndarray:
    """يرجع مصفوفة: القيمة عند مؤشر تأكيد الـ pivot (مثل ta.pivothigh)."""
    n = len(high)
    out = np.full(n, np.nan)
    for i in range(left, n - right):
        v = high[i]
        if v >= high[i - left:i].max(initial=-np.inf) and \
           v > high[i + 1:i + right + 1].max(initial=-np.inf):
            out[i + right] = v
    return out


def pivot_low(low: np.ndarray, left: int, right: int) -> np.ndarray:
    n = len(low)
    out = np.full(n, np.nan)
    for i in range(left, n - right):
        v = low[i]
        if v <= low[i - left:i].min(initial=np.inf) and \
           v < low[i + 1:i + right + 1].min(initial=np.inf):
            out[i + right] = v
    return out


def cum(src: np.ndarray) -> np.ndarray:
    return np.cumsum(np.nan_to_num(src, nan=0.0))


def linreg_slope(src: np.ndarray, length: int) -> np.ndarray:
    n = len(src)
    out = np.full(n, np.nan)
    if n < length or length < 2:
        return out
    x = np.arange(length, dtype=float)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()
    for i in range(length - 1, n):
        y = src[i - length + 1:i + 1]
        out[i] = ((x - x_mean) * (y - y.mean())).sum() / denom
    return out
