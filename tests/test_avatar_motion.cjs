/*
 * Avatar motion engine.
 *
 * The claim being tested is specific: the mouth changes SHAPE, not just
 * opening, and the face keeps moving when the mouth does not. A rig that
 * scales one mouth shape would pass a naive "does it move" test, so the
 * important assertions here are about shape variety and about the layers that
 * are deliberately not driven by the audio envelope.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../frontend-v2/assets/avatar-motion.js');

// --- synthetic audio -----------------------------------------------------

function frame(energy, centroid, hfRatio, flux) {
  return { energy, centroid, hfRatio, flux: flux || 0 };
}

const SILENCE = frame(0, 0, 0, 0);
const VOWEL_WIDE = frame(0.5, 0.75, 0.2, 0.2);     // bright and loud  -> /i/
const VOWEL_ROUND = frame(0.5, 0.12, 0.15, 0.2);   // dark and loud    -> /u/
const VOWEL_OPEN = frame(0.5, 0.38, 0.2, 0.2);     // mid              -> /a/
const SIBILANT = frame(0.12, 0.85, 0.8, 0.6);      // quiet and hissy  -> s/f

function run(rig, features, seconds, dt) {
  const step = dt || 1 / 60;
  const poses = [];
  for (let t = 0; t < seconds; t += step) {
    poses.push(JSON.parse(JSON.stringify(rig.update(step, features))));
  }
  return poses;
}

// --- 1. speech rig: shape is separate from opening -----------------------

test('a loud bright sound and a loud dark sound produce different mouth shapes', () => {
  const wide = M.solveVisemeWeights(VOWEL_WIDE);
  const round = M.solveVisemeWeights(VOWEL_ROUND);
  assert.ok(wide.wide > wide.rounded, 'bright vowel should favour wide');
  assert.ok(round.rounded > round.wide, 'dark vowel should favour rounded');
});

test('sibilants use the contact shape rather than opening the jaw', () => {
  const w = M.solveVisemeWeights(SIBILANT);
  assert.ok(w.contact > 0.3, `expected contact to dominate, got ${JSON.stringify(w)}`);
  assert.ok(w.contact > w.open, 'a sibilant is not an open mouth');
});

test('viseme weights always form a blend that sums to one', () => {
  for (const f of [VOWEL_WIDE, VOWEL_ROUND, VOWEL_OPEN, SIBILANT, SILENCE]) {
    const w = M.solveVisemeWeights(f);
    const sum = M.VISEMES.reduce((a, k) => a + w[k], 0);
    assert.ok(Math.abs(sum - 1) < 1e-6, `weights summed to ${sum}`);
  }
});

test('more than one viseme is active at once - it blends, it does not switch', () => {
  const w = M.solveVisemeWeights(VOWEL_OPEN);
  const active = M.VISEMES.filter((k) => w[k] > 0.01);
  assert.ok(active.length >= 2, `expected a blend, got ${JSON.stringify(w)}`);
});

test('silence rests the mouth rather than holding it open', () => {
  const w = M.solveVisemeWeights(SILENCE);
  assert.equal(w.rest, 1);
});

test('THE POINT: real speech visits several distinct mouth shapes', () => {
  const rig = new M.AvatarRig({ seed: 5 });
  rig.setState('SPEAKING');
  const sequence = [VOWEL_WIDE, SIBILANT, VOWEL_ROUND, VOWEL_OPEN, SIBILANT, VOWEL_WIDE];
  const poses = [];
  for (const f of sequence) poses.push(...run(rig, f, 0.25));
  const variety = M.shapeVariety(poses);
  assert.ok(
    variety.distinctVisemes >= 4,
    `a scale-only rig scores 1; got ${variety.distinctVisemes} (${variety.visemesSeen})`
  );
});

test('aperture opens faster than it closes, so the jaw has weight', () => {
  const rig = new M.AvatarRig({ seed: 5 });
  rig.setState('SPEAKING');
  let opening = 0;
  for (let i = 0; i < 6; i++) opening = rig.update(1 / 60, VOWEL_OPEN).aperture;

  const rig2 = new M.AvatarRig({ seed: 5 });
  rig2.setState('SPEAKING');
  for (let i = 0; i < 40; i++) rig2.update(1 / 60, VOWEL_OPEN);
  const peak = rig2.pose.aperture;
  for (let i = 0; i < 6; i++) rig2.update(1 / 60, SILENCE);
  const closedBy = peak - rig2.pose.aperture;

  assert.ok(opening > 0.05, 'should start opening promptly');
  assert.ok(closedBy < peak * 0.75, 'should settle out, not snap shut');
});

test('the mouth is fully closed after sustained silence', () => {
  const rig = new M.AvatarRig({ seed: 5 });
  rig.setState('SPEAKING');
  run(rig, VOWEL_OPEN, 0.5);
  run(rig, SILENCE, 2);
  assert.equal(rig.pose.aperture, 0);
});

test('the mouth does not move at all when not speaking', () => {
  const rig = new M.AvatarRig({ seed: 5 });
  rig.setState('LISTENING');
  const poses = run(rig, VOWEL_OPEN, 1); // loud audio, but she is listening
  assert.ok(poses.every((p) => p.aperture === 0), 'listening must not lip-sync');
});

// --- 2. eyes -------------------------------------------------------------

test('she blinks, and blink gaps vary rather than ticking like a metronome', () => {
  const eyes = new M.EyeController({ seed: 99 });
  const gaps = [];
  let since = 0, wasOpen = true;
  for (let i = 0; i < 60 * 120; i++) {
    const out = eyes.update(1 / 60, 'IDLE');
    since += 1 / 60;
    const closed = out.lid < 0.25;
    if (closed && wasOpen) { gaps.push(since); since = 0; }
    wasOpen = !closed;
  }
  assert.ok(gaps.length > 10, `expected regular blinking, got ${gaps.length}`);
  const unique = new Set(gaps.map((g) => g.toFixed(2)));
  assert.ok(unique.size > gaps.length * 0.5, 'blink timing should vary');
});

test('gaze drifts while listening and never freezes', () => {
  const eyes = new M.EyeController({ seed: 4 });
  const xs = [];
  for (let i = 0; i < 60 * 12; i++) xs.push(eyes.update(1 / 60, 'LISTENING').gaze.x);
  const spread = Math.max(...xs) - Math.min(...xs);
  assert.ok(spread > 0.02, `gaze should move, spread was ${spread}`);
});

test('thinking looks away further than speaking does', () => {
  const think = new M.EyeController({ seed: 12 });
  const speak = new M.EyeController({ seed: 12 });
  let thinkMax = 0, speakMax = 0;
  for (let i = 0; i < 60 * 20; i++) {
    thinkMax = Math.max(thinkMax, Math.abs(think.update(1 / 60, 'THINKING').gaze.x));
    speakMax = Math.max(speakMax, Math.abs(speak.update(1 / 60, 'SPEAKING').gaze.x));
  }
  assert.ok(thinkMax > speakMax * 1.8, `thinking ${thinkMax} vs speaking ${speakMax}`);
});

test('eyes hold the camera while speaking', () => {
  const eyes = new M.EyeController({ seed: 8 });
  let max = 0;
  for (let i = 0; i < 60 * 20; i++) max = Math.max(max, Math.abs(eyes.update(1 / 60, 'SPEAKING').gaze.x));
  assert.ok(max < 0.2, `speaking gaze wandered to ${max}`);
});

// --- 3. posture ----------------------------------------------------------

test('she breathes while idle with the mouth shut', () => {
  const rig = new M.AvatarRig({ seed: 3 });
  const poses = run(rig, SILENCE, 8);
  const breaths = poses.map((p) => p.breath);
  assert.ok(Math.max(...breaths) - Math.min(...breaths) > 0.5, 'idle should still breathe');
  assert.ok(poses.every((p) => p.aperture === 0));
});

test('speaking carries more postural energy than listening', () => {
  const a = new M.AvatarRig({ seed: 3 });
  a.setState('SPEAKING');
  run(a, VOWEL_OPEN, 3);
  const b = new M.AvatarRig({ seed: 3 });
  b.setState('LISTENING');
  run(b, SILENCE, 3);
  assert.ok(a.pose.energy > b.pose.energy);
});

test('head motion is small and not a visualiser', () => {
  const rig = new M.AvatarRig({ seed: 3 });
  rig.setState('SPEAKING');
  const poses = run(rig, VOWEL_OPEN, 6);
  assert.ok(poses.every((p) => Math.abs(p.tilt) < 0.06), 'tilt must stay subtle');
  assert.ok(poses.every((p) => Math.abs(p.nod) < 0.06), 'nod must stay subtle');
});

test('head motion does not simply track the audio envelope', () => {
  const rig = new M.AvatarRig({ seed: 3 });
  rig.setState('SPEAKING');
  const poses = run(rig, VOWEL_OPEN, 6);
  // Constant audio: a visualiser-style rig would hold the head still.
  const tilts = poses.map((p) => p.tilt);
  assert.ok(Math.max(...tilts) - Math.min(...tilts) > 0.005, 'head should live independently');
});

// --- 4. synthetic detail -------------------------------------------------

test('the vocal chamber lights with speech and goes quiet after', () => {
  const rig = new M.AvatarRig({ seed: 3 });
  rig.setState('SPEAKING');
  run(rig, VOWEL_OPEN, 1);
  const lit = rig.pose.chamber;
  rig.setState('LISTENING');
  run(rig, SILENCE, 2);
  assert.ok(lit > 0.3, `chamber should light, got ${lit}`);
  assert.ok(rig.pose.chamber < 0.15, 'chamber should settle when not speaking');
});

test('circuit pulses respond to onsets, not only loudness', () => {
  const steady = new M.AvatarRig({ seed: 3 });
  steady.setState('SPEAKING');
  run(steady, frame(0.5, 0.4, 0.2, 0.0), 1.5);
  const bursty = new M.AvatarRig({ seed: 3 });
  bursty.setState('SPEAKING');
  run(bursty, frame(0.5, 0.4, 0.2, 0.9), 1.5);
  assert.ok(bursty.pose.circuit > steady.pose.circuit, 'onsets should drive the circuits');
});

// --- 5. state machine ----------------------------------------------------

test('interruption closes the mouth on the very same frame', () => {
  const rig = new M.AvatarRig({ seed: 3 });
  rig.setState('SPEAKING');
  run(rig, VOWEL_OPEN, 1);
  assert.ok(rig.pose.aperture > 0.1, 'should be mid-speech');
  rig.setState('INTERRUPTED');
  assert.equal(rig.speech.aperture, 0, 'mouth must shut immediately, not fade');
});

test('interruption hands over to listening rather than sticking', () => {
  const rig = new M.AvatarRig({ seed: 3 });
  rig.setState('SPEAKING');
  rig.setState('INTERRUPTED');
  run(rig, SILENCE, 1);
  assert.equal(rig.pose.state, 'LISTENING');
});

test('listening falls back to idle when nothing happens for a long time', () => {
  const rig = new M.AvatarRig({ seed: 3, machine: { idleAfter: 2 } });
  rig.setState('LISTENING');
  run(rig, SILENCE, 3);
  assert.equal(rig.pose.state, 'IDLE');
});

test('unknown states are rejected instead of corrupting the rig', () => {
  const rig = new M.AvatarRig({ seed: 3 });
  rig.setState('SPEAKING');
  rig.setState('BANANA');
  assert.equal(rig.machine.state, 'SPEAKING');
});

// --- robustness ----------------------------------------------------------

test('a backgrounded tab does not teleport the rig', () => {
  const rig = new M.AvatarRig({ seed: 3 });
  rig.setState('SPEAKING');
  const pose = rig.update(30, VOWEL_OPEN); // 30 second frame
  assert.ok(pose.aperture <= 1 && pose.aperture >= 0);
  assert.ok(Math.abs(pose.tilt) < 0.06);
});

test('missing audio features never produce NaN', () => {
  const rig = new M.AvatarRig({ seed: 3 });
  rig.setState('SPEAKING');
  const pose = rig.update(1 / 60, null);
  for (const key of ['aperture', 'lid', 'tilt', 'nod', 'breath', 'chamber', 'circuit']) {
    assert.ok(Number.isFinite(pose[key]), `${key} was ${pose[key]}`);
  }
});

test('smoothing is frame-rate independent', () => {
  const slow = new M.AvatarRig({ seed: 3 });
  slow.setState('SPEAKING');
  run(slow, VOWEL_OPEN, 1, 1 / 30);
  const fast = new M.AvatarRig({ seed: 3 });
  fast.setState('SPEAKING');
  run(fast, VOWEL_OPEN, 1, 1 / 144);
  assert.ok(Math.abs(slow.pose.aperture - fast.pose.aperture) < 0.02,
    `30Hz ${slow.pose.aperture} vs 144Hz ${fast.pose.aperture}`);
});

test('the same seed replays identically', () => {
  const a = new M.AvatarRig({ seed: 42 });
  const b = new M.AvatarRig({ seed: 42 });
  a.setState('SPEAKING'); b.setState('SPEAKING');
  const pa = run(a, VOWEL_OPEN, 2);
  const pb = run(b, VOWEL_OPEN, 2);
  assert.deepEqual(pa[pa.length - 1], pb[pb.length - 1]);
});

// --- audio analysis ------------------------------------------------------

test('analyser reports louder energy for a louder waveform', () => {
  const quiet = new Uint8Array(256).fill(128);
  const loud = new Uint8Array(256);
  for (let i = 0; i < loud.length; i++) loud[i] = 128 + Math.sin(i * 0.3) * 100;
  const bins = new Uint8Array(128).fill(40);
  assert.ok(M.analyseFrame(bins, loud).energy > M.analyseFrame(bins, quiet).energy);
});

test('analyser reports a higher centroid for a brighter spectrum', () => {
  const time = new Uint8Array(256).fill(128);
  const dark = new Uint8Array(128);
  const bright = new Uint8Array(128);
  for (let i = 0; i < 128; i++) { dark[i] = i < 30 ? 200 : 5; bright[i] = i > 90 ? 200 : 5; }
  assert.ok(M.analyseFrame(bright, time).centroid > M.analyseFrame(dark, time).centroid);
});

test('analyser survives empty data', () => {
  const out = M.analyseFrame(new Uint8Array(0), new Uint8Array(0));
  for (const k of ['energy', 'centroid', 'hfRatio', 'flux']) {
    assert.ok(Number.isFinite(out[k]), `${k} was ${out[k]}`);
  }
});
