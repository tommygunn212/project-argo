"""
Microphone Recording - Logitech Brio 500 Only

Explicit user-driven audio capture.
No transcription. No background listening. No persistence beyond temp.

Entry point for recording from Logitech Brio 500 USB microphone.

Lifecycle:
1. Enumerate devices
2. Find Logitech Brio 500 or exit loudly
3. Wait for user command: "record"
4. Record audio with fixed 5-second duration
5. Save WAV file to temp folder
6. Report details and exit
"""

import sys
import sounddevice
import scipy.io.wavfile
from pathlib import Path
from datetime import datetime
import numpy as np
import time


# === CONFIGURATION ===

SAMPLE_RATE = 16000  # 16 kHz
CHANNELS = 1  # Mono
CHUNK_SIZE = 4096
TEMP_FOLDER = Path(r"I:\argo\temp")
LOGITECH_BRIO_NAME = "Brio"  # Substring match (more flexible)


# === INITIALIZATION ===

TEMP_FOLDER.mkdir(parents=True, exist_ok=True)


# === DEVICE DETECTION ===

def enumerate_devices():
    """
    List all audio input devices.
    
    Returns:
        dict: {device_id: device_info}
    """
    devices = {}
    for i, device in enumerate(sounddevice.query_devices()):
        if device['max_input_channels'] > 0:  # Input device
            devices[i] = device
    return devices


def find_brio_500():
    """
    Find Logitech Brio 500 microphone by name.
    
    Returns:
        tuple: (device_id, device_info) or (None, None) if not found
    """
    devices = enumerate_devices()
    
    print("\n" + "=" * 70)
    print("AUDIO INPUT DEVICES")
    print("=" * 70)
    
    for device_id, device in devices.items():
        name = device['name']
        channels = device['max_input_channels']
        print(f"{device_id}: {name} ({channels} channels)")
    
    print()
    
    # Search for Brio by substring match
    for device_id, device in devices.items():
        if LOGITECH_BRIO_NAME.lower() in device['name'].lower():
            return device_id, device
    
    return None, None


# === RECORDING ===

def record_audio() -> tuple[np.ndarray, int]:
    """
    Record audio until user types "stop".
    
    This function:
    1. Records in blocking mode (chunks)
    2. Waits for user input
    3. Stops when user types "stop"
    
    Returns:
        tuple: (audio_data, sample_rate)
    """
    audio_chunks = []
    recording = True
    
    print("\n" + "-" * 70)
    print("RECORDING STARTED")
    print("-" * 70)
    print("Type 'stop' and press Enter to stop recording...")
    print()
    
    def audio_callback(indata, frames, time_info, status):
        """Called when audio chunk arrives."""
        if status:
            print(f"Audio error: {status}", file=sys.stderr)
        # Append chunk to list
        audio_chunks.append(indata.copy())
    
    # Start recording in blocking mode with callback
    stream = sounddevice.InputStream(
        device=None,  # Will be set before calling this
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        blocksize=CHUNK_SIZE,
        callback=audio_callback
    )
    
    stream.start()
    
    try:
        # Wait for user to type "stop"
        while True:
            user_input = input().strip().lower()
            if user_input == "stop":
                break
    finally:
        stream.stop()
        stream.close()
    
    # Concatenate all chunks
    if audio_chunks:
        audio_data = np.concatenate(audio_chunks, axis=0)
    else:
        audio_data = np.array([])
    
    print("\nRecording stopped.")
    
    return audio_data, SAMPLE_RATE


def record_audio_blocking(device_id: int, duration_seconds: int = 5) -> tuple[np.ndarray, int]:
    """
    Record audio for a fixed duration (simple, no threads).
    
    This version:
    1. Starts recording
    2. Records for specified duration
    3. Returns audio data
    
    Args:
        device_id: Audio device ID
        duration_seconds: Duration to record (default 5 seconds)
        
    Returns:
        tuple: (audio_data, sample_rate)
    """
    
    print("\n" + "-" * 70)
    print("RECORDING STARTED")
    print("-" * 70)
    print(f"Device: {sounddevice.query_devices(device_id)['name']}")
    print(f"Sample rate: {SAMPLE_RATE} Hz, Mono, 16-bit")
    print(f"Duration: {duration_seconds} seconds")
    print()
    
    # Create stream and record
    try:
        audio_data = sounddevice.rec(
            int(duration_seconds * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            device=device_id,
            dtype='float32'
        )
        
        # Wait for recording to finish
        sounddevice.wait()
        
    except Exception as e:
        print(f"ERROR during recording: {e}", file=sys.stderr)
        raise
    
    print("Recording stopped.")
    
    return audio_data, SAMPLE_RATE


# === FILE WRITING ===

def save_wav(audio_data: np.ndarray, sample_rate: int) -> tuple[Path, float]:
    """
    Save audio data to WAV file.
    
    This function:
    1. Generates timestamp-based filename
    2. Saves as 16-bit PCM WAV
    3. Returns path and duration
    
    Args:
        audio_data: Audio samples (numpy array)
        sample_rate: Sample rate in Hz
        
    Returns:
        tuple: (file_path, duration_seconds)
    """
    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"audio_{timestamp}.wav"
    filepath = TEMP_FOLDER / filename
    
    # Calculate duration
    if len(audio_data) > 0:
        duration = len(audio_data) / sample_rate
    else:
        duration = 0.0
    
    # Save WAV file (16-bit PCM, mono)
    try:
        scipy.io.wavfile.write(str(filepath), sample_rate, audio_data.astype(np.int16))
    except Exception as e:
        print(f"ERROR: Failed to write WAV file: {e}", file=sys.stderr)
        raise
    
    return filepath, duration


# === MAIN ===

def main():
    """Main entry point."""
    
    print("\n" + "=" * 70)
    print("LOGITECH BRIO 500 - MICROPHONE RECORDING")
    print("=" * 70)
    
    # Step 1: Enumerate devices
    print("\nStep 1: Detecting audio devices...")
    device_id, device_info = find_brio_500()
    
    if device_id is None:
        print(f"\nERROR: Logitech Brio 500 not found.")
        print("Cannot proceed without explicit device identification.")
        sys.exit(1)
    
    device_name = device_info['name']
    print(f"\n[OK] Found: {device_name}")
    
    # Step 2: Wait for user to start recording
    print("\n" + "-" * 70)
    print("READY TO RECORD")
    print("-" * 70)
    print("Type 'record' and press Enter to start recording...")
    print()
    
    while True:
        user_input = input().strip().lower()
        if user_input == "record":
            break
        else:
            print("Please type 'record' to start.")
    
    # Step 3: Record audio
    print()
    audio_data, sample_rate = record_audio_blocking(device_id, duration_seconds=3)
    
    # Step 4: Save to WAV
    print("\n" + "-" * 70)
    print("SAVING AUDIO")
    print("-" * 70)
    
    try:
        filepath, duration = save_wav(audio_data, sample_rate)
    except Exception as e:
        print(f"\nFATAL: Could not save audio file: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Step 5: Report results
    print()
    print("=" * 70)
    print("RECORDING COMPLETE")
    print("=" * 70)
    print(f"Device:       {device_name}")
    print(f"Sample rate:  {sample_rate} Hz")
    print(f"Channels:     Mono (1)")
    print(f"Bit depth:    16-bit PCM")
    print(f"Duration:     {duration:.2f} seconds")
    print(f"File saved:   {filepath}")
    print()
    
    # Verify file exists
    if filepath.exists():
        file_size = filepath.stat().st_size
        print(f"File size:    {file_size:,} bytes")
        print()
        print("[OK] Recording saved successfully.")
    else:
        print("ERROR: File was not created.", file=sys.stderr)
        sys.exit(1)
    
    print("=" * 70)
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nFATAL ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
