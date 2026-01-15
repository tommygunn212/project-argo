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
    python voice_one_shot.py                          # Normal execution
    python voice_one_shot.py --test-failure mic       # Inject failure

Failure injection modes (--test-failure):
    mic              Device not found
    wav-missing      WAV file not found
    wav-empty        WAV file exists but is zero-length
    whisper-timeout  Simulate transcription timeout
    model-missing    Simulate missing model file

Expected output (normal):
    [Device info]
    [Recording prompt]
    [Transcript text]
    [Exit 0]

Expected output (failure):
    [ERROR] <one clear error message>
    [Exit non-zero]
"""

import sys
import subprocess
from pathlib import Path
import time
import os

# Add paths
sys.path.insert(0, str(Path(__file__).parent))

from system.speech.whisper_runner import transcribe


# ========================================================================
# FAILURE INJECTION
# ========================================================================

class FailureInjection:
    """Simulate failures for testing error handling."""
    
    @staticmethod
    def inject_mic_not_found():
        """Simulate mic device not found."""
        print("\n[INJECTION] Simulating: Mic device not found")
        raise RuntimeError("No audio input device found (device enum returned empty list)")
    
    @staticmethod
    def inject_wav_missing():
        """Simulate WAV file missing."""
        print("\n[INJECTION] Simulating: WAV file missing")
        # Return a path that doesn't exist
        return Path("nonexistent_audio_file_12345.wav")
    
    @staticmethod
    def inject_wav_empty():
        """Simulate WAV file exists but is zero-length."""
        print("\n[INJECTION] Simulating: WAV file zero-length")
        # Create temp directory if needed
        temp_dir = Path(__file__).parent / "temp"
        temp_dir.mkdir(exist_ok=True)
        
        # Create zero-length WAV file
        empty_wav = temp_dir / "empty_injection.wav"
        empty_wav.write_bytes(b'')
        print(f"Created empty file: {empty_wav}")
        return empty_wav
    
    @staticmethod
    def inject_whisper_timeout():
        """Simulate whisper timeout by replacing transcribe with delay."""
        print("\n[INJECTION] Simulating: Whisper timeout (sleep 65s > 60s timeout)")
        # This will trigger timeout in transcribe() if we wrap it
        import time
        time.sleep(65)  # Longer than whisper_runner's 60s timeout
        raise RuntimeError("Transcription timed out (>60s)")
    
    @staticmethod
    def inject_model_missing():
        """Simulate missing whisper model file."""
        print("\n[INJECTION] Simulating: Missing whisper model (ggml-base.en.bin)")
        raise RuntimeError("Model file not found: whisper.cpp/ggml-base.en.bin (move it before running)")


def get_failure_mode():
    """Parse command-line arguments for failure injection."""
    if "--test-failure" in sys.argv:
        idx = sys.argv.index("--test-failure")
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return None


def print_debug_traceback(debug=False):
    """Conditionally print debug traceback."""
    if debug or "--debug" in sys.argv:
        import traceback
        traceback.print_exc(file=sys.stderr)


# ========================================================================

def run_mic_capture(failure_mode: str = None) -> Path:
    """
    Run record_mic.py and return the path to the recorded WAV file.
    
    This function:
    1. Runs record_mic.py in subprocess
    2. Provides "record" input automatically
    3. Waits for completion
    4. Extracts file path from output
    
    Args:
        failure_mode: Optional failure injection mode
    
    Returns:
        Path to the recorded WAV file
        
    Raises:
        RuntimeError: If recording fails or file not found
    """
    print("\n" + "=" * 70)
    print("STEP 1: RECORD AUDIO")
    print("=" * 70)
    print()
    
    # Inject failures before calling record_mic.py
    if failure_mode == "mic":
        FailureInjection.inject_mic_not_found()
    
    # Inject missing WAV file failure early
    if failure_mode == "wav-missing":
        return FailureInjection.inject_wav_missing()
    
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
                
                # Inject failure after file creation
                if failure_mode == "wav-empty":
                    # Replace with empty file
                    wav_path.write_bytes(b'')
                    print(f"[INJECTION] Truncated file to zero bytes")
                
                return wav_path
    
    raise RuntimeError("Could not find recorded WAV file in output")


def run_transcription(wav_path: Path, failure_mode: str = None) -> str:
    """
    Transcribe audio using whisper_runner.
    
    This function:
    1. Calls whisper_runner.transcribe(wav_path)
    2. Returns transcript text
    
    Args:
        wav_path: Path to WAV file
        failure_mode: Optional failure injection mode
        
    Returns:
        Transcript text
        
    Raises:
        RuntimeError: If transcription fails
    """
    print("\n" + "=" * 70)
    print("STEP 2: TRANSCRIBE AUDIO")
    print("=" * 70)
    print()
    
    # Inject failure before checking file
    if failure_mode == "whisper-timeout":
        FailureInjection.inject_whisper_timeout()
    
    if not wav_path.exists():
        raise RuntimeError(f"WAV file not found: {wav_path}")
    
    # Check for zero-length file
    if wav_path.stat().st_size == 0:
        raise RuntimeError(f"WAV file is empty (zero bytes): {wav_path}")
    
    try:
        print(f"Transcribing: {wav_path.name}...")
        
        # Inject model missing failure
        if failure_mode == "model-missing":
            FailureInjection.inject_model_missing()
        
        transcript = transcribe(str(wav_path))
    except FileNotFoundError as e:
        raise RuntimeError(f"File not found: {e}")
    except RuntimeError as e:
        raise RuntimeError(f"Transcription failed: {e}")
    except FileNotFoundError as e:
        raise RuntimeError(f"File not found: {e}")
    except RuntimeError as e:
        raise RuntimeError(f"Transcription failed: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {type(e).__name__}: {e}")
    
    return transcript


def main():
    """Main entry point."""
    
    # Get failure mode from CLI args
    failure_mode = get_failure_mode()
    
    if failure_mode:
        print("\n" + "=" * 70)
        print("VOICE ONE-SHOT PIPELINE (FAILURE INJECTION TEST)")
        print("=" * 70)
        print(f"Test mode: {failure_mode}")
        print()
    else:
        print("\n" + "=" * 70)
        print("VOICE ONE-SHOT PIPELINE")
        print("=" * 70)
        print("Mic (3s) → Whisper → Text → Exit")
        print()
    
    try:
        # Step 1: Record
        start_time = time.time()
        wav_path = run_mic_capture(failure_mode)
        record_time = time.time() - start_time
        
        # Step 2: Transcribe
        start_time = time.time()
        transcript = run_transcription(wav_path, failure_mode)
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
        print_debug_traceback()
        return 1
    except KeyboardInterrupt:
        print(f"\n[INTERRUPTED] User cancelled", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"\n[FATAL] {type(e).__name__}: {e}", file=sys.stderr)
        print_debug_traceback()
        return 1


if __name__ == "__main__":
    sys.exit(main())
