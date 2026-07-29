"""
ULTRA-HFT QUANT CORE V6 — محرك الاستراتيجية
============================================
ترجمة كاملة لمنطق Pine Script إلى Python مع تحسينات:

  1) SMC   : Swing Structure + BOS + CHoCH + FVG
  2) OFI   : Order Flow Imbalance (Delta / Cumulative Delta / Volume Spike)
  3) Z-SCORE: انحراف إحصائي ومناطق الانعكاس المتطرفة
  4) SESSION: فلتر جلسات لندن/نيويورك
  5) RISK  : SL/TP بمضاعفات ATR + Break-Even + TP جزئي
  6) SCORE : نظام تقييم 0-100 بدل شرط "الكل أو لا شيء"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from . import indicators as ind


# ══════════════════════════════════════════════════════════════
@dataclass
class Signal:
    direction: int                  # 1 = LONG | -1 = SHORT | 0 = لا شيء
    score: float
    entry: float
    sl: float
    tp1: float
    tp2: float
    atr: float
    reasons: List[str] = field(default_factory=list)
    bar_time: int = 0
    bar_index: int = 0

    @property
    def side(self) -> str:
        return "BUY" if self.direction == 1 else ("SELL" if self.direction == -1 else "NONE")

    def to_dict(self) -> dict:
        return {
            "direction": self.direction, "side": self.side,
            "score": round(self.score, 1), "entry": self.entry, "sl": self.sl,
            "tp1": self.tp1, "tp2": self.tp2, "atr": self.atr,
            "reasons": self.reasons, "bar_time": self.bar_time,
            "bar_index": self.bar_index,
        }


def _parse_session(s: str):
    try:
        a, b = s.split("-")
        h1, m1 = [int(x) for x in a.replace(":", " ").split()[:2]] if ":" in a else (int(a[:2]), int(a[2:]))
        h2, m2 = [int(x) for x in b.replace(":", " ").split()[:2]] if ":" in b else (int(b[:2]), int(b[2:]))
        return h1 * 60 + m1, h2 * 60 + m2
    except Exception:
        return 0, 1440


class StrategyEngine:
    """يحلل مصفوفة الشموع ويُخرج كل الطبقات + الإشارة النهائية."""

    def __init__(self, params: Dict[str, Any]):
        self.p = dict(params)

    def update_params(self, params: Dict[str, Any]) -> None:
        self.p.update(params)

    # ──────────────────────────────────────────────────────
    def analyze(self, bars: List[dict]) -> Dict[str, Any]:
        n = len(bars)
        if n < 60:
            return {"ok": False, "error": "بيانات غير كافية للتحليل (نحتاج 60 شمعة على الأقل)"}

        p = self.p
        t = np.array([b["time"] for b in bars], dtype=np.int64)
        o = np.array([b["open"] for b in bars], dtype=float)
        h = np.array([b["high"] for b in bars], dtype=float)
        l = np.array([b["low"] for b in bars], dtype=float)
        c = np.array([b["close"] for b in bars], dtype=float)
        v = np.array([max(b.get("tick_volume", 0) or b.get("real_volume", 0), 1)
                      for b in bars], dtype=float)

        # ══ CORE ══════════════════════════════════════════
        atr_len = int(p["atr_len"])
        atr = ind.atr(h, l, c, atr_len)
        atr_safe = np.nan_to_num(atr, nan=0.0)

        # ── 1) MARKET STRUCTURE ───────────────────────────
        swing_len = int(p["swing_len"])
        ph = ind.pivot_high(h, swing_len, swing_len)
        pl = ind.pivot_low(l, swing_len, swing_len)

        trend = np.zeros(n, dtype=int)
        trend_line = np.full(n, np.nan)
        bos_up = np.zeros(n, dtype=bool)
        bos_dn = np.zeros(n, dtype=bool)
        choch_up = np.zeros(n, dtype=bool)
        choch_dn = np.zeros(n, dtype=bool)

        last_sh = np.nan
        last_sl = np.nan
        last_sh_bar = -1
        last_sl_bar = -1
        cur_trend = 0
        cur_line = np.nan
        prev_trend = 0
        swing_points: List[dict] = []

        for i in range(n):
            if not np.isnan(ph[i]):
                last_sh = ph[i]
                last_sh_bar = i - swing_len
                swing_points.append({"i": last_sh_bar, "time": int(t[last_sh_bar]),
                                     "price": float(last_sh), "type": "high"})
            if not np.isnan(pl[i]):
                last_sl = pl[i]
                last_sl_bar = i - swing_len
                swing_points.append({"i": last_sl_bar, "time": int(t[last_sl_bar]),
                                     "price": float(last_sl), "type": "low"})

            new_trend = cur_trend
            if not np.isnan(ph[i]) and not np.isnan(last_sl) and ph[i] > last_sl:
                new_trend = 1
                cur_line = last_sl
            if not np.isnan(pl[i]) and not np.isnan(last_sh) and pl[i] < last_sh:
                new_trend = -1
                cur_line = last_sh

            # كسر الهيكل بالإغلاق فوق/تحت آخر قمة/قاع
            if not np.isnan(last_sh) and c[i] > last_sh and new_trend >= 0:
                if cur_trend == 1:
                    bos_up[i] = True
                elif cur_trend == -1:
                    choch_up[i] = True
                new_trend = 1
                cur_line = last_sl if not np.isnan(last_sl) else cur_line
            if not np.isnan(last_sl) and c[i] < last_sl and new_trend <= 0:
                if cur_trend == -1:
                    bos_dn[i] = True
                elif cur_trend == 1:
                    choch_dn[i] = True
                new_trend = -1
                cur_line = last_sh if not np.isnan(last_sh) else cur_line

            prev_trend = cur_trend
            cur_trend = new_trend
            trend[i] = cur_trend
            trend_line[i] = cur_line

        # ── 2) FAIR VALUE GAPS ────────────────────────────
        fvg_filter = float(p["fvg_filter"])
        fvgs: List[dict] = []
        for i in range(2, n):
            gap_up = l[i] - h[i - 2]
            if gap_up > 0 and gap_up > atr_safe[i] * fvg_filter:
                fvgs.append({"type": "bull", "i": i, "t1": int(t[i - 2]), "t2": int(t[i]),
                             "top": float(l[i]), "bottom": float(h[i - 2]),
                             "size": float(gap_up)})
            gap_dn = l[i - 2] - h[i]
            if gap_dn > 0 and gap_dn > atr_safe[i] * fvg_filter:
                fvgs.append({"type": "bear", "i": i, "t1": int(t[i - 2]), "t2": int(t[i]),
                             "top": float(l[i - 2]), "bottom": float(h[i]),
                             "size": float(gap_dn)})

        # تعليم الفجوات المملوءة + إبقاء آخر 40
        last_px = c[-1]
        for f in fvgs:
            after = slice(f["i"] + 1, n)
            filled = False
            if f["type"] == "bull":
                filled = bool((l[after] <= f["bottom"]).any()) if f["i"] + 1 < n else False
            else:
                filled = bool((h[after] >= f["top"]).any()) if f["i"] + 1 < n else False
            f["filled"] = filled
            f["active"] = not filled
        fvgs = fvgs[-40:]

        # ── 3) ORDER FLOW IMBALANCE ───────────────────────
        ofi_len = int(p["ofi_len"])
        delta_len = int(p["delta_len"])
        vol_mult = float(p["vol_mult"])

        rng = np.maximum(h - l, 1e-12)
        # دلتا مرجّحة بموقع الإغلاق داخل الشمعة (تقدير أدق من close-open)
        weight = ((c - l) - (h - c)) / rng
        delta = v * weight
        cum_delta = ind.cum(delta)
        delta_ma = ind.sma(cum_delta, delta_len)
        vol_ma = ind.sma(v, ofi_len)
        with np.errstate(divide="ignore", invalid="ignore"):
            rel_vol = np.where(vol_ma > 0, v / vol_ma, 1.0)
        rel_vol = np.nan_to_num(rel_vol, nan=1.0, posinf=1.0)

        body = np.abs(c - o)
        vol_spike = (rel_vol > vol_mult) & (body > atr_safe * 0.3)
        use_ofi = bool(p["use_ofi"])
        dma = np.nan_to_num(delta_ma, nan=0.0)
        bull_ofi = use_ofi & (c > o) & (delta > 0) & (cum_delta > dma) & vol_spike
        bear_ofi = use_ofi & (c < o) & (delta < 0) & (cum_delta < dma) & vol_spike

        # ── 4) Z-SCORE ────────────────────────────────────
        z_len = int(p["z_len"])
        mean_c = ind.sma(c, z_len)
        std_c = ind.stdev(c, z_len)
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(std_c > 0, (c - mean_c) / std_c, 0.0)
        z = np.nan_to_num(z, nan=0.0, posinf=0.0, neginf=0.0)

        z_thresh = float(p["z_thresh"])
        z_extreme = float(p["z_extreme"])

        # ── 5) مؤشرات إضافية للتقييم ──────────────────────
        rsi14 = np.nan_to_num(ind.rsi(c, 14), nan=50.0)
        adx14, plus_di, minus_di = ind.adx(h, l, c, 14)
        adx14 = np.nan_to_num(adx14, nan=0.0)
        ema_fast = ind.ema(c, 21)
        ema_slow = ind.ema(c, 55)
        slope = np.nan_to_num(ind.linreg_slope(c, 20), nan=0.0)

        # ── 6) فلتر الجلسات ───────────────────────────────
        sess_ok = self._session_ok(int(t[-1]))

        # ══ نظام التقييم (Score) ══════════════════════════
        i = n - 1
        long_reasons: List[str] = []
        short_reasons: List[str] = []
        ls = 0.0
        ss = 0.0

        # لا نطلب الإشارة على نفس الشمعة فقط — نبحث في آخر 3 شموع
        look = 3
        seg = slice(max(0, n - look), n)

        if bos_up[seg].any():
            ls += 22; long_reasons.append("BOS صاعد (كسر هيكل)")
        if choch_up[seg].any():
            ls += 26; long_reasons.append("CHoCH صاعد (تغيّر طابع)")
        if bos_dn[seg].any():
            ss += 22; short_reasons.append("BOS هابط (كسر هيكل)")
        if choch_dn[seg].any():
            ss += 26; short_reasons.append("CHoCH هابط (تغيّر طابع)")

        if trend[i] == 1:
            ls += 10; long_reasons.append("الاتجاه العام صاعد")
        elif trend[i] == -1:
            ss += 10; short_reasons.append("الاتجاه العام هابط")

        if bull_ofi[seg].any():
            ls += 20; long_reasons.append(f"تدفق أوامر شرائي (RelVol {rel_vol[i]:.2f}x)")
        if bear_ofi[seg].any():
            ss += 20; short_reasons.append(f"تدفق أوامر بيعي (RelVol {rel_vol[i]:.2f}x)")

        if cum_delta[i] > dma[i]:
            ls += 6; long_reasons.append("الدلتا التراكمية فوق متوسطها")
        else:
            ss += 6; short_reasons.append("الدلتا التراكمية تحت متوسطها")

        if bool(p["use_z"]):
            if z[i] <= -z_extreme:
                ls += 22; long_reasons.append(f"Z-Score تشبع بيعي متطرف ({z[i]:.2f})")
            elif z[i] <= -z_thresh:
                ls += 12; long_reasons.append(f"Z-Score تحت العتبة ({z[i]:.2f})")
            if z[i] >= z_extreme:
                ss += 22; short_reasons.append(f"Z-Score تشبع شرائي متطرف ({z[i]:.2f})")
            elif z[i] >= z_thresh:
                ss += 12; short_reasons.append(f"Z-Score فوق العتبة ({z[i]:.2f})")

        # FVG نشطة قريبة من السعر
        for f in fvgs[-8:]:
            if not f["active"]:
                continue
            near = abs(last_px - (f["top"] + f["bottom"]) / 2) < atr_safe[i] * 2
            if near and f["type"] == "bull":
                ls += 8; long_reasons.append("فجوة قيمة عادلة صاعدة قريبة")
                break
            if near and f["type"] == "bear":
                ss += 8; short_reasons.append("فجوة قيمة عادلة هابطة قريبة")
                break

        if rsi14[i] < 32:
            ls += 8; long_reasons.append(f"RSI تشبع بيعي ({rsi14[i]:.1f})")
        elif rsi14[i] > 68:
            ss += 8; short_reasons.append(f"RSI تشبع شرائي ({rsi14[i]:.1f})")

        if adx14[i] > 22:
            if plus_di[i] > minus_di[i]:
                ls += 8; long_reasons.append(f"ADX قوي صاعد ({adx14[i]:.1f})")
            else:
                ss += 8; short_reasons.append(f"ADX قوي هابط ({adx14[i]:.1f})")

        if not np.isnan(ema_fast[i]) and not np.isnan(ema_slow[i]):
            if ema_fast[i] > ema_slow[i]:
                ls += 6; long_reasons.append("EMA21 فوق EMA55")
            else:
                ss += 6; short_reasons.append("EMA21 تحت EMA55")

        if slope[i] > 0:
            ls += 4
        else:
            ss += 4

        ls = min(ls, 100.0)
        ss = min(ss, 100.0)

        # ══ قرار الدخول ═══════════════════════════════════
        mode = str(p.get("signal_mode", "balanced"))
        min_score = float(p.get("min_score", 65))
        atr_now = float(atr_safe[i]) or float(np.mean(rng[-14:]))

        direction = 0
        score = 0.0
        reasons: List[str] = []

        if mode == "strict":
            strict_long = ((bos_up[seg].any() or choch_up[seg].any())
                           and bull_ofi[seg].any() and z[i] < -z_extreme)
            strict_short = ((bos_dn[seg].any() or choch_dn[seg].any())
                            and bear_ofi[seg].any() and z[i] > z_extreme)
            if strict_long:
                direction, score, reasons = 1, ls, long_reasons
            elif strict_short:
                direction, score, reasons = -1, ss, short_reasons
        else:
            threshold = min_score if mode == "balanced" else max(min_score - 15, 35)
            if ls >= threshold and ls > ss:
                direction, score, reasons = 1, ls, long_reasons
            elif ss >= threshold and ss > ls:
                direction, score, reasons = -1, ss, short_reasons

        if bool(p["sess_on"]) and not sess_ok:
            direction = 0
            reasons = ["خارج جلسات التداول المسموحة"]

        entry = float(c[i])
        sl_mult = float(p["sl_atr"])
        tp1_mult = float(p["tp1_atr"])
        tp2_mult = float(p["tp2_atr"])

        if direction == 1:
            sl = entry - atr_now * sl_mult
            tp1 = entry + atr_now * tp1_mult
            tp2 = entry + atr_now * tp2_mult
        elif direction == -1:
            sl = entry + atr_now * sl_mult
            tp1 = entry - atr_now * tp1_mult
            tp2 = entry - atr_now * tp2_mult
        else:
            sl = tp1 = tp2 = 0.0

        signal = Signal(direction=direction, score=score, entry=entry, sl=sl,
                        tp1=tp1, tp2=tp2, atr=atr_now, reasons=reasons[:6],
                        bar_time=int(t[i]), bar_index=i)

        # ══ backtest داخلي على النافذة ════════════════════
        stats = self.backtest(t, o, h, l, c, ls_arr=None, bars_meta=(
            bos_up, bos_dn, choch_up, choch_dn, bull_ofi, bear_ofi, z, atr_safe, trend))

        # ══ الإخراج ═══════════════════════════════════════
        markers = []
        start = max(0, n - 300)
        for k in range(start, n):
            if bos_up[k]:
                markers.append({"time": int(t[k]), "price": float(l[k]), "type": "bos_up"})
            if bos_dn[k]:
                markers.append({"time": int(t[k]), "price": float(h[k]), "type": "bos_dn"})
            if choch_up[k]:
                markers.append({"time": int(t[k]), "price": float(l[k]), "type": "choch_up"})
            if choch_dn[k]:
                markers.append({"time": int(t[k]), "price": float(h[k]), "type": "choch_dn"})
            if bull_ofi[k]:
                markers.append({"time": int(t[k]), "price": float(l[k]), "type": "ofi_bull"})
            if bear_ofi[k]:
                markers.append({"time": int(t[k]), "price": float(h[k]), "type": "ofi_bear"})

        return {
            "ok": True,
            "signal": signal.to_dict(),
            "scores": {"long": round(ls, 1), "short": round(ss, 1)},
            "state": {
                "trend": int(trend[i]),
                "trend_line": None if np.isnan(trend_line[i]) else float(trend_line[i]),
                "z_score": round(float(z[i]), 3),
                "rel_vol": round(float(rel_vol[i]), 2),
                "cum_delta": round(float(cum_delta[i]), 1),
                "delta_ma": round(float(dma[i]), 1),
                "atr": round(atr_now, 8),
                "rsi": round(float(rsi14[i]), 1),
                "adx": round(float(adx14[i]), 1),
                "ema_fast": None if np.isnan(ema_fast[i]) else round(float(ema_fast[i]), 8),
                "ema_slow": None if np.isnan(ema_slow[i]) else round(float(ema_slow[i]), 8),
                "ofi": "BULL" if bull_ofi[i] else ("BEAR" if bear_ofi[i] else "IDLE"),
                "session_ok": sess_ok,
                "price": float(c[i]),
                "bar_time": int(t[i]),
            },
            "series": {
                "z": [round(float(x), 3) for x in z[-200:]],
                "cum_delta": [round(float(x), 2) for x in cum_delta[-200:]],
                "rel_vol": [round(float(x), 2) for x in rel_vol[-200:]],
                "times": [int(x) for x in t[-200:]],
                "ema_fast": [None if np.isnan(x) else round(float(x), 8) for x in ema_fast[-200:]],
                "ema_slow": [None if np.isnan(x) else round(float(x), 8) for x in ema_slow[-200:]],
            },
            "fvgs": fvgs,
            "swings": swing_points[-30:],
            "markers": markers[-150:],
            "stats": stats,
        }

    # ──────────────────────────────────────────────────────
    def _session_ok(self, ts: int) -> bool:
        p = self.p
        if not bool(p.get("sess_on")):
            return True
        dt = datetime.fromtimestamp(ts, timezone.utc)
        mins = dt.hour * 60 + dt.minute
        for s in (p.get("london_sess", "08:00-17:00"), p.get("ny_sess", "13:00-22:00")):
            a, b = _parse_session(s)
            if a <= b:
                if a <= mins < b:
                    return True
            else:
                if mins >= a or mins < b:
                    return True
        return False

    # ──────────────────────────────────────────────────────
    def backtest(self, t, o, h, l, c, ls_arr=None, bars_meta=None) -> Dict[str, Any]:
        """محاكاة سريعة للاستراتيجية على البيانات المحمّلة (بدون منحنى رصيد)."""
        if bars_meta is None:
            return {}
        bos_up, bos_dn, choch_up, choch_dn, bull_ofi, bear_ofi, z, atr_s, trend = bars_meta
        p = self.p
        n = len(c)
        sl_m, tp1_m, tp2_m = float(p["sl_atr"]), float(p["tp1_atr"]), float(p["tp2_atr"])
        z_ext = float(p["z_extreme"])
        z_th = float(p["z_thresh"])
        mode = str(p.get("signal_mode", "balanced"))

        trades: List[dict] = []
        active = False
        d = 0
        entry = sl = tp1 = tp2 = 0.0
        tp1_hit = False
        entry_i = 0
        r_unit = 0.0

        for i in range(60, n):
            if active:
                if d == 1:
                    if not tp1_hit and h[i] >= tp1:
                        tp1_hit = True
                        sl = max(sl, entry)
                    if l[i] <= sl:
                        trades.append({"dir": d, "in": entry, "out": sl, "i": i,
                                       "r": (sl - entry) / r_unit if r_unit else 0.0,
                                       "t": int(t[i]), "bars": i - entry_i})
                        active = False
                        continue
                    if h[i] >= tp2:
                        trades.append({"dir": d, "in": entry, "out": tp2, "i": i,
                                       "r": (tp2 - entry) / r_unit if r_unit else 0.0,
                                       "t": int(t[i]), "bars": i - entry_i})
                        active = False
                        continue
                else:
                    if not tp1_hit and l[i] <= tp1:
                        tp1_hit = True
                        sl = min(sl, entry)
                    if h[i] >= sl:
                        trades.append({"dir": d, "in": entry, "out": sl, "i": i,
                                       "r": (entry - sl) / r_unit if r_unit else 0.0,
                                       "t": int(t[i]), "bars": i - entry_i})
                        active = False
                        continue
                    if l[i] <= tp2:
                        trades.append({"dir": d, "in": entry, "out": tp2, "i": i,
                                       "r": (entry - tp2) / r_unit if r_unit else 0.0,
                                       "t": int(t[i]), "bars": i - entry_i})
                        active = False
                        continue
            if active:
                continue

            a = atr_s[i]
            if a <= 0:
                continue
            long_ok = (bos_up[i] or choch_up[i]) and (bull_ofi[i] or z[i] < -z_th)
            short_ok = (bos_dn[i] or choch_dn[i]) and (bear_ofi[i] or z[i] > z_th)
            if mode == "strict":
                long_ok = (bos_up[i] or choch_up[i]) and bull_ofi[i] and z[i] < -z_ext
                short_ok = (bos_dn[i] or choch_dn[i]) and bear_ofi[i] and z[i] > z_ext

            if long_ok:
                active, d, entry_i, tp1_hit = True, 1, i, False
                entry = c[i]
                sl, tp1, tp2 = entry - a * sl_m, entry + a * tp1_m, entry + a * tp2_m
                r_unit = a * sl_m
            elif short_ok:
                active, d, entry_i, tp1_hit = True, -1, i, False
                entry = c[i]
                sl, tp1, tp2 = entry + a * sl_m, entry - a * tp1_m, entry - a * tp2_m
                r_unit = a * sl_m

        wins = [x for x in trades if x["r"] > 0]
        losses = [x for x in trades if x["r"] <= 0]
        gp = sum(x["r"] for x in wins)
        gl = abs(sum(x["r"] for x in losses))
        total = len(trades)
        wr = (len(wins) / total * 100.0) if total else 0.0
        pf = (gp / gl) if gl > 0 else (999.0 if gp > 0 else 0.0)
        avg_w = (gp / len(wins)) if wins else 0.0
        avg_l = (gl / len(losses)) if losses else 0.0
        exp_r = (wr / 100.0) * avg_w - (1 - wr / 100.0) * avg_l

        # أقصى تراجع بوحدات R
        peak = 0.0
        cum_r = 0.0
        mdd = 0.0
        streak = best_streak = worst_streak = cur = 0
        for x in trades:
            cum_r += x["r"]
            peak = max(peak, cum_r)
            mdd = max(mdd, peak - cum_r)
            if x["r"] > 0:
                cur = cur + 1 if cur > 0 else 1
                best_streak = max(best_streak, cur)
            else:
                cur = cur - 1 if cur < 0 else -1
                worst_streak = min(worst_streak, cur)

        return {
            "total_trades": total,
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(wr, 1),
            "profit_factor": round(pf, 2),
            "expectancy_r": round(exp_r, 3),
            "gross_profit_r": round(gp, 2),
            "gross_loss_r": round(gl, 2),
            "net_r": round(gp - gl, 2),
            "max_dd_r": round(mdd, 2),
            "avg_win_r": round(avg_w, 2),
            "avg_loss_r": round(avg_l, 2),
            "best_streak": best_streak,
            "worst_streak": abs(worst_streak),
            "avg_bars": round(sum(x["bars"] for x in trades) / total, 1) if total else 0.0,
            "recent": [{"dir": x["dir"], "r": round(x["r"], 2), "time": x["t"]}
                       for x in trades[-25:]],
        }
