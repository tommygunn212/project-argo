#!/usr/bin/env python3
"""
Voice One-Shot Pipeline

Single-shot end-to-end voice capture:
1. Record audio from mic (3 seconds)
2. Transcribe using whisper_runner
3. Print transcript
4. Exit

No loops. No memory. No background tasks.
Manual execution only.

Usage:
    python voice_one_shot.py

Expected output:
    [Device info]
    [Recording prompt]
    [Transcript text]
    [Exit 0]
"""

import sys
import subprocess
from pathlib import Path
import time

# Add paths
sys.path.insert(0, str(Path(__file__).parent))

from system.speech.whisper_runner import transcribe


def run_mic_capture() -> Path:
    """
    Run record_mic.py and return the path to the recorded WAV file.
    
    This function:
    1. Runs record_mic.py in subprocess
    2. Provides "record" input automatically
    3. Waits for completion
    4. Extracts file path from output
    
    Returns:
        Path to the recorded WAV file
        
    Raises:
        RuntimeError: If recording fails or file not found
    """
    print("\n" + "=" * 70)
    print("STEP 1: RECORD AUDIO")
    print("=" * 70)
    print()
    
    # Run record_mic.py with automatic "record" input
    try:
        result = subprocess.run(
            [sys.executable, "record_mic.py"],
            input="record\n",
            capture_output=True,
            text=True,
            timeout=15,
            cwd=str(Path(__file__).parent)
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Mic recording timed out (15s)")
    except Exception as e:
        raise RuntimeError(f"Failed to run record_mic.py: {e}")
    
    # Check for errors
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"record_mic.py failed with code {result.returncode}")
    
    # Print recording output
    print(result.stdout)
    
    # Extract file path from output (look for "File saved:" line)
    for line in result.stdout.split("\n"):
        if "File saved:" in line:
            # Parse: "File saved:   I:\argo\temp\audio_20260115_180232.wav"
            path_str = line.split("File saved:")[-1].strip()
            wav_path = Path(path_str)
            
            if wav_path.exists():
                print(f"\n[OK] Audio file: {wav_path.name}")
                return wav_path
    
    raise RuntimeError("Could not find recorded WAV file in output")


def run_transcription(wav_path: Path) -> str:
    """
    Transcribe audio using whisper_runner.
    
    This function:
    1. Calls whisper_runner.transcribe(wav_path)
    2. Returns transcript text
    
    Args:
        wav_path: Path to WAV file
        
    Returns:
        Transcript text
        
    Raises:
        RuntimeError: If transcription fails
    """
    print("\n" + "=" * 70)
    print("STEP 2: TRANSCRIBE AUDIO")
    print("=" * 70)
    print()
    
    if not wav_path.exists():
        raise RuntimeError(f"WAV file not found: {wav_path}")
    
    try:
        print(f"Transcribing: {wav_path.name}...")
        transcript = transcribe(str(wav_path))
    except FileNotFoundError as e:
        raise RuntimeError(f"File not found: {e}")
    except RuntimeError as e:
        raise RuntimeError(f"Transcription failed: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {type(e).__name__}: {e}")
    
    return transcript


def main():
    """Main entry point."""
    
    print("\n" + "=" * 70)
    print("VOICE ONE-SHOT PIPELINE")
    print("=" * 70)
    print("Mic (3s) → Whisper → Text → Exit")
    print()
    
    try:
        # Step 1: Record
        start_time = time.time()
        wav_path = run_mic_capture()
        record_time = time.time() - start_time
        
        # Step 2: Transcribe
        start_time = time.time()
        transcript = run_transcription(wav_path)
        transcribe_time = time.time() - start_time
        
        # Step 3: Output
        print("\n" + "=" * 70)
        print("TRANSCRIPT")
        print("=" * 70)
        print(transcript)
        print()
        
        # Step 4: Summary
        print("=" * 70)
        print("PIPELINE COMPLETE")
        print("=" * 70)
        print(f"Recording time:      {record_time:.2f}s")
        print(f"Transcription time:  {transcribe_time:.2f}s")
        print(f"Total time:          {record_time + transcribe_time:.2f}s")
        print()
        print("[OK] Pipeline executed successfully")
        print("=" * 70)
        print()
        
        return 0
        
    except RuntimeError as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"\n[INTERRUPTED] User cancelled", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"\n[FATAL] {type(e).__name__}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
