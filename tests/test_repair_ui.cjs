const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require.resolve('../frontend-v2/index.html'), 'utf8');

// Execute actual rendering functions against a tiny DOM; inserted text and
// button handlers are observable without running unrelated audio/WebRTC code.
function harness() {
  class Element {
    constructor() { this.children = []; this.style = {}; this.textContent = ''; }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    set innerHTML(_) { throw Error('Repair rendering must insert untrusted text as text'); }
  }
  const nodes = new Map();
  const sent = [];
  const context = vm.createContext({document: {createElement: () => new Element()},
    $: id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); },
    send: (...args) => sent.push(args), switchPage: () => {}, addSystemLog: () => {}});
  function load(name, next) {
    const start = html.indexOf(`function ${name}(`);
    const end = html.indexOf(next, start);
    assert.ok(start > 0 && end > start);
    vm.runInContext(html.slice(start, end), context);
  }
  load('renderCodeRepairJobs', '\nsetInterval(');
  load('handleCodeRepairProposal', '\nfunction handleCodeRepairResult');
  load('handleRecoveryProposal', '\nfunction handleRecoveryResult');
  return {context, nodes, sent};
}

test('review shows diff, tests and report as literal text and applies exact hash', () => {
  const {context, nodes, sent} = harness();
  const job = {action_id: 'job-1', status: 'review_ready', request: '<img onerror=bad()>',
    message: 'Ready', exit_code: 0, test_exit: 0, changed_files: ['answer.py'],
    diff: '<script>bad()</script>', test_log: '1 passed', report: 'Tested', patch_sha256: 'abc'};
  context.renderCodeRepairJobs([job]);
  const section = nodes.get('codeRepairJobs').children[0];
  assert.ok(section.children[0].textContent.includes(job.request));
  assert.equal(section.children[2].children[1].textContent, job.diff);
  section.children.at(-1).onclick();
  assert.equal(sent[0][0], 'code_repair_apply');
  assert.equal(sent[0][1].patch_sha256, 'abc');
  assert.equal(sent[0][1].approved, true);
});

test('failed job has no apply button and proposals show real scope', () => {
  const {context, nodes} = harness();
  context.renderCodeRepairJobs([{status: 'review_failed', request: 'x', message: 'Tests failed'}]);
  assert.equal(nodes.get('codeRepairJobs').children[0].children.length, 1);
  context.handleRecoveryProposal({proposal_id: 'unique', problem: 'Audio disconnected', proposal: 'Reopen selected audio', command_preview: 'audio.start()'});
  assert.ok(nodes.get('recoveryContent').textContent.includes('Reopen selected audio'));
  context.handleCodeRepairProposal({action_id: 'job', request: 'Fix voice', message: 'Isolated checkout', task_path: 'request.md'});
  assert.ok(nodes.get('codeRepairContent').textContent.includes('Fix voice'));
});
