# -*- coding: utf-8 -*-
"""
==============================================================
  بنك الاستراتيجيات — 4 محركات إشارات قابلة للاختيار
  ----------------------------------------------------------
  smc : APEX SMC (مؤسساتي — BOS/CHoCH + سيولة + OB/FVG + دلتا)
  ema : تقاطع EMA 9/21 مع فلتر الاتجاه EMA200
  rsi : انعكاس RSI من التشبع مع اتجاه EMA200
  macd: تقاطع MACD + زخم الهيستوجرام + فلتر الاتجاه
  ----------------------------------------------------------
  كل استراتيجية تُرجع: اتجاه + درجة قوة + مسافة الوقف + الأسباب
==============================================================
"""
import numpy as np
import pandas as pd

import indicators as ind
from config import Config
from engine import ApexEngine, Signal, in_killzone


class StrategyBase:
    name: str = ""
    label: str = ""

    @classmethod
    def last_signal(cls, df: pd.DataFrame, cfg: Config) -> Signal:
        """إشارة آخر شمعة مغلقة (للتشغيل المباشر)"""
        last = Signal()
        for _, sig in cls.stream_signals(df, cfg):
            last = sig
        return last if last.direction != 0 else cls._state_signal(df, cfg)

    @classmethod
    def _state_signal(cls, df: pd.DataFrame, cfg: Config) -> Signal:
        return Signal()

    @classmethod
    def stream_signals(cls, df: pd.DataFrame, cfg: Config):
        """يولّد (رقم الشمعة، الإشارة) لكل شمعة — للباك تست"""
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════
#  1) استراتيجية APEX SMC — المحرك المؤسساتي الكامل
# ═══════════════════════════════════════════════════════════
class SMCStrategy(StrategyBase):
    name = "smc"
    label = "APEX SMC — تدفق الأوامر المؤسساتي (الأقوى)"

    @classmethod
    def stream_signals(cls, df, cfg):
        eng = ApexEngine(cfg)
        for i, row in enumerate(df.itertuples(index=False)):
            sig = eng.update(row.time, row.open, row.high, row.low, row.close, float(row.volume))
            if sig.direction != 0:
                yield i, sig
        cls._engine = eng

    @classmethod
    def last_signal(cls, df, cfg):
        eng = ApexEngine(cfg)
        sig = Signal()
        for row in df.itertuples(index=False):
            sig = eng.update(row.time, row.open, row.high, row.low, row.close, float(row.volume))
        # حتى بدون إشارة جديدة، نعرض حالة المحرك (الدرجة الحالية)
        if sig.direction == 0:
            sig.trend = eng.trend
        return sig


# ═══════════════════════════════════════════════════════════
#  2) استراتيجية تقاطع المتوسطات EMA 9/21
# ═══════════════════════════════════════════════════════════
class EmaCrossStrategy(StrategyBase):
    name = "ema"
    label = "EMA Cross — تقاطع 9/21 مع فلتر اتجاه 200"

    @classmethod
    def _prepare(cls, df, cfg):
        return {
            "c": df["close"].to_numpy(),
            "e9": ind.ema(df["close"], 9).to_numpy(),
            "e21": ind.ema(df["close"], 21).to_numpy(),
            "e200": ind.ema(df["close"], 200).to_numpy(),
            "a": ind.atr(df, cfg.atr_period).to_numpy(),
            "t": df["time"].tolist(),
        }

    @classmethod
    def _at(cls, d, i, cfg):
        sig = Signal()
        if i < 1 or np.isnan(d["a"][i]) or np.isnan(d["e200"][i]):
            return sig
        sig.atr = float(d["a"][i])
        sig.sl_dist = sig.atr * cfg.atr_sl_mult
        e9, e21, e200, c = d["e9"][i], d["e21"][i], d["e200"][i], d["c"][i]
        e9p, e21p = d["e9"][i - 1], d["e21"][i - 1]
        cross_up = e9 > e21 and e9p <= e21p
        cross_dn = e9 < e21 and e9p >= e21p
        kz = in_killzone(d["t"][i], cfg)

        score_long = score_short = 0
        r_l, r_s = [], []
        if cross_up:
            score_long += 2; r_l.append("تقاطع EMA 9/21 صاعد")
        if cross_dn:
            score_short += 2; r_s.append("تقاطع EMA 9/21 هابط")
        if c > e200:
            score_long += 1; r_l.append("فوق EMA200 (اتجاه صاعد)")
        if c < e200:
            score_short += 1; r_s.append("تحت EMA200 (اتجاه هابط)")
        if e9 > e21:
            score_long += 1
        if e9 < e21:
            score_short += 1
        if kz:
            score_long += 1; r_l.append("Kill Zone")
            score_short += 1; r_s.append("Kill Zone")

        sig.score_long, sig.score_short = score_long, score_short
        cooldown = getattr(cls, "_last", -10_000)
        if cross_up and score_long >= cfg.min_score and i - cooldown > cfg.swing_len:
            sig.direction, sig.score, sig.reasons = 1, score_long, r_l
            cls._last = i
        elif cross_dn and score_short >= cfg.min_score and i - cooldown > cfg.swing_len:
            sig.direction, sig.score, sig.reasons = -1, score_short, r_s
            cls._last = i
        return sig

    @classmethod
    def stream_signals(cls, df, cfg):
        cls._last = -10_000
        d = cls._prepare(df, cfg)
        for i in range(len(df)):
            sig = cls._at(d, i, cfg)
            if sig.direction != 0:
                yield i, sig

    @classmethod
    def last_signal(cls, df, cfg):
        cls._last = -10_000
        d = cls._prepare(df, cfg)
        return cls._at(d, len(df) - 1, cfg)


# ═══════════════════════════════════════════════════════════
#  3) استراتيجية انعكاس RSI
# ═══════════════════════════════════════════════════════════
class RsiReversalStrategy(StrategyBase):
    name = "rsi"
    label = "RSI Reversal — انعكاس من التشبع مع الاتجاه العام"

    @classmethod
    def _prepare(cls, df, cfg):
        return {
            "c": df["close"].to_numpy(),
            "r": ind.rsi(df["close"], 14).to_numpy(),
            "e200": ind.ema(df["close"], 200).to_numpy(),
            "a": ind.atr(df, cfg.atr_period).to_numpy(),
            "t": df["time"].tolist(),
        }

    @classmethod
    def _at(cls, d, i, cfg):
        sig = Signal()
        if i < 1 or np.isnan(d["r"][i]) or np.isnan(d["e200"][i]) or np.isnan(d["a"][i]):
            return sig
        sig.atr = float(d["a"][i])
        sig.sl_dist = sig.atr * cfg.atr_sl_mult
        r, rp = d["r"][i], d["r"][i - 1]
        c, e200 = d["c"][i], d["e200"][i]
        exit_os = r > 30 and rp <= 30      # خروج من التشبع البيعي
        exit_ob = r < 70 and rp >= 70      # خروج من التشبع الشرائي
        kz = in_killzone(d["t"][i], cfg)

        score_long = score_short = 0
        r_l, r_s = [], []
        if exit_os:
            score_long += 2; r_l.append(f"خروج من تشبع بيعي (RSI={r:.0f})")
        if exit_ob:
            score_short += 2; r_s.append(f"خروج من تشبع شرائي (RSI={r:.0f})")
        if c > e200:
            score_long += 2; r_l.append("فوق EMA200")
        if c < e200:
            score_short += 2; r_s.append("تحت EMA200")
        if kz:
            score_long += 1; r_l.append("Kill Zone")
            score_short += 1; r_s.append("Kill Zone")

        sig.score_long, sig.score_short = score_long, score_short
        cooldown = getattr(cls, "_last", -10_000)
        if exit_os and c > e200 and score_long >= cfg.min_score and i - cooldown > cfg.swing_len:
            sig.direction, sig.score, sig.reasons = 1, score_long, r_l
            cls._last = i
        elif exit_ob and c < e200 and score_short >= cfg.min_score and i - cooldown > cfg.swing_len:
            sig.direction, sig.score, sig.reasons = -1, score_short, r_s
            cls._last = i
        return sig

    @classmethod
    def stream_signals(cls, df, cfg):
        cls._last = -10_000
        d = cls._prepare(df, cfg)
        for i in range(len(df)):
            sig = cls._at(d, i, cfg)
            if sig.direction != 0:
                yield i, sig

    @classmethod
    def last_signal(cls, df, cfg):
        cls._last = -10_000
        d = cls._prepare(df, cfg)
        return cls._at(d, len(df) - 1, cfg)


# ═══════════════════════════════════════════════════════════
#  4) استراتيجية MACD
# ═══════════════════════════════════════════════════════════
class MacdTrendStrategy(StrategyBase):
    name = "macd"
    label = "MACD Trend — تقاطع + زخم + فلتر اتجاه"

    @classmethod
    def _prepare(cls, df, cfg):
        line, signal, hist = ind.macd(df["close"])
        return {
            "c": df["close"].to_numpy(),
            "m": line.to_numpy(),
            "s": signal.to_numpy(),
            "h": hist.to_numpy(),
            "e200": ind.ema(df["close"], 200).to_numpy(),
            "a": ind.atr(df, cfg.atr_period).to_numpy(),
            "t": df["time"].tolist(),
        }

    @classmethod
    def _at(cls, d, i, cfg):
        sig = Signal()
        if i < 1 or np.isnan(d["s"][i]) or np.isnan(d["e200"][i]) or np.isnan(d["a"][i]):
            return sig
        sig.atr = float(d["a"][i])
        sig.sl_dist = sig.atr * cfg.atr_sl_mult
        m, s, h = d["m"][i], d["s"][i], d["h"][i]
        mp, sp, hp = d["m"][i - 1], d["s"][i - 1], d["h"][i - 1]
        c, e200 = d["c"][i], d["e200"][i]
        cross_up = m > s and mp <= sp
        cross_dn = m < s and mp >= sp
        kz = in_killzone(d["t"][i], cfg)

        score_long = score_short = 0
        r_l, r_s = [], []
        if cross_up:
            score_long += 2; r_l.append("تقاطع MACD صاعد")
        if cross_dn:
            score_short += 2; r_s.append("تقاطع MACD هابط")
        if h > hp:
            score_long += 1; r_l.append("زخم متزايد")
        if h < hp:
            score_short += 1; r_s.append("زخم متناقص")
        if c > e200:
            score_long += 1; r_l.append("فوق EMA200")
        if c < e200:
            score_short += 1; r_s.append("تحت EMA200")
        if kz:
            score_long += 1; r_l.append("Kill Zone")
            score_short += 1; r_s.append("Kill Zone")

        sig.score_long, sig.score_short = score_long, score_short
        cooldown = getattr(cls, "_last", -10_000)
        if cross_up and score_long >= cfg.min_score and i - cooldown > cfg.swing_len:
            sig.direction, sig.score, sig.reasons = 1, score_long, r_l
            cls._last = i
        elif cross_dn and score_short >= cfg.min_score and i - cooldown > cfg.swing_len:
            sig.direction, sig.score, sig.reasons = -1, score_short, r_s
            cls._last = i
        return sig

    @classmethod
    def stream_signals(cls, df, cfg):
        cls._last = -10_000
        d = cls._prepare(df, cfg)
        for i in range(len(df)):
            sig = cls._at(d, i, cfg)
            if sig.direction != 0:
                yield i, sig

    @classmethod
    def last_signal(cls, df, cfg):
        cls._last = -10_000
        d = cls._prepare(df, cfg)
        return cls._at(d, len(df) - 1, cfg)


# ═══════════════════════════════════════════════════════════
STRATEGIES = {
    SMCStrategy.name: SMCStrategy,
    EmaCrossStrategy.name: EmaCrossStrategy,
    RsiReversalStrategy.name: RsiReversalStrategy,
    MacdTrendStrategy.name: MacdTrendStrategy,
}


def get_strategy(name: str):
    if name not in STRATEGIES:
        raise ValueError(f"استراتيجية غير معروفة: {name} — المتاح: {list(STRATEGIES)}")
    return STRATEGIES[name]
