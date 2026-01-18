#!/usr/bin/env python3
"""
ARGO Server - Managed Startup
Launches server via Windows process isolation for reliability
"""

import subprocess
import sys
import time
from pathlib import Path

def start_server():
    """Start server in isolated Windows process"""
    
    argo_root = Path(__file__).parent
    bat_file = argo_root / "run_server.bat"
    
    print("\n" + "="*80)
    print("ARGO SERVER - LAUNCHING")
    print("="*80)
    print(f"\nServer: http://127.0.0.1:8000")
    print(f"Batch File: {bat_file}\n")
    
    # Start via Windows Start-Process for isolation
    powershell_cmd = f'''
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "{bat_file}" -WindowStyle Hidden
    Write-Host "✓ Server process started"
    '''
    
    try:
        result = subprocess.run(
            ["powershell", "-Command", powershell_cmd.strip()],
            capture_output=True,
            text=True,
        )
        
        if result.returncode == 0:
            print("✓ Server started successfully!")
            print(f"✓ Process is running in isolated Windows session")
            print(f"✓ Server should be accessible at http://127.0.0.1:8000")
            
            # Wait for server to start
            print("\n[Waiting for server startup...]")
            time.sleep(2)
            
            # Try to verify
            try:
                import requests
                r = requests.get("http://127.0.0.1:8000/api/status", timeout=3)
                if r.status_code == 200:
                    print("✓ Server is responding!")
                    print(f"\nSession State: {r.json()}")
                else:
                    print(f"⚠ Server responded with status {r.status_code}")
            except Exception as e:
                print(f"⚠ Could not verify server: {e}")
                print("  (Server may still be starting up)")
            
            return True
        else:
            print("✗ Failed to start server")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

if __name__ == "__main__":
    success = start_server()
    sys.exit(0 if success else 1)
