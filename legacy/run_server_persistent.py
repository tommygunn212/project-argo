#!/usr/bin/env python3
"""
ARGO Server - Persistent Mode Wrapper
Auto-restarts server if it crashes or shuts down
"""

import subprocess
import sys
import time
from pathlib import Path

def run_server():
    """Run server in subprocess and auto-restart on failure"""
    
    argo_root = Path(__file__).parent
    input_shell_dir = argo_root / "input_shell"
    
    print("\n" + "="*80)
    print("ARGO SERVER - PERSISTENT MODE")
    print("="*80)
    print("\nServer: http://127.0.0.1:8000")
    print("Mode: Persistent (auto-restarts if terminated)")
    print("Press Ctrl+C to exit\n")
    
    attempt = 0
    while True:
        attempt += 1
        print(f"\n[Attempt {attempt}] Starting server...", flush=True)
        
        try:
            # Run uvicorn directly from input_shell directory
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m", "uvicorn",
                    "app:app",
                    "--host", "127.0.0.1",
                    "--port", "8000",
                    "--log-level", "info"
                ],
                cwd=str(input_shell_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            
            # Stream output
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                print(line.rstrip(), flush=True)
            
            # If we get here, process ended
            return_code = proc.wait()
            print(f"\n[!] Server terminated with code {return_code}", flush=True)
            
            # Wait before restart to avoid rapid failure loops
            print("[*] Waiting 2 seconds before restart...", flush=True)
            time.sleep(2)
            
        except KeyboardInterrupt:
            print("\n\n[^C] Shutdown requested", flush=True)
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except:
                proc.kill()
            break
        except Exception as e:
            print(f"\n[ERROR] {e}", flush=True)
            time.sleep(2)

if __name__ == "__main__":
    try:
        run_server()
    except Exception as e:
        print(f"\nFatal error: {e}", file=sys.stderr)
        sys.exit(1)
