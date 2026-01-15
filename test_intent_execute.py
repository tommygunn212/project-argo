#!/usr/bin/env python3
"""Test intent execution verifier."""

import subprocess
import sys
import json
from pathlib import Path
import shutil


def cleanup_queue():
    """Clean up intent_queue directory."""
    queue_dir = Path(__file__).parent / "intent_queue"
    if queue_dir.exists():
        shutil.rmtree(queue_dir)


def setup_approved_intent(intent_id: str, intent_hash: str):
    """Create approved.jsonl with a single intent."""
    queue_dir = Path(__file__).parent / "intent_queue"
    queue_dir.mkdir(exist_ok=True)
    
    approved_file = queue_dir / "approved.jsonl"
    record = {"id": intent_id, "timestamp": "2026-01-15T23:30:49Z", "hash": intent_hash}
    
    with open(approved_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def run_execute(intent_id: str, intent_hash: str):
    """Run intent_execute.py with given inputs."""
    result = subprocess.run(
        [sys.executable, "intent_execute.py", intent_id, intent_hash],
        capture_output=True,
        text=True
    )
    return result


def test_valid_approval():
    """Test 1: Valid approval → exit 0"""
    print("\n" + "=" * 70)
    print("TEST 1: Valid approval → exit 0")
    print("=" * 70)
    
    cleanup_queue()
    
    intent_id = "b2831d73-2708-4f50-944b-7b54f11bfbb4"
    intent_hash = "d74524813b020264a1b9e1f35b9c01f2f5cd01233e1f48e0ce5a7f14d8d1a9b0"
    
    setup_approved_intent(intent_id, intent_hash)
    
    result = run_execute(intent_id, intent_hash)
    
    print(f"STDOUT: {result.stdout}")
    print(f"STDERR: {result.stderr}")
    print(f"Exit: {result.returncode}")
    
    if result.returncode == 0 and "[OK]" in result.stdout:
        print("[PASS] Valid approval accepted")
    else:
        print("[FAIL] Expected exit 0 with [OK] message")
    print()


def test_wrong_hash():
    """Test 2: Wrong hash → exit 1"""
    print("=" * 70)
    print("TEST 2: Wrong hash → exit 1")
    print("=" * 70)
    
    cleanup_queue()
    
    intent_id = "b2831d73-2708-4f50-944b-7b54f11bfbb4"
    correct_hash = "d74524813b020264a1b9e1f35b9c01f2f5cd01233e1f48e0ce5a7f14d8d1a9b0"
    wrong_hash = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    
    setup_approved_intent(intent_id, correct_hash)
    
    result = run_execute(intent_id, wrong_hash)
    
    print(f"STDOUT: {result.stdout}")
    print(f"STDERR: {result.stderr}")
    print(f"Exit: {result.returncode}")
    
    if result.returncode == 1 and "[ERROR]" in result.stderr:
        print("[PASS] Wrong hash rejected")
    else:
        print("[FAIL] Expected exit 1 with [ERROR] message")
    print()


def test_unknown_uuid():
    """Test 3: Unknown UUID → exit 1"""
    print("=" * 70)
    print("TEST 3: Unknown UUID → exit 1")
    print("=" * 70)
    
    cleanup_queue()
    
    approved_id = "b2831d73-2708-4f50-944b-7b54f11bfbb4"
    unknown_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    intent_hash = "d74524813b020264a1b9e1f35b9c01f2f5cd01233e1f48e0ce5a7f14d8d1a9b0"
    
    setup_approved_intent(approved_id, intent_hash)
    
    result = run_execute(unknown_id, intent_hash)
    
    print(f"STDOUT: {result.stdout}")
    print(f"STDERR: {result.stderr}")
    print(f"Exit: {result.returncode}")
    
    if result.returncode == 1 and "not in approved queue" in result.stderr:
        print("[PASS] Unknown UUID rejected")
    else:
        print("[FAIL] Expected exit 1 with 'not in approved queue' message")
    print()


def test_malformed_input():
    """Test 4: Malformed input → exit 1"""
    print("=" * 70)
    print("TEST 4: Malformed input → exit 1")
    print("=" * 70)
    
    cleanup_queue()
    
    # Test with invalid UUID
    result = subprocess.run(
        [sys.executable, "intent_execute.py", "not-a-uuid", "d74524813b020264a1b9e1f35b9c01f2f5cd01233e1f48e0ce5a7f14d8d1a9b0"],
        capture_output=True,
        text=True
    )
    
    print(f"STDERR: {result.stderr}")
    print(f"Exit: {result.returncode}")
    
    if result.returncode == 1 and "Invalid intent ID format" in result.stderr:
        print("[PASS] Invalid UUID rejected")
    else:
        print("[FAIL] Expected exit 1 with format error")
    
    # Test with invalid hash
    result = subprocess.run(
        [sys.executable, "intent_execute.py", "b2831d73-2708-4f50-944b-7b54f11bfbb4", "not-a-hash"],
        capture_output=True,
        text=True
    )
    
    print(f"STDERR: {result.stderr}")
    print(f"Exit: {result.returncode}")
    
    if result.returncode == 1 and "Invalid hash format" in result.stderr:
        print("[PASS] Invalid hash rejected")
    else:
        print("[FAIL] Expected exit 1 with format error")
    print()


def test_missing_file():
    """Test 5: Missing file → exit 1"""
    print("=" * 70)
    print("TEST 5: Missing file → exit 1")
    print("=" * 70)
    
    cleanup_queue()
    
    intent_id = "b2831d73-2708-4f50-944b-7b54f11bfbb4"
    intent_hash = "d74524813b020264a1b9e1f35b9c01f2f5cd01233e1f48e0ce5a7f14d8d1a9b0"
    
    result = run_execute(intent_id, intent_hash)
    
    print(f"STDERR: {result.stderr}")
    print(f"Exit: {result.returncode}")
    
    if result.returncode == 1 and "not initialized" in result.stderr:
        print("[PASS] Missing file rejected")
    else:
        print("[FAIL] Expected exit 1 with 'not initialized' message")
    print()


if __name__ == "__main__":
    try:
        test_valid_approval()
        test_wrong_hash()
        test_unknown_uuid()
        test_malformed_input()
        test_missing_file()
        
        print("=" * 70)
        print("ALL TESTS COMPLETE")
        print("=" * 70)
    finally:
        cleanup_queue()
