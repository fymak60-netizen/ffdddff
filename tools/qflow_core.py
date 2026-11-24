"""
QFLOW-CORE  —  المرجع الحسابي (Python) لمحرك "مختبر التدفق الكمي"
=================================================================
هذا الملف هو النسخة المرجعية القابلة للاختبار لكل معادلة مكتوبة داخل
`pine/QFL_QuantFlowLab.pine`.

السبب في وجوده: لغة Pine لا يوجد لها مترجم خارج TradingView، فالطريقة الوحيدة
للتأكد من صحة الرياضيات قبل ما تعلق الكود على الشارت هي تنفيذ نفس المعادلات
هنا على بيانات صناعية معروفة الخصائص (ترند / ارتداد / عشوائي) والتأكد إن
الأرقام بتطلع في الاتجاه الصحيح.

كل دالة هنا مكتوبة بنفس ترتيب العمليات الموجود في Pine — لو عدّلت حاجة هنا
لازم تعدّل نفس الحاجة في Pine.

المصادر العلمية المستخدمة:
  * Easley, Lopez de Prado, O'Hara (2012)  — Bulk Volume Classification + VPIN
  * Andersen & Bondarenko (2014)           — نقد VPIN وضرورة النسخة المُوقّعة (signed)
  * Cont, Kukanov, Stoikov (2014)          — Order Flow Imbalance (OFI)
  * Kyle (1985)                            — lambda = price impact per unit flow
  * Amihud (2002)                          — Illiquidity ratio
  * Corwin & Schultz (2012)                — تقدير السبريد من High/Low فقط
  * Bandt & Pompe (2002)                   — Permutation Entropy
  * Hurst (1951) / Lo (1991)               — Variance-Ratio estimator
  * Kaufman (1995)                         — Efficiency Ratio
  * Katz (1988) / Higuchi (1988)           — Fractal Dimension (استخدمنا Higuchi)
  * Lopez de Prado (2018)                  — Meta-labeling + Triple Barrier
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

__all__ = [
    "norm_cdf",
    "erf_approx",
    "bvc_split",
    "vpin_volume_clock",
    "ofi",
    "kyle_lambda",
    "amihud_illiquidity",
    "corwin_schultz_spread",
    "hurst_varratio",
    "permutation_entropy",
    "shannon_entropy",
    "efficiency_ratio",
    "higuchi_fd",
    "percentile_rank",
    "meta_score",
    "ama",
    "engine_signals",
    "position_size",
    "triple_barrier_walk",
    "trade_stats",
]

# --------------------------------------------------------------------------- #
# 0) أدوات عامة
# --------------------------------------------------------------------------- #

def erf_approx(x: float) -> float:
    """Abramowitz & Stegun 7.1.26 — أقصى خطأ ~1.5e-7. نفس الصيغة في Pine."""
    sign = -1.0 if x < 0 else 1.0
    x = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
                - 0.284496736) * t + 0.254829592) * t * math.exp(-x * x)
    return sign * y


def norm_cdf(z: float) -> float:
    """التوزيع التراكمي الطبيعي Φ(z) — قلب الـ BVC."""
    return 0.5 * (1.0 + erf_approx(z / math.sqrt(2.0)))


def _as_arr(x: Sequence[float] | np.ndarray) -> np.ndarray:
    return np.asarray(x, dtype=float)


# --------------------------------------------------------------------------- #
# 1) تصنيف الحجم: Bulk Volume Classification (BVC)
# --------------------------------------------------------------------------- #

def bvc_split(close: Sequence[float], volume: Sequence[float],
              sigma_len: int = 20) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    يقسم حجم الشمعة إلى حجم شراء وحجم بيع بدون أي بيانات Level-2.

        z      = ln(C_t / C_{t-1}) / sigma
        BuyVol = Volume * Phi(z)
        SellVol= Volume - BuyVol

    بيرجع (buy, sell, sigma).
    """
    c, v = _as_arr(close), _as_arr(volume)
    n = len(c)
    ret = np.full(n, np.nan)
    ret[1:] = np.log(c[1:] / c[:-1])

    sigma = np.full(n, np.nan)
    for t in range(n):
        lo = max(0, t - sigma_len + 1)
        w = ret[lo:t + 1]
        w = w[~np.isnan(w)]
        if len(w) >= 2:
            sigma[t] = float(np.std(w, ddof=1))

    buy = np.zeros(n)
    sell = np.zeros(n)
    for t in range(n):
        s = sigma[t]
        if not np.isfinite(s) or s <= 1e-12 or not np.isfinite(ret[t]):
            # مفيش معلومات اتجاهية → نصف/نصف (الافتراض المحايد في BVC)
            buy[t] = v[t] * 0.5
        else:
            buy[t] = v[t] * norm_cdf(ret[t] / s)
        sell[t] = v[t] - buy[t]
    return buy, sell, sigma


# --------------------------------------------------------------------------- #
# 2) ساعة الحجم: VPIN الحقيقي (Volume Clock)
# --------------------------------------------------------------------------- #

def vpin_volume_clock(buy: Sequence[float], sell: Sequence[float],
                      bucket_size: float, window: int = 50,
                      max_fills: int = 8) -> tuple[np.ndarray, np.ndarray]:
    """
    VPIN على "ساعة الحجم" مش على ساعة الزمن: بنجمّع الحجم في دِلاء ثابتة الحجم
    (bucket_size) وبعدين نحسب عدم التوازن داخل آخر `window` دلو.

    بيرجع:
      vpin_abs    = Σ|B_i - S_i| / Σ(B_i + S_i)      ∈ [0, 1]  (السمية)
      vpin_signed = (ΣB_i - ΣS_i) / Σ(B_i + S_i)     ∈ [-1, 1] (الاتجاه)

    النسخة المُوقّعة مطلوبة بسبب نقد Andersen & Bondarenko: النسخة المطلقة بتتحرك
    مع حجم التداول نفسه، فبتديك "تقلّب" مش "معلومة".
    """
    b, s = _as_arr(buy), _as_arr(sell)
    n = len(b)
    out_abs = np.full(n, np.nan)
    out_sig = np.full(n, np.nan)

    qb: list[float] = []
    qs: list[float] = []
    cb = cs = cv = 0.0

    for t in range(n):
        rb, rs = float(b[t]), float(s[t])
        guard = 0
        while guard < max_fills and (rb + rs) > 0.0:
            space = bucket_size - cv
            incoming = rb + rs
            take = min(space, incoming)
            frac = take / incoming if incoming > 0 else 0.0
            cb += rb * frac
            cs += rs * frac
            rb -= rb * frac
            rs -= rs * frac
            cv += take
            if cv >= bucket_size * 0.999999:
                qb.append(cb)
                qs.append(cs)
                cb = cs = cv = 0.0
                if len(qb) > window:
                    qb.pop(0)
                    qs.pop(0)
            guard += 1

        if len(qb) >= window:
            tb = math.fsum(qb)
            ts = math.fsum(qs)
            tv = tb + ts
            if tv > 0:
                out_abs[t] = math.fsum(abs(x - y) for x, y in zip(qb, qs)) / tv
                out_sig[t] = (tb - ts) / tv

    return out_abs, out_sig


# --------------------------------------------------------------------------- #
# 3) ضغط التدفق والأثر السعري
# --------------------------------------------------------------------------- #

def ofi(buy: Sequence[float], sell: Sequence[float], length: int = 20) -> np.ndarray:
    """عدم توازن التدفق مُطبَّع: Σ(Buy-Sell) / ΣVolume على `length` شمعة (Cont et al.)."""
    b, s = _as_arr(buy), _as_arr(sell)
    v = b + s
    num = np.convolve(b - s, np.ones(length), mode="full")[:len(b)]
    den = np.convolve(v, np.ones(length), mode="full")[:len(b)]
    out = np.full(len(b), np.nan)
    ok = den > 0
    out[ok] = num[ok] / den[ok]
    out[:length - 1] = np.nan
    return np.clip(out, -1.0, 1.0)


def kyle_lambda(close: Sequence[float], open_: Sequence[float],
                signed_vol: Sequence[float], length: int = 30) -> np.ndarray:
    """
    Kyle's lambda = ميل انحدار (Close-Open) على الحجم المُوقّع.
    قيمة عالية = الكتاب رفيق/فيه تداول مطّلع → قلّل الحجم.
    """
    c, o, sv = _as_arr(close), _as_arr(open_), _as_arr(signed_vol)
    y = c - o
    n = len(c)
    out = np.full(n, np.nan)
    for t in range(length - 1, n):
        xw = sv[t - length + 1:t + 1]
        yw = y[t - length + 1:t + 1]
        vx = float(np.var(xw))
        if vx <= 1e-18:
            continue
        out[t] = float(np.cov(xw, yw, bias=True)[0, 1] / vx)
    return out


def amihud_illiquidity(close: Sequence[float], volume: Sequence[float],
                       length: int = 20) -> np.ndarray:
    """Amihud (2002): متوسط |العائد| / (السعر × الحجم)."""
    c, v = _as_arr(close), _as_arr(volume)
    n = len(c)
    ret = np.zeros(n)
    ret[1:] = np.abs(np.log(c[1:] / c[:-1]))
    dv = c * v
    raw = np.where(dv > 0, ret / dv, 0.0)
    out = np.full(n, np.nan)
    for t in range(length - 1, n):
        out[t] = float(np.mean(raw[t - length + 1:t + 1]))
    return out


def corwin_schultz_spread(high: Sequence[float], low: Sequence[float]) -> np.ndarray:
    """
    تقدير السبريد من High/Low بس (Corwin & Schultz 2012). بيرجع نسبة عشرية.
    ده أهم رقم في فوركس/الدهب: لو الحافة المتوقعة أصغر من السبريد → ماتدخلش.
    """
    h, l = _as_arr(high), _as_arr(low)
    n = len(h)
    out = np.full(n, np.nan)
    k = 2.0 * (2.0 * math.sqrt(2.0) - 1.0)          # 3.8284...
    den = 3.0 - 2.0 * math.sqrt(2.0)                # 0.1716...
    for t in range(2, n):
        hl0 = h[t] / l[t]
        hl1 = h[t - 1] / l[t - 1]
        if hl0 <= 1.0 or hl1 <= 1.0:
            out[t] = 0.0
            continue
        beta = k * (math.log(hl0) ** 2 + math.log(hl1) ** 2)
        gamma = math.log(h[t] / l[t - 1]) ** 2
        alpha = ((math.sqrt(2.0 * beta) - math.sqrt(beta)) / den
                 - math.sqrt(beta / den)
                 + math.sqrt(gamma / den))
        ea = math.exp(alpha)
        s = 2.0 * (ea - 1.0) / (1.0 + ea)
        out[t] = max(0.0, min(1.0, s))
    return out


# --------------------------------------------------------------------------- #
# 4) هندسة المعلومات: Hurst / Entropy / Efficiency / Fractal
# --------------------------------------------------------------------------- #

def hurst_varratio(close: Sequence[float], window: int = 100,
                   kmin: int = 2, kmax: int = 8) -> np.ndarray:
    """
    Hurst عن طريق Variance-Ratio على أكتر من أفق k:
        VR(k) = Var(P_t - P_{t-k}) / (k * Var(P_t - P_{t-1}))
        ln VR(k) = (2H - 1) ln k + c      →  انحدار خطي على ln k
    H > 0.5 = استمرارية/ترند، H < 0.5 = ارتداد للمتوسط، H = 0.5 = مشي عشوائي.
    """
    c = _as_arr(close)
    n = len(c)
    p = np.log(np.where(c > 0, c, np.nan))
    out = np.full(n, np.nan)
    need = window + kmax + 1
    lnk = np.array([math.log(k) for k in range(kmin, kmax + 1)])
    for t in range(need, n):
        seg = p[t - (window + kmax) + 1:t + 1]
        if np.isnan(seg).any():
            continue
        d1 = seg[1:] - seg[:-1]
        v1 = float(np.var(d1))
        if v1 <= 1e-18:
            continue
        lvr = []
        for k in range(kmin, kmax + 1):
            dk = seg[k:] - seg[:-k]
            vk = float(np.var(dk))
            if vk <= 0:
                lvr = []
                break
            lvr.append(math.log(vk / (k * v1)))
        if len(lvr) != len(lnk):
            continue
        y = np.array(lvr)
        x = lnk[:len(y)]
        xm, ym = x.mean(), y.mean()
        sxx = float(((x - xm) ** 2).sum())
        if sxx <= 1e-18:
            continue
        slope = float(((x - xm) * (y - ym)).sum() / sxx)
        out[t] = float(min(1.0, max(0.0, 0.5 * (slope + 1.0))))
    return out


def permutation_entropy(ret: Sequence[float], window: int = 60, order: int = 3) -> np.ndarray:
    """
    Permutation Entropy (Bandt & Pompe) مُطبّعة على ln(6).

    الترميز: كود 3-bit من مقارنات (a>b, a>c, b>c) على آخر 3 عوائد.
    الكود ده "حقني" (injective) — كل ترتيب من الستة بياخد كود مختلف
    {0,1,3,4,6,7} — وده بالظبط نفس الترميز المكتوب في Pine.

    ملاحظة مهمة: الترميز الساذج (رقم في نظام عدّ أساسي 3 ثم % 6) بيحصل فيه
    تصادم بين الأنماط وبيكبس الإنتروبي عند ln(3)/ln(6) ≈ 0.613 مهما كانت
    البيانات — التجربة كانت بتطلع 0.608 للعشوائي والترند بنفس القيمة.

    order مدعوم = 3 بس (نفس قيد Pine).
    """
    if order != 3:
        raise ValueError("order=3 is the only supported value (matches the Pine implementation)")
    r = _as_arr(ret)
    n = len(r)
    out = np.full(n, np.nan)
    max_h = math.log(6.0)
    for t in range(window + order, n):
        counts = np.zeros(8)
        used = 0
        for j in range(window):
            a = r[t - j]
            b = r[t - j - 1]
            c = r[t - j - 2]
            if not (np.isfinite(a) and np.isfinite(b) and np.isfinite(c)):
                continue
            code = (1 if a > b else 0) + (2 if a > c else 0) + (4 if b > c else 0)
            counts[code] += 1
            used += 1
        if used < 2:
            continue
        p = counts[counts > 0] / used
        out[t] = float(-np.sum(p * np.log(p)) / max_h)
    return out


def shannon_entropy(ret: Sequence[float], window: int = 60, bins: int = 8) -> np.ndarray:
    """Shannon entropy لعوائد مُقسّمة على 8 صناديق، مُطبّعة على ln(bins)."""
    r = _as_arr(ret)
    n = len(r)
    out = np.full(n, np.nan)
    max_h = math.log(bins)
    for t in range(window * 2, n):
        w = r[t - window + 1:t + 1]
        if np.isnan(w).any():
            continue
        s = float(np.std(r[t - window * 2 + 1:t + 1]))
        if s <= 1e-12:
            out[t] = 1.0
            continue
        z = np.clip((w / s + 4.0) * (bins / 8.0), 0, bins - 1).astype(int)
        counts = np.bincount(z, minlength=bins).astype(float)
        p = counts[counts > 0] / counts.sum()
        out[t] = float(-np.sum(p * np.log(p)) / max_h)
    return out


def efficiency_ratio(close: Sequence[float], length: int = 20) -> np.ndarray:
    """Kaufman ER = |صافي الحركة| / مجموع الحركات."""
    c = _as_arr(close)
    n = len(c)
    out = np.full(n, np.nan)
    for t in range(length, n):
        net = abs(c[t] - c[t - length])
        path = float(np.abs(np.diff(c[t - length:t + 1])).sum())
        out[t] = net / path if path > 0 else 0.0
    return out


def higuchi_fd(close: Sequence[float], window: int = 30, kmax: int = 5) -> np.ndarray:
    """
    Higuchi Fractal Dimension (1988) — البعد الكسوري الحقيقي، محدود عمليًا في [1, 2].

    لكل k من 1 لـ kmax بنحسب طول المنحنى L(k) بعد إعادة قياسه، والبعد هو
    ميل ln L(k) مقابل ln(1/k). قريب من 1 = خط نضيف (ترند)، قريب من 2 = ضجيج
    بيملا المساحة.

    (استخدمنا Higuchi بدل Katz لأن نسخة Katz المبسّطة بتنفجر برا [1,2] لما
    يكون الإزاحة الصافية صغيرة جدًا مقارنة بطول المسار.)
    """
    c = _as_arr(close)
    n = len(c)
    out = np.full(n, np.nan)
    ln_inv_k = np.array([math.log(1.0 / k) for k in range(1, kmax + 1)])
    for t in range(max(window, kmax + 2), n):
        x = c[t - window + 1:t + 1]
        if np.isnan(x).any():
            continue
        N = window
        lk = []
        ok = True
        for k in range(1, kmax + 1):
            seg_lens = []
            for m in range(1, k + 1):
                nseg = int(math.floor((N - m) / k))
                if nseg < 1:
                    ok = False
                    break
                s = 0.0
                for i in range(1, nseg + 1):
                    s += abs(x[m + i * k - 1] - x[m + (i - 1) * k - 1])
                norm = (N - 1) / (nseg * k)
                seg_lens.append(s * norm / k)
            if not ok or not seg_lens:
                break
            lk.append(math.log(max(float(np.mean(seg_lens)), 1e-12)))
        if len(lk) != kmax:
            continue
        y = np.array(lk)
        xg = ln_inv_k[:len(y)]
        xm, ym = xg.mean(), y.mean()
        sxx = float(((xg - xm) ** 2).sum())
        if sxx <= 1e-18:
            continue
        slope = float(((xg - xm) * (y - ym)).sum() / sxx)
        out[t] = slope
    return out


# --------------------------------------------------------------------------- #
# 5) التطبيع والـ Meta-label
# --------------------------------------------------------------------------- #

def percentile_rank(series: Sequence[float], length: int = 100) -> np.ndarray:
    """النسبة المئوية للقيمة الحالية داخل آخر `length` قيمة (0..100)."""
    s = _as_arr(series)
    n = len(s)
    out = np.full(n, np.nan)
    for t in range(length - 1, n):
        w = s[t - length + 1:t + 1]
        w = w[~np.isnan(w)]
        if len(w) < 2:
            continue
        out[t] = 100.0 * float((w < s[t]).sum()) / len(w)
    return out


def meta_score(mode: int, vpin_signed: float, vpin_abs_pct: float,
               spread_pct: float, illiq_pct: float, lambda_pct: float,
               atr_z: float, er_pct: float, htf_agree: bool,
               session_ok: bool, shock: bool) -> float:
    """
    Meta-labeling (Lopez de Prado): مش "هل فيه إشارة؟" لكن "هل أستاهل أخدها؟"
    بيرجع 0..100. كل المدخلات نِسَب مئوية (0..100) ما عدا اللي موضّح.

    mode: 1 = ترند (تدوير مع التدفق)، -1 = ارتداد (عكس الحركة)، 0 = مفيش.
    """
    if mode == 0 or not session_ok or shock:
        return 0.0

    flow = 50.0 + 50.0 * max(-1.0, min(1.0, vpin_signed))
    if mode < 0:
        flow = 100.0 - flow          # في الارتداد عايزين التدفق ضعيف/معكوس

    if mode > 0:
        er_component = er_pct        # الترند محتاج كفاءة حركة عالية
    else:
        er_component = 100.0 - er_pct

    liq = 100.0 - (0.45 * spread_pct + 0.30 * illiq_pct + 0.25 * lambda_pct)
    vol = max(0.0, 100.0 - 45.0 * abs(atr_z))     # العقوبة بتزيد مع |z|

    score = (0.30 * flow
             + 0.22 * er_component
             + 0.18 * liq
             + 0.12 * vol
             + 0.18 * (100.0 if htf_agree else 0.0))

    # سمّية قصوى = خطر اختيار عكسي حتى لو كل حاجة تانية تمام
    if vpin_abs_pct > 97.0:
        score *= 0.5
    return float(max(0.0, min(100.0, score)))


# --------------------------------------------------------------------------- #
# 6) إدارة المال: الحجم + الحواجز الثلاثة
# --------------------------------------------------------------------------- #

def position_size(equity: float, risk_pct: float, entry: float, stop: float,
                  contract_value: float = 100.0) -> tuple[float, float, float]:
    """
    بيرجع (risk_amount, lots, units).
    contract_value = قيمة النقطة للـ lot الواحد (الدهب/الفوركس = 100).
    """
    risk_amount = equity * risk_pct
    dist = abs(entry - stop)
    if dist <= 0:
        return risk_amount, 0.0, 0.0
    lots = risk_amount / (dist * contract_value)
    return risk_amount, float(lots), float(lots * contract_value)


def triple_barrier_walk(high: Sequence[float], low: Sequence[float],
                        close: Sequence[float], entries: Sequence[int],
                        dirs: Sequence[int], sl_dist: Sequence[float],
                        rr: float = 1.8, max_bars: int = 40,
                        breakeven_at_r: float = 1.0) -> list[dict]:
    """
    الحواجز الثلاثة: وقف / هدف / وقت. أول حاجز يتلمس هو اللي بيقرر.
    مع تحريك الوقف لنقطة الدخول بعد 1R.
    """
    h, l, c = _as_arr(high), _as_arr(low), _as_arr(close)
    n = len(c)
    trades: list[dict] = []
    i = 0
    entry_set = set(int(e) for e in entries)
    dir_map = {int(e): int(d) for e, d in zip(entries, dirs)}
    sl_map = {int(e): float(s) for e, s in zip(entries, sl_dist)}

    while i < n:
        if i not in entry_set:
            i += 1
            continue
        d = dir_map[i]
        sld = sl_map[i]
        entry = c[i]
        if not (sld > 0) or d == 0:
            i += 1
            continue
        stop = entry - d * sld
        target = entry + d * sld * rr
        be_armed = False
        exit_price = None
        reason = "time"
        exit_bar = min(n - 1, i + max_bars)
        for b in range(i + 1, exit_bar + 1):
            fav = (h[b] - entry) * d
            adv = (l[b] - entry) * d
            if not be_armed and fav >= sld * breakeven_at_r:
                stop = entry
                be_armed = True
            if d > 0:
                if l[b] <= stop:
                    exit_price, reason, exit_bar = stop, "stop", b
                    break
                if h[b] >= target:
                    exit_price, reason, exit_bar = target, "target", b
                    break
            else:
                if h[b] >= stop:
                    exit_price, reason, exit_bar = stop, "stop", b
                    break
                if l[b] <= target:
                    exit_price, reason, exit_bar = target, "target", b
                    break
            _ = adv
        if exit_price is None:
            exit_price = c[exit_bar]
        r_mult = d * (exit_price - entry) / sld
        trades.append({
            "entry_bar": i, "exit_bar": exit_bar, "dir": d,
            "entry": float(entry), "exit": float(exit_price),
            "reason": reason, "r": float(r_mult),
        })
        i = exit_bar + 1          # مفيش صفقة جديدة قبل ما القديمة تخلص
    return trades


def ama(close: Sequence[float], length: int = 20,
        fast: int = 2, slow: int = 30) -> np.ndarray:
    """Kaufman AMA — المتوسط المتكيّف اللي بيستخدم Efficiency Ratio كـ alpha."""
    c = _as_arr(close)
    n = len(c)
    er = efficiency_ratio(c, length)
    fsc, ssc = 2.0 / (fast + 1.0), 2.0 / (slow + 1.0)
    out = np.full(n, np.nan)
    prev = np.nan
    for t in range(n):
        if not np.isfinite(er[t]):
            continue
        a = (er[t] * (fsc - ssc) + ssc) ** 2
        prev = c[t] if not np.isfinite(prev) else a * c[t] + (1.0 - a) * prev
        out[t] = prev
    return out


def engine_signals(close, high, low, open_, volume, htf_close=None,
                   sigma_len: int = 20, bucket_mult: float = 0.5,
                   vpin_window: int = 50, ofi_len: int = 20,
                   hurst_len: int = 120, pe_len: int = 60, er_len: int = 20,
                   ama_len: int = 20, atr_len: int = 14,
                   h_trend: float = 0.53, h_revert: float = 0.47,
                   pe_trend_max: float = 40.0, pe_revert_min: float = 60.0,
                   er_min: float = 0.28,
                   z_revert: float = 2.0, sl_mult: float = 1.6,
                   entry_window: int = 6, flow_min: float = 0.05,
                   confirm_bars: int = 3, min_meta: float = 55.0,
                   rank_len: int = 200, atr_z_max: float = 2.2,
                   shock_z: float = 2.5) -> dict:
    """
    النسخة المرجعية الكاملة لمحرّك المؤشر (نفس ترتيب الطبقات في Pine):
      طبقة 0 ميكروستركشر → 1 هندسة المعلومات → 2 آلة الأنظمة →
      3 الزناد → 4 الـ meta-label → 5 الحواجز الثلاثة.

    htf_close: إغلاق الفريم الأكبر (لو مفيش، بيستخدم إعادة تشكيل من نفس السلسلة).
    بيرجع dict فيه كل السلاسل الخام + الإشارات + الصفقات.
    """
    c, h, l, o, v = map(_as_arr, (close, high, low, open_, volume))
    n = len(c)

    # ---- طبقة 0 -----------------------------------------------------------
    ret = np.full(n, np.nan)
    ret[1:] = np.log(c[1:] / c[:-1])
    buy, sell, sigma = bvc_split(c, v, sigma_len)
    vol_sma = np.array([np.nanmean(v[max(0, t - 19):t + 1]) for t in range(n)])
    bucket_size = float(np.nanmean(vol_sma[~np.isnan(vol_sma)])) * bucket_mult
    vpin_abs, vpin_sig = vpin_volume_clock(buy, sell, max(bucket_size, 1e-9), vpin_window)
    flow = ofi(buy, sell, ofi_len)
    lam = kyle_lambda(c, o, buy - sell, 30)
    illiq = amihud_illiquidity(c, v, 20)
    spread = corwin_schultz_spread(h, l)

    tr = np.maximum.reduce([
        h - l,
        np.abs(h - np.concatenate([[c[0]], c[:-1]])),
        np.abs(l - np.concatenate([[c[0]], c[:-1]])),
    ])
    atr = np.array([np.nanmean(tr[max(0, t - atr_len + 1):t + 1]) for t in range(n)])

    # ---- طبقة 1 -----------------------------------------------------------
    hurst = hurst_varratio(c, hurst_len)
    pe = permutation_entropy(np.nan_to_num(ret), pe_len)
    er = efficiency_ratio(c, er_len)
    fd = higuchi_fd(c, 30, 5)

    # ---- HTF --------------------------------------------------------------
    if htf_close is None:
        step = 4
        htf = np.array([np.nanmean(c[max(0, t - step + 1):t + 1]) for t in range(n)])
    else:
        htf = _as_arr(htf_close)
    htf_ama = ama(htf, 20)
    htf_dir = np.sign(np.nan_to_num(htf_ama - np.concatenate([htf_ama[:1], htf_ama[:-1]])))

    # ---- طبقة 2: آلة الأنظمة مع hysteresis --------------------------------
    # ملاحظة تصميمية مهمة: الإنتروبي التبادلي على مستوى الشمعة بيكون مشبّع
    # تقريبًا (~0.98) في أغلب الأسواق، فأي حدّ مطلق زيه 0.86 مش هيتحقق أبدًا.
    # الحل: نقارن الإنتروبي بتاريخه هو (percentile rank) مش برقم ثابت —
    # ده بيخلي المؤشر يضبط نفسه على كل أداة وفريم لوحده.
    pr_pe_state = percentile_rank(np.nan_to_num(pe, nan=1.0), rank_len)

    trend_line = ama(c, ama_len)
    resid = c - trend_line
    atr_safe = np.where(atr > 0, atr, np.nan)
    zres = resid / atr_safe

    raw_state = np.zeros(n, dtype=int)
    for t in range(n):
        hh, pp, ee = hurst[t], pr_pe_state[t], er[t]
        if not (np.isfinite(hh) and np.isfinite(pp) and np.isfinite(ee)):
            continue
        if hh >= h_trend and pp <= pe_trend_max and ee >= er_min:
            raw_state[t] = 1
        elif hh <= h_revert and pp >= pe_revert_min and ee < er_min:
            raw_state[t] = -1
    state = np.zeros(n, dtype=int)
    cur, run, cand = 0, 0, 0
    for t in range(n):
        if raw_state[t] == cur:
            state[t] = cur
            cand, run = cur, 0
            continue
        if raw_state[t] == cand:
            run += 1
        else:
            cand, run = raw_state[t], 1
        if run >= confirm_bars:
            cur, cand, run = cand, cand, 0
        state[t] = cur

    # ---- طبقة 3: الزناد ----------------------------------------------------
    cross_up = np.zeros(n, dtype=bool)
    cross_dn = np.zeros(n, dtype=bool)
    for t in range(1, n):
        if np.isfinite(trend_line[t]) and np.isfinite(trend_line[t - 1]):
            cross_up[t] = c[t - 1] <= trend_line[t - 1] and c[t] > trend_line[t]
            cross_dn[t] = c[t - 1] >= trend_line[t - 1] and c[t] < trend_line[t]

    atr_sma = np.array([np.nanmean(atr[max(0, t - 99):t + 1]) for t in range(n)])
    atr_sd = np.array([np.nanstd(atr[max(0, t - 99):t + 1]) for t in range(n)])
    with np.errstate(divide="ignore", invalid="ignore"):
        atr_z = np.where(atr_sd > 0, (atr - atr_sma) / np.where(atr_sd > 0, atr_sd, 1.0), 0.0)
    atr_z = np.nan_to_num(atr_z, nan=0.0, posinf=0.0, neginf=0.0)

    # نافذة الدخول: بنسمح بالدخول خلال `entry_window` شمعة بعد الاختراق
    # (دخول على التصحيح بعد الاشتعال) — ده بيرفع عدد الفرص بشكل واقعي بدل
    # إننا نربط الدخول بلحظة الاختراق نفسها اللي بتحصل مرة كل ~20 شمعة.
    since_up = np.full(n, 1 << 30, dtype=int)
    since_dn = np.full(n, 1 << 30, dtype=int)
    lu = ld = 1 << 30
    for t in range(n):
        if cross_up[t]:
            lu = t
        if cross_dn[t]:
            ld = t
        since_up[t] = t - lu
        since_dn[t] = t - ld

    # ---- طبقة 4: meta-label ------------------------------------------------
    pr_vsig = percentile_rank(np.nan_to_num(vpin_sig), rank_len)
    pr_vabs = percentile_rank(np.nan_to_num(vpin_abs), rank_len)
    pr_sprd = percentile_rank(np.nan_to_num(spread), rank_len)
    pr_ill = percentile_rank(np.nan_to_num(illiq), rank_len)
    pr_lam = percentile_rank(np.nan_to_num(np.abs(lam)), rank_len)
    pr_er = percentile_rank(np.nan_to_num(er), rank_len)
    _ = pr_vsig

    dirs = np.zeros(n, dtype=int)
    metas = np.zeros(n)
    for t in range(n):
        st = state[t]
        if st == 0:
            continue
        sig_dir = 0
        vsig = float(np.nan_to_num(vpin_sig[t]))
        if st > 0 and since_up[t] <= entry_window and c[t] > trend_line[t] and vsig > flow_min:
            sig_dir = 1
        elif st < 0 and since_dn[t] <= entry_window and c[t] < trend_line[t] and vsig < -flow_min:
            sig_dir = -1
        elif st < 0 and np.isfinite(zres[t]) and zres[t] < -z_revert:
            sig_dir = 1
        elif st < 0 and np.isfinite(zres[t]) and zres[t] > z_revert:
            sig_dir = -1
        if sig_dir == 0:
            continue
        if not (np.isfinite(atr[t]) and atr[t] > 0):
            continue
        agree = bool(np.nan_to_num(htf_dir[t]) == sig_dir)
        shock = bool(atr_z[t] > shock_z)
        metas[t] = meta_score(
            mode=st,
            vpin_signed=float(np.nan_to_num(vpin_sig[t])),
            vpin_abs_pct=float(np.nan_to_num(pr_vabs[t])),
            spread_pct=float(np.nan_to_num(pr_sprd[t])),
            illiq_pct=float(np.nan_to_num(pr_ill[t])),
            lambda_pct=float(np.nan_to_num(pr_lam[t])),
            atr_z=float(atr_z[t]),
            er_pct=float(np.nan_to_num(pr_er[t])),
            htf_agree=agree,
            session_ok=True,
            shock=shock,
        )
        if metas[t] >= min_meta and abs(float(atr_z[t])) <= atr_z_max:
            dirs[t] = sig_dir

    idx = np.nonzero(dirs != 0)[0]
    sl_dist = np.where(np.isfinite(atr), atr * sl_mult, np.nan)
    trades = triple_barrier_walk(h, l, c, idx.tolist(), dirs[idx].tolist(),
                                 np.nan_to_num(sl_dist)[idx].tolist(),
                                 rr=1.8, max_bars=40)
    return {
        "ret": ret, "buy": buy, "sell": sell, "sigma": sigma,
        "vpin_abs": vpin_abs, "vpin_sig": vpin_sig, "ofi": flow,
        "kyle_lambda": lam, "amihud": illiq, "spread": spread, "atr": atr,
        "hurst": hurst, "perm_entropy": pe, "eff_ratio": er, "fractal_dim": fd,
        "atr_z": atr_z, "state": state, "dir": dirs, "meta": metas,
        "trades": trades,
    }


def trade_stats(trades: list[dict], risk_amount: float) -> dict:
    """إحصاءات النظام: نسبة النجاح، R:R الفعلي، التوقّع بالدولار، أقصى تراجع."""
    if not trades:
        return {"trades": 0, "win_rate": 0.0, "avg_win_r": 0.0, "avg_loss_r": 0.0,
                "expectancy_r": 0.0, "expectancy_usd": 0.0, "net_usd": 0.0,
                "max_drawdown_usd": 0.0, "profit_factor": 0.0}
    rs = np.array([t["r"] for t in trades], dtype=float)
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    pnl = rs * risk_amount
    equity = np.cumsum(pnl)
    peak = np.maximum.accumulate(equity)
    dd = float(np.max(peak - equity)) if len(equity) else 0.0
    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())
    return {
        "trades": int(len(rs)),
        "win_rate": float(len(wins) / len(rs) * 100.0),
        "avg_win_r": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_r": float(losses.mean()) if len(losses) else 0.0,
        "expectancy_r": float(rs.mean()),
        "expectancy_usd": float(rs.mean() * risk_amount),
        "net_usd": float(pnl.sum()),
        "max_drawdown_usd": dd,
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
    }
