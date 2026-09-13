const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { Envelope } = require('../frontend-v2/assets/cortana-avatar.js');

test('mouth stays closed in silence and below the noise floor', () => {
  const e = new Envelope();
  for (let i=0;i<100;i++) assert.equal(e.update(0.007,0.033),0);
});

test('speech opens mouth promptly and silence closes it without a fake pulse', () => {
  const e = new Envelope();
  for (let i=0;i<4;i++) e.update(0.15,0.033);
  assert.ok(e.value > 0.7);
  for (let i=0;i<25;i++) e.update(0,0.033);
  assert.equal(e.value,0);
});

test('invalid audio and frame deltas cannot produce an invalid morph', () => {
  const e = new Envelope();
  for (const [rms,dt] of [[NaN,0.033],[Infinity,0.033],[-2,-1],[0.9,Infinity],[0,1]]) {
    assert.ok(Number.isFinite(e.update(rms,dt)));
    assert.ok(e.value>=0 && e.value<=1);
  }
});

test('all command center inline scripts compile', () => {
  const html=fs.readFileSync(require.resolve('../frontend-v2/index.html'),'utf8');
  for(const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
    new vm.Script(match[1]);
  }
  assert.ok(!html.includes('<video class="avatar-generated"'));
  assert.ok(html.includes('configureLocalAvatarMedia'));
  assert.ok(html.includes('has-local-media'));
  assert.ok(html.includes('.avatar-hud span:first-child'));
  assert.ok(html.includes('<script src="/v2-assets/livekit-client.umd.js"></script>'));
  assert.ok(!html.includes('loadBundledLiveKitClient'));
  assert.ok(!html.includes('document.write(`<script src="${base}/v2-assets/livekit-client.umd.js">'));
});
