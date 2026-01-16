#!/usr/bin/env python3
"""Task 1: Targeted Regression Tests

Confirm UUID fix did not accidentally loosen or tighten anything else.
"""

import subprocess
import json
from pathlib import Path

queue_dir = Path('intent_queue')
queue_dir.mkdir(exist_ok=True)
approved = queue_dir / 'approved.jsonl'
executed = queue_dir / 'executed.jsonl'

def reset():
    """Reset state."""
    lower_uuid = 'abcdef01-2345-6789-abcd-ef0123456789'
    lower_hash = 'd74524813b020264d5ad0234abc5678d9c0e1a2b3c4d5e6f7a8b9c0d1e2f3a4b'
    with open(approved, 'w') as f:
        f.write(json.dumps({'id': lower_uuid, 'timestamp': '2026-01-15T10:00:00Z', 'hash': lower_hash}) + '\n')
    if executed.exists():
        executed.unlink()
    return lower_uuid, lower_hash

results = []

print("="*70)
print("TASK 1: TARGETED REGRESSION")
print("="*70)
print()

# UUID CANONICALITY SWEEP
print("="*70)
print("1A: UUID CANONICALITY SWEEP")
print("="*70)

lower_uuid, lower_hash = reset()

# Test 1a.1: Lowercase UUID (should work)
print("\n1A.1: Lowercase UUID → allowed")
r = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', lower_uuid, '--hash', lower_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'test'})
], capture_output=True, text=True)
passed = r.returncode == 0 and "executing tool" in r.stdout.lower()
print(f'Exit: {r.returncode}, Executed: {passed}')
print(f'Result: {"✓ PASS" if passed else "✗ FAIL"}')
results.append(('1A.1-lowercase', passed))
reset()

# Test 1a.2: Uppercase UUID (should fail)
print("\n1A.2: Uppercase UUID → denied")
upper_uuid = lower_uuid.upper()
r = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', upper_uuid, '--hash', lower_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'test'})
], capture_output=True, text=True)
passed = r.returncode == 1 and "invalid" in r.stdout.lower()
print(f'Exit: {r.returncode}, Error: {"YES" if "invalid" in r.stdout.lower() else "NO"}')
print(f'Result: {"✓ PASS" if passed else "✗ FAIL"}')
results.append(('1A.2-uppercase', passed))
reset()

# Test 1a.3: Mixed case UUID (should fail)
print("\n1A.3: Mixed case UUID → denied")
mixed_uuid = 'ABCDEF01-2345-6789-abcd-ef0123456789'
r = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', mixed_uuid, '--hash', lower_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'test'})
], capture_output=True, text=True)
passed = r.returncode == 1 and "invalid" in r.stdout.lower()
print(f'Exit: {r.returncode}, Error: {"YES" if "invalid" in r.stdout.lower() else "NO"}')
print(f'Result: {"✓ PASS" if passed else "✗ FAIL"}')
results.append(('1A.3-mixed', passed))
reset()

# Test 1a.4: Valid structure but wrong length (should fail)
print("\n1A.4: Valid structure, wrong length → denied")
bad_length_uuid = 'abcdef01-2345-6789-abcd-ef012345678'  # 35 chars instead of 36
r = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', bad_length_uuid, '--hash', lower_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'test'})
], capture_output=True, text=True)
passed = r.returncode == 1 and "invalid" in r.stdout.lower()
print(f'Exit: {r.returncode}, Error: {"YES" if "invalid" in r.stdout.lower() else "NO"}')
print(f'Result: {"✓ PASS" if passed else "✗ FAIL"}')
results.append(('1A.4-length', passed))

# REPLAY INTEGRITY RECHECK
print("\n" + "="*70)
print("1B: REPLAY INTEGRITY RECHECK")
print("="*70)

lower_uuid, lower_hash = reset()

# Test 1b.1: Lowercase first run → success + record
print("\n1B.1: Lowercase UUID first run → success + record")
r1 = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', lower_uuid, '--hash', lower_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'run1'})
], capture_output=True, text=True)
passed1 = r1.returncode == 0 and executed.exists()
print(f'Exit: {r1.returncode}, Recorded: {executed.exists()}')
print(f'Result: {"✓ PASS" if passed1 else "✗ FAIL"}')
results.append(('1B.1-first-run', passed1))

# Test 1b.2: Same lowercase UUID second run → replay denied
print("\n1B.2: Same lowercase UUID second run → replay denied")
r2 = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', lower_uuid, '--hash', lower_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'run2'})
], capture_output=True, text=True)
passed2 = r2.returncode == 1
print(f'Exit: {r2.returncode}')
print(f'Result: {"✓ PASS" if passed2 else "✗ FAIL"}')
results.append(('1B.2-replay-denied', passed2))

# Test 1b.3: Uppercase variant of same UUID → denied before replay logic
print("\n1B.3: Uppercase variant of same UUID → denied (before replay logic)")
upper_uuid = lower_uuid.upper()
r3 = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', upper_uuid, '--hash', lower_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'run3'})
], capture_output=True, text=True)
passed3 = r3.returncode == 1 and "invalid" in r3.stdout.lower()
print(f'Exit: {r3.returncode}, Error: {"YES" if "invalid" in r3.stdout.lower() else "NO"}')
print(f'Result: {"✓ PASS" if passed3 else "✗ FAIL"}')
results.append(('1B.3-uppercase-variant', passed3))

# DRY-RUN SANITY
print("\n" + "="*70)
print("1C: DRY-RUN SANITY")
print("="*70)

lower_uuid, lower_hash = reset()

# Test 1c.1: Lowercase UUID + dry-run → no execution, no record
print("\n1C.1: Lowercase UUID + dry-run → no execution, no record")
r = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', lower_uuid, '--hash', lower_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'dry'}),
    '--dry-run'
], capture_output=True, text=True)
passed = r.returncode == 0 and not executed.exists()
print(f'Exit: {r.returncode}, Recorded: {executed.exists()}')
print(f'Result: {"✓ PASS" if passed else "✗ FAIL"}')
results.append(('1C.1-dry-run-lowercase', passed))

# Test 1c.2: Uppercase UUID + dry-run → denied (validation before dry-run)
print("\n1C.2: Uppercase UUID + dry-run → denied")
upper_uuid = lower_uuid.upper()
r = subprocess.run([
    'python', 'argo_tool_execute.py',
    '--intent-id', upper_uuid, '--hash', lower_hash,
    '--tool', 'echo_text', '--args', json.dumps({'text': 'dry'}),
    '--dry-run'
], capture_output=True, text=True)
passed = r.returncode == 1 and "invalid" in r.stdout.lower()
print(f'Exit: {r.returncode}, Error: {"YES" if "invalid" in r.stdout.lower() else "NO"}')
print(f'Result: {"✓ PASS" if passed else "✗ FAIL"}')
results.append(('1C.2-dry-run-uppercase', passed))

# SUMMARY
print("\n" + "="*70)
print("REGRESSION SUMMARY")
print("="*70)
for name, passed in results:
    status = '✓ PASS' if passed else '✗ FAIL'
    print(f'{name}: {status}')

all_pass = all(p for _, p in results)
print()
if all_pass:
    print("✓ ALL REGRESSION TESTS PASSED - NO UNINTENDED CHANGES")
else:
    print("✗ REGRESSION FAILURE - STOP HERE")
    import sys
    sys.exit(1)
