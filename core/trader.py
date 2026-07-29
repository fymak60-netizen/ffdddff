"""
مدير التنفيذ — Auto Trading Manager
====================================
• فتح صفقات تلقائية عند صدور إشارة معتمدة
• حساب حجم اللوت بناءً على نسبة المخاطرة من الرصيد
• إغلاق جزئي عند TP1 + نقل الوقف لنقطة التعادل
• Trailing Stop بمضاعف ATR
• حدود الخسارة/الربح اليومية
• تدخل يدوي كامل: فتح/إغلاق/تعديل SL و TP
"""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .mt5_bridge import MT5Bridge


class TradeManager:
    def __init__(self, bridge: MT5Bridge, settings: Dict[str, Any]):
        self.bridge = bridge
        self.s = dict(settings)
        self._lock = threading.RLock()
        self.log: List[dict] = []
        self.managed: Dict[int, dict] = {}     # ticket -> بيانات إدارة
        self.last_signal_bar: Dict[str, int] = {}
        self.day_key = self._today()
        self.day_start_balance: Optional[float] = None
        self.halted_reason: str = ""

    # ── أدوات ─────────────────────────────────────────────
    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _log(self, level: str, msg: str, extra: Optional[dict] = None) -> None:
        entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "level": level, "message": msg}
        if extra:
            entry.update(extra)
        with self._lock:
            self.log.append(entry)
            if len(self.log) > 400:
                del self.log[:len(self.log) - 400]

    def update_settings(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self.s.update(patch)
            if "auto_trade" in patch:
                state = "مُفعّل ✅" if patch["auto_trade"] else "مُوقف ⛔"
                self._log("INFO", f"التداول الآلي: {state}")
                if patch["auto_trade"]:
                    self.halted_reason = ""
            return dict(self.s)

    def logs(self, limit: int = 80) -> List[dict]:
        with self._lock:
            return self.log[-limit:][::-1]

    # ── حجم اللوت ─────────────────────────────────────────
    def calc_lot(self, symbol: str, entry: float, sl: float) -> float:
        info = self.bridge.symbol_info(symbol)
        if not info:
            return float(self.s.get("fixed_lot", 0.01))
        vmin = float(info.get("volume_min", 0.01))
        vmax = float(info.get("volume_max", 100.0))
        vstep = float(info.get("volume_step", 0.01)) or 0.01

        if not bool(self.s.get("use_risk_sizing", True)):
            lot = float(self.s.get("fixed_lot", 0.01))
        else:
            acc = self.bridge.account()
            balance = float(acc.get("balance", 0.0)) or 10000.0
            risk_money = balance * float(self.s.get("risk_percent", 1.0)) / 100.0
            dist = abs(entry - sl)
            tick_size = float(info.get("trade_tick_size") or info.get("point") or 0.00001)
            tick_val = float(info.get("trade_tick_value") or 1.0)
            if dist <= 0 or tick_size <= 0 or tick_val <= 0:
                lot = float(self.s.get("fixed_lot", 0.01))
            else:
                loss_per_lot = (dist / tick_size) * tick_val
                lot = risk_money / loss_per_lot if loss_per_lot > 0 else vmin

        lot = math.floor(lot / vstep) * vstep
        lot = max(vmin, min(lot, vmax))
        return round(lot, 2)

    # ── الحواجز ───────────────────────────────────────────
    def guards(self, symbol: str) -> Optional[str]:
        acc = self.bridge.account()
        if not acc:
            return "تعذر قراءة بيانات الحساب"

        today = self._today()
        if today != self.day_key:
            self.day_key = today
            self.day_start_balance = float(acc.get("balance", 0.0))
            self.halted_reason = ""
        if self.day_start_balance is None:
            self.day_start_balance = float(acc.get("balance", 0.0))

        base = self.day_start_balance or 1.0
        equity = float(acc.get("equity", base))
        change_pct = (equity - base) / base * 100.0

        dl = float(self.s.get("daily_loss_limit", 0) or 0)
        if dl > 0 and change_pct <= -dl:
            self.halted_reason = f"تم بلوغ حد الخسارة اليومي ({change_pct:.2f}%)"
            return self.halted_reason
        dp = float(self.s.get("daily_profit_target", 0) or 0)
        if dp > 0 and change_pct >= dp:
            self.halted_reason = f"تم بلوغ هدف الربح اليومي ({change_pct:.2f}%)"
            return self.halted_reason

        info = self.bridge.symbol_info(symbol)
        max_spread = int(self.s.get("max_spread_points", 0) or 0)
        if max_spread > 0 and int(info.get("spread", 0)) > max_spread:
            return f"السبريد مرتفع ({info.get('spread')} > {max_spread})"

        magic = int(self.s.get("magic", 0))
        mine = [p for p in self.bridge.positions(symbol) if p["magic"] == magic]
        if len(mine) >= int(self.s.get("max_positions", 3)):
            return f"بلغت الحد الأقصى للصفقات المفتوحة ({len(mine)})"
        return None

    # ── التنفيذ الآلي ─────────────────────────────────────
    def on_signal(self, symbol: str, sig: Dict[str, Any]) -> Optional[dict]:
        if not bool(self.s.get("auto_trade")):
            return None
        if not sig or sig.get("direction", 0) == 0:
            return None

        bar = int(sig.get("bar_time", 0))
        cd = int(self.s.get("cooldown_seconds", 0) or 0)
        last = self.last_signal_bar.get(symbol, 0)
        if bar and bar == last:
            return None

        blocked = self.guards(symbol)
        if blocked:
            self._log("WARN", f"[{symbol}] تم منع الدخول: {blocked}")
            return None

        self.last_signal_bar[symbol] = bar
        is_buy = sig["direction"] == 1
        entry, sl = float(sig["entry"]), float(sig["sl"])
        tp = float(sig["tp2"])
        lot = self.calc_lot(symbol, entry, sl)

        info = self.bridge.symbol_info(symbol)
        digits = int(info.get("digits", 5))
        res = self.bridge.send_market_order(
            symbol=symbol, is_buy=is_buy, volume=lot,
            sl=round(sl, digits), tp=round(tp, digits),
            deviation=int(self.s.get("deviation", 20)),
            magic=int(self.s.get("magic", 0)),
            comment=str(self.s.get("comment", "UHFT-V6")),
        )
        if res.get("ok"):
            ticket = int(res.get("order") or 0)
            self.managed[ticket] = {
                "symbol": symbol, "dir": sig["direction"], "entry": entry,
                "sl0": sl, "tp1": float(sig["tp1"]), "tp2": tp,
                "atr": float(sig["atr"]), "tp1_done": False, "be_done": False,
                "opened": time.time(), "auto": True,
            }
            self._log("TRADE",
                      f"[{symbol}] فتح {'شراء' if is_buy else 'بيع'} {lot} لوت "
                      f"@ {entry:.{digits}f} | SL {sl:.{digits}f} | TP {tp:.{digits}f} "
                      f"| نقاط {sig.get('score')}",
                      {"ticket": ticket, "symbol": symbol})
        else:
            self._log("ERROR", f"[{symbol}] فشل الأمر: {res.get('comment')} "
                               f"(code {res.get('retcode')})")
        return res

    # ── إدارة الصفقات المفتوحة ────────────────────────────
    def manage_open(self, symbol: str, atr_now: float) -> None:
        magic = int(self.s.get("magic", 0))
        info = self.bridge.symbol_info(symbol)
        if not info:
            return
        digits = int(info.get("digits", 5))
        point = float(info.get("point", 0.00001))

        for p in self.bridge.positions(symbol):
            if p["magic"] != magic:
                continue
            ticket = p["ticket"]
            m = self.managed.get(ticket)
            if m is None:
                # صفقة سابقة/يدوية بنفس الماجيك — أنشئ سجل إدارة لها
                d = 1 if p["type"] == 0 else -1
                m = {"symbol": symbol, "dir": d, "entry": p["price_open"],
                     "sl0": p["sl"], "tp1": 0.0, "tp2": p["tp"], "atr": atr_now,
                     "tp1_done": False, "be_done": False, "opened": time.time(),
                     "auto": False}
                self.managed[ticket] = m

            d = m["dir"]
            px = p["price_current"]
            entry = m["entry"]
            risk = abs(entry - (m["sl0"] or (entry - d * atr_now)))
            if risk <= 0:
                risk = atr_now
            r_now = ((px - entry) if d == 1 else (entry - px)) / risk

            # 1) إغلاق جزئي عند TP1
            if (bool(self.s.get("partial_tp1")) and not m["tp1_done"]
                    and m.get("tp1") and
                    ((d == 1 and px >= m["tp1"]) or (d == -1 and px <= m["tp1"]))):
                pct = float(self.s.get("partial_tp1_pct", 50.0)) / 100.0
                vol = round(max(float(info.get("volume_min", 0.01)),
                                math.floor(p["volume"] * pct / float(info.get("volume_step", 0.01) or 0.01))
                                * float(info.get("volume_step", 0.01) or 0.01)), 2)
                if 0 < vol < p["volume"]:
                    r = self.bridge.close_position(ticket, vol)
                    if r.get("ok"):
                        m["tp1_done"] = True
                        self._log("TRADE", f"[{symbol}] إغلاق جزئي {vol} لوت عند TP1",
                                  {"ticket": ticket})
                else:
                    m["tp1_done"] = True

            # 2) نقل الوقف لنقطة التعادل
            if (bool(self.s.get("move_to_be")) and not m["be_done"]
                    and r_now >= float(self.s.get("be_trigger", 1.0) or 1.0)):
                be = entry + d * point * 2
                cur_sl = p["sl"]
                better = (d == 1 and (cur_sl == 0 or be > cur_sl)) or \
                         (d == -1 and (cur_sl == 0 or be < cur_sl))
                if better:
                    r = self.bridge.modify_sltp(ticket, round(be, digits), p["tp"])
                    if r.get("ok"):
                        m["be_done"] = True
                        self._log("INFO", f"[{symbol}] نقل الوقف لنقطة التعادل",
                                  {"ticket": ticket})

            # 3) Trailing Stop
            if bool(self.s.get("trailing_stop")) and m.get("be_done"):
                dist = atr_now * float(self.s.get("trail_atr", 1.0) or 1.0)
                new_sl = px - d * dist
                cur_sl = p["sl"]
                improve = (d == 1 and new_sl > cur_sl + point) or \
                          (d == -1 and (cur_sl == 0 or new_sl < cur_sl - point))
                if improve and ((d == 1 and new_sl > entry) or (d == -1 and new_sl < entry)):
                    self.bridge.modify_sltp(ticket, round(new_sl, digits), p["tp"])

        # تنظيف الصفقات المغلقة
        live = {p["ticket"] for p in self.bridge.positions()}
        for tk in list(self.managed):
            if tk not in live:
                self.managed.pop(tk, None)

    # ── أوامر يدوية ───────────────────────────────────────
    def manual_order(self, symbol: str, side: str, volume: Optional[float] = None,
                     sl: Optional[float] = None, tp: Optional[float] = None,
                     sl_atr: Optional[float] = None, tp_atr: Optional[float] = None,
                     atr_now: float = 0.0) -> dict:
        is_buy = side.upper() in ("BUY", "LONG", "1")
        info = self.bridge.symbol_info(symbol)
        if not info:
            return {"ok": False, "comment": "رمز غير معروف"}
        digits = int(info.get("digits", 5))
        price = float(info["ask"] if is_buy else info["bid"])
        d = 1 if is_buy else -1

        if sl in (None, 0) and sl_atr and atr_now:
            sl = price - d * atr_now * float(sl_atr)
        if tp in (None, 0) and tp_atr and atr_now:
            tp = price + d * atr_now * float(tp_atr)

        sl = round(float(sl), digits) if sl else 0.0
        tp = round(float(tp), digits) if tp else 0.0
        lot = float(volume) if volume else self.calc_lot(symbol, price, sl or (price - d * (atr_now or price * 0.001)))

        res = self.bridge.send_market_order(
            symbol=symbol, is_buy=is_buy, volume=lot, sl=sl, tp=tp,
            deviation=int(self.s.get("deviation", 20)),
            magic=int(self.s.get("magic", 0)),
            comment="MANUAL",
        )
        if res.get("ok"):
            ticket = int(res.get("order") or 0)
            self.managed[ticket] = {
                "symbol": symbol, "dir": d, "entry": price, "sl0": sl,
                "tp1": 0.0, "tp2": tp, "atr": atr_now or 0.0,
                "tp1_done": True, "be_done": False, "opened": time.time(),
                "auto": False,
            }
            self._log("TRADE", f"[{symbol}] أمر يدوي {'شراء' if is_buy else 'بيع'} "
                               f"{lot} لوت @ {price:.{digits}f}", {"ticket": ticket})
        else:
            self._log("ERROR", f"[{symbol}] فشل الأمر اليدوي: {res.get('comment')}")
        return res

    def manual_modify(self, ticket: int, sl: float, tp: float) -> dict:
        pos = [p for p in self.bridge.positions() if p["ticket"] == int(ticket)]
        if not pos:
            return {"ok": False, "comment": "الصفقة غير موجودة"}
        info = self.bridge.symbol_info(pos[0]["symbol"])
        digits = int(info.get("digits", 5))
        res = self.bridge.modify_sltp(int(ticket), round(float(sl or 0), digits),
                                      round(float(tp or 0), digits))
        lvl = "INFO" if res.get("ok") else "ERROR"
        self._log(lvl, f"تعديل الصفقة #{ticket} → SL {sl} / TP {tp} — "
                       f"{'تم' if res.get('ok') else res.get('comment')}")
        if res.get("ok") and int(ticket) in self.managed:
            self.managed[int(ticket)]["sl0"] = float(sl or 0)
        return res

    def manual_close(self, ticket: int, volume: Optional[float] = None) -> dict:
        res = self.bridge.close_position(int(ticket), volume)
        lvl = "TRADE" if res.get("ok") else "ERROR"
        self._log(lvl, f"إغلاق الصفقة #{ticket} — "
                       f"{'تم' if res.get('ok') else res.get('comment')}")
        return res

    def close_all(self, symbol: Optional[str] = None) -> dict:
        closed, failed = 0, 0
        for p in self.bridge.positions(symbol):
            r = self.bridge.close_position(p["ticket"])
            if r.get("ok"):
                closed += 1
            else:
                failed += 1
        self._log("TRADE", f"إغلاق الكل: نجح {closed} / فشل {failed}")
        return {"ok": failed == 0, "closed": closed, "failed": failed}

    # ── إحصائيات الحساب الحقيقية ─────────────────────────
    def account_stats(self, days: int = 7) -> Dict[str, Any]:
        deals = self.bridge.history_deals(days)
        closed = [d for d in deals if d.get("entry", 1) == 1 or "profit" in d]
        pnl = [float(d["profit"]) for d in closed if d.get("profit") is not None]
        wins = [x for x in pnl if x > 0]
        losses = [x for x in pnl if x < 0]
        gp, gl = sum(wins), abs(sum(losses))
        total = len(pnl)
        return {
            "period_days": days,
            "total_trades": total,
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / total * 100, 1) if total else 0.0,
            "net_profit": round(gp - gl, 2),
            "gross_profit": round(gp, 2), "gross_loss": round(gl, 2),
            "profit_factor": round(gp / gl, 2) if gl else (999.0 if gp else 0.0),
            "avg_win": round(gp / len(wins), 2) if wins else 0.0,
            "avg_loss": round(gl / len(losses), 2) if losses else 0.0,
            "best": round(max(pnl), 2) if pnl else 0.0,
            "worst": round(min(pnl), 2) if pnl else 0.0,
            "halted": self.halted_reason,
            "day_start_balance": self.day_start_balance,
        }
