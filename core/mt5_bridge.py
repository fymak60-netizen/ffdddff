"""
جسر MetaTrader 5
================
طبقة واحدة تتعامل مع MT5 الحقيقي عبر مكتبة `MetaTrader5` (ويندوز)،
ومع محاكي داخلي عند عدم توفر المكتبة (لينكس/ماك) حتى تعمل اللوحة للاختبار.

الحالة الحقيقية تظهر دائماً في الواجهة: LIVE MT5  أو  SIMULATOR.
"""

from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

# ── محاولة استيراد مكتبة MT5 الحقيقية ──────────────────────────
try:
    import MetaTrader5 as _mt5   # type: ignore
    MT5_AVAILABLE = True
    MT5_IMPORT_ERROR = ""
except Exception as _e:          # pragma: no cover
    _mt5 = None
    MT5_AVAILABLE = False
    MT5_IMPORT_ERROR = str(_e)


# ══════════════════════════════════════════════════════════════
#  خرائط الأطر الزمنية
# ══════════════════════════════════════════════════════════════
TF_SECONDS = {
    "M1": 60, "M2": 120, "M3": 180, "M4": 240, "M5": 300, "M6": 360,
    "M10": 600, "M12": 720, "M15": 900, "M20": 1200, "M30": 1800,
    "H1": 3600, "H2": 7200, "H3": 10800, "H4": 14400, "H6": 21600,
    "H8": 28800, "H12": 43200, "D1": 86400, "W1": 604800,
}


def _mt5_tf(tf: str):
    if not MT5_AVAILABLE:
        return None
    return {
        "M1": _mt5.TIMEFRAME_M1, "M2": _mt5.TIMEFRAME_M2, "M3": _mt5.TIMEFRAME_M3,
        "M4": _mt5.TIMEFRAME_M4, "M5": _mt5.TIMEFRAME_M5, "M6": _mt5.TIMEFRAME_M6,
        "M10": _mt5.TIMEFRAME_M10, "M12": _mt5.TIMEFRAME_M12, "M15": _mt5.TIMEFRAME_M15,
        "M20": _mt5.TIMEFRAME_M20, "M30": _mt5.TIMEFRAME_M30, "H1": _mt5.TIMEFRAME_H1,
        "H2": _mt5.TIMEFRAME_H2, "H3": _mt5.TIMEFRAME_H3, "H4": _mt5.TIMEFRAME_H4,
        "H6": _mt5.TIMEFRAME_H6, "H8": _mt5.TIMEFRAME_H8, "H12": _mt5.TIMEFRAME_H12,
        "D1": _mt5.TIMEFRAME_D1, "W1": _mt5.TIMEFRAME_W1,
    }.get(tf.upper(), _mt5.TIMEFRAME_M5)


# ══════════════════════════════════════════════════════════════
#  المحاكي — يولّد شموع وأسعار واقعية عند غياب MT5
# ══════════════════════════════════════════════════════════════
_SIM_SPECS = {
    # symbol:      (سعر البداية, تقلب, digits, حجم النقطة, قيمة النقطة/لوت)
    "EURUSD":  (1.08500, 0.00035, 5, 0.00001, 1.0),
    "GBPUSD":  (1.27200, 0.00045, 5, 0.00001, 1.0),
    "USDJPY":  (151.250, 0.04500, 3, 0.001,   0.66),
    "AUDUSD":  (0.65800, 0.00035, 5, 0.00001, 1.0),
    "USDCAD":  (1.36400, 0.00035, 5, 0.00001, 0.73),
    "USDCHF":  (0.89600, 0.00035, 5, 0.00001, 1.11),
    "NZDUSD":  (0.60200, 0.00035, 5, 0.00001, 1.0),
    "EURJPY":  (164.100, 0.05000, 3, 0.001,   0.66),
    "GBPJPY":  (192.400, 0.07000, 3, 0.001,   0.66),
    "XAUUSD":  (2325.00, 1.20000, 2, 0.01,    1.0),
    "XAGUSD":  (27.4500, 0.03000, 3, 0.001,   5.0),
    "BTCUSD":  (64500.0, 90.0000, 2, 0.01,    1.0),
    "ETHUSD":  (3350.00, 6.00000, 2, 0.01,    1.0),
    "US30":    (39250.0, 25.0000, 1, 0.1,     1.0),
    "NAS100":  (18300.0, 18.0000, 1, 0.1,     1.0),
    "SP500":   (5230.00, 4.00000, 1, 0.1,     1.0),
    "USOIL":   (81.500,  0.20000, 2, 0.01,    1.0),
}


class _Simulator:
    """محاكي سوق بسيط لكنه واقعي (GBM + جلسات + سبريد + تنفيذ صفقات)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._series: Dict[str, Dict[str, List[dict]]] = {}
        self._tick: Dict[str, dict] = {}
        self.balance = 100000.0
        self.equity = 100000.0
        self.positions: Dict[int, dict] = {}
        self.deals: List[dict] = []
        self._ticket = 500000

    # ── شموع ───────────────────────────────────────────────
    def _seed(self, symbol: str, tf: str, count: int) -> List[dict]:
        base, vol, digits, point, _ = _SIM_SPECS.get(symbol, _SIM_SPECS["EURUSD"])
        step = TF_SECONDS.get(tf, 300)
        now = int(time.time())
        start = now - (now % step) - step * count
        rnd = random.Random(hash((symbol, tf)) & 0xFFFFFFFF)
        px = base
        bars: List[dict] = []
        for i in range(count):
            t = start + i * step
            hour = datetime.fromtimestamp(t, timezone.utc).hour
            # التقلب أعلى في جلسات لندن ونيويورك
            sess = 1.5 if 8 <= hour < 17 else (1.7 if 13 <= hour < 22 else 0.6)
            drift = math.sin(i / 55.0) * vol * 0.35
            o = px
            c = o + rnd.gauss(drift, vol * sess)
            wick = abs(rnd.gauss(0, vol * sess * 0.6))
            h = max(o, c) + wick
            low = min(o, c) - abs(rnd.gauss(0, vol * sess * 0.6))
            v = int(abs(rnd.gauss(1200, 400)) * sess) + 50
            bars.append({
                "time": t,
                "open": round(o, digits), "high": round(h, digits),
                "low": round(low, digits), "close": round(c, digits),
                "tick_volume": v, "real_volume": v, "spread": 8,
            })
            px = c
        return bars

    def bars(self, symbol: str, tf: str, count: int) -> List[dict]:
        with self._lock:
            key = f"{symbol}|{tf}"
            if key not in self._series:
                self._series.setdefault(symbol, {})
                self._series[symbol][tf] = self._seed(symbol, tf, max(count, 900))
                self._series[key] = self._series[symbol][tf]  # alias
            data = self._series[symbol][tf]
            self._advance(symbol, tf)
            return [dict(b) for b in data[-count:]]

    def _advance(self, symbol: str, tf: str) -> None:
        """يقدّم الشمعة الأخيرة زمنياً حسب الساعة الحقيقية."""
        base, vol, digits, point, _ = _SIM_SPECS.get(symbol, _SIM_SPECS["EURUSD"])
        step = TF_SECONDS.get(tf, 300)
        data = self._series[symbol][tf]
        now = int(time.time())
        cur_slot = now - (now % step)
        last = data[-1]
        # تحديث الشمعة الجارية
        drift = random.gauss(0, vol * 0.25)
        newc = round(last["close"] + drift, digits)
        if last["time"] == cur_slot:
            last["close"] = newc
            last["high"] = max(last["high"], newc)
            last["low"] = min(last["low"], newc)
            last["tick_volume"] += random.randint(1, 15)
        while data[-1]["time"] < cur_slot:
            prev = data[-1]
            t = prev["time"] + step
            o = prev["close"]
            c = round(o + random.gauss(0, vol), digits)
            h = round(max(o, c) + abs(random.gauss(0, vol * 0.5)), digits)
            lo = round(min(o, c) - abs(random.gauss(0, vol * 0.5)), digits)
            data.append({"time": t, "open": o, "high": h, "low": lo, "close": c,
                         "tick_volume": random.randint(200, 2500),
                         "real_volume": random.randint(200, 2500), "spread": 8})
            if len(data) > 3000:
                del data[:len(data) - 3000]

    def tick(self, symbol: str) -> dict:
        with self._lock:
            base, vol, digits, point, _ = _SIM_SPECS.get(symbol, _SIM_SPECS["EURUSD"])
            bars = self.bars(symbol, "M1", 2)
            mid = bars[-1]["close"]
            spread = point * random.randint(6, 14)
            return {
                "time": int(time.time()),
                "bid": round(mid - spread / 2, digits),
                "ask": round(mid + spread / 2, digits),
                "last": round(mid, digits),
                "volume": random.randint(1, 50),
            }

    def symbol_info(self, symbol: str) -> dict:
        base, vol, digits, point, tickval = _SIM_SPECS.get(symbol, _SIM_SPECS["EURUSD"])
        t = self.tick(symbol)
        return {
            "name": symbol, "digits": digits, "point": point,
            "trade_contract_size": 100000 if "USD" in symbol and len(symbol) == 6 else 100,
            "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01,
            "trade_tick_value": tickval, "trade_tick_size": point,
            "spread": int(round((t["ask"] - t["bid"]) / point)),
            "bid": t["bid"], "ask": t["ask"],
            "trade_stops_level": 0,
        }

    # ── حساب ───────────────────────────────────────────────
    def account(self) -> dict:
        with self._lock:
            profit = 0.0
            for p in self.positions.values():
                profit += self._pos_profit(p)
            self.equity = self.balance + profit
            margin = sum(p["volume"] * 1000 for p in self.positions.values())
            return {
                "login": 0, "server": "SIMULATOR", "name": "Simulated Account",
                "currency": "USD", "leverage": 500,
                "balance": round(self.balance, 2), "equity": round(self.equity, 2),
                "profit": round(profit, 2), "margin": round(margin, 2),
                "margin_free": round(self.equity - margin, 2),
                "margin_level": round(self.equity / margin * 100, 2) if margin else 0.0,
            }

    def _pos_profit(self, p: dict) -> float:
        info = self.symbol_info(p["symbol"])
        px = info["bid"] if p["type"] == 0 else info["ask"]
        p["price_current"] = px
        diff = (px - p["price_open"]) if p["type"] == 0 else (p["price_open"] - px)
        pts = diff / info["point"]
        val = pts * info["trade_tick_value"] * p["volume"] * (info["point"] / info["trade_tick_size"])
        p["profit"] = round(val, 2)
        return p["profit"]

    def order_send(self, req: dict) -> dict:
        with self._lock:
            symbol = req["symbol"]
            info = self.symbol_info(symbol)
            action = req.get("action")
            if action == "DEAL":
                self._ticket += 1
                is_buy = req["type"] == 0
                price = info["ask"] if is_buy else info["bid"]
                pos = {
                    "ticket": self._ticket, "symbol": symbol, "type": req["type"],
                    "volume": float(req["volume"]), "price_open": price,
                    "price_current": price, "sl": float(req.get("sl") or 0.0),
                    "tp": float(req.get("tp") or 0.0), "profit": 0.0, "swap": 0.0,
                    "time": int(time.time()), "magic": req.get("magic", 0),
                    "comment": req.get("comment", ""),
                }
                self.positions[pos["ticket"]] = pos
                return {"retcode": 10009, "comment": "Request executed",
                        "order": pos["ticket"], "price": price, "volume": pos["volume"]}
            if action == "SLTP":
                p = self.positions.get(int(req["position"]))
                if not p:
                    return {"retcode": 10013, "comment": "Invalid position"}
                p["sl"] = float(req.get("sl") or 0.0)
                p["tp"] = float(req.get("tp") or 0.0)
                return {"retcode": 10009, "comment": "Request executed"}
            if action == "CLOSE":
                p = self.positions.get(int(req["position"]))
                if not p:
                    return {"retcode": 10013, "comment": "Invalid position"}
                vol = float(req.get("volume") or p["volume"])
                profit = self._pos_profit(p)
                part = min(vol, p["volume"]) / p["volume"]
                realized = profit * part
                self.balance += realized
                self.deals.append({
                    "ticket": p["ticket"], "symbol": p["symbol"], "type": p["type"],
                    "volume": round(p["volume"] * part, 2), "profit": round(realized, 2),
                    "price_open": p["price_open"], "price_close": p["price_current"],
                    "time": int(time.time()),
                })
                if part >= 0.999:
                    self.positions.pop(p["ticket"], None)
                else:
                    p["volume"] = round(p["volume"] * (1 - part), 2)
                return {"retcode": 10009, "comment": "Request executed",
                        "profit": round(realized, 2)}
            return {"retcode": 10013, "comment": "Unsupported action"}

    def check_sltp(self) -> List[dict]:
        """يغلق الصفقات التي لامست SL/TP (المحاكي فقط)."""
        closed = []
        with self._lock:
            for ticket, p in list(self.positions.items()):
                info = self.symbol_info(p["symbol"])
                px = info["bid"] if p["type"] == 0 else info["ask"]
                hit = None
                if p["type"] == 0:
                    if p["sl"] and px <= p["sl"]:
                        hit = "SL"
                    elif p["tp"] and px >= p["tp"]:
                        hit = "TP"
                else:
                    if p["sl"] and px >= p["sl"]:
                        hit = "SL"
                    elif p["tp"] and px <= p["tp"]:
                        hit = "TP"
                if hit:
                    self.order_send({"action": "CLOSE", "position": ticket})
                    closed.append({"ticket": ticket, "reason": hit})
        return closed


_SIM = _Simulator()


# ══════════════════════════════════════════════════════════════
#  الجسر الموحّد
# ══════════════════════════════════════════════════════════════
@dataclass
class BridgeStatus:
    connected: bool = False
    mode: str = "DISCONNECTED"        # LIVE | SIMULATOR | DISCONNECTED
    message: str = ""
    login: int = 0
    server: str = ""
    last_error: str = ""
    connected_at: Optional[str] = None


class MT5Bridge:
    def __init__(self, login: int, password: str, server: str,
                 path: str = "", timeout: int = 60000, allow_sim: bool = True):
        self.login = int(login)
        self.password = str(password)
        self.server = str(server)
        self.path = path or None
        self.timeout = int(timeout)
        self.allow_sim = allow_sim
        self.status = BridgeStatus()
        self._lock = threading.RLock()

    # ── الاتصال ────────────────────────────────────────────
    def connect(self) -> BridgeStatus:
        with self._lock:
            if MT5_AVAILABLE:
                kw: Dict[str, Any] = {"login": self.login, "password": self.password,
                                      "server": self.server, "timeout": self.timeout}
                if self.path:
                    kw["path"] = self.path
                ok = False
                try:
                    ok = _mt5.initialize(**kw)
                except Exception as e:
                    self.status.last_error = f"initialize exception: {e}"
                if not ok:
                    # محاولة ثانية: تهيئة ثم login
                    try:
                        if _mt5.initialize(path=self.path) if self.path else _mt5.initialize():
                            ok = _mt5.login(self.login, password=self.password,
                                            server=self.server, timeout=self.timeout)
                    except Exception as e:
                        self.status.last_error = f"login exception: {e}"
                if ok:
                    info = _mt5.account_info()
                    self.status = BridgeStatus(
                        connected=True, mode="LIVE",
                        message="متصل بحساب MetaTrader 5 الحقيقي",
                        login=getattr(info, "login", self.login),
                        server=getattr(info, "server", self.server),
                        connected_at=datetime.now(timezone.utc).isoformat(),
                    )
                    return self.status
                err = ""
                try:
                    err = str(_mt5.last_error())
                except Exception:
                    pass
                self.status.last_error = err or self.status.last_error
                if not self.allow_sim:
                    self.status.connected = False
                    self.status.mode = "DISCONNECTED"
                    self.status.message = f"فشل الاتصال بـ MT5: {self.status.last_error}"
                    return self.status
            else:
                self.status.last_error = (
                    "مكتبة MetaTrader5 غير متاحة على هذا النظام "
                    f"({MT5_IMPORT_ERROR or 'Windows only'})"
                )
            # وضع المحاكي
            if self.allow_sim:
                self.status = BridgeStatus(
                    connected=True, mode="SIMULATOR",
                    message="وضع المحاكي — شغّل على ويندوز مع MetaTrader5 للاتصال الحقيقي",
                    login=self.login, server=self.server,
                    last_error=self.status.last_error,
                    connected_at=datetime.now(timezone.utc).isoformat(),
                )
            else:
                self.status = BridgeStatus(connected=False, mode="DISCONNECTED",
                                           message=self.status.last_error)
            return self.status

    def shutdown(self) -> None:
        with self._lock:
            if MT5_AVAILABLE and self.status.mode == "LIVE":
                try:
                    _mt5.shutdown()
                except Exception:
                    pass
            self.status = BridgeStatus()

    @property
    def live(self) -> bool:
        return self.status.mode == "LIVE"

    # ── بيانات السوق ───────────────────────────────────────
    def symbols(self) -> List[str]:
        if self.live:
            try:
                syms = _mt5.symbols_get()
                out = [s.name for s in syms if s.visible] or [s.name for s in syms]
                return sorted(out)[:600]
            except Exception:
                return []
        return sorted(_SIM_SPECS.keys())

    def ensure_symbol(self, symbol: str) -> bool:
        if self.live:
            try:
                info = _mt5.symbol_info(symbol)
                if info is None:
                    return False
                if not info.visible:
                    return bool(_mt5.symbol_select(symbol, True))
                return True
            except Exception:
                return False
        return symbol in _SIM_SPECS or True

    def bars(self, symbol: str, timeframe: str, count: int) -> List[dict]:
        if self.live:
            try:
                self.ensure_symbol(symbol)
                rates = _mt5.copy_rates_from_pos(symbol, _mt5_tf(timeframe), 0, count)
                if rates is None or len(rates) == 0:
                    return []
                return [{
                    "time": int(r["time"]), "open": float(r["open"]),
                    "high": float(r["high"]), "low": float(r["low"]),
                    "close": float(r["close"]),
                    "tick_volume": int(r["tick_volume"]),
                    "real_volume": int(r["real_volume"]),
                    "spread": int(r["spread"]),
                } for r in rates]
            except Exception as e:
                self.status.last_error = f"bars: {e}"
                return []
        return _SIM.bars(symbol, timeframe.upper(), count)

    def tick(self, symbol: str) -> dict:
        if self.live:
            try:
                t = _mt5.symbol_info_tick(symbol)
                if t is None:
                    return {}
                return {"time": int(t.time), "bid": float(t.bid), "ask": float(t.ask),
                        "last": float(t.last), "volume": int(t.volume)}
            except Exception:
                return {}
        return _SIM.tick(symbol)

    def symbol_info(self, symbol: str) -> dict:
        if self.live:
            try:
                i = _mt5.symbol_info(symbol)
                if i is None:
                    return {}
                t = self.tick(symbol)
                return {
                    "name": i.name, "digits": i.digits, "point": i.point,
                    "trade_contract_size": i.trade_contract_size,
                    "volume_min": i.volume_min, "volume_max": i.volume_max,
                    "volume_step": i.volume_step,
                    "trade_tick_value": i.trade_tick_value,
                    "trade_tick_size": i.trade_tick_size or i.point,
                    "spread": i.spread, "bid": t.get("bid", i.bid),
                    "ask": t.get("ask", i.ask),
                    "trade_stops_level": getattr(i, "trade_stops_level", 0),
                }
            except Exception:
                return {}
        return _SIM.symbol_info(symbol)

    # ── الحساب ─────────────────────────────────────────────
    def account(self) -> dict:
        if self.live:
            try:
                a = _mt5.account_info()
                if a is None:
                    return {}
                return {
                    "login": a.login, "server": a.server, "name": a.name,
                    "currency": a.currency, "leverage": a.leverage,
                    "balance": round(a.balance, 2), "equity": round(a.equity, 2),
                    "profit": round(a.profit, 2), "margin": round(a.margin, 2),
                    "margin_free": round(a.margin_free, 2),
                    "margin_level": round(a.margin_level, 2),
                }
            except Exception:
                return {}
        return _SIM.account()

    def positions(self, symbol: Optional[str] = None) -> List[dict]:
        if self.live:
            try:
                ps = _mt5.positions_get(symbol=symbol) if symbol else _mt5.positions_get()
                if ps is None:
                    return []
                return [{
                    "ticket": p.ticket, "symbol": p.symbol, "type": int(p.type),
                    "volume": float(p.volume), "price_open": float(p.price_open),
                    "price_current": float(p.price_current), "sl": float(p.sl),
                    "tp": float(p.tp), "profit": round(float(p.profit), 2),
                    "swap": float(p.swap), "time": int(p.time),
                    "magic": int(p.magic), "comment": p.comment,
                } for p in ps]
            except Exception:
                return []
        _SIM.account()
        out = list(_SIM.positions.values())
        return [dict(p) for p in out if not symbol or p["symbol"] == symbol]

    def history_deals(self, days: int = 7) -> List[dict]:
        if self.live:
            try:
                to = datetime.now()
                frm = to - timedelta(days=days)
                deals = _mt5.history_deals_get(frm, to)
                if deals is None:
                    return []
                return [{
                    "ticket": d.ticket, "symbol": d.symbol, "type": int(d.type),
                    "volume": float(d.volume), "profit": round(float(d.profit), 2),
                    "price": float(d.price), "time": int(d.time),
                    "entry": int(d.entry), "comment": d.comment,
                } for d in deals if d.symbol]
            except Exception:
                return []
        return list(_SIM.deals)[-500:]

    # ── التنفيذ ────────────────────────────────────────────
    def send_market_order(self, symbol: str, is_buy: bool, volume: float,
                          sl: float = 0.0, tp: float = 0.0, deviation: int = 20,
                          magic: int = 0, comment: str = "") -> dict:
        if self.live:
            try:
                self.ensure_symbol(symbol)
                t = _mt5.symbol_info_tick(symbol)
                price = t.ask if is_buy else t.bid
                req = {
                    "action": _mt5.TRADE_ACTION_DEAL, "symbol": symbol,
                    "volume": float(volume),
                    "type": _mt5.ORDER_TYPE_BUY if is_buy else _mt5.ORDER_TYPE_SELL,
                    "price": price, "deviation": int(deviation),
                    "magic": int(magic), "comment": comment[:31],
                    "type_time": _mt5.ORDER_TIME_GTC,
                    "type_filling": self._filling(symbol),
                }
                if sl:
                    req["sl"] = float(sl)
                if tp:
                    req["tp"] = float(tp)
                r = _mt5.order_send(req)
                return self._result(r)
            except Exception as e:
                return {"ok": False, "retcode": -1, "comment": str(e)}
        r = _SIM.order_send({"action": "DEAL", "symbol": symbol,
                             "type": 0 if is_buy else 1, "volume": volume,
                             "sl": sl, "tp": tp, "magic": magic, "comment": comment})
        return {"ok": r["retcode"] == 10009, "retcode": r["retcode"],
                "comment": r["comment"], "order": r.get("order"),
                "price": r.get("price")}

    def modify_sltp(self, ticket: int, sl: float, tp: float) -> dict:
        if self.live:
            try:
                ps = _mt5.positions_get(ticket=ticket)
                if not ps:
                    return {"ok": False, "retcode": -1, "comment": "الصفقة غير موجودة"}
                p = ps[0]
                req = {"action": _mt5.TRADE_ACTION_SLTP, "symbol": p.symbol,
                       "position": int(ticket), "sl": float(sl), "tp": float(tp),
                       "magic": int(p.magic)}
                return self._result(_mt5.order_send(req))
            except Exception as e:
                return {"ok": False, "retcode": -1, "comment": str(e)}
        r = _SIM.order_send({"action": "SLTP", "position": ticket, "sl": sl, "tp": tp,
                             "symbol": ""})
        return {"ok": r["retcode"] == 10009, "retcode": r["retcode"], "comment": r["comment"]}

    def close_position(self, ticket: int, volume: Optional[float] = None,
                       deviation: int = 20) -> dict:
        if self.live:
            try:
                ps = _mt5.positions_get(ticket=ticket)
                if not ps:
                    return {"ok": False, "retcode": -1, "comment": "الصفقة غير موجودة"}
                p = ps[0]
                t = _mt5.symbol_info_tick(p.symbol)
                is_buy = int(p.type) == 0
                req = {
                    "action": _mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
                    "volume": float(volume or p.volume), "position": int(ticket),
                    "type": _mt5.ORDER_TYPE_SELL if is_buy else _mt5.ORDER_TYPE_BUY,
                    "price": t.bid if is_buy else t.ask,
                    "deviation": int(deviation), "magic": int(p.magic),
                    "comment": "close", "type_time": _mt5.ORDER_TIME_GTC,
                    "type_filling": self._filling(p.symbol),
                }
                return self._result(_mt5.order_send(req))
            except Exception as e:
                return {"ok": False, "retcode": -1, "comment": str(e)}
        r = _SIM.order_send({"action": "CLOSE", "position": ticket, "volume": volume,
                             "symbol": ""})
        return {"ok": r["retcode"] == 10009, "retcode": r["retcode"],
                "comment": r["comment"], "profit": r.get("profit")}

    def _filling(self, symbol: str):
        try:
            info = _mt5.symbol_info(symbol)
            mode = info.filling_mode
            if mode & 1:
                return _mt5.ORDER_FILLING_FOK
            if mode & 2:
                return _mt5.ORDER_FILLING_IOC
            return _mt5.ORDER_FILLING_RETURN
        except Exception:
            return _mt5.ORDER_FILLING_IOC

    @staticmethod
    def _result(r) -> dict:
        if r is None:
            return {"ok": False, "retcode": -1, "comment": "لا يوجد رد من المنصة"}
        return {
            "ok": int(r.retcode) == 10009,
            "retcode": int(r.retcode),
            "comment": str(r.comment),
            "order": int(getattr(r, "order", 0)),
            "price": float(getattr(r, "price", 0.0)),
            "volume": float(getattr(r, "volume", 0.0)),
        }

    def maintain_simulator(self) -> List[dict]:
        if not self.live:
            return _SIM.check_sltp()
        return []
