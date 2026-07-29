"""
ULTRA-HFT QUANT CORE V6 — الإعدادات المركزية
=============================================
كل القيم هنا يمكن تجاوزها عبر متغيرات البيئة (Environment Variables)
أو عبر لوحة التحكم في المتصفح.
"""

import os


def _env(key: str, default):
    v = os.getenv(key)
    if v is None or v == "":
        return default
    if isinstance(default, bool):
        return v.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        try:
            return int(float(v))
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(v)
        except ValueError:
            return default
    return v


# ══════════════════════════════════════════════════════════════
#  [1] بيانات حساب MetaTrader 5
# ══════════════════════════════════════════════════════════════
ACCOUNT_NUMBER   = _env("MT5_LOGIN",    109215262)
ACCOUNT_PASSWORD = _env("MT5_PASSWORD", "Io-x3aSm")
BROKER_SERVER    = _env("MT5_SERVER",   "MetaQuotes-Demo")

# مسار terminal64.exe — اتركه فارغاً ليتم اكتشافه تلقائياً
MT5_PATH         = _env("MT5_PATH", "")

# مهلة الاتصال بالملي ثانية
MT5_TIMEOUT      = _env("MT5_TIMEOUT", 60000)

# السماح بتشغيل محاكي بيانات عند غياب مكتبة MetaTrader5 (لينكس/ماك)
# على ويندوز مع MT5 مثبت => يتم استخدام الاتصال الحقيقي دائماً.
ALLOW_SIMULATOR  = _env("ALLOW_SIMULATOR", True)


# ══════════════════════════════════════════════════════════════
#  [2] السيرفر
# ══════════════════════════════════════════════════════════════
HOST = _env("HOST", "127.0.0.1")
PORT = _env("PORT", 8000)


# ══════════════════════════════════════════════════════════════
#  [3] الرموز الافتراضية + الإطار الزمني
# ══════════════════════════════════════════════════════════════
DEFAULT_SYMBOL    = _env("DEFAULT_SYMBOL", "EURUSD")
DEFAULT_TIMEFRAME = _env("DEFAULT_TIMEFRAME", "M5")
BARS_TO_LOAD      = _env("BARS_TO_LOAD", 800)

# سرعة تحديث المحرك (ثانية)
ENGINE_INTERVAL   = _env("ENGINE_INTERVAL", 1.0)


# ══════════════════════════════════════════════════════════════
#  [4] إعدادات الاستراتيجية الافتراضية (قابلة للتعديل من اللوحة)
# ══════════════════════════════════════════════════════════════
STRATEGY_DEFAULTS = {
    # 🧠 SMC
    "swing_len":     5,
    "show_bos":      True,
    "show_choch":    True,
    "show_fvg":      True,
    "fvg_filter":    0.0,

    # ⚡ OFI
    "use_ofi":       True,
    "ofi_len":       14,
    "vol_mult":      1.5,
    "delta_len":     20,

    # 📐 Z-SCORE
    "use_z":         True,
    "z_len":         50,
    "z_thresh":      2.0,
    "z_extreme":     3.0,

    # 🌍 الجلسات (UTC)
    "sess_on":       False,
    "london_sess":   "08:00-17:00",
    "ny_sess":       "13:00-22:00",

    # 💰 المخاطر
    "use_atr":       True,
    "atr_len":       14,
    "sl_atr":        1.5,
    "tp1_atr":       2.0,
    "tp2_atr":       4.0,
    "be_trigger":    1.0,

    # 🎯 محرك الإشارات
    # strict = كل الشروط مطلوبة | balanced = نظام نقاط | aggressive = نقاط منخفضة
    "signal_mode":   "balanced",
    "min_score":     65,          # حد النقاط للدخول في وضع balanced
    "cooldown_bars": 3,           # عدد الشموع بين إشارتين
}


# ══════════════════════════════════════════════════════════════
#  [5] إعدادات التداول الآلي الافتراضية
# ══════════════════════════════════════════════════════════════
TRADING_DEFAULTS = {
    "auto_trade":        False,   # ⚠️ يبدأ مطفأ دائماً — تفعّله أنت من اللوحة
    "risk_percent":      1.0,     # نسبة المخاطرة من الرصيد لكل صفقة
    "fixed_lot":         0.01,    # يُستخدم عند إيقاف حساب اللوت بالمخاطرة
    "use_risk_sizing":   True,
    "max_positions":     3,       # أقصى عدد صفقات مفتوحة للرمز
    "max_spread_points": 30,      # فلتر السبريد
    "magic":             20260729,
    "deviation":         20,      # الانزلاق المسموح (points)
    "partial_tp1":       True,    # إغلاق 50% عند TP1
    "partial_tp1_pct":   50.0,
    "move_to_be":        True,    # نقل الوقف لنقطة الدخول بعد TP1
    "trailing_stop":     True,
    "trail_atr":         1.0,     # مسافة التريلينج بمضاعف ATR
    "daily_loss_limit":  5.0,     # % خسارة يومية => إيقاف التداول
    "daily_profit_target": 0.0,   # % ربح يومي => إيقاف (0 = معطل)
    "comment":           "UHFT-V6",
}
