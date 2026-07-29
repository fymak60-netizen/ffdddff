/* ══════════════════════════════════════════════════════════
   محرك رسم احتياطي 2D — يعمل بدون إنترنت / بدون Three.js
   نفس واجهة Chart3D تماماً (update / resetView / toggle3D …)
   يرسم منظوراً شبه ثلاثي الأبعاد (isometric) على Canvas عادي.
   ══════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';

  class Chart2D {
    constructor(canvas) {
      this.cv = canvas;
      this.ctx = canvas.getContext('2d');
      this.mode3d = true;
      this.showFvg = true;
      this.showVol = true;
      this.autoRotate = false;
      this.depth = 16;      // عمق المنظور
      this.tilt = 0.42;     // ميل
      this._last = null;
      this._t = 0;
      this._drag = null;
      this.pan = 0;
      this.zoom = 1;
      this._bind();
      this.resize();
      new ResizeObserver(() => { this.resize(); this.draw(); }).observe(canvas.parentElement);
      const loop = t => { this._t = t; if (this.autoRotate) this.tilt = 0.42 + Math.sin(t / 2600) * 0.22;
        this.draw(); requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
    }

    _bind() {
      const cv = this.cv;
      cv.style.cursor = 'grab';
      cv.addEventListener('pointerdown', e => { this._drag = { y: e.clientY, x: e.clientX };
        cv.style.cursor = 'grabbing'; });
      cv.addEventListener('pointermove', e => {
        if (!this._drag) return;
        this.tilt = Math.max(0, Math.min(1.1, this.tilt + (e.clientY - this._drag.y) * 0.003));
        this.pan += (e.clientX - this._drag.x) * 0.5;
        this._drag = { y: e.clientY, x: e.clientX };
      });
      const end = () => { this._drag = null; cv.style.cursor = 'grab'; };
      cv.addEventListener('pointerup', end);
      cv.addEventListener('pointerleave', end);
      cv.addEventListener('wheel', e => {
        e.preventDefault();
        this.zoom = Math.max(0.4, Math.min(3, this.zoom * (1 - Math.sign(e.deltaY) * 0.1)));
      }, { passive: false });
    }

    resize() {
      const p = this.cv.parentElement, r = Math.min(devicePixelRatio, 2);
      this.w = p.clientWidth; this.h = p.clientHeight;
      this.cv.width = this.w * r; this.cv.height = this.h * r;
      this.cv.style.width = this.w + 'px'; this.cv.style.height = this.h + 'px';
      this.ctx.setTransform(r, 0, 0, r, 0, 0);
    }

    resetView() { this.tilt = 0.42; this.pan = 0; this.zoom = 1; }
    toggle3D() { this.mode3d = !this.mode3d; this.depth = this.mode3d ? 16 : 0; }

    update(d) { this._last = d; }

    draw() {
      const d = this._last, ctx = this.ctx;
      if (!ctx) return;
      ctx.clearRect(0, 0, this.w, this.h);
      if (!d || !d.bars || d.bars.length < 3) {
        ctx.fillStyle = '#64748b'; ctx.font = '14px Cairo, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('في انتظار بيانات السوق…', this.w / 2, this.h / 2);
        return;
      }
      const digits = (d.symbol_info && d.symbol_info.digits) || 5;
      const N = Math.min(d.bars.length, Math.round(150 / this.zoom));
      const view = d.bars.slice(-N);

      const padL = 14, padR = 84, padT = 54, padB = 46;
      const W = this.w - padL - padR, H = this.h - padT - padB;
      let lo = Infinity, hi = -Infinity, vmax = 1;
      view.forEach(b => { lo = Math.min(lo, b.low); hi = Math.max(hi, b.high);
        vmax = Math.max(vmax, b.tick_volume || 1); });
      const s = d.signal || {};
      [s.sl, s.tp1, s.tp2].forEach(v => { if (v) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
      (d.positions || []).forEach(p => { if (p.symbol === d.symbol)
        [p.sl, p.tp, p.price_open].forEach(v => { if (v) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }); });
      const pad = (hi - lo) * 0.1 || 1; lo -= pad; hi += pad;

      const dz = this.mode3d ? this.depth : 0;
      const dy = dz * this.tilt;
      const X = i => padL + (i + 0.5) * (W / N) + this.pan * 0.2;
      const Y = p => padT + H - ((p - lo) / (hi - lo)) * H;
      const bw = Math.max((W / N) * 0.6, 1.4);

      // ── خلفية وشبكة ──
      const g = ctx.createLinearGradient(0, padT, 0, padT + H);
      g.addColorStop(0, 'rgba(0,255,213,0.035)'); g.addColorStop(1, 'rgba(5,7,15,0)');
      ctx.fillStyle = g; ctx.fillRect(padL, padT, W, H);
      ctx.font = '10px Consolas, monospace'; ctx.textAlign = 'left';
      for (let k = 0; k <= 6; k++) {
        const price = lo + (hi - lo) * k / 6, y = Y(price);
        ctx.strokeStyle = 'rgba(22,35,58,0.85)'; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + W, y); ctx.stroke();
        if (dz) { ctx.strokeStyle = 'rgba(22,35,58,0.4)';
          ctx.beginPath(); ctx.moveTo(padL + W, y); ctx.lineTo(padL + W + dz, y - dy); ctx.stroke(); }
        ctx.fillStyle = '#64748b';
        ctx.fillText(price.toFixed(digits), padL + W + dz + 6, y + 3);
      }

      // ── فجوات FVG ──
      if (this.showFvg && d.fvgs) {
        const tmap = new Map(view.map((b, i) => [b.time, i]));
        d.fvgs.slice(-24).forEach(f => {
          const i1 = tmap.get(f.t1), i2 = tmap.get(f.t2);
          if (i1 === undefined && i2 === undefined) return;
          const a = i1 !== undefined ? i1 : Math.max(0, i2 - 2);
          const x = X(a) - bw, y1 = Y(f.top), y2 = Y(f.bottom);
          const w = (W / N) * 3.4 + (padL + W - X(a));
          ctx.fillStyle = f.type === 'bull'
            ? (f.active ? 'rgba(0,255,213,0.10)' : 'rgba(0,255,213,0.035)')
            : (f.active ? 'rgba(255,46,99,0.10)' : 'rgba(255,46,99,0.035)');
          ctx.fillRect(x, Math.min(y1, y2), Math.max(w, 10), Math.abs(y2 - y1));
          ctx.strokeStyle = f.type === 'bull'
            ? (f.active ? 'rgba(0,255,213,0.45)' : 'rgba(0,255,213,0.12)')
            : (f.active ? 'rgba(255,46,99,0.45)' : 'rgba(255,46,99,0.12)');
          ctx.lineWidth = 1;
          ctx.strokeRect(x, Math.min(y1, y2), Math.max(w, 10), Math.abs(y2 - y1));
        });
      }

      // ── الحجم ──
      if (this.showVol) {
        view.forEach((b, i) => {
          const vh = ((b.tick_volume || 1) / vmax) * (padB * 0.62);
          ctx.fillStyle = b.close >= b.open ? 'rgba(0,255,213,0.28)' : 'rgba(255,46,99,0.28)';
          ctx.fillRect(X(i) - bw / 2, padT + H + 10, bw, vh);
        });
      }

      // ── الشموع (منظور مائل) ──
      view.forEach((b, i) => {
        const up = b.close >= b.open;
        const col = up ? '#00ffd5' : '#ff2e63';
        const x = X(i), yO = Y(b.open), yC = Y(b.close), yH = Y(b.high), yL = Y(b.low);
        const top = Math.min(yO, yC), hgt = Math.max(Math.abs(yC - yO), 1.2);
        // فتيل
        ctx.strokeStyle = col; ctx.globalAlpha = 0.55; ctx.lineWidth = Math.max(bw * 0.14, 1);
        ctx.beginPath(); ctx.moveTo(x, yH); ctx.lineTo(x, yL); ctx.stroke();
        ctx.globalAlpha = 1;
        if (dz) { // الوجه العلوي والجانبي لإيهام العمق
          ctx.fillStyle = up ? 'rgba(0,255,213,0.45)' : 'rgba(255,46,99,0.45)';
          ctx.beginPath();
          ctx.moveTo(x - bw / 2, top); ctx.lineTo(x - bw / 2 + dz, top - dy);
          ctx.lineTo(x + bw / 2 + dz, top - dy); ctx.lineTo(x + bw / 2, top);
          ctx.closePath(); ctx.fill();
          ctx.fillStyle = up ? 'rgba(0,190,160,0.55)' : 'rgba(190,30,70,0.55)';
          ctx.beginPath();
          ctx.moveTo(x + bw / 2, top); ctx.lineTo(x + bw / 2 + dz, top - dy);
          ctx.lineTo(x + bw / 2 + dz, top + hgt - dy); ctx.lineTo(x + bw / 2, top + hgt);
          ctx.closePath(); ctx.fill();
        }
        ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = 6;
        ctx.fillRect(x - bw / 2, top, bw, hgt);
        ctx.shadowBlur = 0;
      });

      // ── متوسطات EMA ──
      const ser = d.series || {};
      const tmap2 = new Map(view.map((b, i) => [b.time, i]));
      const drawLine = (key, color) => {
        const arr = ser[key], times = ser.times; if (!arr || !times) return;
        ctx.strokeStyle = color; ctx.lineWidth = 1.4; ctx.globalAlpha = 0.8;
        ctx.beginPath(); let started = false;
        for (let k = 0; k < arr.length; k++) {
          const v = arr[k]; if (v == null) continue;
          const i = tmap2.get(times[k]); if (i === undefined) continue;
          const x = X(i), y = Y(v);
          started ? ctx.lineTo(x, y) : (ctx.moveTo(x, y), started = true);
        }
        ctx.stroke(); ctx.globalAlpha = 1;
      };
      drawLine('ema_fast', '#38bdf8'); drawLine('ema_slow', '#a855f7');

      // ── علامات الهيكل ──
      (d.markers || []).forEach(mk => {
        const i = tmap2.get(mk.time); if (i === undefined) return;
        const map = { bos_up: ['#a855f7', 1], bos_dn: ['#a855f7', -1],
          choch_up: ['#ffd700', 1], choch_dn: ['#ffd700', -1],
          ofi_bull: ['#00ffd5', 1], ofi_bear: ['#ff2e63', -1] };
        const m = map[mk.type]; if (!m) return;
        const [col, dir] = m, x = X(i), y = Y(mk.price) - dir * 9;
        const sz = mk.type.startsWith('ofi') ? 3 : 5;
        ctx.fillStyle = col; ctx.globalAlpha = 0.9;
        ctx.beginPath();
        ctx.moveTo(x, y - dir * sz); ctx.lineTo(x - sz * 0.8, y + dir * sz * 0.6);
        ctx.lineTo(x + sz * 0.8, y + dir * sz * 0.6); ctx.closePath(); ctx.fill();
        ctx.globalAlpha = 1;
      });

      // ── مستويات ──
      const level = (price, col, label, dash) => {
        if (!price) return;
        const y = Y(price); if (!isFinite(y) || y < padT - 20 || y > padT + H + 20) return;
        ctx.save();
        ctx.strokeStyle = col; ctx.lineWidth = 1.2;
        if (dash) ctx.setLineDash([6, 5]);
        ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + W, y); ctx.stroke();
        ctx.restore();
        ctx.fillStyle = 'rgba(5,7,15,0.85)';
        const tw = ctx.measureText(label).width + 10;
        ctx.fillRect(padL + 2, y - 8, tw, 14);
        ctx.fillStyle = col; ctx.font = '700 10px Consolas, monospace';
        ctx.fillText(label, padL + 7, y + 3);
      };

      if (s.direction) {
        const col = s.direction === 1 ? '#00ffd5' : '#ff2e63';
        level(s.entry, col, 'ENTRY ' + s.entry.toFixed(digits));
        level(s.sl, '#ff2e63', 'SL ' + s.sl.toFixed(digits), true);
        level(s.tp1, '#ffd700', 'TP1 ' + s.tp1.toFixed(digits), true);
        level(s.tp2, '#00ffd5', 'TP2 ' + s.tp2.toFixed(digits), true);
        // سهم نابض
        const puls = 1 + Math.sin(this._t * 0.005) * 0.25;
        const x = X(N - 1), y = Y(s.entry) - s.direction * 26;
        ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = 14;
        ctx.beginPath();
        ctx.moveTo(x, y + s.direction * 11 * puls);
        ctx.lineTo(x - 8 * puls, y - s.direction * 7 * puls);
        ctx.lineTo(x + 8 * puls, y - s.direction * 7 * puls);
        ctx.closePath(); ctx.fill(); ctx.shadowBlur = 0;
      }

      (d.positions || []).filter(p => p.symbol === d.symbol).forEach(p => {
        const col = p.type === 0 ? '#00ffd5' : '#ff2e63';
        level(p.price_open, col, `#${p.ticket} ${p.type === 0 ? 'BUY' : 'SELL'} ${p.volume}`);
        if (p.sl) level(p.sl, '#ff6b8a', 'SL', true);
        if (p.tp) level(p.tp, '#38bdf8', 'TP', true);
      });

      const cur = (d.tick && d.tick.bid) || view[view.length - 1].close;
      const cy = Y(cur);
      ctx.setLineDash([2, 3]); ctx.strokeStyle = 'rgba(255,255,255,0.55)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(padL, cy); ctx.lineTo(padL + W + dz, cy); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#ffffff'; ctx.fillRect(padL + W + dz + 2, cy - 8, padR - dz - 6, 16);
      ctx.fillStyle = '#05070f'; ctx.font = '700 10px Consolas, monospace';
      ctx.fillText(cur.toFixed(digits), padL + W + dz + 6, cy + 3);

      const fps = document.getElementById('fpsTag');
      if (fps) fps.textContent = '2D Fallback';
    }
  }

  global.Chart2D = Chart2D;
})(window);
