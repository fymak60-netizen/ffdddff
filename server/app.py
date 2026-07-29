"""
ULTRA-HFT QUANT CORE V6 — FastAPI Server
=========================================
واجهة REST + WebSocket تربط اللوحة ثلاثية الأبعاد بمحرك MT5 الحي.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from core.engine import ENGINE

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ENGINE.connect()
    task = asyncio.create_task(ENGINE.run())
    yield
    ENGINE.stop()
    task.cancel()
    ENGINE.bridge.shutdown()


app = FastAPI(title="ULTRA-HFT QUANT CORE V6", version="6.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# ══════════════════════════════════════════════════════════════
#  نماذج الطلبات
# ══════════════════════════════════════════════════════════════
class MarketReq(BaseModel):
    symbol: Optional[str] = None
    timeframe: Optional[str] = None


class SettingsReq(BaseModel):
    strategy: Optional[Dict[str, Any]] = None
    trading: Optional[Dict[str, Any]] = None


class OrderReq(BaseModel):
    symbol: Optional[str] = None
    side: str
    volume: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None
    sl_atr: Optional[float] = None
    tp_atr: Optional[float] = None


class ModifyReq(BaseModel):
    ticket: int
    sl: float = 0.0
    tp: float = 0.0


class CloseReq(BaseModel):
    ticket: Optional[int] = None
    volume: Optional[float] = None
    all: bool = False
    symbol: Optional[str] = None


class LoginReq(BaseModel):
    login: Optional[int] = None
    password: Optional[str] = None
    server: Optional[str] = None
    path: Optional[str] = None


# ══════════════════════════════════════════════════════════════
#  المسارات
# ══════════════════════════════════════════════════════════════
@app.get("/api/status")
def api_status():
    return ENGINE.status()


@app.post("/api/connect")
def api_connect(req: LoginReq):
    if req.login:
        ENGINE.bridge.login = int(req.login)
    if req.password:
        ENGINE.bridge.password = req.password
    if req.server:
        ENGINE.bridge.server = req.server
    if req.path is not None:
        ENGINE.bridge.path = req.path or None
    ENGINE.bridge.shutdown()
    return ENGINE.connect()


@app.get("/api/snapshot")
def api_snapshot():
    return ENGINE.snapshot


@app.get("/api/symbols")
def api_symbols():
    return {"symbols": ENGINE.bridge.symbols(), "current": ENGINE.symbol,
            "timeframes": ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]}


@app.post("/api/market")
def api_market(req: MarketReq):
    res = ENGINE.set_market(req.symbol, req.timeframe)
    ENGINE.cycle()
    return res


@app.get("/api/settings")
def api_get_settings():
    return {"strategy": ENGINE.strategy.p, "trading": ENGINE.trader.s}


@app.post("/api/settings")
def api_set_settings(req: SettingsReq):
    if req.strategy:
        ENGINE.strategy.update_params(req.strategy)
        ENGINE.trader._log("INFO", f"تحديث إعدادات الاستراتيجية: "
                                   f"{list(req.strategy.keys())}")
    if req.trading:
        ENGINE.trader.update_settings(req.trading)
    return {"ok": True, "strategy": ENGINE.strategy.p, "trading": ENGINE.trader.s}


@app.post("/api/order")
def api_order(req: OrderReq):
    symbol = req.symbol or ENGINE.symbol
    atr_now = float((ENGINE.snapshot.get("state") or {}).get("atr", 0.0) or 0.0)
    res = ENGINE.trader.manual_order(
        symbol=symbol, side=req.side, volume=req.volume, sl=req.sl, tp=req.tp,
        sl_atr=req.sl_atr, tp_atr=req.tp_atr, atr_now=atr_now,
    )
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@app.post("/api/modify")
def api_modify(req: ModifyReq):
    res = ENGINE.trader.manual_modify(req.ticket, req.sl, req.tp)
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@app.post("/api/close")
def api_close(req: CloseReq):
    if req.all:
        return ENGINE.trader.close_all(req.symbol)
    if not req.ticket:
        return JSONResponse({"ok": False, "comment": "ticket مطلوب"}, status_code=400)
    res = ENGINE.trader.manual_close(req.ticket, req.volume)
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@app.post("/api/autotrade/{state}")
def api_autotrade(state: str):
    on = state.lower() in ("on", "1", "true", "start")
    ENGINE.trader.update_settings({"auto_trade": on})
    return {"ok": True, "auto_trade": on}


@app.get("/api/positions")
def api_positions():
    return {"positions": ENGINE.bridge.positions()}


@app.get("/api/history")
def api_history(days: int = 7):
    return {"deals": ENGINE.bridge.history_deals(days),
            "stats": ENGINE.trader.account_stats(days)}


@app.get("/api/signals")
def api_signals():
    return {"signals": ENGINE.signal_history[-100:][::-1]}


@app.get("/api/logs")
def api_logs(limit: int = 100):
    return {"logs": ENGINE.trader.logs(limit)}


@app.websocket("/ws")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    ENGINE.subscribe(ws)
    try:
        if ENGINE.snapshot:
            await ws.send_json(ENGINE.snapshot)
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        ENGINE.unsubscribe(ws)


# ── الملفات الثابتة ───────────────────────────────────────────
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))
