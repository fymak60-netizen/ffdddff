#!/usr/bin/env python3
"""فاحص ثابت لأخطاء Pine Script الشائعة (v6) — أقواس، مسافات بادئة، أنواع na، Scope."""
import re, sys

PATH = "/home/user/ffdddff/SMC_Institutional_Beast_PRO.pine"
src = open(PATH, encoding="utf-8").read()
lines = src.split("\n")
errors, warnings = [], []

# ---------- 1) إزالة التعليقات والنصوص لفحص الأقواس ----------
def strip_code(line):
    out, in_str = "", False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_str:
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if ch == '/' and i + 1 < len(line) and line[i+1] == '/':
            break
        out += ch
        i += 1
    return out, in_str

# ---------- 2) تجميع الجُمل المنطقية (line wrapping) ----------
logical = []  # (start_lineno, joined_code)
buf, start = None, None
for n, raw in enumerate(lines, 1):
    code, _ = strip_code(raw)
    if code.strip() == "":
        continue
    indent = len(raw) - len(raw.lstrip(" "))
    if "\t" in raw:
        errors.append(f"L{n}: يوجد TAB في الملف (مسموح فقط مسافات)")
    is_continuation = buf is not None and (indent % 4 != 0) and indent > 0
    if is_continuation:
        buf += " " + code.strip()
    else:
        if buf is not None:
            logical.append((start, buf))
        buf, start = code, n
if buf is not None:
    logical.append((start, buf))

# ---------- 3) توازن الأقواس لكل جملة منطقية ----------
PAIR = {"(": ")", "[": "]"}
for n, code in logical:
    stack = []
    for ch in code:
        if ch in PAIR:
            stack.append(PAIR[ch])
        elif ch in ")]":
            if not stack or stack.pop() != ch:
                errors.append(f"L{n}: قوس غير متوازن قرب: …{code[max(0, code.find(ch)-20):][:60]}")
                break
    else:
        if stack:
            errors.append(f"L{n}: أقواس غير مغلقة ({''.join(stack)}): {code[:80]}")

# ---------- 4) قواعد v6 الأساسية ----------
bool_vars = set()
decl_re = re.compile(r"^\s*(?:var\s+)?(bool|int|float|string|color)\s+([A-Za-z_]\w*)")
destructure_re = re.compile(r"^\s*\[([^\]]+)\]\s*=\s*([A-Za-z_]\w*)\(")

funcs_defined = set(re.findall(r"^([fF]_\w+)\s*\(", src, re.M))
funcs_used = set(re.findall(r"\b(f_\w+)\s*\(", src))
for f in funcs_used - funcs_defined:
    errors.append(f"دالة مستخدمة غير معرّفة: {f}( )")

names_seen = {}
for n, code in logical:
    s = code.strip()
    m = decl_re.match(s)
    if m:
        t, name = m.group(1), m.group(2)
        names_seen[name] = (t, n)
        if t == "bool":
            bool_vars.add(name)
            if t == "bool" and re.search(r"=\s*na\s*$", s):
                errors.append(f"L{n}: bool لا يقبل na في v6: {name}")

# bool لا يُقارن مع na()
for name in bool_vars:
    for n, code in logical:
        if re.search(rf"\bna\s*\(\s*{name}\s*\)", code) or re.search(rf"\b{name}\s*==\s*na\b|\bna\s*==\s*{name}\b", code):
            errors.append(f"L{n}: مقارنة bool مع na: {name}")

# plot/bgcolor/barcolor/plotshape/hline/fill يجب أن تكون Global (indent 0)
for n, raw in enumerate(lines, 1):
    indent = len(raw) - len(raw.lstrip(" "))
    s = raw.strip()
    if re.match(r"(plot|plotshape|plotchar|bgcolor|barcolor|hline|fill|alertcondition)\s*\(", s) and indent != 0:
        errors.append(f"L{n}: {s.split('(')[0]} يجب أن يكون في Global Scope (indent={indent})")

# if/else محلي داخل global واحد — تحقق إضافي: لا '= na' عاري بدون نوع
for n, code in logical:
    if re.match(r"^[A-Za-z_]\w*\s*=\s*na\s*$", code.strip()):
        errors.append(f"L{n}: تعريف na بدون نوع صريح (v6 يشترط float/int …): {code.strip()[:60]}")

# التحقق من وجود indicator() و alertcondition
if "indicator(" not in src:
    errors.append("لا يوجد تعريف indicator()")
if "alertcondition(" not in src:
    warnings.append("لا توجد alertcondition — الإشعارات معطلة")

# توازن if/fun blocks عبر المسافات البادئة — فحص بسيط للتدرج
prev_indent = 0
for n, raw in enumerate(lines, 1):
    if raw.strip() == "" or raw.lstrip().startswith("//"):
        continue
    indent = len(raw) - len(raw.lstrip(" "))
    if indent > prev_indent and (indent - prev_indent) % 4 != 0 and prev_indent % 4 == 0 and indent % 4 == 0:
        errors.append(f"L{n}: قفزة مسافة بادئة غير قياسية {prev_indent}→{indent}")
    prev_indent = indent

print(f"📄 الأسطر: {len(lines)} | الجُمل المنطقية: {len(logical)}")
print(f"🔧 دوال معرّفة: {sorted(funcs_defined)}")
print(f"📛 أخطاء: {len(errors)}")
for e in errors:
    print("  ❌", e)
print(f"⚠️ تحذيرات: {len(warnings)}")
for w in warnings:
    print("  ⚠️", w)
sys.exit(1 if errors else 0)
