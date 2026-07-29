# -*- coding: utf-8 -*-
"""
==============================================================
  APEX FOREX BOT — حلقة التشغيل التلقائي المباشر
  ----------------------------------------------------------
  1) يتصل بـ MT5 (أو وضع ورقي)
  2) ينتظر إغلاق كل شمعة جديدة
  3) يحلل السوق بالاستراتيجية المختارة
  4) يفتح الصفقة تلقائياً بحجم محسوب من نسبة المخاطرة
  5) يدير الصفقة: الوقف/الهدف على المنصة + وقف تعادل اختياري
==============================================================
"""
import time as _time
from datetime import datetime, timezone

from brokers import MT5Broker, PaperBroker
from config import Config
from risk import RiskManager
from strategies import get_strategy


class ApexBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        feed = MT5Broker(cfg).connect()
        if cfg.mode == "paper":
            self.broker = PaperBroker(cfg, feed)
            self.is_paper = True
        else:
            self.broker = feed
            self.is_paper = False
        self.strategy = get_strategy(cfg.strategy)
        self.risk = RiskManager(cfg)
        self.sym_info = None

    # ----------------------------------------------------------
    def run(self):
        cfg = self.cfg
        self.sym_info = self.broker.select_symbol(cfg.symbol)
        spread_pts = (self.sym_info.ask - self.sym_info.bid) / max(self.sym_info.point, 1e-12)

        print("\n" + "═" * 62)
        print("  ⚡ APEX FOREX BOT — تشغيل تلقائي")
        print("═" * 62)
        print(cfg.summary())
        print(f"  السبريد الحالي : {spread_pts:.1f} نقطة")
        print(f"  وضع التنفيذ  : {'🧪 ورقي (محاكاة)' if self.is_paper else '🔴 حقيقي — تأكد أنه حساب تجريبي!'}")
        print("  اضغط Ctrl+C للإيقاف الآمن")
        print("═" * 62)

        last_bar_time = None
        heartbeat = _time.time()

        try:
            while True:
                try:
                    df = self.broker.get_candles(cfg.symbol, cfg.timeframe, cfg.lookback)
                    tick = self.broker.get_tick(cfg.symbol)
                except Exception as e:
                    print(f"   ⚠️ خطأ بيانات: {e} — إعادة محاولة بعد {cfg.poll_seconds*2}ث")
                    _time.sleep(cfg.poll_seconds * 2)
                    continue

                # فحص وقف/هدف الصفقات الورقية بالسعر اللحظي
                if self.is_paper:
                    self.broker.check_stops(cfg.symbol, tick.bid, tick.ask)

                # شمعة جديدة مغلقت؟
                cur_time = df["time"].iloc[-1]
                if cur_time != last_bar_time:
                    last_bar_time = cur_time
                    self._on_new_candle(df, tick)
                    heartbeat = _time.time()
                elif _time.time() - heartbeat > 60:
                    self._heartbeat(tick)
                    heartbeat = _time.time()

                _time.sleep(cfg.poll_seconds)

        except KeyboardInterrupt:
            print("\n\n🛑 إيقاف البوت...")
        finally:
            self._summary()
            self.broker.shutdown()
            print("👋 انتهى الاتصال. بالتوفيق!")

    # ----------------------------------------------------------
    def _on_new_candle(self, df, tick):
        cfg = self.cfg
        row = df.iloc[-1]
        sig = self.strategy.last_signal(df, cfg)
        t = datetime.now(timezone.utc).strftime("%H:%M:%S")
        arrow = "▲" if sig.trend == 1 else ("▼" if sig.trend == -1 else "◆")
        print(f"\n[{t}] 🕯️ شمعة جديدة | السعر: {row['close']:.5f} | "
              f"الهيكل: {arrow} | درجة: شراء {sig.score_long}/5 — بيع {sig.score_short}/5 | ATR: {sig.atr:.5f}")
        if sig.reasons:
            print(f"        العوامل: {', '.join(sig.reasons)}")

        positions = self.broker.get_positions(cfg.symbol, cfg.magic)
        # إدارة الوقف التعادلي للصفقات المفتوحة
        if cfg.trailing_breakeven:
            self._trailing_breakeven(positions, tick)

        if sig.direction == 0:
            return
        if len(positions) >= cfg.max_positions:
            print(f"        ℹ️ إشارة {'شراء' if sig.direction==1 else 'بيع'} مرفوضة — الحد الأقصى للصفقات ({cfg.max_positions})")
            return
        if not (sig.sl_dist == sig.sl_dist) or sig.sl_dist <= 0:
            print("        ⚠️ مسافة الوقف غير صالحة (بيانات غير كافية)")
            return
        self._enter(sig, tick)

    # ----------------------------------------------------------
    def _enter(self, sig, tick):
        cfg = self.cfg
        direction = sig.direction
        side = "🟢 شراء BUY" if direction == 1 else "🔴 بيع SELL"
        price = tick.ask if direction == 1 else tick.bid
        sl, tp = self.risk.sl_tp(direction, price, sig.sl_dist, cfg.rr1)

        acc = self.broker.account_info()
        balance = acc.balance
        info = self.broker.symbol_info(cfg.symbol) if not self.is_paper else self.broker._sym_info
        volume = self.risk.calc_volume(info, sig.sl_dist, balance)
        if volume <= 0:
            print("        ⚠️ تعذر حساب حجم صفقة صالح — تخطي الإشارة")
            return

        comment = f"APEX {sig.score}/5"
        ticket = self.broker.open_position(cfg.symbol, direction, volume, sl, tp, comment)
        if ticket:
            print("        ┌────────────── صفقة جديدة ──────────────")
            print(f"        │ {side}  {cfg.symbol}  |  لوت: {volume}")
            print(f"        │ الدخول : {price:.5f}")
            print(f"        │ الوقف  : {sl:.5f}  (-{sig.sl_dist:.5f})")
            print(f"        │ الهدف  : {tp:.5f}  (+{sig.sl_dist*cfg.rr1:.5f} = {cfg.rr1}R)")
            print(f"        │ المخاطرة: {cfg.risk_percent}% من {balance:.2f}$")
            print(f"        │ الأسباب: {', '.join(sig.reasons)}")
            print("        └────────────────────────────────────────")

    # ----------------------------------------------------------
    def _trailing_breakeven(self, positions, tick):
        """نقل الوقف لنقطة الدخول (+هامش بسيط) بعد تحقيق ربح ≥ مسافة الوقف"""
        cfg = self.cfg
        point = self.sym_info.point if self.sym_info else 1e-5
        buffer = cfg.be_buffer_points * point
        for p in positions:
            sl_dist0 = abs(p.price_open - p.price_sl)
            if sl_dist0 <= 0:
                continue
            if p.type == 0:  # شراء
                moved = p.price_sl >= p.price_open
                profit_dist = tick.bid - p.price_open
                new_sl = p.price_open + buffer
                if not moved and profit_dist >= sl_dist0 and new_sl > p.price_sl:
                    if self.broker.modify_sl(p.ticket, new_sl):
                        print(f"        🔒 صفقة #{p.ticket}: نُقل الوقف لنقطة الدخول ({new_sl:.5f})")
            else:            # بيع
                moved = p.price_sl > 0 and p.price_sl <= p.price_open
                profit_dist = p.price_open - tick.ask
                new_sl = p.price_open - buffer
                if not moved and profit_dist >= sl_dist0 and (p.price_sl == 0 or new_sl < p.price_sl):
                    if self.broker.modify_sl(p.ticket, new_sl):
                        print(f"        🔒 صفقة #{p.ticket}: نُقل الوقف لنقطة الدخول ({new_sl:.5f})")

    # ----------------------------------------------------------
    def _heartbeat(self, tick):
        cfg = self.cfg
        acc = self.broker.account_info()
        pos = self.broker.get_positions(cfg.symbol, cfg.magic)
        t = datetime.now(timezone.utc).strftime("%H:%M:%S")
        open_txt = ""
        if pos:
            p = pos[0]
            d = "شراء" if p.type == 0 else "بيع"
            open_txt = f" | صفقة مفتوحة: {d} من {p.price_open:.5f}"
        print(f"[{t}] 💓 السعر: {(tick.bid+tick.ask)/2:.5f} | الرصيد: {acc.balance:.2f} {getattr(acc,'currency','')}{open_txt}")

    # ----------------------------------------------------------
    def _summary(self):
        acc = self.broker.account_info()
        pos = self.broker.get_positions(self.cfg.symbol, self.cfg.magic)
        print("\n┌────────────── ملخص الجلسة ──────────────")
        print(f"│ الرصيد النهائي : {acc.balance:.2f} {getattr(acc, 'currency', '')}")
        print(f"│ صفقات ما زالت مفتوحة: {len(pos)}")
        for p in pos:
            d = "شراء" if p.type == 0 else "بيع"
            print(f"│   #{p.ticket} {d} {p.symbol} من {p.price_open:.5f} | وقف {p.price_sl:.5f} | هدف {p.price_tp:.5f}")
        print("└─────────────────────────────────────────")
