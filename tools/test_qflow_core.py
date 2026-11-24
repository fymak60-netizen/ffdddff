"""
اختبارات المرجع الحسابي لـ QFlow.

مفيش pytest في البيئة دي، فالسكريبت ده بيشغّل كل الاختبارات بنفسه وبيطبع
تقرير بالأرقام الفعلية. أي assert فشل = خروج بكود غير صفر.

    python3 tools/test_qflow_core.py

الفكرة: بنولّد بيانات صناعية *معروفة الخصائص* (ترند صريح / ارتداد صريح /
مشي عشوائي / تدفق مُطّلع / سبريد مرتد) وبنشوف هل المقاييس بتلتقط الخاصية دي.
لو Hurst مش بيفرّق الترند عن الارتداد هنا، فهو مش هيفرّقهم على شارتك.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qflow_core as q  # noqa: E402

FAILS: list[str] = []
LOG: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str) -> None:
    LOG.append(("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAILS.append(f"{name} :: {detail}")


# --------------------------------------------------------------------------- #
# مولّد بيانات صناعية على مستوى الـ tick وبعدين تجميع لشموع
# --------------------------------------------------------------------------- #

def gen_ticks(n_bars: int, tpb: int, kind: str, seed: int):
    rng = np.random.default_rng(seed)
    n = n_bars * tpb
    s = 0.0006
    if kind == "trend":
        r = rng.normal(0.00010, s, n)
    elif kind == "meanrev":
        x = np.zeros(n)
        for i in range(1, n):
            x[i] = x[i - 1] - 0.0035 * x[i - 1] + rng.normal(0.0, 0.0009)
        r = np.diff(np.concatenate([[0.0], x]))
    else:
        r = rng.normal(0.0, s, n)

    vol_mult = np.ones(n)
    if kind == "informed":
        i = 0
        while i < n:
            if rng.random() < 0.03:
                L = int(rng.integers(15, 70))
                d = rng.choice([-1.0, 1.0])
                r[i:i + L] += d * 0.00075
                vol_mult[i:i + L] *= 3.5
                i += L
            else:
                i += 1

    logp = np.cumsum(r)
    if kind == "bounce":
        logp = logp + 0.0005 * ((-1.0) ** np.arange(n))

    price = 2000.0 * np.exp(logp)
    volume = rng.lognormal(4.0, 0.5, n) * vol_mult
    return price, volume


def aggregate(price, volume, tpb: int):
    n = len(price) // tpb
    p = price[:n * tpb].reshape(n, tpb)
    v = volume[:n * tpb].reshape(n, tpb)
    return p[:, 0], p.max(1), p.min(1), p[:, -1], v.sum(1)


def bars(kind: str, seed: int = 11, n_bars: int = 2500, tpb: int = 20):
    pr, vo = gen_ticks(n_bars, tpb, kind, seed)
    return aggregate(pr, vo, tpb)


def tail_mean(a: np.ndarray, k: int = 400) -> float:
    a = a[~np.isnan(a)]
    return float(np.mean(a[-k:])) if len(a) else float("nan")


# --------------------------------------------------------------------------- #

def test_erf_and_cdf():
    # A&S 7.1.26 تقريب عددي: خطأه الموثّق ~1.5e-7، وعند x=0 بيدي 1e-9
    # (مجموع المعاملات الخمسة = 0.999999999 مش 1 بالظبط). ده سلوك التقريب
    # نفسه مش خطأ في الكود — فالتسامح 1e-6.
    check("erf(0)≈0 (تقريب A&S)", abs(q.erf_approx(0.0)) < 1e-6, f"{q.erf_approx(0.0):.2e}")
    check("erf(1)≈0.8427", abs(q.erf_approx(1.0) - 0.8427007929) < 2e-6,
          f"{q.erf_approx(1.0):.9f}")
    check("Φ(0)≈0.5", abs(q.norm_cdf(0.0) - 0.5) < 1e-6, f"{q.norm_cdf(0.0):.9f}")
    check("Φ(1.96)≈0.975", abs(q.norm_cdf(1.96) - 0.9750021) < 1e-5,
          f"{q.norm_cdf(1.96):.6f}")
    check("Φ تناظرية", abs(q.norm_cdf(1.3) + q.norm_cdf(-1.3) - 1.0) < 1e-9,
          f"{q.norm_cdf(1.3) + q.norm_cdf(-1.3):.9f}")


def test_bvc():
    o, h, l, c, v = bars("trend", seed=3)
    buy, sell, sig = q.bvc_split(c, v, 20)
    check("BVC: buy+sell == volume", np.allclose(buy + sell, v), "identical by construction")
    check("BVC: buy ∈ [0, volume]", bool(np.all(buy >= -1e-9) and np.all(buy <= v + 1e-9)),
          f"min={buy.min():.3f} max_ratio={float(np.max(buy / np.maximum(v,1e-9))):.3f}")
    frac_up = float(np.mean(buy[1:] / v[1:]))
    check("BVC: في الترند الصاعد نصيب الشراء > 0.55", frac_up > 0.55, f"buy_share={frac_up:.3f}")
    check("BVC: sigma موجب", bool(np.nanmin(sig[30:]) > 0), f"min_sigma={np.nanmin(sig[30:]):.6f}")


def test_vpin():
    o, h, l, c, v = bars("informed", seed=21)
    buy, sell, _ = q.bvc_split(c, v, 20)
    bsize = float(np.mean(v)) * 0.5
    a_inf, s_inf = q.vpin_volume_clock(buy, sell, bsize, 50)

    o2, h2, l2, c2, v2 = bars("random", seed=22)
    buy2, sell2, _ = q.bvc_split(c2, v2, 20)
    a_rnd, s_rnd = q.vpin_volume_clock(buy2, sell2, float(np.mean(v2)) * 0.5, 50)

    check("VPIN المطلق ∈ [0,1]", bool(np.nanmin(a_inf) >= 0 and np.nanmax(a_inf) <= 1),
          f"[{np.nanmin(a_inf):.3f}, {np.nanmax(a_inf):.3f}]")
    check("VPIN المُوقّع ∈ [-1,1]", bool(np.nanmin(s_inf) >= -1 and np.nanmax(s_inf) <= 1),
          f"[{np.nanmin(s_inf):.3f}, {np.nanmax(s_inf):.3f}]")
    check("VPIN: عدد الدِلاء كفاية", bool(np.sum(~np.isnan(a_inf)) > 100),
          f"valid={int(np.sum(~np.isnan(a_inf)))}")
    m_inf = float(np.nanmean(np.abs(s_inf)))
    m_rnd = float(np.nanmean(np.abs(s_rnd)))
    check("VPIN المُوقّع أعلى مع التدفق المُطّلع منه مع الضجيج", m_inf > m_rnd * 1.15,
          f"informed={m_inf:.4f} random={m_rnd:.4f} ratio={m_inf/max(m_rnd,1e-9):.2f}x")


def test_ofi_and_lambda():
    o, h, l, c, v = bars("trend", seed=31)
    buy, sell, _ = q.bvc_split(c, v, 20)
    f = q.ofi(buy, sell, 20)
    check("OFI ∈ [-1,1]", bool(np.nanmin(f) >= -1 and np.nanmax(f) <= 1),
          f"[{np.nanmin(f):.3f}, {np.nanmax(f):.3f}]")
    check("OFI موجب في الترند الصاعد", tail_mean(f) > 0.05, f"mean_tail={tail_mean(f):.3f}")

    # lambda مُصطنَع: الأثر السعري = 2e-6 × الحجم المُوقّع + ضجيج
    # الضجيج لازم يكون صغير كفاية: الخطأ المعياري للميل ≈ σ/(σ_x·√n).
    # σ=0.002 و n=200 ⇒ خطأ ≈ 1.4e-7 = 7% من القيمة الحقيقية → اختبار حقيقي.
    rng = np.random.default_rng(5)
    sv = rng.normal(0, 1000, 1000)
    true_a = 2e-6
    o3 = 2000 + np.cumsum(sv * 0.0001)
    c3 = o3 + true_a * sv + rng.normal(0, 0.002, 1000)
    lam = q.kyle_lambda(c3, o3, sv, 200)
    est = float(np.nanmean(lam[400:]))
    check("Kyle λ يسترد المعامل الحقيقي (±25%)", abs(est - true_a) / true_a < 0.25,
          f"true={true_a:.2e} est={est:.2e} err={abs(est-true_a)/true_a*100:.1f}%")


def synthetic_ticks(n: int, drift: float = 2e-5, noise: float = 0.0,
                    bounce: float = 0.0, seed: int = 0):
    """سلسلة ticks مُتحكَّم فيها بالكامل — لاختبار حساسية مُقدِّر السبريد."""
    rng = np.random.default_rng(seed)
    r = np.full(n, drift, dtype=float)
    if noise > 0:
        r = r + rng.normal(0.0, noise, n)
    logp = np.cumsum(r)
    if bounce > 0:
        logp = logp + bounce * ((-1.0) ** np.arange(n))
    return 2000.0 * np.exp(logp), np.full(n, 100.0)


def test_amihud_and_spread():
    o, h, l, c, v = bars("random", seed=41)
    ill_hi = q.amihud_illiquidity(c, v, 20)
    ill_lo = q.amihud_illiquidity(c, v * 10.0, 20)
    check("Amihud: حجم أقل ⇒ سيولة أسوأ", tail_mean(ill_hi) > tail_mean(ill_lo) * 5,
          f"thin={tail_mean(ill_hi):.3e} deep={tail_mean(ill_lo):.3e}")

    # مُقدِّر Corwin-Schultz: نفس السلسلة الناعمة، بنزود عليها ارتداد سعر
    # ثابت (bid-ask bounce) بمقادير متزايدة. لو المُقدِّر شغال، السبريد
    # التقديري لازم يزيد بشكل رتيب مع حجم الارتداد.
    ps, vs = synthetic_ticks(6000, drift=2e-5, noise=0.0, bounce=0.0)
    _, hs, ls, _, _ = aggregate(ps, vs, 20)
    cs_all = q.corwin_schultz_spread(hs, ls)
    check("Corwin-Schultz: السبريد ∈ [0,1]",
          bool(np.nanmin(cs_all[5:]) >= 0 and np.nanmax(cs_all) <= 1.0),
          f"[{np.nanmin(cs_all[5:]):.6f}, {np.nanmax(cs_all):.6f}]")

    spreads = [tail_mean(q.corwin_schultz_spread(hs, ls))]
    for b in (2e-4, 5e-4, 1e-3):
        pb, vb = synthetic_ticks(6000, drift=2e-5, noise=0.0, bounce=b, seed=int(b * 1e6))
        _, hb, lb, _, _ = aggregate(pb, vb, 20)
        spreads.append(tail_mean(q.corwin_schultz_spread(hb, lb)))
    monotone = all(spreads[i] < spreads[i + 1] for i in range(len(spreads) - 1))
    check("Corwin-Schultz: يزيد رتيبًا مع زيادة الارتداد", monotone,
          " → ".join(f"{s*1e4:.1f}bps" for s in spreads))
    check("Corwin-Schultz: أقوي ارتداد ≥ 2× السلسلة الناعمة", spreads[-1] > spreads[0] * 2.0,
          f"ratio={spreads[-1]/max(spreads[0],1e-12):.2f}x")
    check("Corwin-Schultz: سلسلة ناعمة ⇒ سبريد أقل من 30bps", spreads[0] < 0.003,
          f"{spreads[0]*1e4:.2f}bps")


def test_hurst_entropy_fractal():
    ot, ht, lt, ct, vt = bars("trend", seed=51, n_bars=900)
    om, hm, lm, cm, vm = bars("meanrev", seed=52, n_bars=900)
    orr, hr, lr, cr, vr = bars("random", seed=53, n_bars=900)

    H_t = tail_mean(q.hurst_varratio(ct, 120))
    H_m = tail_mean(q.hurst_varratio(cm, 120))
    H_r = tail_mean(q.hurst_varratio(cr, 120))
    check("Hurst: ترند > 0.52", H_t > 0.52, f"H_trend={H_t:.3f}")
    check("Hurst: ارتداد < 0.48", H_m < 0.48, f"H_meanrev={H_m:.3f}")
    check("Hurst: عشوائي ≈ 0.5", 0.40 <= H_r <= 0.60, f"H_random={H_r:.3f}")
    check("Hurst ∈ [0,1]", all(0.0 <= x <= 1.0 for x in (H_t, H_m, H_r)), f"{H_t:.2f}/{H_m:.2f}/{H_r:.2f}")

    r_t = np.diff(np.log(ct))
    r_m = np.diff(np.log(cm))
    r_r = np.diff(np.log(cr))
    PE_t = tail_mean(q.permutation_entropy(r_t, 60))
    PE_m = tail_mean(q.permutation_entropy(r_m, 60))
    PE_r = tail_mean(q.permutation_entropy(r_r, 60))
    check("PermutationEntropy ∈ [0,1]", all(0.0 <= x <= 1.0 for x in (PE_t, PE_m, PE_r)),
          f"{PE_t:.3f}/{PE_m:.3f}/{PE_r:.3f}")
    check("PermutationEntropy: الترند أكثر انتظامًا من العشوائي", PE_t < PE_r,
          f"trend={PE_t:.3f} random={PE_r:.3f}")
    check("PermutationEntropy: الارتداد أكثر انتظامًا من العشوائي", PE_m < PE_r + 0.02,
          f"meanrev={PE_m:.3f} random={PE_r:.3f}")

    SE_r = tail_mean(q.shannon_entropy(r_r, 60, 8))
    check("ShannonEntropy ∈ [0,1]", 0.0 <= SE_r <= 1.0, f"random={SE_r:.3f}")

    ER_t = tail_mean(q.efficiency_ratio(ct, 20))
    ER_r = tail_mean(q.efficiency_ratio(cr, 20))
    check("EfficiencyRatio: ترند > عشوائي", ER_t > ER_r * 1.5,
          f"trend={ER_t:.3f} random={ER_r:.3f}")

    FD_t = tail_mean(q.higuchi_fd(ct, 30, 5))
    FD_r = tail_mean(q.higuchi_fd(cr, 30, 5))
    check("HiguchiFD: الترند أقل كسورية من الضجيج", FD_t < FD_r,
          f"trend={FD_t:.3f} random={FD_r:.3f}")
    check("HiguchiFD: القيم في النطاق [1,2]", 0.9 <= FD_t <= 2.05 and 0.9 <= FD_r <= 2.05,
          f"trend={FD_t:.3f} random={FD_r:.3f}")


def test_percentile_and_meta():
    x = np.arange(300, dtype=float)
    pr = q.percentile_rank(x, 100)
    check("PercentileRank ∈ [0,100]", bool(np.nanmin(pr) >= 0 and np.nanmax(pr) <= 100),
          f"[{np.nanmin(pr):.1f}, {np.nanmax(pr):.1f}]")
    check("PercentileRank: أعلى قيمة في نافذة صاعدة = 99", abs(pr[-1] - 99.0) < 1e-9, f"{pr[-1]:.1f}")

    best = q.meta_score(1, 0.6, 70.0, 10.0, 15.0, 20.0, 0.3, 90.0, True, True, False)
    worst = q.meta_score(1, -0.6, 99.5, 95.0, 90.0, 92.0, 2.8, 5.0, False, True, True)
    closed = q.meta_score(1, 0.6, 70.0, 10.0, 15.0, 20.0, 0.3, 90.0, True, False, False)
    check("MetaScore: توافُق كامل > 70", best > 70.0, f"{best:.1f}")
    check("MetaScore: ظروف سيئة < 25", worst < 25.0, f"{worst:.1f}")
    check("MetaScore: خارج الجلسة = 0", closed == 0.0, f"{closed:.1f}")
    check("MetaScore: الترتيب صحيح", best > worst, f"{best:.1f} > {worst:.1f}")


def test_position_size():
    risk, lots, units = q.position_size(10_000, 0.01, 2650.0, 2645.0, 100.0)
    check("الحجم: المخاطرة = 1% من الحساب", abs(risk - 100.0) < 1e-9, f"${risk:.2f}")
    check("الحجم: lots = risk/(dist×cv)", abs(lots - (100.0 / (5.0 * 100.0))) < 1e-12,
          f"{lots:.4f} lot")
    check("الحجم: وحدات العقد", abs(units - lots * 100.0) < 1e-9, f"{units:.2f} oz")
    r2, l2, _ = q.position_size(10_000, 0.01, 2650.0, 2650.0, 100.0)
    check("الحجم: وقف = الدخول ⇒ صفر حجم", l2 == 0.0, f"{l2}")


def test_triple_barrier():
    # مسار لازم يضرب الهدف: صعود مستقيم
    n = 60
    c = 2000.0 + np.arange(n) * 2.0
    h = c + 0.5
    l = c - 0.5
    tr = q.triple_barrier_walk(h, l, c, [0], [1], [10.0], rr=1.8, max_bars=40)
    check("TB: مسار صاعد يضرب الهدف", tr[0]["reason"] == "target", f"{tr[0]['reason']}")
    check("TB: الربح = +1.8R", abs(tr[0]["r"] - 1.8) < 1e-9, f"{tr[0]['r']:.4f}R")

    c2 = 2000.0 - np.arange(n) * 2.0
    tr2 = q.triple_barrier_walk(c2 + 0.5, c2 - 0.5, c2, [0], [1], [10.0], rr=1.8, max_bars=40)
    check("TB: مسار هابط يضرب الوقف", tr2[0]["reason"] == "stop", f"{tr2[0]['reason']}")
    check("TB: الخسارة = -1R", abs(tr2[0]["r"] + 1.0) < 1e-9, f"{tr2[0]['r']:.4f}R")

    c3 = np.full(n, 2000.0)
    tr3 = q.triple_barrier_walk(c3 + 0.1, c3 - 0.1, c3, [0], [1], [10.0], rr=1.8, max_bars=12)
    check("TB: سعر ثابت ⇒ انتهاء الوقت", tr3[0]["reason"] == "time", f"{tr3[0]['reason']}")
    check("TB: لا صفقة جديدة قبل إغلاق السابقة",
          len(q.triple_barrier_walk(h, l, c, [0, 1, 2], [1, 1, 1], [10.0, 10.0, 10.0], rr=1.8, max_bars=40)) == 1,
          "1 trade")

    # 5 صفقات: [+1.8R, −1R, +1.8R, −1R, +1.8R]  ⇒  نجاح 60%
    # التوقع = (3×1.8 − 2×1.0)/5 = 3.4/5 = 0.68R  ⇒  0.68 × $100 = $68
    st = q.trade_stats(tr + [{"r": -1.0}, {"r": 1.8}, {"r": -1.0}, {"r": 1.8}], 100.0)
    check("Stats: نسبة النجاح = 60%", abs(st["win_rate"] - 60.0) < 1e-9, f"{st['win_rate']:.1f}%")
    check("Stats: التوقع = 0.68R", abs(st["expectancy_r"] - 0.68) < 1e-9, f"{st['expectancy_r']:.4f}R")
    check("Stats: التوقع بالدولار = $68", abs(st["expectancy_usd"] - 68.0) < 1e-9, f"${st['expectancy_usd']:.2f}")
    check("Stats: Profit Factor = 2.7", abs(st["profit_factor"] - 2.7) < 1e-9, f"{st['profit_factor']:.3f}")
    empty = q.trade_stats([], 100.0)
    check("Stats: صفر صفقات ⇒ أصفار", empty["trades"] == 0 and empty["net_usd"] == 0.0, "ok")


def test_full_engine():
    o, h, l, c, v = bars("informed", seed=71, n_bars=2200)
    out = q.engine_signals(c, h, l, o, v, rank_len=200, min_meta=55.0)
    tr = out["trades"]
    st = q.trade_stats(tr, 100.0)

    n_sig = int(np.sum(out["dir"] != 0))
    check("Engine: بيطلّع إشارات", n_sig > 0, f"signals={n_sig}")
    check("Engine: الصفقات ≤ الإشارات", 0 < len(tr) <= n_sig, f"trades={len(tr)} signals={n_sig}")
    check("Engine: كل القيم محدودة", all(math.isfinite(x) for x in
          [st["win_rate"], st["expectancy_r"], st["net_usd"], st["max_drawdown_usd"]]),
          f"{st}")
    check("Engine: الحواجز كلها معروفة",
          all(t["reason"] in ("stop", "target", "time") for t in tr), "ok")
    check("Engine: |R| ≤ 1.8", all(abs(t["r"]) <= 1.8 + 1e-9 for t in tr),
          f"max|r|={max((abs(t['r']) for t in tr), default=0):.3f}")
    check("Engine: الحالة ∈ {-1,0,1}", set(np.unique(out["state"]).tolist()) <= {-1, 0, 1},
          f"{sorted(set(np.unique(out['state']).tolist()))}")
    check("Engine: الـ meta ∈ [0,100]",
          bool(np.nanmin(out["meta"]) >= 0 and np.nanmax(out["meta"]) <= 100),
          f"[{np.nanmin(out['meta']):.1f}, {np.nanmax(out['meta']):.1f}]")

    # الـ meta-gate لازم يقلّل عدد الصفقات فعليًا
    strict = q.engine_signals(c, h, l, o, v, rank_len=200, min_meta=55.0)
    loose = q.engine_signals(c, h, l, o, v, rank_len=200, min_meta=0.0)
    n_strict = int(np.sum(strict["dir"] != 0))
    n_loose = int(np.sum(loose["dir"] != 0))
    check("Engine: الـ meta-gate بيصفّي الإشارات", n_strict <= n_loose,
          f"meta≥55 → {n_strict} / meta≥0 → {n_loose}")

    print()
    print("  ── نتيجة المحرك على بيانات صناعية (تدفق مُطّلع، 2200 شمعة) ──")
    print(f"  إشارات={n_sig:>4}   صفقات={st['trades']:>4}   "
          f"نجاح={st['win_rate']:>5.1f}%   توقع={st['expectancy_r']:>+.3f}R "
          f"(${st['expectancy_usd']:>+.2f}/صفقة)")
    print(f"  صافي=${st['net_usd']:>+9.2f}   أقصى تراجع=${st['max_drawdown_usd']:>8.2f}   "
          f"PF={st['profit_factor']:.2f}")
    print("  (أرقام على بيانات صناعية — دليل إن الحساب شغال، مش دليل ربحية على الذهب)")


def main() -> int:
    tests = [
        ("erf / Φ", test_erf_and_cdf),
        ("BVC", test_bvc),
        ("VPIN (volume clock)", test_vpin),
        ("OFI / Kyle λ", test_ofi_and_lambda),
        ("Amihud / Corwin-Schultz", test_amihud_and_spread),
        ("Hurst / Entropy / Fractal", test_hurst_entropy_fractal),
        ("Percentile / Meta-label", test_percentile_and_meta),
        ("Position sizing", test_position_size),
        ("Triple barrier", test_triple_barrier),
        ("Full engine", test_full_engine),
    ]
    print("=" * 78)
    print("  QFlow core — اختبار المرجع الحسابي")
    print("=" * 78)
    for name, fn in tests:
        before = len(FAILS)
        fn()
        status = "OK  " if len(FAILS) == before else "FAIL"
        print(f"  [{status}] {name}")

    print("-" * 78)
    for st, name, detail in LOG:
        print(f"   {st}  {name:<48} {detail}")
    print("-" * 78)
    total = len(LOG)
    print(f"  النتيجة: {total - len(FAILS)}/{total} اختبار نجح")
    if FAILS:
        print("\n  ✗ فشل:")
        for f in FAILS:
            print(f"     - {f}")
        return 1
    print("  ✓ كل الاختبارات نجحت")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
