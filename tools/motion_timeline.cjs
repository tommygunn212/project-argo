/*
 * Headless proof: run the rig over a speech-like sequence and print what the
 * mouth actually does, frame by frame, next to what the old scale-only rig
 * would have done at the same moment.
 *
 *   node tools/motion_timeline.cjs
 */
const M = require('../frontend-v2/assets/avatar-motion.js');

const SEQUENCE = [
  ['wide vowel   /i/', { energy: 0.55, centroid: 0.74, hfRatio: 0.18, flux: 0.3 }],
  ['sibilant     /s/', { energy: 0.13, centroid: 0.86, hfRatio: 0.80, flux: 0.8 }],
  ['round vowel  /u/', { energy: 0.60, centroid: 0.13, hfRatio: 0.12, flux: 0.3 }],
  ['open vowel   /a/', { energy: 0.50, centroid: 0.40, hfRatio: 0.20, flux: 0.3 }],
  ['closure      /p/', { energy: 0.02, centroid: 0.20, hfRatio: 0.10, flux: 0.1 }],
  ['fricative    /f/', { energy: 0.15, centroid: 0.82, hfRatio: 0.74, flux: 0.7 }],
  ['wide vowel   /e/', { energy: 0.52, centroid: 0.68, hfRatio: 0.20, flux: 0.3 }],
  ['silence         ', { energy: 0.00, centroid: 0.00, hfRatio: 0.00, flux: 0.0 }],
];

function legacy(energy, prev, dt) {
  const target = energy > 0.045 ? Math.min(1, energy * 2.4) : 0;
  return prev + (target - prev) * (1 - Math.exp(-dt / 0.08));
}

const rig = new M.AvatarRig({ seed: 20260915 });
rig.setState('SPEAKING');

const dt = 1 / 60;
let legacyValue = 0;
const seen = new Set();
const legacySeen = new Set();
let lastViseme = null;
let transitions = 0;

const bar = (v) => '#'.repeat(Math.round(v * 14)).padEnd(14, '.');

console.log('');
console.log('  segment            aperture        dominant     top blend            BEFORE');
console.log('  ' + '-'.repeat(88));

for (const [label, features] of SEQUENCE) {
  for (let i = 0; i < 12; i++) {
    const pose = rig.update(dt, features);
    legacyValue = legacy(features.energy, legacyValue, dt);
    seen.add(pose.dominantViseme);
    legacySeen.add(legacyValue > 0.05 ? 'open' : 'rest');
    if (lastViseme && lastViseme !== pose.dominantViseme) transitions++;
    lastViseme = pose.dominantViseme;
  }
  const p = rig.pose;
  const top = M.VISEMES
    .map((k) => [k, p.visemes[k]])
    .filter(([, v]) => v > 0.08)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k} ${v.toFixed(2)}`)
    .join(' + ');
  console.log(
    `  ${label}  ${bar(p.aperture)} ${p.aperture.toFixed(2)}  ` +
    `${p.dominantViseme.padEnd(9)}  ${top.padEnd(28)} ${bar(legacyValue)}`
  );
}

console.log('');
console.log('  RESULT');
console.log(`    distinct mouth shapes   AFTER ${seen.size}  (${[...seen].join(', ')})`);
console.log(`                            BEFORE ${legacySeen.size}  (${[...legacySeen].join(', ')})`);
console.log(`    shape changes           AFTER ${transitions}   BEFORE 0`);
console.log('');

// Non-mouth layers keep moving with the mouth completely shut.
const idle = new M.AvatarRig({ seed: 4 });
idle.setState('LISTENING');
let blinks = 0, wasOpen = true;
const tilts = [], breaths = [];
for (let i = 0; i < 60 * 30; i++) {
  const pose = idle.update(dt, { energy: 0, centroid: 0, hfRatio: 0, flux: 0 });
  const closed = pose.lid < 0.25;
  if (closed && wasOpen) blinks++;
  wasOpen = !closed;
  tilts.push(pose.tilt);
  breaths.push(pose.breath);
}
console.log('  WITH THE MOUTH SHUT FOR 30 SECONDS (listening)');
console.log(`    blinks                  ${blinks}`);
console.log(`    head tilt range         ${(Math.max(...tilts) - Math.min(...tilts)).toFixed(4)} rad`);
console.log(`    breathing range         ${(Math.max(...breaths) - Math.min(...breaths)).toFixed(3)}`);
console.log(`    mouth aperture          ${idle.pose.aperture} (still)`);
console.log('');

// Interruption
const int = new M.AvatarRig({ seed: 4 });
int.setState('SPEAKING');
for (let i = 0; i < 60; i++) int.update(dt, SEQUENCE[0][1]);
const before = int.pose.aperture;
int.setState('INTERRUPTED');
console.log('  INTERRUPTION');
console.log(`    aperture before         ${before.toFixed(3)}`);
console.log(`    aperture same frame     ${int.speech.aperture.toFixed(3)}`);
console.log('');
