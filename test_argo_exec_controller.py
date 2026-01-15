#!/usr/bin/env python3
"""Tests for ARGO Execution Controller v0

Five tests proving eligibility enforcement:
1. Approved + not executed → exit 0
2. Approved + already executed → exit 1
3. Not approved → exit 1
4. Missing executed.jsonl → treated as empty, continue
5. Any ambiguity → exit 1
"""

import subprocess
import json
import sys
import os
from pathlib import Path


def run_controller(intent_id, hash_value):
    """Helper: Run controller and return exit code + output"""
    result = subprocess.run(
        [sys.executable, "argo_execution_controller.py", intent_id, hash_value],
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def test_approved_not_executed():
    """TEST 1: Approved + not executed → exit 0"""
    print("\nTEST 1: Approved + not executed → exit 0")

    # Create a clean intent queue directory
    queue_dir = Path("intent_queue")
    queue_dir.mkdir(exist_ok=True)

    # Create approved.jsonl with one approved intent
    test_uuid = "12345678-1234-1234-1234-123456789012"
    test_hash = "d74524813b020264d5ad0234abc5678d9c0e1a2b3c4d5e6f7a8b9c0d1e2f3a4b"

    approved_file = queue_dir / "approved.jsonl"
    with open(approved_file, 'w') as f:
        f.write(json.dumps({"id": test_uuid, "timestamp": "2026-01-15T10:00:00Z", "hash": test_hash}) + "\n")

    # Make sure executed.jsonl doesn't exist (or is empty)
    executed_file = queue_dir / "executed.jsonl"
    if executed_file.exists():
        executed_file.unlink()

    exit_code, stdout, stderr = run_controller(test_uuid, test_hash)

    if exit_code == 0 and "eligible" in stdout.lower():
        print("✓ PASS: Approved + not executed → exit 0")
        return True
    else:
        print(f"✗ FAIL: Expected exit 0, got {exit_code}. Output: {stdout}")
        return False


def test_approved_already_executed():
    """TEST 2: Approved + already executed → exit 1 (replay prevention)"""
    print("\nTEST 2: Approved + already executed → exit 1")

    queue_dir = Path("intent_queue")
    queue_dir.mkdir(exist_ok=True)

    test_uuid = "87654321-4321-4321-4321-210987654321"
    test_hash = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"

    # Create approved.jsonl
    approved_file = queue_dir / "approved.jsonl"
    with open(approved_file, 'w') as f:
        f.write(json.dumps({"id": test_uuid, "timestamp": "2026-01-15T10:00:00Z", "hash": test_hash}) + "\n")

    # Create executed.jsonl with this intent already executed
    executed_file = queue_dir / "executed.jsonl"
    with open(executed_file, 'w') as f:
        f.write(json.dumps({"id": test_uuid, "timestamp": "2026-01-15T11:00:00Z"}) + "\n")

    exit_code, stdout, stderr = run_controller(test_uuid, test_hash)

    if exit_code == 1 and "replay" in stdout.lower():
        print("✓ PASS: Approved + already executed → exit 1")
        return True
    else:
        print(f"✗ FAIL: Expected exit 1 with replay error, got {exit_code}. Output: {stdout}")
        return False


def test_not_approved():
    """TEST 3: Not approved → exit 1"""
    print("\nTEST 3: Not approved → exit 1")

    queue_dir = Path("intent_queue")
    queue_dir.mkdir(exist_ok=True)

    # Create empty approved.jsonl
    approved_file = queue_dir / "approved.jsonl"
    with open(approved_file, 'w') as f:
        pass  # Empty file

    # Try to use intent that's not in approved list
    unknown_uuid = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    unknown_hash = "0000000000000000000000000000000000000000000000000000000000000000"

    exit_code, stdout, stderr = run_controller(unknown_uuid, unknown_hash)

    if exit_code == 1 and "not approved" in stdout.lower():
        print("✓ PASS: Not approved → exit 1")
        return True
    else:
        print(f"✗ FAIL: Expected exit 1 with 'not approved', got {exit_code}. Output: {stdout}")
        return False


def test_missing_executed_jsonl():
    """TEST 4: Missing executed.jsonl → treated as empty, continue"""
    print("\nTEST 4: Missing executed.jsonl → treated as empty, continue")

    queue_dir = Path("intent_queue")
    queue_dir.mkdir(exist_ok=True)

    test_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    test_hash = "1111111111111111111111111111111111111111111111111111111111111111"

    # Create approved.jsonl
    approved_file = queue_dir / "approved.jsonl"
    with open(approved_file, 'w') as f:
        f.write(json.dumps({"id": test_uuid, "timestamp": "2026-01-15T10:00:00Z", "hash": test_hash}) + "\n")

    # Make sure executed.jsonl does NOT exist
    executed_file = queue_dir / "executed.jsonl"
    if executed_file.exists():
        executed_file.unlink()

    exit_code, stdout, stderr = run_controller(test_uuid, test_hash)

    if exit_code == 0 and "eligible" in stdout.lower():
        print("✓ PASS: Missing executed.jsonl → treated as empty, approved intent eligible")
        return True
    else:
        print(f"✗ FAIL: Expected exit 0 when executed.jsonl missing, got {exit_code}. Output: {stdout}")
        return False


def test_ambiguity_malformed_hash():
    """TEST 5: Any ambiguity (bad hash format) → exit 1"""
    print("\nTEST 5: Any ambiguity (bad hash format) → exit 1")

    queue_dir = Path("intent_queue")
    queue_dir.mkdir(exist_ok=True)

    # Create approved.jsonl with valid UUID
    test_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    test_hash = "2222222222222222222222222222222222222222222222222222222222222222"

    approved_file = queue_dir / "approved.jsonl"
    with open(approved_file, 'w') as f:
        f.write(json.dumps({"id": test_uuid, "timestamp": "2026-01-15T10:00:00Z", "hash": test_hash}) + "\n")

    # Try with malformed hash (too short)
    bad_hash = "tooshort"

    exit_code, stdout, stderr = run_controller(test_uuid, bad_hash)

    if exit_code == 1:
        print("✓ PASS: Malformed hash → exit 1")
        return True
    else:
        print(f"✗ FAIL: Expected exit 1 for bad hash, got {exit_code}. Output: {stdout}")
        return False


def main():
    print("=" * 70)
    print("ARGO EXECUTION CONTROLLER v0 - TEST SUITE")
    print("=" * 70)

    results = []

    results.append(test_approved_not_executed())
    results.append(test_approved_already_executed())
    results.append(test_not_approved())
    results.append(test_missing_executed_jsonl())
    results.append(test_ambiguity_malformed_hash())

    print("\n" + "=" * 70)
    print(f"RESULTS: {sum(results)}/{len(results)} tests passed")
    print("=" * 70)

    if all(results):
        print("\n✓ ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("\n✗ SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
