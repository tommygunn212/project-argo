/* Neural orb: a constantly drifting 3-D point cloud that swells when ARGO talks. */
(function (root) {
  'use strict';
  const clamp = (n, a = 0, b = 1) => Math.min(b, Math.max(a, Number(n) || 0));
  const lerp = (a, b, t) => a + (b - a) * t;

  // Small seeded generator so the orb has the same shape on every load (and in tests).
  function rng(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Points fill a ball, denser toward the centre. Each point links to its nearest
  // neighbours once, so the "network" keeps its shape while the points drift.
  function createField(count = 360, seed = 7, links = 3) {
    const rand = rng(seed);
    const pts = [];
    for (let i = 0; i < count; i++) {
      const u = rand() * 2 - 1;
      const th = rand() * Math.PI * 2;
      const s = Math.sqrt(1 - u * u);
      const r = Math.pow(rand(), 0.75);
      pts.push({
        x: r * s * Math.cos(th), y: r * u, z: r * s * Math.sin(th), r,
        phase: rand() * Math.PI * 2, speed: 0.35 + rand() * 0.7, size: 0.6 + rand() * 1.1,
      });
    }
    const seen = new Set();
    const edges = [];
    for (let i = 0; i < count; i++) {
      const near = [];
      for (let j = 0; j < count; j++) {
        if (i === j) continue;
        const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y, dz = pts[i].z - pts[j].z;
        near.push([dx * dx + dy * dy + dz * dz, j]);
      }
      near.sort((p, q) => p[0] - q[0]);
      for (let k = 0; k < links; k++) {
        const j = near[k][1];
        const key = i < j ? i * count + j : j * count + i;
        if (!seen.has(key)) { seen.add(key); edges.push([i, j]); }
      }
    }
    return { pts, edges };
  }

  // Rotate (y axis, then x axis) and apply perspective. depth runs about -1 (far) to 1 (near).
  function project(x, y, z, ay, ax, fov = 3) {
    const cy = Math.cos(ay), sy = Math.sin(ay);
    const x1 = x * cy + z * sy, z1 = -x * sy + z * cy;
    const cx = Math.cos(ax), sx = Math.sin(ax);
    const y2 = y * cx - z1 * sx, z2 = y * sx + z1 * cx;
    const k = fov / (fov - z2);
    return { x: x1 * k, y: y2 * k, depth: z2, k };
  }

  // Turns raw audio RMS into a 0..1 "how hard is it talking" value: fast attack, slow release.
  class VoiceLevel {
    constructor() { this.value = 0; }
    update(rms, dt) {
      const target = clamp((rms - 0.008) / 0.12);
      const rate = target > this.value ? 18 : 5;
      this.value += (target - this.value) * Math.min(1, dt * rate);
      if (this.value < 0.002) this.value = 0;
      return this.value;
    }
  }

  // Per-state look. Values are blended toward each frame so state changes glide.
  const STATES = {
    IDLE:         { spin: 0.10, bright: 0.55, breath: 0.010, swirl: 0.0, color: [139, 92, 246] },
    LISTENING:    { spin: 0.14, bright: 0.80, breath: 0.030, swirl: 0.0, color: [167, 139, 250] },
    TRANSCRIBING: { spin: 0.20, bright: 0.85, breath: 0.030, swirl: 0.3, color: [167, 139, 250] },
    THINKING:     { spin: 0.34, bright: 0.90, breath: 0.050, swirl: 1.0, color: [196, 165, 253] },
    SPEAKING:     { spin: 0.18, bright: 1.00, breath: 0.020, swirl: 0.0, color: [196, 181, 253] },
    ERROR:        { spin: 0.06, bright: 0.70, breath: 0.010, swirl: 0.0, color: [248, 113, 113] },
  };
  const stateParams = state => STATES[state] || STATES.IDLE;

  class Orb {
    constructor(canvas, opts = {}) {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.field = createField(opts.count || 480, opts.seed || 7, opts.links || 3);
      const n = this.field.pts.length;
      this.px = new Float32Array(n); this.py = new Float32Array(n); this.pd = new Float32Array(n);
      this.voice = new VoiceLevel();
      const base = stateParams('IDLE');
      this.cur = { spin: base.spin, bright: base.bright, breath: base.breath, swirl: base.swirl, color: base.color.slice() };
      this.angle = 0; this.last = 0; this.dpr = 1;
      this.resize();
      if (typeof ResizeObserver !== 'undefined') {
        this.observer = new ResizeObserver(() => this.resize());
        this.observer.observe(canvas);
      }
    }

    resize() {
      const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
      const rect = this.canvas.getBoundingClientRect ? this.canvas.getBoundingClientRect() : { width: this.canvas.width, height: this.canvas.height };
      this.dpr = dpr;
      if (!rect.width || !rect.height) return;
      const w = Math.max(1, Math.floor(rect.width * dpr)), h = Math.max(1, Math.floor(rect.height * dpr));
      if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
    }

    // level: raw audio RMS (0 when silent). state: IDLE / LISTENING / THINKING / SPEAKING / ERROR.
    draw(now, level, state, reduced) {
      const canvas = this.canvas, ctx = this.ctx;
      if (!canvas.width || !canvas.height) { this.resize(); if (!canvas.width) return; }
      const dt = this.last ? Math.min(0.1, (now - this.last) / 1000) : 0.016;
      this.last = now;
      const t = now / 1000, motion = reduced ? 0.25 : 1;
      const cur = this.cur, target = stateParams(state), blend = Math.min(1, dt * 3);
      for (const key of ['spin', 'bright', 'breath', 'swirl']) cur[key] = lerp(cur[key], target[key], blend);
      for (let c = 0; c < 3; c++) cur.color[c] = lerp(cur.color[c], target.color[c], blend);

      let rms = Number(level) || 0;
      // Speaking with no audio level available (classic voice path): fake a speech rhythm so it never freezes.
      if (state === 'SPEAKING' && rms < 0.008) rms = 0.05 + 0.04 * (0.5 + 0.5 * Math.sin(t * 9) * Math.sin(t * 3.7 + 1));
      const v = this.voice.update(rms, dt) * (reduced ? 0.3 : 1);

      this.angle += dt * (cur.spin + cur.swirl * 0.25 + v * 0.25) * motion;
      const ay = this.angle, ax = 0.35 + Math.sin(t * 0.11) * 0.22 * motion;
      const w = canvas.width, h = canvas.height, R = Math.min(w, h) * 0.34, cx = w / 2, cy = h / 2;
      const scale = 1 + cur.breath * Math.sin(t * 1.3) * motion + 0.14 * v;
      const { pts, edges } = this.field, px = this.px, py = this.py, pd = this.pd;
      const wob = 0.035 * motion;

      for (let i = 0; i < pts.length; i++) {
        const p = pts[i];
        let x = p.x + Math.sin(t * p.speed + p.phase) * wob;
        const y = p.y + Math.sin(t * p.speed * 0.9 + p.phase * 1.7) * wob;
        let z = p.z + Math.cos(t * p.speed * 1.1 + p.phase * 0.6) * wob;
        if (cur.swirl > 0.01) { // thinking: the cloud twists around its axis
          const tw = cur.swirl * 0.6 * y * Math.sin(t * 0.7) * motion, c = Math.cos(tw), s = Math.sin(tw);
          const nx = x * c + z * s; z = -x * s + z * c; x = nx;
        }
        const k = scale * (1 + v * 0.09 * Math.sin(p.r * 10 - t * 9)); // ripples travel out from the core
        const pr = project(x * k, y * k, z * k, ay, ax);
        px[i] = cx + pr.x * R; py[i] = cy + pr.y * R; pd[i] = pr.depth;
      }

      const [cr, cg, cb] = cur.color.map(Math.round), bright = cur.bright, dpr = this.dpr;
      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = 'lighter';

      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * (0.55 + 0.35 * v));
      glow.addColorStop(0, `rgba(${cr},${cg},${cb},${clamp((0.16 + 0.5 * v) * bright, 0, 0.8)})`);
      glow.addColorStop(1, `rgba(${cr},${cg},${cb},0)`);
      ctx.fillStyle = glow; ctx.fillRect(0, 0, w, h);

      const buckets = [[], [], []];
      for (let e = 0; e < edges.length; e++) {
        const [i, j] = edges[e], dn = clamp((pd[i] + pd[j]) / 4 + 0.5);
        buckets[dn < 0.4 ? 0 : dn < 0.7 ? 1 : 2].push(e);
      }
      for (let b = 0; b < 3; b++) {
        ctx.beginPath();
        for (const e of buckets[b]) { const [i, j] = edges[e]; ctx.moveTo(px[i], py[i]); ctx.lineTo(px[j], py[j]); }
        ctx.strokeStyle = `rgba(${cr},${cg},${cb},${clamp((0.10 + 0.14 * b) * (0.5 + 0.5 * bright) * (1 + v * 0.9), 0, 0.85)})`;
        ctx.lineWidth = (0.6 + 0.3 * b) * dpr;
        ctx.stroke();
      }

      for (let i = 0; i < pts.length; i++) {
        const p = pts[i], dn = clamp((pd[i] + 1) / 2), white = (1 - p.r) * 0.6 * bright;
        const rr = Math.round(lerp(cr, 255, white)), gg = Math.round(lerp(cg, 255, white)), bb = Math.round(lerp(cb, 255, white));
        ctx.fillStyle = `rgba(${rr},${gg},${bb},${clamp((0.35 + 0.55 * dn) * bright, 0, 1)})`;
        ctx.beginPath();
        ctx.arc(px[i], py[i], p.size * (0.7 + 0.9 * dn) * dpr * (1 + 0.6 * v), 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalCompositeOperation = 'source-over';
      return v;
    }

    destroy() { if (this.observer) this.observer.disconnect(); }
  }

  root.NeuralOrb = { Orb, createField, project, VoiceLevel, stateParams };
  if (typeof module !== 'undefined') module.exports = { Orb, createField, project, VoiceLevel, stateParams };
})(typeof window !== 'undefined' ? window : globalThis);
