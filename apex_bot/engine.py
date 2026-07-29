# -*- coding: utf-8 -*-
"""
==============================================================
  APEX LIQUIDITY ENGINE — Python (نقل دقيق لمحرك Pine Script)
  ----------------------------------------------------------
  7 محركات مؤسساتية (Smart Money / ICT):
    1) Market Structure  : BOS / CHoCH
    2) Liquidity Sweep   : اصطياد الستوبات (Stop Hunt)
    3) Equal Highs/Lows  : مغناطيس السيولة
    4) Order Blocks      : أوردر بلوك مع Mitigation
    5) Fair Value Gap    : فجوات عدم التوازن
    6) Delta Volume      : ضغط المشترين مقابل البائعين
    7) Kill Zones + Premium/Discount
  + نظام تقييم 0-5 (لا إشارة إلا باجتماع عدة شروط)
==============================================================
"""
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Signal:
    """نتيجة تحليل شمعة واحدة"""
    direction: int = 0          # 1 = شراء | -1 = بيع | 0 = لا إشارة
    score: int = 0              # درجة الاتجاه المختار
    score_long: int = 0
    score_short: int = 0
    atr: float = 0.0
    sl_dist: float = 0.0        # مسافة وقف الخسارة بالسعر
    trend: int = 0              # اتجاه الهيكل الحالي 1/-1/0
    reasons: List[str] = field(default_factory=list)


def in_killzone(dt, cfg) -> bool:
    """جلسات المؤسسات: لندن 07-10 UTC ونيويورك 12:30-16 UTC"""
    h = (dt.hour + dt.minute / 60.0) - cfg.broker_utc_offset
    return (7.0 <= h < 10.0) or (12.5 <= h < 16.0)


class ApexEngine:
    """محرك SMC تزايدي: تُغذّيه شمعة شمعة ويعطيك إشارة كل شمعة"""

    def __init__(self, cfg):
        self.cfg = cfg
        sw = cfg.swing_len
        # مخازن الشموع (يكفي أقدمها لحساب FVG و OB)
        self.o = deque(maxlen=3)
        self.c = deque(maxlen=3)
        hl = max(60, 2 * sw + 3)
        self.h = deque(maxlen=hl)
        self.l = deque(maxlen=hl)
        # مخازن القمم/القيعان للكشف عن الـ Swing
        self.ph_buf = deque(maxlen=2 * sw + 1)
        self.pl_buf = deque(maxlen=2 * sw + 1)
        # حالة الهيكل السعري
        self.last_ph: Optional[float] = None
        self.last_pl: Optional[float] = None
        self.prev_ph: Optional[float] = None
        self.prev_pl: Optional[float] = None
        self.trend = 0
        # مناطق المؤسسات
        self.obs: List[dict] = []     # {"top","bot","dir"}
        self.fvgs: List[dict] = []
        # ATR تزايدي (Wilder)
        self.atr: Optional[float] = None
        self._tr_seed: List[float] = []
        self.prev_close: Optional[float] = None
        # دلتا الحجم
        self.ema_delta: Optional[float] = None
        self.ema_vol: Optional[float] = None
        # نطاق البريميوم/الخصم
        self.hi50 = deque(maxlen=50)
        self.lo50 = deque(maxlen=50)
        # تبريد الإشارات
        self.last_sig_bar = -10_000
        self.bar_i = -1

    # ----------------------------------------------------------
    def update(self, dt, o: float, h: float, l: float, c: float, v: float) -> Signal:
        """إدخال شمعة مغلقة واحدة → إرجاع إشارتها"""
        cfg = self.cfg
        self.bar_i += 1
        i = self.bar_i
        sig = Signal()
        sig.atr = self.atr or 0.0

        # ── ATR (Wilder) ──
        if self.prev_close is not None:
            tr = max(h - l, abs(h - self.prev_close), abs(l - self.prev_close))
        else:
            tr = h - l
        if self.atr is None:
            self._tr_seed.append(tr)
            if len(self._tr_seed) >= cfg.atr_period:
                self.atr = sum(self._tr_seed) / cfg.atr_period
        else:
            self.atr = (self.atr * (cfg.atr_period - 1) + tr) / cfg.atr_period

        # ── كشف القمم/القيعان (Swing) — تؤكد بعد swLen شمعة ──
        self.ph_buf.append(h)
        self.pl_buf.append(l)
        sw = cfg.swing_len
        new_ph = new_pl = None
        if len(self.ph_buf) == 2 * sw + 1:
            arr = list(self.ph_buf)
            cand = arr[sw]
            if all(cand > x for j, x in enumerate(arr) if j != sw):
                new_ph = cand
        if len(self.pl_buf) == 2 * sw + 1:
            arr = list(self.pl_buf)
            cand = arr[sw]
            if all(cand < x for j, x in enumerate(arr) if j != sw):
                new_pl = cand
        if new_ph is not None:
            self.prev_ph = self.last_ph
            self.last_ph = new_ph
        if new_pl is not None:
            self.prev_pl = self.last_pl
            self.last_pl = new_pl

        # ── 1) الهيكل: BOS / CHoCH ──
        bos_up = choch_up = bos_dn = choch_dn = False
        pc = self.prev_close
        if self.last_ph is not None and pc is not None and pc <= self.last_ph < c:
            if self.trend == -1:
                choch_up = True
            else:
                bos_up = True
            self.trend = 1
            self.last_ph = None
        if self.last_pl is not None and pc is not None and pc >= self.last_pl > c:
            if self.trend == 1:
                choch_dn = True
            else:
                bos_dn = True
            self.trend = -1
            self.last_pl = None

        # ── 2) اصطياد السيولة (Sweep) ──
        sweep_hi = (self.prev_ph is not None and h > self.prev_ph and c < self.prev_ph)
        sweep_lo = (self.prev_pl is not None and l < self.prev_pl and c > self.prev_pl)

        # ── 3) سيولة متساوية (معلومة مساعدة) ──
        eq_h = eq_l = False
        if self.atr and self.last_ph is not None and self.prev_ph is not None:
            eq_h = abs(self.last_ph - self.prev_ph) <= cfg.eq_tol * self.atr
        if self.atr and self.last_pl is not None and self.prev_pl is not None:
            eq_l = abs(self.last_pl - self.prev_pl) <= cfg.eq_tol * self.atr

        # ── 6) دلتا الحجم ──
        rng = max(h - l, 1e-12)
        buy_v = v * (c - l) / rng
        sell_v = v * (h - c) / rng
        delta = buy_v - sell_v
        a = 2.0 / (14 + 1)
        self.ema_delta = delta if self.ema_delta is None else a * delta + (1 - a) * self.ema_delta
        self.ema_vol = v if self.ema_vol is None else a * v + (1 - a) * self.ema_vol
        d_norm = self.ema_delta / max(self.ema_vol, 1.0)
        bull_delta = d_norm > 0.05
        bear_delta = d_norm < -0.05

        # ── 7) Kill Zones + Premium/Discount ──
        in_kz = in_killzone(dt, cfg)
        self.hi50.append(h)
        self.lo50.append(l)
        in_discount = in_premium = False
        if len(self.hi50) >= 20:
            eq50 = (max(self.hi50) + min(self.lo50)) / 2.0
            in_discount = c < eq50
            in_premium = c > eq50

        # ── تحديث الشموع المخزنة (قبل كشف FVG/OB) ──
        self.o.append(o)
        self.c.append(c)
        self.h.append(h)
        self.l.append(l)

        # ── 5) Fair Value Gap ──
        bull_fvg = bear_fvg = False
        if len(self.h) >= 3 and self.atr is not None:
            if l > self.h[-3] and self.c[-2] > self.o[-2]:
                bull_fvg = True
                self.fvgs.append({"top": l, "bot": self.h[-3], "dir": 1})
            if h < self.l[-3] and self.c[-2] < self.o[-2]:
                bear_fvg = True
                self.fvgs.append({"top": self.l[-3], "bot": h, "dir": -1})
        # تنظيف FVG (امتلاء)
        keep = []
        for f in self.fvgs:
            filled = (c < f["bot"]) if f["dir"] == 1 else (c > f["top"])
            if not (cfg.mitigate and filled):
                keep.append(f)
        self.fvgs = keep[-30:]

        # ── 4) Order Blocks ──
        ob_tap_bull = ob_tap_bear = False
        if len(self.o) >= 2 and self.atr is not None:
            impulse = abs(c - o) > self.atr * 0.9
            if impulse and c > o and self.c[-2] < self.o[-2] and (bos_up or choch_up or bull_fvg):
                self.obs.append({"top": max(self.o[-2], self.c[-2]), "bot": self.l[-2], "dir": 1})
            if impulse and c < o and self.c[-2] > self.o[-2] and (bos_dn or choch_dn or bear_fvg):
                self.obs.append({"top": self.h[-2], "bot": min(self.o[-2], self.c[-2]), "dir": -1})
        keep = []
        for ob in self.obs:
            if ob["dir"] == 1 and l <= ob["top"] and h >= ob["bot"]:
                ob_tap_bull = True
            if ob["dir"] == -1 and h >= ob["bot"] and l <= ob["top"]:
                ob_tap_bear = True
            broken = (c < ob["bot"]) if ob["dir"] == 1 else (c > ob["top"])
            if not (cfg.mitigate and broken):
                keep.append(ob)
        self.obs = keep[-cfg.ob_max:]

        # ── نظام التقييم 0-5 (مطابق للباي) ──
        score_long = score_short = 0
        r_long: List[str] = []
        r_short: List[str] = []

        if choch_up or bos_up:
            score_long += 1
            r_long.append("CHoCH↑ انقلاب صاعد" if choch_up else "BOS↑ كسر هيكل صاعد")
        if choch_dn or bos_dn:
            score_short += 1
            r_short.append("CHoCH↓ انقلاب هابط" if choch_dn else "BOS↓ كسر هيكل هابط")
        if sweep_lo:
            score_long += 1
            r_long.append("💧 اصطياد سيولة من الأسفل")
        if sweep_hi:
            score_short += 1
            r_short.append("💧 اصطياد سيولة من الأعلى")
        if ob_tap_bull or bull_fvg:
            score_long += 1
            r_long.append("لمس أوردر بلوك شرائي OB+" if ob_tap_bull else "فجوة FVG صاعدة")
        if ob_tap_bear or bear_fvg:
            score_short += 1
            r_short.append("لمس أوردر بلوك بيعي OB-" if ob_tap_bear else "فجوة FVG هابطة")
        if (not cfg.use_delta) or bull_delta:
            score_long += 1
            if cfg.use_delta:
                r_long.append("ضغط دلتا شرائي")
        if (not cfg.use_delta) or bear_delta:
            score_short += 1
            if cfg.use_delta:
                r_short.append("ضغط دلتا بيعي")
        kz_ok = (not cfg.use_killzones) or in_kz
        if kz_ok and ((not cfg.use_premium_discount) or in_discount):
            score_long += 1
            extra = []
            if cfg.use_killzones and in_kz:
                extra.append("Kill Zone")
            if cfg.use_premium_discount and in_discount:
                extra.append("منطقة خصم")
            if extra:
                r_long.append(" + ".join(extra))
        if kz_ok and ((not cfg.use_premium_discount) or in_premium):
            score_short += 1
            extra = []
            if cfg.use_killzones and in_kz:
                extra.append("Kill Zone")
            if cfg.use_premium_discount and in_premium:
                extra.append("منطقة بريميوم")
            if extra:
                r_short.append(" + ".join(extra))

        # ── القرار النهائي + التبريد ──
        cooldown = (i - self.last_sig_bar) > cfg.swing_len
        long_sig = score_long >= cfg.min_score and score_long > score_short and cooldown
        short_sig = score_short >= cfg.min_score and score_short > score_long and cooldown

        sig.score_long = score_long
        sig.score_short = score_short
        sig.trend = self.trend
        # لا إشارة قبل اكتمال ATR (تدفئة المؤشرات)
        if self.atr is None:
            long_sig = short_sig = False
        if long_sig:
            sig.direction = 1
            sig.score = score_long
            sig.reasons = r_long
            self.last_sig_bar = i
        elif short_sig:
            sig.direction = -1
            sig.score = score_short
            sig.reasons = r_short
            self.last_sig_bar = i
        else:
            sig.direction = 0
            sig.score = max(score_long, score_short)
            sig.reasons = r_long if score_long >= score_short else r_short

        if self.atr is not None:
            sig.atr = self.atr
            sig.sl_dist = self.atr * cfg.atr_sl_mult

        self.prev_close = c
        return sig

    # ----------------------------------------------------------
    @property
    def equal_highs(self) -> bool:
        return (
            self.atr is not None
            and self.last_ph is not None
            and self.prev_ph is not None
            and abs(self.last_ph - self.prev_ph) <= self.cfg.eq_tol * self.atr
        )

    @property
    def equal_lows(self) -> bool:
        return (
            self.atr is not None
            and self.last_pl is not None
            and self.prev_pl is not None
            and abs(self.last_pl - self.prev_pl) <= self.cfg.eq_tol * self.atr
        )
