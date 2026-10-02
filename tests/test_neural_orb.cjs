const test = require('node:test');
const assert = require('node:assert/strict');
const { Orb, createField, project, VoiceLevel, stateParams } = require('../frontend-v2/assets/neural-orb.js');

function fakeCanvas(width = 300, height = 300) {
  const calls = { arc: 0, stroke: 0, fillStyles: [] };
  const grad = { addColorStop() {} };
  const ctx = {
    clearRect() {}, fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, fill() {},
    stroke() { calls.stroke++; }, arc() { calls.arc++; },
    createRadialGradient() { return grad; },
    set fillStyle(v) { calls.fillStyles.push(v); }, set strokeStyle(_) {}, set lineWidth(_) {},
    set globalCompositeOperation(_) {},
  };
  return { width, height, getContext: () => ctx, getBoundingClientRect: () => ({ width, height }), calls };
}

test('the field is deterministic, dense toward the core, and links are unique', () => {
  const a = createField(200, 7, 3), b = createField(200, 7, 3);
  assert.deepEqual(a.pts[10], b.pts[10]);
  assert.equal(a.pts.length, 200);
  assert.ok(a.pts.every(p => p.r >= 0 && p.r <= 1));
  const inner = a.pts.filter(p => p.r < 0.5).length;
  assert.ok(inner > 200 * 0.25, 'a uniform ball puts 12.5% inside half the radius; the orb core should be well above that');
  const keys = new Set(a.edges.map(([i, j]) => `${Math.min(i, j)}-${Math.max(i, j)}`));
  assert.equal(keys.size, a.edges.length);
  assert.ok(a.edges.every(([i, j]) => i !== j));
});

test('projection: nearer points appear larger and a zero rotation keeps x/y', () => {
  const far = project(0.5, 0, -0.8, 0, 0), near = project(0.5, 0, 0.8, 0, 0);
  assert.ok(near.x > far.x && near.depth > far.depth);
  const flat = project(0.3, 0.2, 0, 0, 0);
  assert.ok(Math.abs(flat.x - 0.3) < 1e-9 && Math.abs(flat.y - 0.2) < 1e-9);
});

test('voice level ignores the noise floor, attacks fast and releases slowly', () => {
  const v = new VoiceLevel();
  for (let i = 0; i < 50; i++) assert.equal(v.update(0.005, 0.033), 0);
  const up = v.update(0.12, 0.033);
  assert.ok(up > 0.4, 'a loud frame should jump quickly');
  const afterOne = v.update(0, 0.033);
  assert.ok(afterOne > up * 0.6, 'release should be slower than attack');
  for (let i = 0; i < 200; i++) v.update(0, 0.033);
  assert.equal(v.value, 0);
});

test('speaking swells the orb more than idling, with the same audio', () => {
  const quiet = new Orb(fakeCanvas()), loud = new Orb(fakeCanvas());
  let q = 0, l = 0;
  for (let i = 0; i < 30; i++) { q = quiet.draw(i * 33, 0, 'IDLE', false); l = loud.draw(i * 33, 0.15, 'SPEAKING', false); }
  assert.equal(q, 0);
  assert.ok(l > 0.5);
});

test('speaking with no audio level still pulses (classic voice fallback)', () => {
  const orb = new Orb(fakeCanvas());
  let peak = 0;
  for (let i = 0; i < 60; i++) peak = Math.max(peak, orb.draw(i * 33, 0, 'SPEAKING', false));
  assert.ok(peak > 0.1);
});

test('every frame draws every point and the links, and survives odd input', () => {
  const canvas = fakeCanvas(), orb = new Orb(canvas, { count: 120 });
  orb.draw(0, 0, 'IDLE', false);
  assert.equal(canvas.calls.arc, 120);
  assert.equal(canvas.calls.stroke, 3);
  assert.doesNotThrow(() => orb.draw(33, NaN, 'NOT_A_STATE', true));
  assert.doesNotThrow(() => orb.draw(66, undefined, 'ERROR', false));
  const empty = new Orb(fakeCanvas(0, 0));
  assert.equal(empty.draw(0, 0, 'IDLE', false), undefined);
});

test('reduced motion damps the pulse and error turns the orb red', () => {
  const calm = new Orb(fakeCanvas()), full = new Orb(fakeCanvas());
  let c = 0, f = 0;
  for (let i = 0; i < 30; i++) { c = calm.draw(i * 33, 0.15, 'SPEAKING', true); f = full.draw(i * 33, 0.15, 'SPEAKING', false); }
  assert.ok(c < f * 0.5);
  const [r, g] = stateParams('ERROR').color;
  assert.ok(r > g * 1.5);
  assert.deepEqual(stateParams('???'), stateParams('IDLE'));
});
