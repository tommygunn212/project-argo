/* Winamp-style MilkDrop visuals that dance to ARGO's voice.
 *
 * Uses butterchurn (MIT, a WebGL port of MilkDrop) from /v2-assets. Each
 * avatar stage gets one visualizer canvas. Audio comes from the same Web Audio
 * source node the avatar meter already builds for ARGO's LiveKit track, so the
 * visuals follow exactly what she says. With no audio connected they idle
 * quietly instead of going black.
 *
 *   MilkdropVisuals.init(canvases)        once, after the scripts load
 *   MilkdropVisuals.connect(ctx, node)    when ARGO's audio track arrives
 *   MilkdropVisuals.disconnect()          when it goes away
 *   MilkdropVisuals.setActive(bool)       render only while the mode is shown
 *   MilkdropVisuals.next()                jump to another preset
 */
(function (root) {
  'use strict';

  const PRESET_SECONDS = 24;      // how long each preset plays
  const BLEND_SECONDS = 2.7;      // cross-fade between presets
  const FAVES_KEY = 'argoMilkdropFaves', FAVES_ONLY_KEY = 'argoMilkdropFavesOnly';
  const state = {
    faves: [], favesOnly: false, ticks: 0,
    viz: [], audioContext: null, node: null, presets: [], names: [],
    active: false, raf: null, lastSwitch: 0, index: -1, ready: false, idle: null,
  };

  // A quiet, slowly wobbling tone feeds the visuals when ARGO's voice is not
  // connected, so the stage breathes instead of sitting black. It goes only to
  // butterchurn's analyser, never to the speakers.
  function idleSource(ctx) {
    if (state.idle && state.idle.ctx === ctx) return state.idle.out;
    const osc = ctx.createOscillator(), lfo = ctx.createOscillator();
    const depth = ctx.createGain(), out = ctx.createGain();
    osc.frequency.value = 110; lfo.frequency.value = 0.35;
    depth.gain.value = 0.06; out.gain.value = 0.06;
    lfo.connect(depth); depth.connect(out.gain); osc.connect(out);
    osc.start(); lfo.start();
    state.idle = { ctx, out };
    return out;
  }

  function attach(node) {
    state.viz.forEach(v => { try { v.viz.connectAudio(node); } catch (_) {} });
  }
  function detach(node) {
    state.viz.forEach(v => { try { v.viz.disconnectAudio(node); } catch (_) {} });
  }

  function supported() {
    try {
      const c = document.createElement('canvas');
      return Boolean(root.butterchurn && root.butterchurnPresets &&
                     (c.getContext('webgl2') || c.getContext('webgl')));
    } catch (_) { return false; }
  }

  function lib() { return root.butterchurn.default || root.butterchurn; }

  function ensureContext() {
    if (state.audioContext) return state.audioContext;
    const AudioCtx = root.AudioContext || root.webkitAudioContext;
    state.audioContext = new AudioCtx();
    return state.audioContext;
  }

  function sizeOf(canvas) {
    const r = canvas.getBoundingClientRect();
    const ratio = Math.min(root.devicePixelRatio || 1, 2);
    return { w: Math.max(64, Math.round(r.width * ratio)), h: Math.max(64, Math.round(r.height * ratio)) };
  }

  function shuffle(list) {
    const a = list.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function loadSaved() {
    try {
      const list = JSON.parse(root.localStorage.getItem(FAVES_KEY) || '[]');
      state.faves = Array.isArray(list) ? list.filter(n => typeof n === 'string').slice(0, 500) : [];
      state.favesOnly = root.localStorage.getItem(FAVES_ONLY_KEY) === '1';
    } catch (_) { state.faves = []; state.favesOnly = false; }
  }
  function saveFaves() {
    try {
      root.localStorage.setItem(FAVES_KEY, JSON.stringify(state.faves));
      root.localStorage.setItem(FAVES_ONLY_KEY, state.favesOnly ? '1' : '0');
    } catch (_) {}
  }
  function current() { return state.names[state.index] || ''; }
  function isFave(name) { return state.faves.indexOf(name || current()) >= 0; }
  // Which preset comes next. With "favorites only" on and at least one favorite
  // that exists in this preset pack, only favorites are visited.
  function step(dir, blend) {
    if (!state.names.length) return;
    const n = state.names.length;
    const usable = state.favesOnly && state.names.some(name => state.faves.indexOf(name) >= 0);
    let i = state.index;
    for (let tries = 0; tries < n; tries++) {
      i = (i + dir + n) % n;
      if (!usable || state.faves.indexOf(state.names[i]) >= 0) break;
    }
    loadPreset(i, blend);
    refreshControls();
  }
  function toggleFavorite() {
    const name = current();
    if (!name) return false;
    const at = state.faves.indexOf(name);
    if (at >= 0) state.faves.splice(at, 1); else state.faves.push(name);
    saveFaves(); refreshControls();
    return at < 0;
  }
  function setFavoritesOnly(on) {
    state.favesOnly = Boolean(on);
    saveFaves(); refreshControls();
    if (state.favesOnly && !isFave()) step(1, BLEND_SECONDS);
  }

  // A small control strip on each visualizer: previous, favorite, next, and
  // "favorites only". It shows only while that visualizer is on screen.
  const controls = [];
  function refreshControls() {
    controls.forEach(c => {
      c.name.textContent = current();
      c.fave.textContent = isFave() ? '\u2605' : '\u2606';
      c.only.style.opacity = state.favesOnly ? '1' : '0.55';
      c.only.title = state.favesOnly ? 'Playing favorites only (click for all)' : 'Playing all presets (click for favorites only)';
      c.bar.style.display = c.canvas.offsetParent !== null ? 'flex' : 'none';
    });
  }
  function buildControls(canvas) {
    try {
      const parent = canvas.parentElement;
      if (!parent || !root.document) return;
      if (root.getComputedStyle(parent).position === 'static') parent.style.position = 'relative';
      const bar = root.document.createElement('div');
      bar.style.cssText = 'position:absolute;left:8px;right:8px;bottom:8px;display:none;gap:6px;align-items:center;' +
        'padding:4px 8px;border-radius:8px;background:rgba(0,0,0,.55);color:#cfe;font:12px system-ui;z-index:5';
      const mk = (label, title, fn) => {
        const b = root.document.createElement('button');
        b.textContent = label; b.title = title; b.type = 'button';
        b.style.cssText = 'background:none;border:0;color:inherit;cursor:pointer;font-size:15px;padding:0 4px';
        b.addEventListener('click', ev => { ev.stopPropagation(); fn(); });
        bar.appendChild(b);
        return b;
      };
      mk('\u25c0', 'Previous preset', () => step(-1, BLEND_SECONDS));
      const fave = mk('\u2606', 'Favorite this preset', toggleFavorite);
      mk('\u25b6', 'Next preset', () => step(1, BLEND_SECONDS));
      const only = mk('Faves only', '', () => setFavoritesOnly(!state.favesOnly));
      only.style.fontSize = '12px';
      const name = root.document.createElement('span');
      name.style.cssText = 'flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;opacity:.8';
      bar.appendChild(name);
      parent.appendChild(bar);
      controls.push({ canvas, bar, fave, only, name });
    } catch (_) {}
  }

  function loadPreset(index, blend) {
    if (!state.names.length) return;
    state.index = (index + state.names.length) % state.names.length;
    const preset = state.presets[state.names[state.index]];
    state.viz.forEach(v => { try { v.viz.loadPreset(preset, blend); } catch (_) {} });
    state.lastSwitch = performance.now();
  }

  function init(canvases) {
    if (state.ready) return true;
    if (!supported()) return false;
    try {
      state.presets = root.butterchurnPresets.getPresets();
      loadSaved();
      state.names = shuffle(Object.keys(state.presets));
      const ctx = ensureContext();
      Array.from(canvases || []).forEach(canvas => {
        const { w, h } = sizeOf(canvas);
        canvas.width = w; canvas.height = h;
        const viz = lib().createVisualizer(ctx, canvas, { width: w, height: h, pixelRatio: 1 });
        state.viz.push({ canvas, viz, w, h });
        if (!controls.some(c => c.canvas === canvas)) buildControls(canvas);
      });
      state.ready = state.viz.length > 0;
      if (state.ready) { loadPreset(state.favesOnly ? -1 : 0, 0); if (state.favesOnly) step(1, 0); attach(idleSource(ctx)); refreshControls(); }
      return state.ready;
    } catch (err) {
      console.warn('MilkDrop visuals unavailable', err);
      return false;
    }
  }

  function connect(audioContext, node) {
    if (!state.ready || !node) return;
    // butterchurn needs its nodes on the same AudioContext as the source.
    if (audioContext && audioContext !== state.audioContext) {
      const canvases = state.viz.map(v => v.canvas);
      state.viz = []; state.ready = false; state.audioContext = audioContext;
      init(canvases);
    }
    disconnect();
    if (state.idle) detach(state.idle.out);
    state.node = node;
    attach(node);
  }

  function disconnect() {
    if (!state.node) return;
    detach(state.node);
    state.node = null;
    if (state.ready && state.audioContext) attach(idleSource(state.audioContext));
  }

  function frame(now) {
    state.raf = state.active ? requestAnimationFrame(frame) : null;
    if (!state.active || document.hidden) return;
    if (now - state.lastSwitch > PRESET_SECONDS * 1000) step(1, BLEND_SECONDS);
    if (controls.length && ++state.ticks % 30 === 0) refreshControls();
    state.viz.forEach(v => {
      const { w, h } = sizeOf(v.canvas);
      if (w !== v.w || h !== v.h) {
        v.canvas.width = w; v.canvas.height = h; v.w = w; v.h = h;
        try { v.viz.setRendererSize(w, h); } catch (_) {}
      }
      if (v.canvas.offsetParent !== null) { try { v.viz.render(); } catch (_) {} }
    });
  }

  function setActive(on) {
    state.active = Boolean(on) && state.ready;
    if (state.active) {
      try { if (state.audioContext.state === 'suspended') state.audioContext.resume(); } catch (_) {}
      if (!state.raf) state.raf = requestAnimationFrame(frame);
    }
  }

  root.MilkdropVisuals = {
    init, connect, disconnect, setActive, supported,
    next: () => step(1, BLEND_SECONDS),
    prev: () => step(-1, BLEND_SECONDS),
    toggleFavorite, setFavoritesOnly,
    get favorites() { return state.faves.slice(); },
    get favoritesOnly() { return state.favesOnly; },
    get presetName() { return state.names[state.index] || ''; },
  };
})(typeof window !== 'undefined' ? window : this);
