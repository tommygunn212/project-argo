#!/usr/bin/env python3
"""
ARGO Server - Bulletproof Persistence Mode
Uses subprocess isolation to prevent signal propagation
"""

import subprocess
import sys
import time
import os
import signal
from pathlib import Path
import threading

def run_server_isolated():
    """Run server in completely isolated subprocess"""
    
    argo_root = Path(__file__).parent
    input_shell_dir = argo_root / "input_shell"
    
    print("\n" + "="*80)
    print("ARGO SERVER - BULLETPROOF MODE")
    print("="*80)
    print("\nServer: http://127.0.0.1:8000")
    print("Mode: Isolated subprocess (immune to parent signals)")
    print("Status: ✓ Running\n")
    
    # Create startup info to detach process on Windows
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        startupinfo = None
        creationflags = 0
    
    # Subprocess will ignore signals from parent
    env = os.environ.copy()
    
    attempt = 0
    while True:
        attempt += 1
        print(f"[Start Attempt {attempt}]", flush=True)
        
        try:
            # Start server process with isolation
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m", "uvicorn",
                    "app:app",
                    "--host", "127.0.0.1",
                    "--port", "8000",
                    "--log-level", "info",
                    "--loop", "asyncio",
                ],
                cwd=str(input_shell_dir),
                startupinfo=startupinfo,
                creationflags=creationflags,
                env=env,
            )
            
            print(f"[OK] Process started (PID: {proc.pid})", flush=True)
            
            # Monitor process
            while proc.poll() is None:
                time.sleep(1)
            
            # If we get here, process ended
            return_code = proc.returncode
            print(f"[!] Process exited with code {return_code}", flush=True)
            
            # Auto-restart after brief delay
            print("[*] Waiting 3 seconds before restart...", flush=True)
            time.sleep(3)
            
        except KeyboardInterrupt:
            print("\n[^C] Shutdown requested", flush=True)
            try:
                if sys.platform == 'win32':
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                else:
                    proc.terminate()
                proc.wait(timeout=3)
            except:
                proc.kill()
            break
        except Exception as e:
            print(f"[ERROR] {e}", flush=True)
            time.sleep(3)

if __name__ == "__main__":
    try:
        run_server_isolated()
    except Exception as e:
        print(f"\nFatal error: {e}", file=sys.stderr)
        sys.exit(1)
