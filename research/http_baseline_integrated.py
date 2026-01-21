#!/usr/bin/env python3
"""
HTTP Baseline with Integrated Server
Starts server in background, runs baseline, captures results
"""

import subprocess
import time
import sys
import requests
import json
from pathlib import Path

def start_server():
    """Start the server in background"""
    print("Starting server...")
    proc = subprocess.Popen(
        [sys.executable, "run_server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(Path.cwd())
    )
    return proc

def wait_for_server(max_attempts=10, wait_between=0.5):
    """Wait for server to be ready"""
    for attempt in range(max_attempts):
        try:
            r = requests.get("http://127.0.0.1:8000/", timeout=1)
            print("[OK] Server ready")
            return True
        except:
            if attempt < max_attempts - 1:
                time.sleep(wait_between)
    return False

def run_baseline():
    """Run the baseline measurement"""
    print("\nRunning baseline collection...")
    import subprocess
    result = subprocess.run(
        [sys.executable, "collect_baseline_measurements.py"],
        capture_output=False,
        text=True
    )
    return result.returncode == 0

def main():
    print("="*70)
    print("HTTP BASELINE WITH INTEGRATED SERVER")
    print("="*70)
    
    # Start server
    server_proc = start_server()
    time.sleep(2)  # Give it a moment to start
    
    try:
        # Wait for server
        if not wait_for_server():
            print("[FAIL] Server failed to start")
            server_proc.terminate()
            return False
        
        # Run baseline
        success = run_baseline()
        
        return success
        
    finally:
        # Stop server
        print("\nStopping server...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        print("[OK] Server stopped")

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
