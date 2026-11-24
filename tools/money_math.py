"""
حساب الأرقام التقديرية بالدولار — قابل لإعادة التشغيل.

    python3 tools/money_math.py

⚠ كل الأرقام هنا *حساب رياضي على افتراضات مكتوبة*، مش نتيجة باك تست.
   الأرقام الحقيقية بتيجي من `pine/QFL_QuantFlowLab_Strategy.pine` جوه
   Strategy Tester بتاع TradingView على بيانات فعلية.
"""

from __future__ import annotations

import math

EQUITY = 10_000.0
RISK_PCT = 0.01
WIN_RATE = 0.55          # البروفايل اللي اختارته: "متوازن"
RR = 1.8                 # الهدف = 1.8 × الوقف
COST_PER_TRADE = 4.0     # عمولة + سبريد تقريبي للدهب (round trip)


def expectancy(win_rate: float, rr: float) -> tuple[float, float, float]:
    """بيرجع (التوقع بـ R، الانحراف المعياري بـ R، نقطة التعادل)."""
    e = win_rate * rr - (1 - win_rate) * 1.0
    var = win_rate * (rr - e) ** 2 + (1 - win_rate) * (-1.0 - e) ** 2
    breakeven = 1.0 / (1.0 + rr)
    return e, math.sqrt(var), breakeven


def kelly(win_rate: float, rr: float) -> float:
    """Kelly: f = p/a − q/b  (a = الخسارة = 1R، b = الربح = rr)."""
    return win_rate / 1.0 - (1 - win_rate) / rr


def worst_streak(win_rate: float, trades: int) -> int:
    """أطول سلسلة خسارة متوقعة: أطول k بحيث n·q^k ≥ 1."""
    q = 1 - win_rate
    k = 1
    while trades * (q ** k) >= 1.0 and k < 60:
        k += 1
    return k


def main() -> int:
    risk = EQUITY * RISK_PCT
    e_r, sd_r, be = expectancy(WIN_RATE, RR)
    e_net_r = e_r - COST_PER_TRADE / risk
    e_usd = e_r * risk
    e_net_usd = e_net_r * risk

    print("=" * 76)
    print("  QFlow LAB — الحساب التقديري (افتراضات صريحة، مش باك تست)")
    print("=" * 76)
    print(f"  الحساب            : ${EQUITY:,.0f}")
    print(f"  المخاطرة          : {RISK_PCT*100:.1f}%  ⇒  ${risk:.0f} في الصفقة (1R)")
    print(f"  نسبة النجاح       : {WIN_RATE*100:.0f}%")
    print(f"  الهدف : الوقف     : {RR:.1f} : 1")
    print(f"  نقطة التعادل      : {be*100:.1f}%  (أقل من كده ⇒ النظام خاسر)")
    print(f"  التوقع الخام      : {e_r:+.3f}R  =  ${e_usd:+.2f} / صفقة")
    print(f"  تكلفة الصفقة      : ${COST_PER_TRADE:.2f}  =  {COST_PER_TRADE/risk:.3f}R")
    print(f"  التوقع الصافي     : {e_net_r:+.3f}R  =  ${e_net_usd:+.2f} / صفقة")
    print(f"  الانحراف المعياري : {sd_r:.3f}R  =  ${sd_r*risk:.2f} / صفقة")
    print(f"  Kelly الكامل      : {kelly(WIN_RATE, RR)*100:.1f}%  ⇒  "
          f"إنت بتخاطر {RISK_PCT*100:.1f}% = {RISK_PCT/kelly(WIN_RATE, RR)*100:.1f}% من Kelly")
    print()

    print("  ── الإسقاط الشهري (فائدة مركّبة على 12 شهر) ─────────────────────────")
    print(f"  {'صفقات/شهر':>10} | {'صافي/شهر':>10} | {'% شهري':>8} | "
          f"{'آخر السنة':>12} | {'أقصى DD متوقع':>14}")
    print("  " + "-" * 72)
    for n in (5, 10, 20, 40, 60):
        monthly = e_net_usd * n
        pct = monthly / EQUITY * 100.0
        yearly = EQUITY * ((1 + e_net_usd * n / EQUITY) ** 12)
        streak = worst_streak(WIN_RATE, n * 12)
        dd = streak * risk
        dd2 = 2.0 * sd_r * risk * math.sqrt(n)
        print(f"  {n:>10} | ${monthly:>9,.0f} | {pct:>7.1f}% | "
              f"${yearly:>11,.0f} | ${max(dd, dd2):>13,.0f}")

    print()
    print("  ── حساسية النتيجة لنسبة النجاح (نفس الـ R:R = 1.8) ──────────────────")
    print(f"  {'نسبة النجاح':>10} | {'التوقع':>9} | {'$ / صفقة':>10} | {'20 صفقة/شهر':>12}")
    print("  " + "-" * 50)
    for w in (0.30, 0.358, 0.40, 0.45, 0.50, 0.55, 0.60):
        er, _, _ = expectancy(w, RR)
        net = er * risk - COST_PER_TRADE
        tag = "  ← نقطة التعادل" if abs(w - be) < 0.01 else ""
        print(f"  {w*100:>9.1f}% | {er:>+8.3f}R | ${net:>+9.2f} | ${net*20:>+11,.0f}{tag}")

    print()
    print("  ⚠ الأرقام دي مش وعد. هي بتقول: *لو* النظام حقق 55% نجاح بـ 1:1.8،")
    print("    *و* التزمت بالحجم، دي النتيجة الحسابية. الشرط الأول هو الصعب،")
    print("    والطريقة الوحيدة لمعرفته هي الـ Strategy Tester على بياناتك إنت.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
