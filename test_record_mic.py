#!/usr/bin/env python3
"""Test record_mic.py by simulating user input."""

import sys
import subprocess
from pathlib import Path
from datetime import datetime
import time

# Create input sequence:
# 1. User types "record"
# 2. Wait 2 seconds (recording happens)
# 3. User types "stop"

input_sequence = "record\nstop\n"

print("\n" + "=" * 70)
print("TEST: record_mic.py with simulated input")
print("=" * 70)
print(f"Input sequence: {repr(input_sequence)}")
print()

try:
    # Run script with piped input
    process = subprocess.Popen(
        [sys.executable, "record_mic.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(Path(__file__).parent)
    )
    
    # Send input and close stdin
    stdout, stderr = process.communicate(input=input_sequence, timeout=15)
    
    # Print output
    print("STDOUT:")
    print(stdout)
    
    if stderr:
        print("\nSTDERR:")
        print(stderr)
    
    # Check for audio file
    print("\n" + "-" * 70)
    print("VERIFICATION")
    print("-" * 70)
    
    temp_folder = Path(r"I:\argo\temp")
    audio_files = list(temp_folder.glob("audio_*.wav"))
    
    if audio_files:
        latest_file = sorted(audio_files)[-1]
        file_size = latest_file.stat().st_size
        file_time = datetime.fromtimestamp(latest_file.stat().st_mtime)
        
        print(f"✓ Audio file created: {latest_file.name}")
        print(f"  Path: {latest_file}")
        print(f"  Size: {file_size:,} bytes")
        print(f"  Created: {file_time}")
    else:
        print("✗ No audio file found in temp folder")
    
    print()
    
except subprocess.TimeoutExpired:
    print("ERROR: Process timed out")
    process.kill()
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    sys.exit(1)
