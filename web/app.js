/* ══════════════════════════════════════════════════════════
   ULTRA-HFT QUANT CORE V6 — Front Controller
   ══════════════════════════════════════════════════════════ */
'use strict';

const $ = id => document.getElementById(id);
const API = p => fetch(p).then(r => r.json());
const POST = (p, b) => fetch(p, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(b || {})
}).then(async r => ({ ok: r.ok, data: await r.json().catch(() => ({})) }));

let SNAP = {};
let DIGITS = 5;
let chart = null;
let suppress = false;   // منع حلقة التغذية الراجعة عند تحديث الحقول

/* ── Toast ─────────────────────────────────────────────── */
function toast(msg, kind = 'info', ms = 3600) {
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.textContent = msg;
  $('toasts').appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transform = 'translateX(-20px)';
    setTimeout(() => t.remove(), 300); }, ms);
}

const fmt = (v, d = 2) => (v === null || v === undefined || isNaN(v)) ? '—'
  : Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const px = v => fmt(v, DIGITS);
const timeStr = ts => new Date(ts * 1000).toLocaleTimeString('en-GB');

/* ══════════════════════════════════════════════════════════
   إعدادات: ربط عناصر الواجهة بمفاتيح الخادم
   ══════════════════════════════════════════════════════════ */
const STRAT_MAP = {
  swingLen: 'swing_len', showBos: 'show_bos', showChoch: 'show_choch',
  showFvg: 'show_fvg', fvgFilter: 'fvg_filter',
  useOfi: 'use_ofi', ofiLen: 'ofi_len', volMult: 'vol_mult', deltaLen: 'delta_len',
  useZ: 'use_z', zLen: 'z_len', zThresh: 'z_thresh', zExtreme: 'z_extreme',
  sessOn: 'sess_on', londonSess: 'london_sess', nySess: 'ny_sess',
  atrLen: 'atr_len', slAtr: 'sl_atr', tp1Atr: 'tp1_atr', tp2Atr: 'tp2_atr',
  beTrigger: 'be_trigger', signalMode: 'signal_mode', minScore: 'min_score'
};
const TRADE_MAP = {
  autoTrade: 'auto_trade', riskPercent: 'risk_percent', fixedLot: 'fixed_lot',
  useRiskSizing: 'use_risk_sizing', maxPositions: 'max_positions',
  maxSpread: 'max_spread_points', partialTp1: 'partial_tp1', moveToBe: 'move_to_be',
  trailingStop: 'trailing_stop', trailAtr: 'trail_atr',
  dailyLoss: 'daily_loss_limit', dailyProfit: 'daily_profit_target'
};

function readEl(el) {
  if (el.type === 'checkbox') return el.checked;
  if (el.type === 'number' || el.type === 'range') {
    const v = parseFloat(el.value);
    return isNaN(v) ? 0 : v;
  }
  return el.value;
}
function writeEl(el, v) {
  if (el.type === 'checkbox') el.checked = !!v;
  else el.value = v;
}

function pushSettings() {
  if (suppress) return;
  const strategy = {}, trading = {};
  for (const [id, key] of Object.entries(STRAT_MAP)) {
    const el = $(id); if (el) strategy[key] = readEl(el);
  }
  for (const [id, key] of Object.entries(TRADE_MAP)) {
    const el = $(id); if (el) trading[key] = readEl(el);
  }
  POST('/api/settings', { strategy, trading });
  updateSliderLabels();
}

function updateSliderLabels() {
  const m = {
    vRisk: ['riskPercent', 1], vMinScore: ['minScore', 0], vSwing: ['swingLen', 0],
    vOfi: ['ofiLen', 0], vVol: ['volMult', 1], vZlen: ['zLen', 0],
    vZth: ['zThresh', 1], vZex: ['zExtreme', 1], vAtr: ['atrLen', 0],
    vSl: ['slAtr', 1], vTp1: ['tp1Atr', 1], vTp2: ['tp2Atr', 1]
  };
  for (const [out, [src, dec]] of Object.entries(m)) {
    const o = $(out), s = $(src);
    if (o && s) o.textContent = Number(s.value).toFixed(dec);
  }
}

function loadSettings(st, tr) {
  suppress = true;
  for (const [id, key] of Object.entries(STRAT_MAP)) {
    const el = $(id); if (el && st && key in st) writeEl(el, st[key]);
  }
  for (const [id, key] of Object.entries(TRADE_MAP)) {
    const el = $(id); if (el && tr && key in tr) writeEl(el, tr[key]);
  }
  updateSliderLabels();
  suppress = false;
}

/* ══════════════════════════════════════════════════════════
   تحديث الواجهة من اللقطة
   ══════════════════════════════════════════════════════════ */
function render(d) {
  if (!d) return;
  SNAP = d;

  // ── حالة الاتصال ──
  const st = d.status || {};
  const pill = $('connPill'), txt = $('connText');
  pill.className = 'pill ' + (st.mode === 'LIVE' ? 'live' : st.mode === 'SIMULATOR' ? 'sim' : 'off');
  txt.textContent = st.mode === 'LIVE'
    ? `MT5 حقيقي · ${st.login}`
    : st.mode === 'SIMULATOR' ? 'وضع المحاكي' : 'غير متصل';

  if (d.error) { $('cycleMs').textContent = '⚠ ' + d.error.slice(0, 40); return; }
  if (!d.ok) return;

  DIGITS = (d.symbol_info && d.symbol_info.digits) || 5;
  $('cycleMs').textContent = (d.cycle_ms || 0) + 'ms';

  // ── الحساب ──
  const a = d.account || {};
  $('mBalance').textContent = fmt(a.balance);
  $('mEquity').textContent = fmt(a.equity);
  const pr = $('mProfit');
  pr.textContent = fmt(a.profit);
  pr.className = a.profit > 0 ? 'pos' : a.profit < 0 ? 'neg' : '';
  $('mFree').textContent = fmt(a.margin_free);
  const myPos = (d.positions || []);
  $('mPos').textContent = myPos.length;
  $('posCount').textContent = myPos.length;

  // ── التداول الآلي ──
  const auto = ((d.settings || {}).trading || {}).auto_trade;
  const ap = $('autoPill');
  ap.className = 'pill ' + (auto ? 'live' : 'off');
  $('autoText').textContent = auto ? 'الآلي: يعمل ⚡' : 'الآلي: موقوف';

  // ── السعر ──
  const tk = d.tick || {};
  $('tagSym').textContent = `${d.symbol} · ${d.timeframe}`;
  const last = tk.bid || (d.state || {}).price || 0;
  const el = $('tagPx');
  const prev = parseFloat(el.dataset.v || '0');
  el.textContent = px(last);
  el.style.color = last > prev ? 'var(--bull)' : last < prev ? 'var(--bear)' : 'var(--text)';
  el.dataset.v = last;
  $('tagBidAsk').textContent = `${px(tk.bid)} / ${px(tk.ask)}`;
  $('tagSpread').textContent = (d.symbol_info || {}).spread ?? '—';

  // ── الإشارة ──
  const s = d.signal || {};
  const card = $('signalCard'), badge = $('sigBadge');
  card.className = s.direction === 1 ? 'long' : s.direction === -1 ? 'short' : '';
  badge.className = 'sig-badge ' + (s.direction === 1 ? 'long' : s.direction === -1 ? 'short' : 'flat');
  badge.textContent = s.direction === 1 ? '▲ LONG' : s.direction === -1 ? '▼ SHORT' : 'FLAT';
  const sc = Math.max(d.scores?.long || 0, d.scores?.short || 0);
  $('sigScoreBar').style.width = sc + '%';
  $('sigScoreTxt').textContent = sc.toFixed(0) + ' / 100';
  $('sigEntry').textContent = s.entry ? px(s.entry) : '—';
  $('sigSl').textContent = s.sl ? px(s.sl) : '—';
  $('sigTp1').textContent = s.tp1 ? px(s.tp1) : '—';
  $('sigTp2').textContent = s.tp2 ? px(s.tp2) : '—';
  $('sigReasons').innerHTML = (s.reasons || []).map(r => `<span>${r}</span>`).join('') ||
    `<span style="opacity:.5">لا توجد شروط كافية — نقاط شراء ${d.scores?.long ?? 0} / بيع ${d.scores?.short ?? 0}</span>`;
  $('btnTakeSignal').disabled = !s.direction;
  $('btnTakeSignal').className = (s.direction === -1 ? 'btn-sell' : 'btn-buy') + ' btn-sm';

  // ── الحالة الحية ──
  const stt = d.state || {};
  const tr = stt.trend;
  const tEl = $('stTrend');
  tEl.textContent = tr === 1 ? 'صاعد' : tr === -1 ? 'هابط' : 'محايد';
  tEl.className = tr === 1 ? 'pos' : tr === -1 ? 'neg' : '';
  $('stZ').textContent = fmt(stt.z_score, 2);
  $('stZ').className = Math.abs(stt.z_score) > 2 ? 'pos' : '';
  const oEl = $('stOfi'); oEl.textContent = stt.ofi;
  oEl.className = stt.ofi === 'BULL' ? 'pos' : stt.ofi === 'BEAR' ? 'neg' : '';
  $('stVol').textContent = fmt(stt.rel_vol, 2) + 'x';
  $('stRsi').textContent = fmt(stt.rsi, 1);
  $('stAdx').textContent = fmt(stt.adx, 1);
  $('stAtr').textContent = fmt(stt.atr, DIGITS);
  const sEl = $('stSess');
  sEl.textContent = stt.session_ok ? 'نشطة' : 'مغلقة';
  sEl.className = stt.session_ok ? 'pos' : 'neg';

  // ── إحصائيات المحاكاة ──
  const bt = d.stats || {};
  $('btTrades').textContent = bt.total_trades ?? 0;
  const wr = $('btWr'); wr.textContent = (bt.win_rate ?? 0) + '%';
  wr.className = (bt.win_rate ?? 0) >= 50 ? 'pos' : 'neg';
  const pf = $('btPf'); pf.textContent = fmt(bt.profit_factor, 2);
  pf.className = (bt.profit_factor ?? 0) >= 1.5 ? 'pos' : 'neg';
  const ex = $('btExp'); ex.textContent = fmt(bt.expectancy_r, 3);
  ex.className = (bt.expectancy_r ?? 0) > 0 ? 'pos' : 'neg';
  const nt = $('btNet'); nt.textContent = fmt(bt.net_r, 2) + 'R';
  nt.className = (bt.net_r ?? 0) > 0 ? 'pos' : 'neg';
  $('btDd').textContent = fmt(bt.max_dd_r, 2) + 'R';
  $('btWl').textContent = `${bt.wins ?? 0}/${bt.losses ?? 0}`;
  $('btBars').textContent = bt.avg_bars ?? 0;

  // ── إحصائيات الحساب ──
  const ac = d.account_stats || {};
  $('acTrades').textContent = ac.total_trades ?? 0;
  $('acWr').textContent = (ac.win_rate ?? 0) + '%';
  const an = $('acNet'); an.textContent = fmt(ac.net_profit, 2);
  an.className = (ac.net_profit ?? 0) > 0 ? 'pos' : (ac.net_profit ?? 0) < 0 ? 'neg' : '';
  $('acPf').textContent = fmt(ac.profit_factor, 2);
  $('acBest').textContent = fmt(ac.best, 2);
  $('acWorst').textContent = fmt(ac.worst, 2);
  $('acHalt').textContent = ac.halted ? '⛔ ' + ac.halted : '';

  // ── الصفقات ──
  const tb = $('posTable').querySelector('tbody');
  tb.innerHTML = myPos.map(p => `
    <tr>
      <td class="mono">${p.ticket}</td>
      <td>${p.symbol}</td>
      <td class="${p.type === 0 ? 'pos' : 'neg'}">${p.type === 0 ? 'شراء' : 'بيع'}</td>
      <td>${p.volume}</td>
      <td class="mono">${fmt(p.price_open, DIGITS)}</td>
      <td class="mono neg">${p.sl ? fmt(p.sl, DIGITS) : '—'}</td>
      <td class="mono pos">${p.tp ? fmt(p.tp, DIGITS) : '—'}</td>
      <td class="${p.profit > 0 ? 'pos' : p.profit < 0 ? 'neg' : ''}">${fmt(p.profit)}</td>
      <td style="white-space:nowrap">
        <button class="btn-gold btn-sm" onclick="openEdit(${p.ticket},${p.sl},${p.tp})">✏</button>
        <button class="btn-sell btn-sm" onclick="closePos(${p.ticket})">✖</button>
      </td>
    </tr>`).join('') ||
    '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:14px">لا توجد صفقات مفتوحة</td></tr>';

  // ── الإشارات ──
  const sg = $('sigTable').querySelector('tbody');
  sg.innerHTML = (d.signals_recent || []).map(x => `
    <tr>
      <td class="mono">${timeStr(x.bar_time)}</td>
      <td class="${x.direction === 1 ? 'pos' : 'neg'}">${x.direction === 1 ? '▲ شراء' : '▼ بيع'}</td>
      <td>${x.score}</td>
      <td class="mono">${fmt(x.entry, DIGITS)}</td>
      <td>${x.executed ? '✅' : '—'}</td>
    </tr>`).join('') ||
    '<tr><td colspan="5" style="text-align:center;color:var(--muted);padding:10px">لا توجد إشارات بعد</td></tr>';

  // ── السجل ──
  $('logs').innerHTML = (d.logs || []).map(l =>
    `<div class="log-line log-${l.level}"><time>${(l.time || '').slice(11, 19)}</time>${l.message}</div>`
  ).join('');

  // ── الرسم ──
  if (chart) chart.update(d);
}

/* ══════════════════════════════════════════════════════════
   إجراءات
   ══════════════════════════════════════════════════════════ */
window.closePos = async ticket => {
  const r = await POST('/api/close', { ticket });
  toast(r.ok ? `تم إغلاق الصفقة #${ticket}` : 'فشل الإغلاق: ' + (r.data.comment || ''),
    r.ok ? 'ok' : 'err');
};

window.openEdit = (ticket, sl, tp) => {
  $('editTicket').textContent = '#' + ticket;
  $('editSl').value = sl || '';
  $('editTp').value = tp || '';
  $('modalEdit').classList.add('show');
  $('modalEdit').dataset.ticket = ticket;
};

async function manualOrder(side) {
  const body = {
    side,
    volume: parseFloat($('mLot').value) || null,
    sl: parseFloat($('mSl').value) || null,
    tp: parseFloat($('mTp').value) || null,
    sl_atr: parseFloat($('mSlAtr').value) || null,
    tp_atr: parseFloat($('mTpAtr').value) || null,
  };
  const r = await POST('/api/order', body);
  toast(r.ok ? `تم تنفيذ ${side === 'BUY' ? 'الشراء' : 'البيع'} بنجاح`
    : 'فشل الأمر: ' + (r.data.comment || ''), r.ok ? 'ok' : 'err');
}

/* ══════════════════════════════════════════════════════════
   الإقلاع
   ══════════════════════════════════════════════════════════ */
function makeChart() {
  const cv = $('three');
  if (!window.__noThree && typeof THREE !== 'undefined') {
    try { return new Chart3D(cv); }
    catch (e) { console.warn('WebGL/Three فشل — التبديل إلى 2D', e); }
  }
  toast('تعذر تحميل Three.js — تم تفعيل محرك الرسم 2D الاحتياطي', 'info', 5000);
  return new Chart2D(cv);
}

async function boot() {
  chart = makeChart();

  // الرموز والأطر
  const sy = await API('/api/symbols');
  $('symbolSel').innerHTML = sy.symbols.map(s =>
    `<option ${s === sy.current ? 'selected' : ''}>${s}</option>`).join('');
  $('tfSel').innerHTML = sy.timeframes.map(t => `<option>${t}</option>`).join('');

  const cfg = await API('/api/settings');
  loadSettings(cfg.strategy, cfg.trading);
  const stt = await API('/api/status');
  $('tfSel').value = stt.timeframe;
  $('accLogin').value = stt.login || '';
  $('accServer').value = stt.server || '';

  // ربط كل عناصر الإعدادات
  [...Object.keys(STRAT_MAP), ...Object.keys(TRADE_MAP)].forEach(id => {
    const el = $(id); if (!el) return;
    el.addEventListener('input', () => {
      updateSliderLabels();
      clearTimeout(el._t); el._t = setTimeout(pushSettings, 220);
    });
    el.addEventListener('change', pushSettings);
  });

  $('autoTrade').addEventListener('change', e => {
    toast(e.target.checked ? '⚡ تم تفعيل التداول الآلي — سيتم فتح الصفقات تلقائياً'
      : '⛔ تم إيقاف التداول الآلي', e.target.checked ? 'ok' : 'info', 4500);
  });

  $('symbolSel').addEventListener('change', async e => {
    await POST('/api/market', { symbol: e.target.value });
    toast('تم التبديل إلى ' + e.target.value, 'info');
  });
  $('tfSel').addEventListener('change', async e => {
    await POST('/api/market', { timeframe: e.target.value });
    toast('الإطار الزمني: ' + e.target.value, 'info');
  });

  $('btnBuy').onclick = () => manualOrder('BUY');
  $('btnSell').onclick = () => manualOrder('SELL');
  $('btnCloseAll').onclick = async () => {
    if (!confirm('هل تريد إغلاق جميع الصفقات المفتوحة؟')) return;
    const r = await POST('/api/close', { all: true });
    toast(`تم إغلاق ${r.data.closed || 0} صفقة`, 'ok');
  };
  $('btnTakeSignal').onclick = async () => {
    const s = SNAP.signal; if (!s || !s.direction) return;
    const r = await POST('/api/order', {
      side: s.direction === 1 ? 'BUY' : 'SELL',
      sl: s.sl, tp: s.tp2,
      volume: parseFloat($('mLot').value) || null
    });
    toast(r.ok ? 'تم تنفيذ الإشارة ⚡' : 'فشل: ' + (r.data.comment || ''), r.ok ? 'ok' : 'err');
  };

  // أزرار الرسم
  $('btnRotate').onclick = e => {
    chart.autoRotate = !chart.autoRotate;
    e.target.style.color = chart.autoRotate ? 'var(--bull)' : '';
  };
  $('btnReset').onclick = () => chart.resetView();
  $('btn3d').onclick = e => { chart.toggle3D(); e.target.textContent = chart.mode3d ? '📐 3D / 2D' : '📊 2D / 3D'; };
  $('btnFvg').onclick = e => { chart.showFvg = !chart.showFvg; e.target.style.color = chart.showFvg ? 'var(--bull)' : ''; if (SNAP.ok) chart.update(SNAP); };
  $('btnVol').onclick = e => { chart.showVol = !chart.showVol; e.target.style.color = chart.showVol ? 'var(--bull)' : ''; if (SNAP.ok) chart.update(SNAP); };
  $('btnFvg').style.color = 'var(--bull)';
  $('btnVol').style.color = 'var(--bull)';

  // مودالات
  $('btnAccount').onclick = () => $('modalAccount').classList.add('show');
  $('btnCloseModal').onclick = () => $('modalAccount').classList.remove('show');
  $('btnCloseEdit').onclick = () => $('modalEdit').classList.remove('show');
  $('btnDoConnect').onclick = async () => {
    const r = await POST('/api/connect', {
      login: parseInt($('accLogin').value) || null,
      password: $('accPass').value || null,
      server: $('accServer').value || null,
      path: $('accPath').value || null
    });
    $('modalAccount').classList.remove('show');
    toast(r.data.message || 'تمت المحاولة', r.data.mode === 'LIVE' ? 'ok' : 'info', 5000);
  };
  $('btnDoModify').onclick = async () => {
    const ticket = parseInt($('modalEdit').dataset.ticket);
    const r = await POST('/api/modify', {
      ticket, sl: parseFloat($('editSl').value) || 0, tp: parseFloat($('editTp').value) || 0
    });
    $('modalEdit').classList.remove('show');
    toast(r.ok ? 'تم تعديل SL/TP ✅' : 'فشل: ' + (r.data.comment || ''), r.ok ? 'ok' : 'err');
  };

  // تبويبات
  document.querySelectorAll('.tabs button').forEach(b => {
    b.onclick = () => {
      document.querySelectorAll('.tabs button').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.tab-page').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      $('tab-' + b.dataset.tab).classList.add('active');
    };
  });

  connectWS();
}

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = e => {
    try { render(JSON.parse(e.data)); } catch (err) { console.error(err); }
  };
  ws.onopen = () => toast('تم الاتصال بالبث الحي 📡', 'ok', 2200);
  ws.onclose = () => {
    toast('انقطع البث — إعادة الاتصال…', 'err', 2500);
    setTimeout(connectWS, 2500);
  };
  ws.onerror = () => ws.close();
  setInterval(() => { if (ws.readyState === 1) ws.send('ping'); }, 20000);
}

document.addEventListener('DOMContentLoaded', boot);
