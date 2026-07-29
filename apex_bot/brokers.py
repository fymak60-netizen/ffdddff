# -*- coding: utf-8 -*-
"""
==============================================================
  طبقة الاتصال بالسوق
  ----------------------------------------------------------
  MT5Broker    : اتصال رسمي بميتاتريدر 5 (مكتبة MetaQuotes)
  PaperBroker  : محاكاة تنفيذ على بيانات حقيقية (بدون مخاطرة)
==============================================================
"""
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List, Optional

import pandas as pd

from config import Config, TF_SECONDS
from risk import approx_pnl


def _import_mt5():
    try:
        import MetaTrader5 as mt5
        return mt5
    except ImportError:
        raise SystemExit(
            "\n⛔ مكتبة MetaTrader5 غير مثبتة أو نظامك لا يدعمها.\n"
            "   • المكتبة تعمل على Windows فقط (تحتاج منصة MT5 مثبتة).\n"
            "   • للتثبيت:  pip install MetaTrader5\n"
            "   • على Mac/Linux استخدم الباك تست مع CSV:\n"
            "         python run.py backtest --csv data.csv\n"
        )


# ═══════════════════════════════════════════════════════════
class MT5Broker:
    """الاتصال الرسمي مع منصة MetaTrader 5"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.mt5 = None

    # ---------- الاتصال ----------
    def connect(self) -> "MT5Broker":
        mt5 = _import_mt5()
        kwargs = {}
        if self.cfg.terminal_path:
            kwargs["path"] = self.cfg.terminal_path
        if self.cfg.login:
            kwargs.update(
                login=int(self.cfg.login),
                password=self.cfg.password or "",
                server=self.cfg.server or "",
            )
        if not mt5.initialize(**kwargs):
            err = mt5.last_error()
            raise SystemExit(
                "\n⛔ فشل الاتصال بمنصة MT5!\n"
                f"   الخطأ: {err}\n"
                "   تأكد من:\n"
                "     1) منصة MT5 مفتوحة على جهازك\n"
                "     2) Tools → Options → Expert Advisors → تفعيل\n"
                "        ☑ Allow Algo Trading  و  ☑ Allow Python integration\n"
                "     3) تسجيل الدخول لحساب (تجريبي أو حقيقي) داخل المنصة\n"
                "     4) صحة بيانات login/password/server إن مررتها\n"
            )
        self.mt5 = mt5
        info = mt5.terminal_info()
        acc = mt5.account_info()
        if info:
            print(f"✅ متصل بالمنصة: {info.name}  | build {info.build}")
        if acc:
            print(f"✅ الحساب: {acc.login} @ {acc.server}  |  الرصيد: {acc.balance:.2f} {acc.currency}")
        return self

    def shutdown(self):
        if self.mt5:
            self.mt5.shutdown()

    # ---------- البيانات ----------
    def select_symbol(self, symbol: str):
        mt5 = self.mt5
        if not mt5.symbol_select(symbol, True):
            avail = [s.name for s in (mt5.symbols_get() or [])][:30]
            raise SystemExit(
                f"\n⛔ الرمز {symbol} غير موجود أو غير ظاهر!\n"
                f"   افتح Market Watch في المنصة وتأكد من اسم الرمز بالضبط\n"
                f"   (بعض الوسطاء يضيفون لاحقة مثل {symbol}.m أو {symbol}m)\n"
                f"   عينة من الرموز المتاحة: {', '.join(avail)} ...\n"
            )
        return mt5.symbol_info(symbol)

    def symbol_info(self, symbol: str):
        return self.mt5.symbol_info(symbol)

    def get_candles(self, symbol: str, timeframe: str, count: int = 400) -> pd.DataFrame:
        """شموع OHLCV — مع استبعاد الشمعة الحالية غير المكتملة"""
        mt5 = self.mt5
        tf = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
        if tf is None:
            raise ValueError(f"فريم غير مدعوم: {timeframe}")
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"تعذر جلب شموع {symbol} — {mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={"tick_volume": "volume"})
        df = df[["time", "open", "high", "low", "close", "volume"]].astype(
            {"open": float, "high": float, "low": float, "close": float, "volume": float}
        )
        # استبعاد الشمعة الجارية (آخر شمعة مؤكدة فقط)
        now = datetime.now(timezone.utc)
        last_open = df["time"].iloc[-1].to_pydatetime()
        if last_open.timestamp() + TF_SECONDS[timeframe] > now.timestamp():
            df = df.iloc[:-1]
        return df.reset_index(drop=True)

    def get_tick(self, symbol: str):
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"لا يوجد سعر لحظي لـ {symbol} (السوق مغلق؟)")
        return tick

    def account_info(self):
        return self.mt5.account_info()

    # ---------- التنفيذ ----------
    def _filling_modes(self):
        mt5 = self.mt5
        return [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]

    def _send(self, request: dict):
        """إرسال أمر مع تجربة أوضاع الملء الثلاثة (تختلف حسب الوسيط)"""
        last = None
        for fill in self._filling_modes():
            req = dict(request)
            req["type_filling"] = fill
            res = self.mt5.order_send(req)
            if res is None:
                last = f"None — {self.mt5.last_error()}"
                continue
            last = res
            if res.retcode in (10008, 10009):   # Placed / Done
                return res
            if res.retcode == 10030:            # Invalid fill → جرّب وضعاً آخر
                continue
            break
        return last

    def open_position(self, symbol: str, direction: int, volume: float,
                      sl: float, tp: float, comment: str = "APEX") -> Optional[int]:
        mt5 = self.mt5
        info = mt5.symbol_info(symbol)
        digits = info.digits
        tick = self.get_tick(symbol)
        price = tick.ask if direction == 1 else tick.bid
        order_type = mt5.ORDER_TYPE_BUY if direction == 1 else mt5.ORDER_TYPE_SELL

        # احترام Stops Level من الوسيط
        stops_dist = info.trade_stops_level * info.point
        if direction == 1:
            if price - sl < stops_dist:
                sl = price - max(stops_dist, sl * 0 + info.point * 10)
            if tp - price < stops_dist:
                tp = price + max(stops_dist, info.point * 10)
        else:
            if sl - price < stops_dist:
                sl = price + max(stops_dist, info.point * 10)
            if price - tp < stops_dist:
                tp = price - max(stops_dist, info.point * 10)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "sl": round(sl, digits),
            "tp": round(tp, digits),
            "deviation": self.cfg.slippage_points,
            "magic": self.cfg.magic,
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
        }
        res = self._send(request)
        if hasattr(res, "retcode") and res.retcode in (10008, 10009):
            return res.order
        print(f"   ⚠️ فشل فتح الصفقة: {res}")
        return None

    def get_positions(self, symbol: Optional[str] = None, magic: Optional[int] = None) -> list:
        mt5 = self.mt5
        if symbol:
            positions = mt5.positions_get(symbol=symbol) or []
        else:
            positions = mt5.positions_get() or []
        if magic is not None:
            positions = [p for p in positions if p.magic == magic]
        return positions

    def close_position(self, ticket: int) -> bool:
        mt5 = self.mt5
        found = mt5.positions_get(ticket=ticket)
        if not found:
            return False
        p = found[0]
        tick = self.get_tick(p.symbol)
        if p.type == mt5.POSITION_TYPE_BUY:
            otype, price = mt5.ORDER_TYPE_SELL, tick.bid
        else:
            otype, price = mt5.ORDER_TYPE_BUY, tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": otype,
            "position": ticket,
            "price": price,
            "deviation": self.cfg.slippage_points,
            "magic": self.cfg.magic,
            "comment": "APEX CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        res = self._send(request)
        return hasattr(res, "retcode") and res.retcode in (10008, 10009)

    def modify_sl(self, ticket: int, sl: float, tp: Optional[float] = None) -> bool:
        mt5 = self.mt5
        found = mt5.positions_get(ticket=ticket)
        if not found:
            return False
        p = found[0]
        info = mt5.symbol_info(p.symbol)
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": p.symbol,
            "position": ticket,
            "sl": round(sl, info.digits),
            "tp": round(tp if tp is not None else p.price_tp, info.digits),
        }
        res = mt5.order_send(request)
        return res is not None and res.retcode in (10008, 10009)


# ═══════════════════════════════════════════════════════════
class PaperBroker:
    """وسيط ورقي: بيانات حقيقية من MT5 + تنفيذ محاكى (صفر مخاطرة)"""

    def __init__(self, cfg: Config, feed: MT5Broker):
        self.cfg = cfg
        self.feed = feed
        self.mt5 = feed.mt5
        self.balance = cfg.bt_start_balance
        self.positions: List[dict] = []
        self._ticket = 1000
        self.is_paper = True

    # ---------- تفويض البيانات للوسيط الحقيقي ----------
    def connect(self):
        return self

    def shutdown(self):
        self.feed.shutdown()

    def select_symbol(self, symbol):
        info = self.feed.select_symbol(symbol)
        self._info = info
        self._sym_info = SimpleNamespace(
            trade_tick_size=info.trade_tick_size or (10 ** -info.digits),
            trade_tick_value=info.trade_tick_value or 10.0,
            volume_min=info.volume_min or 0.01,
            volume_max=info.volume_max or 100.0,
            volume_step=info.volume_step or 0.01,
        )
        return info

    def symbol_info(self, symbol):
        return self._sym_info

    def get_candles(self, symbol, timeframe, count=400):
        return self.feed.get_candles(symbol, timeframe, count)

    def get_tick(self, symbol):
        return self.feed.get_tick(symbol)

    def account_info(self):
        return SimpleNamespace(balance=self.balance, equity=self._equity(),
                               currency="PAPER", login=0, server="PAPER")

    def _equity(self):
        eq = self.balance
        for p in self.positions:
            try:
                tick = self.feed.get_tick(p["symbol"])
                price = tick.bid if p["type"] == 0 else tick.ask
                eq += approx_pnl(p["symbol"], p["price_open"], price,
                                 1 if p["type"] == 0 else -1, p["volume"])
            except Exception:
                pass
        return eq

    # ---------- تنفيذ محاكى ----------
    def open_position(self, symbol, direction, volume, sl, tp, comment="APEX"):
        tick = self.get_tick(symbol)
        price = tick.ask if direction == 1 else tick.bid
        self._ticket += 1
        self.positions.append({
            "ticket": self._ticket, "symbol": symbol,
            "type": 0 if direction == 1 else 1,
            "price_open": price, "price_sl": sl, "price_tp": tp,
            "volume": float(volume), "magic": self.cfg.magic, "comment": comment,
            "time": datetime.now(timezone.utc),
        })
        return self._ticket

    def get_positions(self, symbol=None, magic=None):
        out = []
        for p in self.positions:
            if symbol and p["symbol"] != symbol:
                continue
            if magic is not None and p["magic"] != magic:
                continue
            out.append(SimpleNamespace(
                ticket=p["ticket"], symbol=p["symbol"], type=p["type"],
                price_open=p["price_open"], price_sl=p["price_sl"],
                price_tp=p["price_tp"], volume=p["volume"], magic=p["magic"],
                profit=0.0,
            ))
        return out

    def close_position(self, ticket, price=None):
        for p in list(self.positions):
            if p["ticket"] == ticket:
                if price is None:
                    tick = self.get_tick(p["symbol"])
                    price = tick.bid if p["type"] == 0 else tick.ask
                pnl = approx_pnl(p["symbol"], p["price_open"], price,
                                 1 if p["type"] == 0 else -1, p["volume"])
                self.balance += pnl
                self.positions.remove(p)
                return pnl
        return None

    def modify_sl(self, ticket, sl, tp=None):
        for p in self.positions:
            if p["ticket"] == ticket:
                p["price_sl"] = sl
                if tp is not None:
                    p["price_tp"] = tp
                return True
        return False

    def check_stops(self, symbol: str, bid: float, ask: float):
        """فحص ضرب الوقف/الهدف بالسعر اللحظي"""
        for p in self.get_positions(symbol=symbol, magic=self.cfg.magic):
            hit_sl = hit_tp = False
            if p.type == 0:   # شراء
                hit_sl = bid <= p.price_sl
                hit_tp = bid >= p.price_tp
            else:             # بيع
                hit_sl = ask >= p.price_sl
                hit_tp = ask <= p.price_tp
            if hit_sl:
                pnl = self.close_position(p.ticket, p.price_sl)
                tag = "وقف خسارة 🔴"
            elif hit_tp:
                pnl = self.close_position(p.ticket, p.price_tp)
                tag = "هدف تحقق 🟢"
            else:
                continue
            print(f"   📌 [{tag}] صفقة #{p.ticket} أُغلقت | الربح: {pnl:+.2f}$ | الرصيد: {self.balance:.2f}$")
