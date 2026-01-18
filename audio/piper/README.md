"""
================================================================================
PIPER TTS INSTALLATION SETUP
================================================================================

Version: 1.2.0 (Pinned)
Platform: Windows x64
Installation Scope: Local to ARGO repository (no global installation)

================================================================================
STATUS
================================================================================

This directory structure is ready to receive the Piper v1.2.0 binary.

Directory Structure:
  audio/piper/              ← Binary location
  audio/piper/voices/       ← Voice models location
  audio/piper/piper.exe     ← Will be the actual binary (currently stub)

================================================================================
MANUAL INSTALLATION STEPS
================================================================================

Step 1: Download Piper v1.2.0 Binary
  
  URL: https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_windows_amd64.exe
  
  Command (using curl):
    curl -L -o audio/piper/piper.exe ^
      "https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_windows_amd64.exe"
  
  Or download manually and place at: audio/piper/piper.exe
  
  Do NOT rename the executable.
  Do NOT move it elsewhere.

Step 2: Download Voice Model
  
  Recommended: en_US-lessac-medium.onnx
  
  URL: https://github.com/rhasspy/piper/releases/download/v1.2.0/en_US-lessac-medium.onnx
  
  Command (using curl):
    curl -L -o audio/piper/voices/en_US-lessac-medium.onnx ^
      "https://github.com/rhasspy/piper/releases/download/v1.2.0/en_US-lessac-medium.onnx"
  
  Or download manually and place at: audio/piper/voices/en_US-lessac-medium.onnx

Step 3: Verify Installation
  
  From repo root:
    audio\piper\piper.exe --help
  
  Expected output:
    - Help text prints
    - Process exits cleanly (exit code 0)
    - No crashes or errors

================================================================================
PINNED CONFIGURATION
================================================================================

DO NOT change:
  - Piper version (locked at 1.2.0)
  - Binary location (must be audio/piper/piper.exe)
  - Voice model location (must be audio/piper/voices/)
  
DO NOT upgrade automatically:
  - Any upgrades require explicit decision and testing
  - No auto-update mechanisms
  - Manual version bump only via code change

================================================================================
USAGE
================================================================================

From Python:
  import subprocess
  result = subprocess.run([
      'audio/piper/piper.exe',
      '--model', 'audio/piper/voices/en_US-lessac-medium.onnx',
      '--output-raw'
  ], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

From Command Line:
  audio\piper\piper.exe --help

================================================================================
NOTES
================================================================================

- This is Windows x64 only
- Piper requires no system dependencies (statically linked)
- Audio output requires platform-specific audio drivers (handled by Piper)
- Model is ~40 MB (medium-sized)
- Binary is ~65 MB

================================================================================
TROUBLESHOOTING
================================================================================

If piper.exe --help fails:

1. Check file exists and is executable:
   dir audio\piper\piper.exe

2. Verify it's the correct binary (v1.2.0, Windows x64):
   wsl file audio/piper/piper.exe  # If WSL available
   
3. Check for corrupted download:
   certutil -hashfile audio\piper\piper.exe SHA256
   (Compare with GitHub release)

4. Ensure file permissions allow execution:
   Right-click → Properties → Unblock (if Windows blocks it)

================================================================================
UPGRADE POLICY
================================================================================

To upgrade Piper:

1. Create a decision record (e.g., DECISION_PIPER_UPGRADE_X_Y_Z.md)
2. Document testing results
3. Update this README with new version
4. Commit and push to git
5. No silent upgrades

================================================================================
"""
