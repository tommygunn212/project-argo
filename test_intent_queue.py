#!/usr/bin/env python3
"""Test intent queue and review system."""

import subprocess
import sys
import json
from pathlib import Path
import shutil


def cleanup_queue():
    """Delete intent_queue directory if it exists."""
    queue_dir = Path(__file__).parent / "intent_queue"
    if queue_dir.exists():
        shutil.rmtree(queue_dir)
        print(f"[CLEANUP] Removed {queue_dir}")


def test_queue_normal():
    """Test normal intent queuing."""
    print("\n" + "=" * 70)
    print("TEST 1: Queue normal intent")
    print("=" * 70)
    print()
    
    result = subprocess.run(
        [sys.executable, "intent_queue.py", "Turn on the lights"],
        capture_output=True,
        text=True
    )
    
    print("STDOUT:")
    print(result.stdout)
    print(f"Exit code: {result.returncode}")
    
    if result.returncode == 0:
        print("[PASS] Queued successfully")
    else:
        print("[FAIL] Expected exit 0")
    print()


def test_queue_empty():
    """Test queuing with no input."""
    print("=" * 70)
    print("TEST 2: Queue empty intent")
    print("=" * 70)
    print()
    
    result = subprocess.run(
        [sys.executable, "intent_queue.py"],
        input="",
        capture_output=True,
        text=True
    )
    
    print("STDERR:")
    print(result.stderr)
    print(f"Exit code: {result.returncode}")
    
    if result.returncode == 1:
        print("[PASS] Rejected empty input")
    else:
        print("[FAIL] Expected exit 1")
    print()


def test_queue_multiple():
    """Test queuing multiple intents."""
    print("=" * 70)
    print("TEST 3: Queue multiple intents")
    print("=" * 70)
    print()
    
    intents = ["Turn on the lights", "Set temperature to 72", "Close the door"]
    
    for intent in intents:
        result = subprocess.run(
            [sys.executable, "intent_queue.py", intent],
            capture_output=True,
            text=True
        )
        print(f"[{result.returncode}] {intent}")
    
    # Check pending.jsonl
    pending_file = Path(__file__).parent / "intent_queue" / "pending.jsonl"
    if pending_file.exists():
        with open(pending_file, "r") as f:
            lines = f.readlines()
        print(f"\n[OK] Queued {len(lines)} intents in pending.jsonl")
        for i, line in enumerate(lines[:2], 1):
            record = json.loads(line)
            print(f"  [{i}] {record['id'][:8]}... hash={record['hash'][:16]}...")
    print()


def test_review_no_approval():
    """Test review without approving."""
    print("=" * 70)
    print("TEST 4: Review without approval")
    print("=" * 70)
    print()
    
    # Queue an intent first
    subprocess.run(
        [sys.executable, "intent_queue.py", "Delete something"],
        capture_output=True
    )
    
    # Review without approving
    result = subprocess.run(
        [sys.executable, "intent_review.py"],
        input="\n",  # Just press Enter
        capture_output=True,
        text=True
    )
    
    print("STDOUT:")
    print(result.stdout)
    print(f"Exit code: {result.returncode}")
    
    # Check approved.jsonl does NOT exist yet
    approved_file = Path(__file__).parent / "intent_queue" / "approved.jsonl"
    if not approved_file.exists():
        print("[PASS] No approvals created")
    else:
        # If it exists, it should be empty
        with open(approved_file, "r") as f:
            lines = [l for l in f.readlines() if l.strip()]
        if not lines:
            print("[PASS] Approved file exists but empty")
        else:
            print("[FAIL] Approved file has content")
    print()


def test_review_with_approval():
    """Test review with approval."""
    print("=" * 70)
    print("TEST 5: Review with approval")
    print("=" * 70)
    print()
    
    # Clean up and start fresh
    cleanup_queue()
    
    # Queue an intent
    queue_result = subprocess.run(
        [sys.executable, "intent_queue.py", "Turn on the lights"],
        capture_output=True,
        text=True
    )
    
    # Extract intent ID from output
    intent_id = None
    for line in queue_result.stdout.split("\n"):
        if "Intent queued:" in line:
            intent_id = line.split(": ")[1].strip()
            break
    
    print(f"Queued intent: {intent_id}")
    
    # Review and approve
    review_result = subprocess.run(
        [sys.executable, "intent_review.py"],
        input=intent_id + "\n",
        capture_output=True,
        text=True
    )
    
    print("\nReview output:")
    print(review_result.stdout)
    
    # Check approved.jsonl
    approved_file = Path(__file__).parent / "intent_queue" / "approved.jsonl"
    if approved_file.exists():
        with open(approved_file, "r") as f:
            lines = f.readlines()
        if lines:
            record = json.loads(lines[0])
            if record["id"] == intent_id:
                print(f"[PASS] Intent approved: {intent_id[:8]}...")
            else:
                print("[FAIL] Approved intent ID mismatch")
        else:
            print("[FAIL] Approved file is empty")
    else:
        print("[FAIL] Approved file not created")
    print()


def test_review_invalid_id():
    """Test review with invalid ID."""
    print("=" * 70)
    print("TEST 6: Review with invalid ID")
    print("=" * 70)
    print()
    
    # Queue an intent
    subprocess.run(
        [sys.executable, "intent_queue.py", "Something"],
        capture_output=True
    )
    
    # Try to approve with wrong ID
    result = subprocess.run(
        [sys.executable, "intent_review.py"],
        input="invalid-id-12345\n",
        capture_output=True,
        text=True
    )
    
    print("STDOUT:")
    print(result.stdout)
    print(f"Exit code: {result.returncode}")
    
    if result.returncode == 1:
        print("[PASS] Rejected invalid ID")
    else:
        print("[FAIL] Expected exit 1")
    print()


if __name__ == "__main__":
    try:
        cleanup_queue()
        test_queue_normal()
        test_queue_empty()
        test_queue_multiple()
        test_review_no_approval()
        test_review_with_approval()
        test_review_invalid_id()
        print("=" * 70)
        print("ALL TESTS COMPLETE")
        print("=" * 70)
    finally:
        # Clean up after tests
        cleanup_queue()
