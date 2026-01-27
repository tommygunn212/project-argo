#!/usr/bin/env python
"""Test Piper TTS - Convert text to speech"""
import subprocess
import sys
import os

print("=" * 60)
print("PIPER TTS TEST")
print("=" * 60)
print()

# Test text
test_text = "Hello, this is a test of the piper text to speech system"

print(f"Converting text to speech:")
print(f"  Text: '{test_text}'")
print()

try:
    # Try to use piper via python module
    print("Attempting to synthesize...")
    
    cmd = [
        sys.executable, "-m", "piper",
        "--model", "en_US-lessac-medium",
        "--output-file", "i:/argo/test_output.wav"
    ]
    
    # Run piper with text input
    result = subprocess.run(
        cmd,
        input=test_text,
        text=True,
        capture_output=True,
        timeout=30
    )
    
    if result.returncode == 0:
        # Check if output file was created
        if os.path.exists("i:/argo/test_output.wav"):
            size = os.path.getsize("i:/argo/test_output.wav")
            print(f"✓ Successfully generated audio")
            print(f"  - Output file: i:/argo/test_output.wav")
            print(f"  - File size: {size} bytes")
            print()
            print("Playing audio...")
            
            # Try to play the audio
            import sounddevice as sd
            import soundfile as sf
            
            try:
                audio, sr = sf.read("i:/argo/test_output.wav")
                sd.play(audio, sr, device=4)  # Device 4 = M-Track Speakers
                sd.wait()
                print("✓ Audio playback complete")
            except Exception as e:
                print(f"⚠ Could not play audio: {e}")
                print("  But the WAV file was created successfully")
        else:
            print("❌ Piper ran but didn't create output file")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
    else:
        print(f"❌ Piper command failed")
        print(f"Return code: {result.returncode}")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")

except Exception as e:
    print(f"❌ Error: {e}")
    print()
    print("Trying alternative approach with piper subprocess...")
    
    try:
        # Alternative: try calling piper directly
        result = subprocess.run(
            ["piper", "--model", "en_US-lessac-medium", "--output-file", "i:/argo/test_output.wav"],
            input=test_text,
            text=True,
            capture_output=True,
            timeout=30
        )
        
        if result.returncode == 0 and os.path.exists("i:/argo/test_output.wav"):
            print(f"✓ Successfully generated audio via direct piper call")
            size = os.path.getsize("i:/argo/test_output.wav")
            print(f"  - File size: {size} bytes")
        else:
            print(f"❌ Direct piper call also failed")
    except Exception as e2:
        print(f"❌ Alternative method also failed: {e2}")

print()
print("=" * 60)
