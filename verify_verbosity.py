#!/usr/bin/env python3
"""Verification script to show last 3 log entries with verbosity and persona."""

import json
from pathlib import Path

log_file = Path('logs/2026-01-11.log')
if log_file.exists():
    with open(log_file) as f:
        lines = f.readlines()[-3:]
    
    print('\n=== Last 3 Log Entries (Verbosity & Persona) ===\n')
    for i, line in enumerate(lines, 1):
        entry = json.loads(line)
        user_preview = entry['user_prompt'][:50]
        verb = entry['verbosity']
        pers = entry['persona']
        print(f"Entry {i}:")
        print(f"  User: {user_preview}...")
        print(f"  Verbosity: {verb}")
        print(f"  Persona: {pers}")
        print()
else:
    print("Log file not found!")
