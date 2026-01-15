#!/usr/bin/env python3
"""Test voice_confirm.py"""

import subprocess
import sys

def test_yes():
    """Test with 'yes' response."""
    print("Test 1: Normal confirmation (yes)")
    result = subprocess.run(
        [sys.executable, "voice_confirm.py"],
        input="Turn on the lights\nyes\n",
        capture_output=True,
        text=True
    )
    
    print("STDOUT:")
    print(result.stdout)
    print(f"Exit code: {result.returncode}")
    
    if result.returncode == 0:
        print("[PASS] Returned exit code 0")
    else:
        print("[FAIL] Expected exit code 0")
    print()


def test_no():
    """Test with 'no' response."""
    print("Test 2: Denial (no)")
    result = subprocess.run(
        [sys.executable, "voice_confirm.py"],
        input="Delete all files\nno\n",
        capture_output=True,
        text=True
    )
    
    print("STDOUT:")
    print(result.stdout)
    print(f"Exit code: {result.returncode}")
    
    if result.returncode == 1:
        print("[PASS] Returned exit code 1")
    else:
        print("[FAIL] Expected exit code 1")
    print()


def test_empty():
    """Test with empty input."""
    print("Test 3: Empty input")
    result = subprocess.run(
        [sys.executable, "voice_confirm.py"],
        input="",
        capture_output=True,
        text=True
    )
    
    print("STDOUT:")
    print(result.stdout)
    print("STDERR:")
    print(result.stderr)
    print(f"Exit code: {result.returncode}")
    
    if result.returncode == 1:
        print("[PASS] Returned exit code 1")
    else:
        print("[FAIL] Expected exit code 1")
    print()


def test_random_response():
    """Test with random response."""
    print("Test 4: Random response (maybe)")
    result = subprocess.run(
        [sys.executable, "voice_confirm.py"],
        input="Do something\nmaybe\n",
        capture_output=True,
        text=True
    )
    
    print("STDOUT:")
    print(result.stdout)
    print(f"Exit code: {result.returncode}")
    
    if result.returncode == 1:
        print("[PASS] Returned exit code 1")
    else:
        print("[FAIL] Expected exit code 1")
    print()


if __name__ == "__main__":
    test_yes()
    test_no()
    test_empty()
    test_random_response()
