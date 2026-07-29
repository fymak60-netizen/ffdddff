/* ══════════════════════════════════════════════════════════
   ULTRA-HFT 3D CHART ENGINE — Three.js
   شموع ثلاثية الأبعاد + FVG + مستويات SL/TP + علامات الإشارات
   ══════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';

  const C = {
    bull: 0x00ffd5, bear: 0xff2e63, gold: 0xffd700,
    purple: 0xa855f7, blue: 0x38bdf8, grid: 0x16233a, wick: 0x94a3b8
  };

  class Chart3D {
    constructor(canvas) {
      this.canvas = canvas;
      this.mode3d = true;
      this.showFvg = true;
      this.showVol = true;
      this.autoRotate = false;
      this.frames = 0; this.fps = 0; this._t0 = performance.now();

      this.renderer = new THREE.WebGLRenderer({
        canvas, antialias: true, alpha: true, powerPreference: 'high-performance'
      });
      this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

      this.scene = new THREE.Scene();
      this.scene.fog = new THREE.FogExp2(0x05070f, 0.0032);

      this.camera = new THREE.PerspectiveCamera(52, 1, 0.1, 4000);
      this.world = new THREE.Group();
      this.scene.add(this.world);

      // groups
      this.gCandles = new THREE.Group();
      this.gWicks   = new THREE.Group();
      this.gFvg     = new THREE.Group();
      this.gLevels  = new THREE.Group();
      this.gMarkers = new THREE.Group();
      this.gVolume  = new THREE.Group();
      this.gGrid    = new THREE.Group();
      [this.gGrid, this.gFvg, this.gVolume, this.gWicks, this.gCandles,
       this.gLevels, this.gMarkers].forEach(g => this.world.add(g));

      // lights
      this.scene.add(new THREE.AmbientLight(0xffffff, 0.55));
      const key = new THREE.DirectionalLight(0xffffff, 0.85);
      key.position.set(60, 120, 90); this.scene.add(key);
      const rim1 = new THREE.PointLight(C.bull, 1.4, 900); rim1.position.set(-160, 60, 130);
      const rim2 = new THREE.PointLight(C.purple, 1.1, 900); rim2.position.set(180, 70, -110);
      this.scene.add(rim1, rim2);

      // orbit state
      this.rot = { x: -0.42, y: 0.0 };
      this.dist = 340;
      this.target = new THREE.Vector3(0, 0, 0);
      this.panY = 0;
      this._drag = null;
      this._bind();

      this.geoBox = new THREE.BoxGeometry(1, 1, 1);
      this.geoWick = new THREE.BoxGeometry(1, 1, 1);
      this.matCache = {};

      this.resize();
      new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
      this._loop = this._loop.bind(this);
      requestAnimationFrame(this._loop);
    }

    mat(color, opacity, emissive) {
      const k = color + '|' + opacity + '|' + (emissive || 0);
      if (!this.matCache[k]) {
        this.matCache[k] = new THREE.MeshPhongMaterial({
          color, transparent: opacity < 1, opacity,
          emissive: emissive || color, emissiveIntensity: emissive === 0 ? 0 : 0.32,
          shininess: 70, specular: 0x223344
        });
      }
      return this.matCache[k];
    }

    _bind() {
      const cv = this.canvas;
      cv.style.cursor = 'grab';
      cv.addEventListener('pointerdown', e => {
        this._drag = { x: e.clientX, y: e.clientY, btn: e.button };
        cv.setPointerCapture(e.pointerId); cv.style.cursor = 'grabbing';
      });
      cv.addEventListener('pointermove', e => {
        if (!this._drag) return;
        const dx = e.clientX - this._drag.x, dy = e.clientY - this._drag.y;
        this._drag.x = e.clientX; this._drag.y = e.clientY;
        if (this._drag.btn === 2 || e.shiftKey) {
          this.panY += dy * 0.35;
        } else {
          this.rot.y -= dx * 0.005;
          this.rot.x = Math.max(-1.45, Math.min(0.35, this.rot.x - dy * 0.004));
        }
      });
      const end = e => { this._drag = null; cv.style.cursor = 'grab'; };
      cv.addEventListener('pointerup', end);
      cv.addEventListener('pointerleave', end);
      cv.addEventListener('contextmenu', e => e.preventDefault());
      cv.addEventListener('wheel', e => {
        e.preventDefault();
        this.dist = Math.max(90, Math.min(1200, this.dist * (1 + Math.sign(e.deltaY) * 0.09)));
      }, { passive: false });
    }

    resize() {
      const p = this.canvas.parentElement;
      const w = p.clientWidth, h = p.clientHeight;
      if (!w || !h) return;
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
    }

    resetView() { this.rot = { x: -0.42, y: 0 }; this.dist = 340; this.panY = 0; }
    toggle3D() {
      this.mode3d = !this.mode3d;
      if (!this.mode3d) { this.rot = { x: 0, y: 0 }; this.dist = 330; }
      else this.resetView();
      if (this._last) this.update(this._last);
    }

    clear(g) {
      while (g.children.length) {
        const c = g.children.pop();
        if (c.geometry && c.geometry !== this.geoBox && c.geometry !== this.geoWick)
          c.geometry.dispose();
        if (c.material && c.material.map) c.material.map.dispose();
      }
    }

    /* ── الرسم الرئيسي ──────────────────────────────────── */
    update(data) {
      this._last = data;
      const bars = data.bars || [];
      if (bars.length < 3) return;

      const N = Math.min(bars.length, 200);
      const view = bars.slice(-N);

      let lo = Infinity, hi = -Infinity, vmax = 0;
      view.forEach(b => { lo = Math.min(lo, b.low); hi = Math.max(hi, b.high);
        vmax = Math.max(vmax, b.tick_volume || 1); });
      // include levels in scale
      const sig = data.signal || {};
      [sig.sl, sig.tp1, sig.tp2].forEach(v => { if (v) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
      (data.positions || []).forEach(p => {
        [p.sl, p.tp, p.price_open].forEach(v => { if (v) { lo = Math.min(lo, v); hi = Math.max(hi, v); } });
      });
      const pad = (hi - lo) * 0.12 || 1;
      lo -= pad; hi += pad;

      const W = 400, H = 190, D = this.mode3d ? 26 : 4;
      const step = W / N;
      const bw = step * 0.62;
      const X = i => -W / 2 + i * step + step / 2;
      const Y = p => ((p - lo) / (hi - lo)) * H - H / 2;

      this._geo = { lo, hi, W, H, D, step, X, Y, N, t0: view[0].time,
        t1: view[view.length - 1].time };

      this.clear(this.gCandles); this.clear(this.gWicks); this.clear(this.gFvg);
      this.clear(this.gLevels); this.clear(this.gMarkers); this.clear(this.gVolume);
      this.clear(this.gGrid);

      // ── grid floor ──
      const grid = new THREE.GridHelper(W * 1.15, 26, C.grid, C.grid);
      grid.position.y = -H / 2 - 12;
      grid.material.transparent = true; grid.material.opacity = 0.35;
      this.gGrid.add(grid);
      // price ladder
      for (let k = 0; k <= 6; k++) {
        const price = lo + (hi - lo) * k / 6;
        const y = Y(price);
        const geo = new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(-W / 2, y, -D / 2), new THREE.Vector3(W / 2, y, -D / 2)
        ]);
        const line = new THREE.Line(geo, new THREE.LineBasicMaterial({
          color: C.grid, transparent: true, opacity: 0.55 }));
        this.gGrid.add(line);
        this.gGrid.add(this._label(price.toFixed(this._digits(data)), W / 2 + 22, y, -D / 2,
          '#64748b', 11));
      }

      // ── FVG boxes ──
      if (this.showFvg && data.fvgs) {
        const tmap = new Map(view.map((b, i) => [b.time, i]));
        data.fvgs.slice(-24).forEach(f => {
          const i1 = tmap.get(f.t1), i2 = tmap.get(f.t2);
          if (i1 === undefined && i2 === undefined) return;
          const a = i1 !== undefined ? i1 : Math.max(0, i2 - 2);
          const b = i2 !== undefined ? i2 : a + 2;
          const yTop = Y(f.top), yBot = Y(f.bottom);
          const h = Math.max(Math.abs(yTop - yBot), 0.4);
          const w = Math.max((b - a) * step + step * 3.5, step * 4);
          const g = new THREE.BoxGeometry(w, h, D * 0.9);
          const col = f.type === 'bull' ? C.bull : C.bear;
          const m = new THREE.MeshBasicMaterial({
            color: col, transparent: true, opacity: f.active ? 0.14 : 0.05,
            depthWrite: false });
          const mesh = new THREE.Mesh(g, m);
          mesh.position.set(X(a) + w / 2 - step / 2, (yTop + yBot) / 2, 0);
          this.gFvg.add(mesh);
          const edges = new THREE.LineSegments(new THREE.EdgesGeometry(g),
            new THREE.LineBasicMaterial({ color: col, transparent: true,
              opacity: f.active ? 0.5 : 0.16 }));
          edges.position.copy(mesh.position);
          this.gFvg.add(edges);
        });
      }

      // ── volume bars ──
      if (this.showVol) {
        view.forEach((b, i) => {
          const vh = ((b.tick_volume || 1) / vmax) * (H * 0.16);
          const g = new THREE.BoxGeometry(bw, Math.max(vh, 0.3), D * 0.5);
          const up = b.close >= b.open;
          const mesh = new THREE.Mesh(g, new THREE.MeshBasicMaterial({
            color: up ? C.bull : C.bear, transparent: true, opacity: 0.22 }));
          mesh.position.set(X(i), -H / 2 - 10 + vh / 2, 0);
          this.gVolume.add(mesh);
        });
      }

      // ── candles ──
      view.forEach((b, i) => {
        const up = b.close >= b.open;
        const yO = Y(b.open), yC = Y(b.close), yH = Y(b.high), yL = Y(b.low);
        const bodyH = Math.max(Math.abs(yC - yO), 0.45);
        const body = new THREE.Mesh(this.geoBox,
          this.mat(up ? C.bull : C.bear, 0.92));
        body.scale.set(bw, bodyH, D);
        body.position.set(X(i), (yO + yC) / 2, 0);
        this.gCandles.add(body);

        const wick = new THREE.Mesh(this.geoWick,
          this.mat(up ? C.bull : C.bear, 0.55, 0));
        wick.scale.set(Math.max(bw * 0.14, 0.5), Math.max(yH - yL, 0.4), D * 0.22);
        wick.position.set(X(i), (yH + yL) / 2, 0);
        this.gWicks.add(wick);
      });

      // ── EMA ribbons ──
      const ser = data.series || {};
      if (ser.ema_fast && ser.times) {
        this._polyline(ser, view, 'ema_fast', 0x38bdf8, X, Y);
        this._polyline(ser, view, 'ema_slow', 0xa855f7, X, Y);
      }

      // ── markers ──
      const tmap2 = new Map(view.map((b, i) => [b.time, i]));
      (data.markers || []).forEach(mk => {
        const i = tmap2.get(mk.time);
        if (i === undefined) return;
        let col = C.gold, size = 2.2, yOff = 0, up = true;
        if (mk.type === 'bos_up') { col = C.purple; up = true; }
        else if (mk.type === 'bos_dn') { col = C.purple; up = false; }
        else if (mk.type === 'choch_up') { col = C.gold; up = true; size = 3; }
        else if (mk.type === 'choch_dn') { col = C.gold; up = false; size = 3; }
        else if (mk.type === 'ofi_bull') { col = C.bull; up = true; size = 1.6; }
        else if (mk.type === 'ofi_bear') { col = C.bear; up = false; size = 1.6; }
        const geo = new THREE.ConeGeometry(size, size * 2.1, 4);
        const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
          color: col, transparent: true, opacity: 0.85 }));
        mesh.position.set(X(i), Y(mk.price) + (up ? -6 : 6), 0);
        mesh.rotation.z = up ? 0 : Math.PI;
        this.gMarkers.add(mesh);
      });

      // ── signal levels ──
      if (sig.direction) {
        const col = sig.direction === 1 ? C.bull : C.bear;
        this._level(sig.entry, col, 'ENTRY ' + sig.entry.toFixed(this._digits(data)), 0.85);
        this._level(sig.sl, C.bear, 'SL ' + sig.sl.toFixed(this._digits(data)), 0.7);
        this._level(sig.tp1, C.gold, 'TP1 ' + sig.tp1.toFixed(this._digits(data)), 0.7);
        this._level(sig.tp2, C.bull, 'TP2 ' + sig.tp2.toFixed(this._digits(data)), 0.7);
        // big arrow at last bar
        const geo = new THREE.ConeGeometry(6, 14, 5);
        const m = new THREE.Mesh(geo, new THREE.MeshPhongMaterial({
          color: col, emissive: col, emissiveIntensity: 0.7 }));
        m.position.set(X(N - 1), Y(sig.entry) + (sig.direction === 1 ? -20 : 20), 0);
        m.rotation.z = sig.direction === 1 ? 0 : Math.PI;
        m.userData.pulse = true;
        this.gMarkers.add(m);
      }

      // ── open positions ──
      (data.positions || []).filter(p => p.symbol === data.symbol).forEach(p => {
        const col = p.type === 0 ? C.bull : C.bear;
        this._level(p.price_open, col, `#${p.ticket} ${p.type === 0 ? 'BUY' : 'SELL'} ${p.volume}`, 0.9, true);
        if (p.sl) this._level(p.sl, C.bear, 'SL', 0.45, true);
        if (p.tp) this._level(p.tp, C.blue, 'TP', 0.45, true);
      });

      // ── current price line ──
      const px = (data.tick && data.tick.bid) || view[view.length - 1].close;
      this._level(px, 0xffffff, px.toFixed(this._digits(data)), 0.55);
    }

    _digits(data) {
      return (data.symbol_info && data.symbol_info.digits) || 5;
    }

    _polyline(ser, view, key, color, X, Y) {
      const arr = ser[key]; if (!arr) return;
      const times = ser.times || [];
      const tmap = new Map(view.map((b, i) => [b.time, i]));
      const pts = [];
      for (let k = 0; k < arr.length; k++) {
        const v = arr[k]; if (v === null || v === undefined) continue;
        const i = tmap.get(times[k]); if (i === undefined) continue;
        pts.push(new THREE.Vector3(X(i), Y(v), 0));
      }
      if (pts.length < 2) return;
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.75 }));
      this.gLevels.add(line);
    }

    _level(price, color, text, opacity, dashed) {
      if (!price || !this._geo) return;
      const { W, D, Y } = this._geo;
      const y = Y(price);
      if (!isFinite(y)) return;
      const pts = [new THREE.Vector3(-W / 2, y, 0), new THREE.Vector3(W / 2, y, 0)];
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      let mat;
      if (dashed) {
        mat = new THREE.LineDashedMaterial({ color, dashSize: 5, gapSize: 4,
          transparent: true, opacity });
      } else {
        mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity });
      }
      const line = new THREE.Line(geo, mat);
      if (dashed) line.computeLineDistances();
      this.gLevels.add(line);
      if (text) this.gLevels.add(this._label(text, -W / 2 - 34, y, 0,
        '#' + color.toString(16).padStart(6, '0'), 12));
    }

    _label(text, x, y, z, color, size) {
      const cv = document.createElement('canvas');
      const ctx = cv.getContext('2d');
      const fs = (size || 12) * 3;
      ctx.font = `700 ${fs}px Consolas, monospace`;
      const w = ctx.measureText(text).width + 16;
      cv.width = Math.ceil(w); cv.height = Math.ceil(fs * 1.5);
      const c2 = cv.getContext('2d');
      c2.font = `700 ${fs}px Consolas, monospace`;
      c2.fillStyle = 'rgba(5,7,15,0.72)';
      c2.fillRect(0, 0, cv.width, cv.height);
      c2.fillStyle = color; c2.textBaseline = 'middle';
      c2.fillText(text, 8, cv.height / 2);
      const tex = new THREE.CanvasTexture(cv);
      tex.minFilter = THREE.LinearFilter;
      const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex,
        transparent: true, depthTest: false }));
      spr.scale.set(cv.width / 3.4, cv.height / 3.4, 1);
      spr.position.set(x, y, z);
      return spr;
    }

    _loop(t) {
      requestAnimationFrame(this._loop);
      if (this.autoRotate) this.rot.y += 0.0026;
      const r = this.rot, d = this.dist;
      this.camera.position.set(
        Math.sin(r.y) * Math.cos(r.x) * d,
        -Math.sin(r.x) * d + this.panY,
        Math.cos(r.y) * Math.cos(r.x) * d
      );
      this.camera.lookAt(0, this.panY * 0.5, 0);
      // pulse animation
      const s = 1 + Math.sin(t * 0.005) * 0.16;
      this.gMarkers.children.forEach(m => { if (m.userData.pulse) m.scale.setScalar(s); });
      this.renderer.render(this.scene, this.camera);
      this.frames++;
      if (t - this._t0 > 1000) {
        this.fps = Math.round(this.frames * 1000 / (t - this._t0));
        this.frames = 0; this._t0 = t;
        const el = document.getElementById('fpsTag');
        if (el) el.textContent = this.fps + ' FPS';
      }
    }
  }

  global.Chart3D = Chart3D;
})(window);
