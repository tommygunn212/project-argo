/*
 * ARGO Avatar Motion Lab - motion engine.
 *
 * The old rig drove one mouth shape's scale from an audio envelope. That is
 * why she reads as a still face with a moving hole: a real mouth changes SHAPE
 * as well as opening, and a face that only moves its mouth reads as dead.
 *
 * Five independent layers run here, each with its own timing, so nothing is
 * locked to the audio envelope in a way that looks like a music visualiser:
 *
 *   1. speech   - jaw aperture, separate from a blend across six visemes
 *   2. eyes     - blinks with variation, saccades, camera focus while speaking
 *   3. posture  - breathing, micro tilt and nod
 *   4. detail   - vocal-chamber light and circuit pulses
 *   5. state    - IDLE / LISTENING / THINKING / SPEAKING / INTERRUPTED
 *
 * Everything except the renderer is pure and deterministic given a seed, so it
 * can be tested in node without a browser or an audio device.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ArgoAvatarMotion = api;
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
  const clamp01 = (v) => clamp(v, 0, 1);
  const lerp = (a, b, t) => a + (b - a) * t;

  /* Frame-rate independent smoothing. A per-frame coefficient would move at a
   * different speed on a 144Hz monitor than on a 60Hz one. */
  function smoothTowards(current, target, dt, timeConstant) {
    if (timeConstant <= 0) return target;
    const k = 1 - Math.exp(-dt / timeConstant);
    return current + (target - current) * k;
  }

  /* Deterministic PRNG so tests and recorded runs reproduce exactly. */
  function makeRandom(seed) {
    let s = (seed >>> 0) || 0x9e3779b9;
    return function random() {
      s ^= s << 13; s >>>= 0;
      s ^= s >> 17;
      s ^= s << 5; s >>>= 0;
      return s / 0x100000000;
    };
  }

  /* Sum of incommensurate sines. Cheap, and it never visibly repeats the way a
   * single sine does - a single sine is exactly what makes a head look like it
   * is bobbing to a beat. */
  function wobble(t, freqs, phases) {
    let sum = 0;
    for (let i = 0; i < freqs.length; i++) sum += Math.sin(t * freqs[i] * Math.PI * 2 + phases[i]);
    return sum / freqs.length;
  }

  // ---------------------------------------------------------------------
  // 1. Audio features
  // ---------------------------------------------------------------------

  const VISEMES = ['closed', 'open', 'wide', 'rounded', 'contact', 'rest'];

  /* Pull the few descriptors the rig actually needs out of raw analyser data.
   *
   *   energy   - how loud, drives jaw aperture
   *   centroid - brightness, separates front vowels (wide) from back (rounded)
   *   hfRatio  - high-frequency share, finds fricatives and sibilants
   *   flux     - how fast the spectrum is changing, finds consonant onsets
   */
  function analyseFrame(freqData, timeData, previousSpectrum) {
    const bins = freqData ? freqData.length : 0;
    let rms = 0;
    if (timeData && timeData.length) {
      for (let i = 0; i < timeData.length; i++) {
        const v = (timeData[i] - 128) / 128;
        rms += v * v;
      }
      rms = Math.sqrt(rms / timeData.length);
    }

    let total = 0, weighted = 0, high = 0, flux = 0;
    const hfStart = Math.floor(bins * 0.45);
    for (let i = 0; i < bins; i++) {
      const mag = freqData[i] / 255;
      total += mag;
      weighted += mag * i;
      if (i >= hfStart) high += mag;
      if (previousSpectrum && previousSpectrum.length === bins) {
        const d = mag - previousSpectrum[i] / 255;
        if (d > 0) flux += d;
      }
    }

    return {
      energy: clamp01(rms * 3.2),
      centroid: total > 0 ? clamp01(weighted / total / Math.max(1, bins) * 2.6) : 0,
      hfRatio: total > 0 ? clamp01(high / total * 1.8) : 0,
      flux: clamp01(flux / Math.max(1, bins) * 12),
    };
  }

  // ---------------------------------------------------------------------
  // 2. Viseme solver - shape, kept separate from aperture
  // ---------------------------------------------------------------------

  /* Returns weights across the six visemes. Weights, not a winner: a mouth
   * caught between two shapes is most of what makes speech read as speech. */
  function solveVisemeWeights(features, opts) {
    const o = opts || {};
    const silence = o.silence == null ? 0.045 : o.silence;
    const f = features;
    const w = { closed: 0, open: 0, wide: 0, rounded: 0, contact: 0, rest: 0 };

    if (f.energy < silence) {
      w.rest = 1;
      return w;
    }

    const voiced = clamp01((f.energy - silence) / 0.25);

    // Sibilants and stops: bright, noisy, and not especially loud. Teeth show,
    // the jaw barely opens - this is the state a scale-only rig cannot express.
    const contact = clamp01((f.hfRatio - 0.42) / 0.3) * clamp01(1 - f.energy * 1.1);
    w.contact = contact * voiced;

    // Front/back vowel axis from brightness.
    const front = clamp01((f.centroid - 0.34) / 0.3);
    const back = clamp01((0.42 - f.centroid) / 0.3);
    const openness = clamp01((f.energy - silence) / 0.3);

    const vowel = Math.max(0, voiced - w.contact);
    w.wide = vowel * front * openness;
    w.rounded = vowel * back * openness;
    w.open = vowel * Math.max(0, 1 - front - back) * openness;
    w.closed = vowel * clamp01(1 - openness) * 0.8;

    let sum = 0;
    for (const k of VISEMES) sum += w[k];
    if (sum <= 0.0001) { w.rest = 1; return w; }
    for (const k of VISEMES) w[k] /= sum;
    return w;
  }

  // ---------------------------------------------------------------------
  // 3. Speech rig - aperture with lead-in and settle-out
  // ---------------------------------------------------------------------

  /* Aperture opens fast and closes slowly. Symmetric timing is the other half
   * of why the old rig looked mechanical: real jaws have mass, so they lag
   * opening slightly and settle rather than snapping shut. */
  function SpeechRig(opts) {
    const o = opts || {};
    this.attack = o.attack == null ? 0.045 : o.attack;
    this.release = o.release == null ? 0.13 : o.release;
    this.shapeTime = o.shapeTime == null ? 0.055 : o.shapeTime;
    this.silence = o.silence == null ? 0.045 : o.silence;
    this.aperture = 0;
    this.weights = { closed: 0, open: 0, wide: 0, rounded: 0, contact: 0, rest: 1 };
  }

  SpeechRig.prototype.reset = function () {
    this.aperture = 0;
    this.weights = { closed: 0, open: 0, wide: 0, rounded: 0, contact: 0, rest: 1 };
  };

  SpeechRig.prototype.update = function (features, dt, speaking) {
    const f = features || { energy: 0, centroid: 0, hfRatio: 0, flux: 0 };
    const target = speaking && f.energy > this.silence
      ? clamp01((f.energy - this.silence) * 2.4)
      : 0;
    const tc = target > this.aperture ? this.attack : this.release;
    this.aperture = smoothTowards(this.aperture, target, dt, tc);
    if (this.aperture < 0.002) this.aperture = 0;

    const want = speaking
      ? solveVisemeWeights(f, { silence: this.silence })
      : { closed: 0, open: 0, wide: 0, rounded: 0, contact: 0, rest: 1 };
    for (const k of VISEMES) {
      this.weights[k] = smoothTowards(this.weights[k], want[k], dt, this.shapeTime);
    }
    return { aperture: this.aperture, weights: this.weights };
  };

  SpeechRig.prototype.closeImmediately = function () {
    this.aperture = 0;
    for (const k of VISEMES) this.weights[k] = k === 'rest' ? 1 : 0;
  };

  // ---------------------------------------------------------------------
  // 4. Eyes and attention
  // ---------------------------------------------------------------------

  function EyeController(opts) {
    const o = opts || {};
    this.random = makeRandom(o.seed == null ? 1337 : o.seed);
    this.minGap = o.minGap == null ? 1.8 : o.minGap;
    this.maxGap = o.maxGap == null ? 6.5 : o.maxGap;
    this.blinkDuration = o.blinkDuration == null ? 0.13 : o.blinkDuration;
    this.timeToBlink = this._nextGap();
    this.blinkPhase = -1;
    this.pendingDouble = false;
    this.lid = 1;            // 1 open, 0 shut
    this.gaze = { x: 0, y: 0 };
    this._target = { x: 0, y: 0 };
    this._holdFor = 0;
  }

  EyeController.prototype._nextGap = function () {
    return this.minGap + this.random() * (this.maxGap - this.minGap);
  };

  EyeController.prototype.update = function (dt, state) {
    // --- blinks -------------------------------------------------------
    if (this.blinkPhase >= 0) {
      this.blinkPhase += dt;
      const t = this.blinkPhase / this.blinkDuration;
      // Down fast, up slower - a symmetric blink looks like a shutter.
      this.lid = t < 0.4 ? 1 - t / 0.4 : clamp01((t - 0.4) / 0.6);
      if (this.blinkPhase >= this.blinkDuration) {
        this.blinkPhase = -1;
        this.lid = 1;
        if (this.pendingDouble) {
          this.pendingDouble = false;
          this.timeToBlink = 0.09 + this.random() * 0.06;
        } else {
          this.timeToBlink = this._nextGap();
        }
      }
    } else {
      this.timeToBlink -= dt;
      if (this.timeToBlink <= 0) {
        this.blinkPhase = 0;
        this.pendingDouble = this.random() < 0.18;
      }
    }

    // --- gaze ---------------------------------------------------------
    this._holdFor -= dt;
    if (this._holdFor <= 0) {
      if (state === 'SPEAKING') {
        // Hold the camera, with only enough drift to avoid a dead stare.
        this._target.x = (this.random() - 0.5) * 0.10;
        this._target.y = (this.random() - 0.5) * 0.07;
        this._holdFor = 0.7 + this.random() * 1.1;
      } else if (state === 'THINKING') {
        // Look away and up - the gesture that reads as working something out.
        this._target.x = (this.random() < 0.5 ? -1 : 1) * (0.35 + this.random() * 0.3);
        this._target.y = -0.25 - this.random() * 0.25;
        this._holdFor = 0.9 + this.random() * 1.2;
      } else if (state === 'LISTENING') {
        this._target.x = (this.random() - 0.5) * 0.24;
        this._target.y = (this.random() - 0.5) * 0.14;
        this._holdFor = 1.1 + this.random() * 1.6;
      } else {
        this._target.x = (this.random() - 0.5) * 0.4;
        this._target.y = (this.random() - 0.5) * 0.22;
        this._holdFor = 1.6 + this.random() * 2.6;
      }
    }
    const tc = state === 'SPEAKING' ? 0.10 : 0.16;
    this.gaze.x = smoothTowards(this.gaze.x, this._target.x, dt, tc);
    this.gaze.y = smoothTowards(this.gaze.y, this._target.y, dt, tc);

    return { lid: this.lid, gaze: { x: this.gaze.x, y: this.gaze.y } };
  };

  // ---------------------------------------------------------------------
  // 5. Head and posture
  // ---------------------------------------------------------------------

  function PostureController(opts) {
    const o = opts || {};
    const rnd = makeRandom(o.seed == null ? 7331 : o.seed);
    this.t = 0;
    this.phases = [rnd() * 6.28, rnd() * 6.28, rnd() * 6.28, rnd() * 6.28];
    this.energy = 0;
    this.breathRate = o.breathRate == null ? 0.22 : o.breathRate;
  }

  const POSTURE_ENERGY = {
    IDLE: 0.35, LISTENING: 0.5, THINKING: 0.45, SPEAKING: 1.0, INTERRUPTED: 0.5,
  };

  PostureController.prototype.update = function (dt, state, speechAperture) {
    this.t += dt;
    const want = POSTURE_ENERGY[state] == null ? 0.4 : POSTURE_ENERGY[state];
    this.energy = smoothTowards(this.energy, want, dt, 0.45);

    // Deliberately slow and small. Anything faster reads as a bobblehead.
    const tilt = wobble(this.t, [0.11, 0.19], [this.phases[0], this.phases[1]]) * 0.035 * this.energy;
    const nod = wobble(this.t, [0.13, 0.27], [this.phases[2], this.phases[3]]) * 0.028 * this.energy;
    const breath = (Math.sin(this.t * this.breathRate * Math.PI * 2) * 0.5 + 0.5);

    // A small amount of speech energy reaches the head, so emphasis carries -
    // but capped, or it becomes a visualiser.
    const emphasis = clamp01(speechAperture || 0) * 0.02;

    return {
      tilt,
      nod: nod - emphasis,
      breath,
      energy: this.energy,
    };
  };

  // ---------------------------------------------------------------------
  // 6. Synthetic detail - non-human, no fake skin
  // ---------------------------------------------------------------------

  function DetailController() {
    this.chamber = 0;
    this.circuit = 0;
    this.pulsePhase = 0;
  }

  DetailController.prototype.update = function (dt, features, state, aperture) {
    const f = features || { energy: 0, flux: 0 };
    const speaking = state === 'SPEAKING';

    // Vocal chamber glows with the jaw, slightly ahead of it.
    const chamberTarget = speaking ? clamp01(aperture * 0.75 + f.energy * 0.45) : 0.06;
    this.chamber = smoothTowards(this.chamber, chamberTarget, dt, speaking ? 0.05 : 0.3);

    // Circuit lines answer consonant onsets rather than volume, so the face
    // does not simply pump in time with loudness.
    this.pulsePhase += dt * (speaking ? 1.4 : 0.35);
    const onset = speaking ? clamp01(f.flux * 1.6) : 0;
    const target = speaking
      ? clamp01(0.22 + onset * 0.65 + Math.sin(this.pulsePhase * 2.1) * 0.06)
      : 0.1 + Math.sin(this.pulsePhase) * 0.04;
    this.circuit = smoothTowards(this.circuit, target, dt, 0.09);

    return { chamber: this.chamber, circuit: this.circuit };
  };

  // ---------------------------------------------------------------------
  // 7. State machine
  // ---------------------------------------------------------------------

  const STATES = ['IDLE', 'LISTENING', 'THINKING', 'SPEAKING', 'INTERRUPTED'];

  function AvatarStateMachine(opts) {
    const o = opts || {};
    this.state = 'IDLE';
    this.previous = 'IDLE';
    this.timeInState = 0;
    this.interruptHold = o.interruptHold == null ? 0.35 : o.interruptHold;
    this.idleAfter = o.idleAfter == null ? 12 : o.idleAfter;
  }

  AvatarStateMachine.prototype.set = function (next) {
    if (STATES.indexOf(next) === -1) return this.state;
    if (next === this.state) return this.state;
    this.previous = this.state;
    this.state = next;
    this.timeInState = 0;
    return this.state;
  };

  AvatarStateMachine.prototype.update = function (dt) {
    this.timeInState += dt;
    // An interruption is a moment, not a mode: it exists so the mouth shuts
    // instantly, then hands over to listening.
    if (this.state === 'INTERRUPTED' && this.timeInState >= this.interruptHold) {
      this.set('LISTENING');
    } else if (this.state === 'LISTENING' && this.timeInState >= this.idleAfter) {
      this.set('IDLE');
    }
    return this.state;
  };

  // ---------------------------------------------------------------------
  // 8. The rig
  // ---------------------------------------------------------------------

  function AvatarRig(opts) {
    const o = opts || {};
    this.speech = new SpeechRig(o.speech);
    this.eyes = new EyeController(Object.assign({ seed: o.seed }, o.eyes));
    this.posture = new PostureController(Object.assign({ seed: (o.seed || 0) + 11 }, o.posture));
    this.detail = new DetailController();
    this.machine = new AvatarStateMachine(o.machine);
    this.pose = null;
  }

  AvatarRig.prototype.setState = function (next) {
    const before = this.machine.state;
    const now = this.machine.set(next);
    if (now === 'INTERRUPTED' && before !== 'INTERRUPTED') this.speech.closeImmediately();
    return now;
  };

  AvatarRig.prototype.update = function (dt, features) {
    const step = clamp(dt, 0, 0.1); // a backgrounded tab must not teleport the rig
    const state = this.machine.update(step);
    const speaking = state === 'SPEAKING';
    const speech = this.speech.update(features, step, speaking);
    const eyes = this.eyes.update(step, state);
    const posture = this.posture.update(step, state, speech.aperture);
    const detail = this.detail.update(step, features, state, speech.aperture);

    this.pose = {
      state,
      aperture: speech.aperture,
      visemes: speech.weights,
      dominantViseme: dominant(speech.weights),
      lid: eyes.lid,
      gaze: eyes.gaze,
      tilt: posture.tilt,
      nod: posture.nod,
      breath: posture.breath,
      energy: posture.energy,
      chamber: detail.chamber,
      circuit: detail.circuit,
    };
    return this.pose;
  };

  function dominant(weights) {
    let best = 'rest', bestValue = -1;
    for (const k of VISEMES) {
      if (weights[k] > bestValue) { bestValue = weights[k]; best = k; }
    }
    return best;
  }

  /* How much of the mouth's movement is shape change rather than opening.
   * A scale-only rig scores ~0 here; this is the number that says whether the
   * rig is actually doing what it claims. */
  function shapeVariety(samples) {
    if (!samples || samples.length < 2) return 0;
    let changed = 0;
    const seen = Object.create(null);
    for (let i = 0; i < samples.length; i++) {
      const d = samples[i].dominantViseme;
      seen[d] = true;
      if (i > 0 && samples[i - 1].dominantViseme !== d) changed++;
    }
    return {
      distinctVisemes: Object.keys(seen).length,
      transitions: changed,
      transitionsPerSecond: 0,
      visemesSeen: Object.keys(seen),
    };
  }

  return {
    VISEMES,
    STATES,
    clamp01,
    lerp,
    smoothTowards,
    makeRandom,
    wobble,
    analyseFrame,
    solveVisemeWeights,
    SpeechRig,
    EyeController,
    PostureController,
    DetailController,
    AvatarStateMachine,
    AvatarRig,
    dominant,
    shapeVariety,
  };
});
