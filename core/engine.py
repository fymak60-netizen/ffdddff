"""
المحرك الحي — يجمع الجسر + الاستراتيجية + التنفيذ في حلقة واحدة.
"""

from __future__ import annotations

import asyncio
import copy
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import config
from .mt5_bridge import MT5Bridge
from .strategy import StrategyEngine
from .trader import TradeManager


class LiveEngine:
    def __init__(self) -> None:
        self.bridge = MT5Bridge(
            login=config.ACCOUNT_NUMBER,
            password=config.ACCOUNT_PASSWORD,
            server=config.BROKER_SERVER,
            path=config.MT5_PATH,
            timeout=config.MT5_TIMEOUT,
            allow_sim=config.ALLOW_SIMULATOR,
        )
        self.strategy = StrategyEngine(copy.deepcopy(config.STRATEGY_DEFAULTS))
        self.trader = TradeManager(self.bridge, copy.deepcopy(config.TRADING_DEFAULTS))

        self.symbol = config.DEFAULT_SYMBOL
        self.timeframe = config.DEFAULT_TIMEFRAME
        self.bars_count = int(config.BARS_TO_LOAD)
        self.interval = float(config.ENGINE_INTERVAL)

        self.snapshot: Dict[str, Any] = {"ok": False, "message": "المحرك لم يبدأ بعد"}
        self.signal_history: List[dict] = []
        self._lock = threading.RLock()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._subs: set = set()
        self._last_error = ""
        self._tick_count = 0

    # ── التحكم ────────────────────────────────────────────
    def connect(self) -> dict:
        st = self.bridge.connect()
        self.trader._log("INFO", f"حالة الاتصال: {st.mode} — {st.message}")
        return self.status()

    def status(self) -> dict:
        st = self.bridge.status
        return {
            "connected": st.connected, "mode": st.mode, "message": st.message,
            "login": st.login, "server": st.server, "last_error": st.last_error,
            "connected_at": st.connected_at, "running": self._running,
            "symbol": self.symbol, "timeframe": self.timeframe,
            "ticks": self._tick_count,
        }

    def set_market(self, symbol: Optional[str] = None,
                   timeframe: Optional[str] = None) -> dict:
        with self._lock:
            if symbol:
                self.symbol = symbol.upper().strip()
                self.bridge.ensure_symbol(self.symbol)
            if timeframe:
                self.timeframe = timeframe.upper().strip()
            self.trader._log("INFO", f"تغيير السوق → {self.symbol} / {self.timeframe}")
        return {"symbol": self.symbol, "timeframe": self.timeframe}

    # ── دورة واحدة ────────────────────────────────────────
    def cycle(self) -> Dict[str, Any]:
        started = time.time()
        symbol, tf = self.symbol, self.timeframe
        try:
            self.bridge.maintain_simulator()
            bars = self.bridge.bars(symbol, tf, self.bars_count)
            if not bars:
                raise RuntimeError(f"لا توجد بيانات للرمز {symbol} على الإطار {tf}")

            analysis = self.strategy.analyze(bars)
            if not analysis.get("ok"):
                raise RuntimeError(analysis.get("error", "فشل التحليل"))

            sig = analysis["signal"]
            atr_now = float(analysis["state"]["atr"]) or 0.0

            # إدارة الصفقات القائمة أولاً
            try:
                self.trader.manage_open(symbol, atr_now)
            except Exception as e:
                self.trader._log("ERROR", f"إدارة الصفقات: {e}")

            # تنفيذ الإشارة إن كان الآلي مفعّلاً
            exec_result = None
            if sig["direction"] != 0:
                exec_result = self.trader.on_signal(symbol, sig)
                with self._lock:
                    prev = self.signal_history[-1] if self.signal_history else None
                    if not prev or prev["bar_time"] != sig["bar_time"] or \
                            prev["direction"] != sig["direction"]:
                        self.signal_history.append({
                            **sig, "symbol": symbol, "timeframe": tf,
                            "executed": bool(exec_result and exec_result.get("ok")),
                            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        })
                        if len(self.signal_history) > 200:
                            del self.signal_history[:len(self.signal_history) - 200]

            tick = self.bridge.tick(symbol)
            info = self.bridge.symbol_info(symbol)
            account = self.bridge.account()
            positions = self.bridge.positions()

            chart_bars = bars[-300:]
            self._tick_count += 1

            snap = {
                "ok": True,
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "status": self.status(),
                "symbol": symbol, "timeframe": tf,
                "tick": tick,
                "symbol_info": info,
                "account": account,
                "positions": positions,
                "bars": chart_bars,
                "signal": sig,
                "scores": analysis["scores"],
                "state": analysis["state"],
                "series": analysis["series"],
                "fvgs": analysis["fvgs"],
                "swings": analysis["swings"],
                "markers": analysis["markers"],
                "stats": analysis["stats"],
                "account_stats": self.trader.account_stats(7),
                "settings": {
                    "strategy": self.strategy.p,
                    "trading": self.trader.s,
                },
                "signals_recent": self.signal_history[-20:][::-1],
                "logs": self.trader.logs(60),
                "exec": exec_result,
                "cycle_ms": round((time.time() - started) * 1000, 1),
            }
            self._last_error = ""
            with self._lock:
                self.snapshot = snap
            return snap
        except Exception as e:
            self._last_error = f"{e}"
            err = {
                "ok": False, "error": str(e),
                "trace": traceback.format_exc(limit=3),
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "status": self.status(),
                "logs": self.trader.logs(40),
            }
            with self._lock:
                self.snapshot = {**self.snapshot, **err} if self.snapshot.get("ok") else err
            return err

    # ── الحلقة غير المتزامنة ──────────────────────────────
    async def run(self) -> None:
        self._running = True
        self.trader._log("INFO", "بدأ المحرك الحي ⚡")
        loop = asyncio.get_running_loop()
        while self._running:
            t0 = time.time()
            snap = await loop.run_in_executor(None, self.cycle)
            await self._broadcast(snap)
            await asyncio.sleep(max(0.15, self.interval - (time.time() - t0)))
        self.trader._log("INFO", "توقف المحرك")

    def stop(self) -> None:
        self._running = False

    # ── WebSocket ─────────────────────────────────────────
    def subscribe(self, ws) -> None:
        self._subs.add(ws)

    def unsubscribe(self, ws) -> None:
        self._subs.discard(ws)

    async def _broadcast(self, snap: Dict[str, Any]) -> None:
        if not self._subs:
            return
        dead = []
        for ws in list(self._subs):
            try:
                await ws.send_json(snap)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._subs.discard(ws)


ENGINE = LiveEngine()
