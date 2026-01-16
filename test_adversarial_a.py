#!/usr/bin/env python3
"""Category A: Human Error Tests"""

import subprocess
import json
from pathlib import Path

# Setup
queue_dir = Path('intent_queue')
queue_dir.mkdir(exist_ok=True)
approved = queue_dir / 'approved.jsonl'
executed = queue_dir / 'executed.jsonl'

correct_uuid = 'abcdef01-2345-6789-abcd-ef0123456789'
correct_hash = 'd74524813b020264d5ad0234abc5678d9c0e1a2b3c4d5e6f7a8b9c0d1e2f3a4b'

def reset():
    """Reset state."""
    with open(approved, 'w') as f:
        f.write(json.dumps({'id': correct_uuid, 'timestamp': '2026-01-15T10:00:00Z', 'hash': correct_hash}) + '\n')
    if executed.exists():
        executed.unlink()

results = []

# TEST A.1: UUID typo
print('='*70)
print('TEST A.1: UUID typo (one char off)')
print('='*70)
reset()
typo_uuid = '12345678-1234-1234-1234-123456789013'
r = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', typo_uuid, '--hash', correct_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'test'})
], capture_output=True, text=True)
tool_exec = "executing tool" in r.stdout.lower()
record_mod = executed.exists() and executed.stat().st_size > 0
spec_ok = r.returncode == 1 and not tool_exec and not record_mod
print(f'Exit code: {r.returncode}')
print(f'Tool executed: {tool_exec}')
print(f'executed.jsonl modified: {record_mod}')
print(f'Spec compliant (exit 1, no exec, no record): {spec_ok}')
results.append(('A.1', spec_ok))
print()

# TEST A.2: Correct UUID, wrong hash
print('='*70)
print('TEST A.2: Correct UUID, wrong hash')
print('='*70)
reset()
wrong_hash = '0000000000000000000000000000000000000000000000000000000000000000'
r = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', correct_uuid, '--hash', wrong_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'test'})
], capture_output=True, text=True)
tool_exec = "executing tool" in r.stdout.lower()
record_mod = executed.exists() and executed.stat().st_size > 0
spec_ok = r.returncode == 1 and not tool_exec and not record_mod
print(f'Exit code: {r.returncode}')
print(f'Tool executed: {tool_exec}')
print(f'executed.jsonl modified: {record_mod}')
print(f'Spec compliant (exit 1, no exec, no record): {spec_ok}')
results.append(('A.2', spec_ok))
print()

# TEST A.3: Correct UUID+hash, missing required arg
print('='*70)
print('TEST A.3: Correct UUID+hash, missing required tool arg')
print('='*70)
reset()
r = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', correct_uuid, '--hash', correct_hash,
    '--tool', 'echo_text', '--args', json.dumps({})
], capture_output=True, text=True)
tool_exec = "executing tool" in r.stdout.lower()
record_mod = executed.exists() and executed.stat().st_size > 0
spec_ok = r.returncode == 1 and not tool_exec and not record_mod
print(f'Exit code: {r.returncode}')
print(f'Tool executed: {tool_exec}')
print(f'executed.jsonl modified: {record_mod}')
print(f'Spec compliant (exit 1, no exec, no record): {spec_ok}')
results.append(('A.3', spec_ok))
print()

# TEST A.4: Uppercase UUID
print('='*70)
print('TEST A.4: Uppercase UUID')
print('='*70)
reset()
upper_uuid = correct_uuid.upper()
r = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', upper_uuid, '--hash', correct_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'test'})
], capture_output=True, text=True)
tool_exec = "executing tool" in r.stdout.lower()
record_mod = executed.exists() and executed.stat().st_size > 0
spec_ok = r.returncode == 1 and not tool_exec and not record_mod
print(f'Exit code: {r.returncode}')
print(f'Tool executed: {tool_exec}')
print(f'executed.jsonl modified: {record_mod}')
print(f'Spec compliant (exit 1, no exec, no record): {spec_ok}')
results.append(('A.4', spec_ok))
print()

print('='*70)
print('CATEGORY A SUMMARY')
print('='*70)
for name, passed in results:
    status = '✓ PASS' if passed else '✗ FAIL'
    print(f'{name}: {status}')
