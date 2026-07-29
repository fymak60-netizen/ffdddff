# -*- coding: utf-8 -*-
"""
==============================================================
  محرك الاختبار التاريخي (Backtesting)
  ----------------------------------------------------------
  • دخول واقعي: الإشارة على إغلاق الشمعة → تنفيذ على فتح التالية
  • خروج محافظ: لو ضرب الوقف والهدف بنفس الشمعة ⇒ يُحتسب الوقف
  • تقرير كامل: نسبة الفوز، عامل الربح، أقصى تراجع، التوقع الرياضي
==============================================================
"""
from typing import Optional

import numpy as np
import pandas as pd

from config import Config
from risk import RiskManager, approx_pnl, approx_volume
from strategies import get_strategy


def load_csv(path: str) -> pd.DataFrame:
    """
    تحميل شموع من CSV. الأعمدة المقبولة:
      time/date/datetime , open , high , low , close , volume/tick_volume
    """
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next((c for c in ("time", "date", "datetime", "timestamp") if c in df.columns), None)
    if tcol is None:
        raise SystemExit("⛔ ملف CSV يجب أن يحتوي عمود وقت باسم time أو date")
    df["time"] = pd.to_datetime(df[tcol], errors="coerce")
    if df["time"].dt.tz is None:
        df["time"] = df["time"].dt.tz_localize("UTC")
    else:
        df["time"] = df["time"].dt.tz_convert("UTC")
    vcol = next((c for c in ("volume", "tick_volume", "vol") if c in df.columns), None)
    df["volume"] = df[vcol].astype(float) if vcol else 1000.0
    need = ["open", "high", "low", "close"]
    for c in need:
        if c not in df.columns:
            raise SystemExit(f"⛔ ملف CSV ينقصه عمود: {c}")
    df = df[["time", "open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
    df = df.sort_values("time").reset_index(drop=True)
    return df


def run_backtest(df: pd.DataFrame, cfg: Config) -> dict:
    strat = get_strategy(cfg.strategy)
    print("\n" + "═" * 62)
    print(f"  🔬 اختبار تاريخي — {cfg.symbol} | {cfg.timeframe} | {strat.label}")
    print(f"     الشموع: {len(df)}  |  من {df['time'].iloc[0]}  إلى {df['time'].iloc[-1]}")
    print("═" * 62)

    sig_map = {i: s for i, s in strat.stream_signals(df, cfg)}

    balance = cfg.bt_start_balance
    start_balance = balance
    trades = []
    pending = None
    pos: Optional[dict] = None
    equity_curve = [balance]
    peak = balance
    max_dd = 0.0

    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    opens = df["open"].to_numpy()
    times = df["time"].tolist()

    for i in range(len(df)):
        # 1) تنفيذ صفقة معلقة على فتح هذه الشمعة
        if pending is not None and pos is None:
            entry = float(opens[i])
            sd = pending.sl_dist
            vol = 0.0
            if (sd == sd) and sd > 0:   # مسافة وقف صالحة؟
                vol = approx_volume(cfg.symbol, entry, sd, balance, cfg.risk_percent)
            if vol > 0:
                sl, tp = RiskManager.sl_tp(pending.direction, entry, sd, cfg.rr1)
                risk_amt = balance * cfg.risk_percent / 100.0
                pos = dict(entry=entry, sl=sl, tp=tp, direction=pending.direction,
                           volume=vol, t_in=times[i], score=pending.score,
                           reasons=" | ".join(pending.reasons), balance_in=balance,
                           risk_amt=risk_amt)
            pending = None

        # 2) فحص الوقف/الهدف داخل الشمعة (الوقف أولاً — محافظ)
        if pos is not None:
            hi, lo = float(highs[i]), float(lows[i])
            if pos["direction"] == 1:
                hit_sl, hit_tp = lo <= pos["sl"], hi >= pos["tp"]
            else:
                hit_sl, hit_tp = hi >= pos["sl"], lo <= pos["tp"]
            if hit_sl or hit_tp:
                exit_price = pos["sl"] if hit_sl else pos["tp"]
                pnl = approx_pnl(cfg.symbol, pos["entry"], exit_price,
                                 pos["direction"], pos["volume"])
                balance += pnl
                r_mult = pnl / pos["risk_amt"] if pos["risk_amt"] > 0 else 0.0
                trades.append({
                    "entry_time": pos["t_in"], "exit_time": times[i],
                    "direction": "BUY" if pos["direction"] == 1 else "SELL",
                    "entry": round(pos["entry"], 6), "exit": round(exit_price, 6),
                    "volume": pos["volume"], "score": pos["score"],
                    "pnl": round(pnl, 2), "R": round(r_mult, 2),
                    "result": "WIN" if pnl > 0 else "LOSS",
                    "reasons": pos["reasons"],
                })
                pos = None

        # 3) إشارة على إغلاق هذه الشمعة → تنفيذ على فتح التالية
        if i in sig_map and pos is None:
            pending = sig_map[i]

        # 4) منحنى الأكويتي
        mark = balance
        if pos is not None:
            mark += approx_pnl(cfg.symbol, pos["entry"], float(closes[i]),
                               pos["direction"], pos["volume"])
        equity_curve.append(mark)
        peak = max(peak, mark)
        dd = (peak - mark) / peak * 100.0 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    # إغلاق أي صفقة مفتوحة على آخر إغلاق
    if pos is not None:
        exit_price = float(closes[-1])
        pnl = approx_pnl(cfg.symbol, pos["entry"], exit_price, pos["direction"], pos["volume"])
        balance += pnl
        trades.append({
            "entry_time": pos["t_in"], "exit_time": times[-1],
            "direction": "BUY" if pos["direction"] == 1 else "SELL",
            "entry": round(pos["entry"], 6), "exit": round(exit_price, 6),
            "volume": pos["volume"], "score": pos["score"],
            "pnl": round(pnl, 2),
            "R": round(pnl / pos["risk_amt"], 2) if pos["risk_amt"] > 0 else 0.0,
            "result": "WIN" if pnl > 0 else "LOSS", "reasons": pos["reasons"],
        })

    report = _build_report(trades, equity_curve, start_balance, balance, max_dd, cfg)
    _print_report(report, trades)
    if cfg.save_trades:
        pd.DataFrame(trades).to_csv(cfg.save_trades, index=False, encoding="utf-8-sig")
        print(f"\n💾 حُفظت تفاصيل الصفقات في: {cfg.save_trades}")
    return report


def _build_report(trades, equity_curve, start_balance, balance, max_dd, cfg):
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    net = balance - start_balance
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0
    win_rate = len(wins) / n * 100.0 if n else 0.0
    expectancy = net / n if n else 0.0
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = -gross_loss / len(losses) if losses else 0.0
    return {
        "n": n, "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate, "profit_factor": pf,
        "net": net, "return_pct": net / start_balance * 100.0,
        "max_dd": max_dd, "expectancy": expectancy,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "best": max((t["pnl"] for t in trades), default=0.0),
        "worst": min((t["pnl"] for t in trades), default=0.0),
        "start": start_balance, "end": balance,
    }


def _print_report(r, trades):
    pf = f"{r['profit_factor']:.2f}" if r["profit_factor"] != float("inf") else "∞"
    print("\n┌────────────────────── 📊 نتيجة الاختبار ──────────────────────┐")
    print(f"  عدد الصفقات        : {r['n']}")
    print(f"  صفقات رابحة/خاسرة  : {r['wins']} ✅  /  {r['losses']} ❌")
    print(f"  نسبة الفوز         : {r['win_rate']:.1f}%")
    print(f"  عامل الربح (PF)    : {pf}   (أكبر من 1.5 = جيد)")
    print(f"  صافي الربح         : {r['net']:+.2f}$")
    print(f"  العائد             : {r['return_pct']:+.1f}%")
    print(f"  أقصى تراجع (DD)    : {r['max_dd']:.1f}%")
    print(f"  التوقع لكل صفقة    : {r['expectancy']:+.2f}$")
    print(f"  متوسط ربح/خسارة    : {r['avg_win']:+.2f}$ / {r['avg_loss']:+.2f}$")
    print(f"  أفضل/أسوأ صفقة     : {r['best']:+.2f}$ / {r['worst']:+.2f}$")
    print(f"  الرصيد             : {r['start']:.2f}$ ← {r['end']:.2f}$")
    print("└─────────────────────────────────────────────────────────────┘")

    if trades:
        print("\n  آخر 10 صفقات:")
        print("  " + "-" * 96)
        print(f"  {'الدخول':<20}{'الاتجاه':<7}{'الدخول':>12}{'الخروج':>12}{'اللوت':>8}{'النتيجة':>12}{'R':>8}")
        print("  " + "-" * 96)
        for t in trades[-10:]:
            et = str(t["entry_time"])[:16]
            print(f"  {et:<20}{t['direction']:<7}{t['entry']:>12.5f}{t['exit']:>12.5f}"
                  f"{t['volume']:>8.2f}{t['pnl']:>+12.2f}{t['R']:>+8.2f}")

    if r["n"] == 0:
        print("\n  ℹ️ لا صفقات — جرّب تخفيض min_score أو تغيير الفريم/الاستراتيجية")
