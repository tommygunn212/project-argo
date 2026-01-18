#!/usr/bin/env python3
"""
ARGO App Server Launcher
Starts and keeps the app running
"""

import sys
import os
from pathlib import Path

# Add input_shell to path
sys.path.insert(0, str(Path(__file__).parent / "input_shell"))

# Change to input_shell directory
os.chdir(Path(__file__).parent / "input_shell")

# Import and run
import uvicorn
from app import app

if __name__ == "__main__":
    print("\n" + "="*80)
    print("ARGO INPUT SHELL (v1.4.2) - SERVER RUNNING")
    print("="*80)
    print("\nStarting server on http://127.0.0.1:8000")
    print("Press Ctrl+C to stop\n")
    
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
