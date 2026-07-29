# -*- coding: utf-8 -*-
"""
==============================================================
  APEX FOREX BOT — ملف الإعدادات المركزي
  عدّل القيم الافتراضية هنا أو مرّرها كأوامر عند التشغيل
==============================================================
"""
from dataclasses import dataclass
from typing import Optional

# الفريمات الزمنية المدعومة + مدتها بالثواني
TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
TF_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400,
}

# أزواج شائعة للاختيار السريع من القائمة
COMMON_SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "GBPJPY", "AUDUSD",
    "USDCAD", "USDCHF", "EURJPY", "NZDUSD", "XAUUSD",
]


@dataclass
class Config:
    # ─────────── السوق والاستراتيجية ───────────
    symbol: str = "EURUSD"          # زوج الفوركس (كما يظهر في Market Watch)
    timeframe: str = "M15"          # الفريم الزمني (من القائمة TIMEFRAMES)
    strategy: str = "smc"           # smc | ema | rsi | macd
    mode: str = "paper"             # live = تنفيذ حقيقي | paper = محاكاة على بيانات حقيقية

    # ─────────── محرك APEX SMC (نفس إعدادات مؤشر الباي) ───────────
    swing_len: int = 8              # حساسية القمم/القيعان (Swing)
    atr_period: int = 14            # فترة ATR
    atr_sl_mult: float = 1.2        # وقف الخسارة = ATR × القيمة
    rr1: float = 2.0                # الهدف (R:R)
    rr2: float = 3.5                # هدف ثانٍ (مرجعي)
    eq_tol: float = 0.08            # تسامح السيولة المتساوية (× ATR)
    ob_max: int = 6                 # أقصى عدد أوردر بلوك نشط
    mitigate: bool = True           # حذف المناطق بعد اختراقها
    use_delta: bool = True          # فلتر الدلتا الحجمية
    use_killzones: bool = True      # فلتر جلسات لندن/نيويورك
    use_premium_discount: bool = True  # فلتر الخصم/البريميوم
    min_score: int = 3              # أقل درجة لقبول الإشارة (0-5)
    broker_utc_offset: float = 0.0  # فرق توقيت سيرفر الوسيط عن UTC
                                    # (بيانات MT5 عبر بايثون تصل UTC عادة = 0)

    # ─────────── إدارة المخاطر ───────────
    risk_percent: float = 1.0       # نسبة المخاطرة لكل صفقة % من الرصيد
    max_positions: int = 1          # أقصى عدد صفقات مفتوحة معاً
    magic: int = 26072026           # رقم سحري لتمييز صفقات البوت
    slippage_points: int = 20       # أقصى انزلاق سعري بالنقاط
    trailing_breakeven: bool = True # نقل الوقف لنقطة الدخول بعد ربح +1R
    be_buffer_points: int = 10      # نقاط زيادة فوق نقطة الدخول عند التعادل

    # ─────────── الاتصال بمنصة MT5 ───────────
    # اتركها None للاتصال بالمنصة المفتوحة حالياً على جهازك
    login: Optional[int] = None
    password: Optional[str] = None
    server: Optional[str] = None
    terminal_path: Optional[str] = None   # مسار terminal64.exe (اختياري)

    # ─────────── التشغيل المباشر ───────────
    lookback: int = 400             # عدد الشموع المحللة كل دورة
    poll_seconds: int = 5           # مدة الانتظار بين كل فحص وآخر

    # ─────────── الاختبار التاريخي (Backtest) ───────────
    bt_bars: int = 5000             # عدد الشموع التاريخية
    bt_start_balance: float = 10000.0  # رصيد البداية الافتراضي
    csv: Optional[str] = None       # ملف CSV بديل عن بيانات MT5
    save_trades: Optional[str] = None  # مسار حفظ صفقات الباك تست (CSV)

    def summary(self) -> str:
        """ملخص الإعدادات للعرض"""
        return (
            f"الزوج          : {self.symbol}\n"
            f"الفريم         : {self.timeframe}\n"
            f"الاستراتيجية   : {self.strategy}\n"
            f"الوضع          : {self.mode}\n"
            f"أقل درجة إشارة : {self.min_score}/5\n"
            f"المخاطرة       : {self.risk_percent}% لكل صفقة\n"
            f"وقف الخسارة    : {self.atr_sl_mult} × ATR\n"
            f"الهدف          : {self.rr1}R\n"
        )
