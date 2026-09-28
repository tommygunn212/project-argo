'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const html = fs.readFileSync(
  path.join(__dirname, '..', 'frontend-v2', 'index.html'),
  'utf8',
);

test('Home Assistant status comes from the backend and has honest failure states', () => {
  assert.match(html, /fetch\('\/api\/home-assistant-status'/);
  assert.match(html, /Unavailable — check Home Assistant and the network/);
  assert.match(html, /Not configured — add the URL and token in config\.json/);
  assert.doesNotMatch(html, /172\.31\.109\.193/);
});
