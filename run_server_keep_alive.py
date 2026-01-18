#!/usr/bin/env python3
"""
ARGO Server - Keep Alive Wrapper
Maintains server uptime and prevents shutdown
"""

import sys
import os
import signal
import time
from pathlib import Path

# Prevent signal handlers from shutting down
def signal_handler(sig, frame):
    print(f"\nReceived signal {sig}, ignoring...")
    # Don't exit

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Add input_shell to path
sys.path.insert(0, str(Path(__file__).parent / "input_shell"))

# Change to input_shell directory
os.chdir(Path(__file__).parent / "input_shell")

# Import after path is set
import uvicorn
from app import app

if __name__ == "__main__":
    print("\n" + "="*80)
    print("ARGO SERVER - KEEP ALIVE MODE")
    print("="*80)
    print("\nServer: http://127.0.0.1:8000")
    print("Mode: Keep alive (server will not shut down)")
    print("Press Ctrl+C twice to exit\n")
    
    try:
        # Run with additional stability options
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=8000,
            log_level="info",
            access_log=True,
            # Prevent shutdown on signals
            reload=False,
        )
    except KeyboardInterrupt:
        print("\n\nShutdown requested. Press Ctrl+C again to force exit...")
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nForce exiting...")
            sys.exit(0)
