# ARGO AUDIO DEBUGGING CHECKLIST
# ============================================================================
# Follow these steps in order to identify where audio is failing

# STEP 1: Check Configuration Flags
# ============================================================================
print("=== STEP 1: Configuration Flags ===")

import os
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "false").lower() == "true"
PIPER_ENABLED = os.getenv("PIPER_ENABLED", "false").lower() == "true"

print(f"VOICE_ENABLED={VOICE_ENABLED}")
print(f"PIPER_ENABLED={PIPER_ENABLED}")

if not VOICE_ENABLED:
    print("❌ VOICE_ENABLED is FALSE - audio disabled entirely")
    print("   FIX: Set environment variable VOICE_ENABLED=true")

if VOICE_ENABLED and not PIPER_ENABLED:
    print("❌ PIPER_ENABLED is FALSE - using silent sink")
    print("   FIX: Set environment variable PIPER_ENABLED=true")

if VOICE_ENABLED and PIPER_ENABLED:
    print("✓ Both flags enabled, continuing to Step 2...")


# STEP 2: Check Piper Binary Exists
# ============================================================================
print("\n=== STEP 2: Piper Binary ===")

PIPER_PATH = os.getenv("PIPER_PATH", "audio/piper/piper/piper.exe")
print(f"Looking for: {PIPER_PATH}")

if os.path.exists(PIPER_PATH):
    print(f"✓ Piper binary found")
else:
    print(f"❌ Piper binary NOT found")
    print(f"   Current working directory: {os.getcwd()}")
    print(f"   Please verify the path is correct")
    print(f"   Or set PIPER_PATH environment variable")


# STEP 3: Check Voice Model Exists
# ============================================================================
print("\n=== STEP 3: Voice Model ===")

VOICE_PROFILE = os.getenv("VOICE_PROFILE", "lessac").lower()
print(f"Voice profile: {VOICE_PROFILE}")

# Map to voice model path (from output_sink.py)
voice_models = {
    "lessac": "audio/piper/voices/en_US-lessac-medium.onnx",
}

VOICE_PATH = voice_models.get(VOICE_PROFILE, voice_models["lessac"])
print(f"Looking for: {VOICE_PATH}")

if os.path.exists(VOICE_PATH):
    print(f"✓ Voice model found")
else:
    print(f"❌ Voice model NOT found")
    print(f"   Current working directory: {os.getcwd()}")
    print(f"   Please verify the path is correct")


# STEP 4: Test PiperOutputSink Initialization
# ============================================================================
print("\n=== STEP 4: PiperOutputSink Initialization ===")

try:
    from core.output_sink import PiperOutputSink
    
    print("Attempting to initialize PiperOutputSink...")
    sink = PiperOutputSink()
    print("✓ PiperOutputSink initialized successfully")
    
    # Check worker thread is running
    if sink.worker_thread.is_alive():
        print("✓ Worker thread is running")
    else:
        print("❌ Worker thread is NOT running")
        
except Exception as e:
    print(f"❌ PiperOutputSink initialization failed:")
    print(f"   {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()


# STEP 5: Test Simple Speak Call
# ============================================================================
print("\n=== STEP 5: Test Simple Speak Call ===")

try:
    test_text = "Hello, this is a test."
    print(f"Attempting to speak: '{test_text}'")
    
    # This should queue the text immediately (non-blocking)
    sink.speak(test_text)
    print("✓ Text queued for playback")
    
    # Give worker thread time to process
    import time
    time.sleep(3)
    
    print("✓ Playback should have completed")
    
except Exception as e:
    print(f"❌ Speak failed:")
    print(f"   {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()


# STEP 6: Check Dependencies
# ============================================================================
print("\n=== STEP 6: Python Dependencies ===")

dependencies = [
    ("sounddevice", "pip install sounddevice"),
    ("numpy", "pip install numpy"),
    ("scipy", "pip install scipy"),
]

for pkg, install_cmd in dependencies:
    try:
        __import__(pkg)
        print(f"✓ {pkg} installed")
    except ImportError:
        print(f"❌ {pkg} NOT installed")
        print(f"   FIX: {install_cmd}")


# STEP 7: Check Audio Device
# ============================================================================
print("\n=== STEP 7: Audio Device ===")

try:
    import sounddevice as sd
    
    device_info = sd.query_devices(None, 'output')
    print(f"Default output device: {device_info['name']}")
    print(f"Sample rate: {device_info['default_samplerate']}")
    print(f"Channels: {device_info['max_output_channels']}")
    print("✓ Audio device accessible")
    
except Exception as e:
    print(f"❌ Audio device check failed:")
    print(f"   {type(e).__name__}: {e}")


# STEP 8: Test Piper Directly
# ============================================================================
print("\n=== STEP 8: Test Piper Subprocess ===")

import subprocess
import sys

try:
    test_text = "Test audio output"
    print(f"Running Piper with: '{test_text}'")
    
    process = subprocess.Popen(
        [
            PIPER_PATH,
            "--model", VOICE_PATH,
            "--output-raw",
            "--length_scale", "0.85",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    
    stdout, stderr = process.communicate(input=test_text.encode("utf-8"), timeout=10)
    
    if stdout:
        print(f"✓ Piper produced {len(stdout)} bytes of audio")
    else:
        print(f"❌ Piper produced NO audio output")
        if stderr:
            print(f"   Piper stderr: {stderr.decode('utf-8', errors='ignore')}")
    
except subprocess.TimeoutExpired:
    print("❌ Piper subprocess timeout")
    process.kill()
except Exception as e:
    print(f"❌ Piper test failed:")
    print(f"   {type(e).__name__}: {e}")


print("\n=== SUMMARY ===")
print("If you see ✓ for all steps above, audio should work.")
print("If you see ❌, fix that specific issue first.")
print("Common issues:")
print("  - VOICE_ENABLED=false (not set to 'true')")
print("  - PIPER_ENABLED=false (not set to 'true')")
print("  - Missing Piper binary at audio/piper/piper/piper.exe")
print("  - Missing voice model at audio/piper/voices/en_US-lessac-medium.onnx")
print("  - Missing Python dependencies (sounddevice, numpy)")
