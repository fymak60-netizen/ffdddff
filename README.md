# ffdddff — APEX Trading Suite

مجموعة أدوات تداول احترافية مبنية على مفاهيم **Smart Money / ICT**:

## 📂 المكونات

| المجلد | الوصف |
|--------|-------|
| [`pine/`](pine/) | **APEX LIQUIDITY ENGINE** — مؤشر TradingView (Pine Script v5): هيكل سعري BOS/CHoCH، اصطياد سيولة، أوردر بلوك، FVG، دلتا، Kill Zones — مع نظام تقييم 0-5 |
| [`apex_bot/`](apex_bot/) | **APEX FOREX BOT** — بوت بايثون تلقائي يربط **MetaTrader 5**، ينفّذ نسخة مطابقة لمحرك الباي + 3 استراتيجيات إضافية + اختبار تاريخي + إدارة مخاطر تلقائية |

## ⚡ البدء السريع مع البوت

```bash
cd apex_bot
pip install -r requirements.txt
python run.py            # قائمة تفاعلية بالعربية: اختر الزوج ← الاستراتيجية ← شغّل
```

📖 الدليل الكامل بالعربية: **[apex_bot/README_AR.md](apex_bot/README_AR.md)**

> ⚠️ أدوات تحليلية/تنفيذية وليست نصيحة مالية. اختبر على حساب تجريبي قبل أي مال حقيقي.
