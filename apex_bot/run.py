#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================
  ⚡ APEX FOREX BOT — نقطة التشغيل
  ----------------------------------------------------------
  تفاعلي (قوائم عربية)      :  python run.py
  مباشر بأوامر (أوتوماتيك)   :  python run.py live --symbol EURUSD
  اختبار تاريخي             :  python run.py backtest --symbol XAUUSD
  اختبار من ملف CSV         :  python run.py backtest --csv data.csv
  도움말                     :  python run.py -h
==============================================================
"""
import argparse
import sys

from config import COMMON_SYMBOLS, TIMEFRAMES, Config
from strategies import STRATEGIES

BANNER = r"""
    █████╗ ██████╗ ███████╗██╗  ██╗    ███████╗ ██████╗ ██████╗ ██╗  ██╗
   ██╔══██╗██╔══██╗██╔════╝╚██╗██╔╝    ██╔════╝██╔═══██╗██╔══██╗╚██╗██╔╝
   ███████║██████╔╝█████╗   ╚███╔╝     █████╗  ██║   ██║██████╔╝ ╚███╔╝
   ██╔══██║██╔═══╝ ██╔══╝   ██╔██╗     ██╔══╝  ██║   ██║██╔══██╗ ██╔██╗
   ██║  ██║██║     ███████╗██╔╝ ██╗    ██║     ╚██████╔╝██║  ██║██╔╝ ██╗
   ╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝    ╚═╝      ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝
        بوت فوركس تلقائي — محرك SMC مؤسساتي + ربط MetaTrader 5
"""


# ═══════════════════════════════════════════════════════════
#  قوائم تفاعلية
# ═══════════════════════════════════════════════════════════
def _ask(title: str, options: list, allow_custom=False) -> str:
    print(f"\n{title}")
    for i, (key, label) in enumerate(options, 1):
        print(f"   {i}) {label}")
    while True:
        raw = input("\n   اختيارك: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        if allow_custom and raw:
            return raw.upper()
        print("   ⚠️ أدخل رقماً صحيحاً من القائمة")


def interactive_cfg() -> Config:
    cfg = Config()
    print(BANNER)

    # 1) الزوج
    pairs = [(s, s) for s in COMMON_SYMBOLS] + [("CUSTOM", "✏️ زوج آخر (اكتبه يدوياً)")]
    sym = _ask("① اختر زوج العملات / الأصل:", pairs, allow_custom=False)
    if sym == "CUSTOM":
        sym = input("   اكتب الرمز كما يظهر في المنصة (مثال EURUSD.m): ").strip().upper()
    cfg.symbol = sym

    # 2) الاستراتيجية
    strats = [(k, v.label) for k, v in STRATEGIES.items()]
    cfg.strategy = _ask("② اختر الاستراتيجية:", strats)

    # 3) الفريم
    tfs = [(t, t) for t in TIMEFRAMES]
    cfg.timeframe = _ask("③ اختر الفريم الزمني:", tfs)

    # 4) درجة الإشارة لـ SMC
    if cfg.strategy == "smc":
        scores = [("2", "2 — إشارات أكثر (سكالبينج)"),
                  ("3", "3 — متوازن (الافتراضي)"),
                  ("4", "4 — دقيق (صفقات نادرة وقوية)"),
                  ("5", "5 — قنص فقط (نادر جداً)")]
        cfg.min_score = int(_ask("④ حساسية الإشارات (min_score):", scores))

    # 5) الوضع
    modes = [
        ("backtest", "🔬 اختبار تاريخي Backtest (جرّب استراتيجيتك أولاً!)"),
        ("paper",    "🧪 تشغيل ورقي على بيانات حية (بدون مخاطرة)"),
        ("live",     "🔴 تشغيل حقيقي تلقائي (تأكد أنه حساب DEMO أولاً)"),
    ]
    mode = _ask("⑤ اختر وضع التشغيل:", modes)

    if mode == "backtest":
        srcs = [("mt5", "جلب بيانات تاريخية من منصة MT5 المفتوحة"),
                ("csv", "تحميل ملف CSV عندي")]
        src = _ask("⑥ مصدر البيانات التاريخية:", srcs)
        if src == "csv":
            cfg.csv = input("   مسار ملف CSV: ").strip()
        else:
            bars = input("   عدد الشموع التاريخية [5000]: ").strip()
            cfg.bt_bars = int(bars) if bars.isdigit() else 5000
        save = input("   حفظ تفاصيل الصفقات في ملف؟ (اضغط Enter للتخطي أو اكتب المسار): ").strip()
        cfg.save_trades = save or None
        cfg.mode = "backtest"
    else:
        cfg.mode = mode
        risk = input("\n⑦ نسبة المخاطرة لكل صفقة % [1.0]: ").strip()
        cfg.risk_percent = float(risk) if risk else 1.0
        if mode == "live":
            confirm = input("   ⚠️ سيُنفذ البوت صفقات حقيقية. اكتب YES للتأكيد: ").strip()
            if confirm != "YES":
                print("   تم الإلغاء. جرّب الوضع الورقي أولاً 😉")
                sys.exit(0)
            custom = input("   إدخال بيانات الحساب يدوياً؟ (Enter = المنصة المفتوحة): ").strip()
            if custom.lower() in ("y", "yes", "نعم"):
                cfg.login = int(input("   رقم الحساب (login): "))
                cfg.password = input("   كلمة المرور: ")
                cfg.server = input("   اسم السيرفر: ")

    print("\n✅ الإعدادات:\n" + cfg.summary())
    return cfg


# ═══════════════════════════════════════════════════════════
#  الأوامر
# ═══════════════════════════════════════════════════════════
def cmd_backtest(cfg: Config):
    import pandas as pd
    from backtest import load_csv, run_backtest

    if cfg.csv:
        df = load_csv(cfg.csv)
    else:
        from brokers import MT5Broker
        broker = MT5Broker(cfg).connect()
        broker.select_symbol(cfg.symbol)
        print(f"\n⏬ تحميل {cfg.bt_bars} شمعة {cfg.timeframe} لـ {cfg.symbol} ...")
        # نأخذ الشموع كاملة (بما فيها الجارية) — الباك تست يتجاهل آخر شمعة تلقائياً
        import MetaTrader5 as mt5
        rates = mt5.copy_rates_from_pos(cfg.symbol, getattr(mt5, f"TIMEFRAME_{cfg.timeframe}"), 0, cfg.bt_bars)
        if rates is None or len(rates) == 0:
            raise SystemExit(f"⛔ لا بيانات: {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={"tick_volume": "volume"})[["time", "open", "high", "low", "close", "volume"]]
        broker.shutdown()

    run_backtest(df, cfg)
    print("\n⚠️ تذكير: الأداء التاريخي لا يضمن نتائج مستقبلية — اختبر على ديمو قبل الحقيقي.")


def cmd_live(cfg: Config):
    from bot import ApexBot
    ApexBot(cfg).run()


# ═══════════════════════════════════════════════════════════
#  argparse
# ═══════════════════════════════════════════════════════════
def build_parser():
    p = argparse.ArgumentParser(
        description="⚡ APEX FOREX BOT — بوت فوركس تلقائي بمحرك SMC مؤسساتي",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("command", nargs="?", choices=["live", "backtest"],
                   help="live = تشغيل مباشر | backtest = اختبار تاريخي | (بدون = قائمة تفاعلية)")
    p.add_argument("--symbol", default="EURUSD", help="الزوج (افتراضي EURUSD)")
    p.add_argument("--strategy", default="smc", choices=list(STRATEGIES),
                   help="smc | ema | rsi | macd (افتراضي smc)")
    p.add_argument("--timeframe", default="M15", choices=TIMEFRAMES, help="الفريم (افتراضي M15)")
    p.add_argument("--risk", type=float, default=1.0, help="نسبة المخاطرة %% (افتراضي 1.0)")
    p.add_argument("--min-score", type=int, default=3, help="أقل درجة إشارة 0-5 (افتراضي 3)")
    p.add_argument("--paper", action="store_true", help="وضع ورقي محاكى مع live")
    p.add_argument("--csv", default=None, help="ملف CSV للباك تست بدون MT5")
    p.add_argument("--bars", type=int, default=5000, help="عدد شموع الباك تست من MT5")
    p.add_argument("--save-trades", default=None, help="حفظ صفقات الباك تست (CSV)")
    p.add_argument("--login", type=int, default=None, help="رقم حساب MT5")
    p.add_argument("--password", default=None, help="كلمة مرور MT5")
    p.add_argument("--server", default=None, help="سيرفر الوسيط")
    p.add_argument("--path", default=None, help="مسار terminal64.exe")
    p.add_argument("--no-trailing", action="store_true", help="تعطيل وقف التعادل")
    return p


def main():
    if len(sys.argv) == 1:
        cfg = interactive_cfg()
        if cfg.mode == "backtest":
            cmd_backtest(cfg)
        else:
            cmd_live(cfg)
        return

    args = build_parser().parse_args()
    cfg = Config(
        symbol=args.symbol.upper(),
        strategy=args.strategy,
        timeframe=args.timeframe,
        risk_percent=args.risk,
        min_score=args.min_score,
        login=args.login,
        password=args.password,
        server=args.server,
        terminal_path=args.path,
        trailing_breakeven=not args.no_trailing,
        bt_bars=args.bars,
        csv=args.csv,
        save_trades=args.save_trades,
    )

    if args.command == "backtest":
        cmd_backtest(cfg)
    elif args.command == "live":
        cfg.mode = "paper" if args.paper else "live"
        cmd_live(cfg)
    else:
        build_parser().print_help()


if __name__ == "__main__":
    main()
