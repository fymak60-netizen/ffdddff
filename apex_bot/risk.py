# -*- coding: utf-8 -*-
"""
==============================================================
  إدارة المخاطر — قلب البوت النابض
  ----------------------------------------------------------
  • حجم اللوت يُحسب تلقائياً من: الرصيد × نسبة المخاطرة ÷ خسارة الوقف
  • الوقف = ATR × 1.2 | الهدف = R:R (افتراضي 2.0)
  • تقريب اللوت لخطوة الوسيط (volume_step) والالتزام بالحدود
==============================================================
"""
from config import Config

# حجم العقد لكل 1.0 لوت (لحسابات standard)
CONTRACT_SIZES = {
    "XAU": 100,      # الذهب: 100 أونصة
    "XAG": 5000,     # الفضة
    "BTC": 1,        # بيتكوين
    "ETH": 1,
    "US30": 1, "US500": 1, "NAS100": 1, "GER40": 1,
}
DEFAULT_CONTRACT = 100_000  # أزواج الفوركس


def contract_size(symbol: str) -> int:
    sym = symbol.upper()
    for key, size in CONTRACT_SIZES.items():
        if key in sym:
            return size
    return DEFAULT_CONTRACT


def approx_pnl(symbol: str, entry: float, exit_price: float, direction: int, volume: float) -> float:
    """تقدير الربح/الخسارة بالدولار (للباك تست والوضع الورقي)"""
    diff = (exit_price - entry) * direction
    size = contract_size(symbol)
    pnl = diff * volume * size
    # أزواج الين: عملة الاقتباس JPY → نقسم على سعر الخروج
    if "JPY" in symbol.upper():
        pnl /= max(exit_price, 1e-9)
    return pnl


def approx_volume(symbol: str, price: float, sl_dist: float, balance: float, risk_pct: float) -> float:
    """تقدير اللوت للباك تست (بدون بيانات الوسيط الدقيقة)"""
    if not (sl_dist == sl_dist) or sl_dist <= 0:   # NaN أو سالب
        return 0.0
    size = contract_size(symbol)
    loss_per_lot = sl_dist * size
    if "JPY" in symbol.upper():
        loss_per_lot /= max(price, 1e-9)
    vol = (balance * risk_pct / 100.0) / loss_per_lot
    vol = max(0.01, min(100.0, vol))
    return round(vol / 0.01) * 0.01


class RiskManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def calc_volume(self, symbol_info, sl_dist: float, balance: float) -> float:
        """
        حساب اللوت الدقيق من بيانات الرمز في MT5:
        خسارة اللوت الواحد = (مسافة الوقف ÷ tick_size) × tick_value
        """
        if not (sl_dist == sl_dist) or sl_dist <= 0:
            return 0.0
        risk_amount = balance * self.cfg.risk_percent / 100.0
        tick_size = max(symbol_info.trade_tick_size, 1e-12)
        tick_value = max(symbol_info.trade_tick_value, 1e-12)
        loss_per_lot = (sl_dist / tick_size) * tick_value
        vol = risk_amount / loss_per_lot
        step = max(symbol_info.volume_step, 1e-8)
        vol = round(vol / step) * step
        vol = max(symbol_info.volume_min, min(symbol_info.volume_max, vol))
        return round(vol, 2)

    @staticmethod
    def sl_tp(direction: int, price: float, sl_dist: float, rr: float):
        """مستويات الوقف والهدف"""
        if direction == 1:
            return price - sl_dist, price + sl_dist * rr
        return price + sl_dist, price - sl_dist * rr
