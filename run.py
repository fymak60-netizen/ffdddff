#!/usr/bin/env python3
"""
ULTRA-HFT QUANT CORE V6 — نقطة التشغيل
======================================
    python run.py                 تشغيل عادي
    python run.py --port 8080     منفذ مخصص
    python run.py --host 0.0.0.0  السماح بالوصول من الشبكة
"""
import argparse, os, sys, webbrowser, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    import config
    ap = argparse.ArgumentParser(description="ULTRA-HFT QUANT CORE V6")
    ap.add_argument("--host", default=config.HOST)
    ap.add_argument("--port", type=int, default=config.PORT)
    ap.add_argument("--login", type=int)
    ap.add_argument("--password")
    ap.add_argument("--server")
    ap.add_argument("--symbol")
    ap.add_argument("--timeframe")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    if a.login:     os.environ["MT5_LOGIN"]    = str(a.login)
    if a.password:  os.environ["MT5_PASSWORD"] = a.password
    if a.server:    os.environ["MT5_SERVER"]   = a.server
    if a.symbol:    os.environ["DEFAULT_SYMBOL"] = a.symbol
    if a.timeframe: os.environ["DEFAULT_TIMEFRAME"] = a.timeframe

    import importlib
    importlib.reload(config)

    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0','') else a.host}:{a.port}"
    print("\n" + "=" * 62)
    print("  ⚡  ULTRA-HFT QUANT CORE V6  —  MetaTrader 5 Live Engine")
    print("=" * 62)
    print(f"  الحساب   : {config.ACCOUNT_NUMBER} @ {config.BROKER_SERVER}")
    print(f"  الرمز     : {config.DEFAULT_SYMBOL} / {config.DEFAULT_TIMEFRAME}")
    print(f"  اللوحة    : {url}")
    print("=" * 62 + "\n")

    if not a.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.8), webbrowser.open(url)),
                         daemon=True).start()

    import uvicorn
    uvicorn.run("server.app:app", host=a.host, port=a.port, log_level="warning")

if __name__ == "__main__":
    main()
