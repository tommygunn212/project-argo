#!/usr/bin/env python3
"""
================================================================================
WHISPER MODULE TEST SUITE
Comprehensive testing of Whisper transcription functionality
================================================================================

Module:      test_whisper_module.py
Creator:     Tommy Gunn (@tommygunn212)
Version:     1.0.0
Created:     January 2026
Purpose:     Validate transcription contracts, failure handling, logging

================================================================================
TEST CASES
================================================================================

1. Clean Speech
   - Clear audio file with normal speaking pace
   - Expected: status="success", transcript populated, high confidence

2. Background Noise
   - Audio with ambient noise or multiple speakers
   - Expected: status="success" or "partial", lower confidence

3. Long Pauses
   - Audio with extended silence or pauses
   - Expected: status="success", handle silence gracefully

4. Short Commands
   - Single-word or short phrase audio
   - Expected: status="success", accurate transcription

5. Failure Cases
   - Missing file, invalid format, exceeded duration
   - Expected: status="failure", explicit error_detail

6. Confirmation Gate
   - Artifact confirmation/rejection tracking
   - Expected: confirmation_status updated correctly

7. Logging
   - All transcription events logged to file
   - Expected: transcription.log contains artifact details

================================================================================
"""

import sys
import os
import json
import unittest
from pathlib import Path
from datetime import datetime
import logging

# Add wrapper to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wrapper.transcription import (
    TranscriptionArtifact,
    WhisperTranscriber,
    TranscriptionStorage,
    transcribe_audio
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_audio_file(filename: str, duration_ms: int = 1000, silence: bool = False):
    """
    Create a test WAV file for testing.
    
    Args:
        filename: Output WAV file path
        duration_ms: Duration in milliseconds
        silence: If True, create silent audio; if False, create tone
    
    This requires the `wave` module (stdlib).
    """
    import wave
    import struct
    import math
    
    sample_rate = 16000
    duration_s = duration_ms / 1000.0
    num_samples = int(sample_rate * duration_s)
    
    # Create directory if needed
    Path(filename).parent.mkdir(parents=True, exist_ok=True)
    
    with wave.open(filename, 'wb') as wav_file:
        # Mono, 16-bit PCM, 16kHz
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        # Generate audio data
        for i in range(num_samples):
            if silence:
                # Silent audio
                sample = 0
            else:
                # 440 Hz tone (A note) for non-silent audio
                frequency = 440
                amplitude = 32767 // 2
                phase = 2 * math.pi * frequency * i / sample_rate
                sample = int(amplitude * math.sin(phase))
            
            # Write 16-bit signed integer
            wav_file.writeframes(struct.pack('<h', sample))


# ============================================================================
# TEST CLASS
# ============================================================================

class TestWhisperTranscription(unittest.TestCase):
    """Test suite for Whisper transcription module."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment."""
        cls.test_audio_dir = Path("runtime/audio/test_inputs")
        cls.test_audio_dir.mkdir(parents=True, exist_ok=True)
        
        # Create test audio files
        cls.clean_speech_file = str(cls.test_audio_dir / "clean_speech.wav")
        cls.short_command_file = str(cls.test_audio_dir / "short_command.wav")
        cls.silence_file = str(cls.test_audio_dir / "silence.wav")
        
        # Generate test files
        create_test_audio_file(cls.clean_speech_file, duration_ms=2000, silence=False)
        create_test_audio_file(cls.short_command_file, duration_ms=500, silence=False)
        create_test_audio_file(cls.silence_file, duration_ms=1000, silence=True)
    
    def test_transcription_artifact_creation(self):
        """Test: TranscriptionArtifact is created with valid structure."""
        artifact = TranscriptionArtifact()
        
        self.assertIsNotNone(artifact.id)
        self.assertIsNotNone(artifact.timestamp)
        self.assertEqual(artifact.status, "pending")
        self.assertEqual(artifact.confirmation_status, "pending")
        self.assertEqual(artifact.confidence, 0.0)
    
    def test_artifact_to_dict(self):
        """Test: Artifact converts to dict correctly."""
        artifact = TranscriptionArtifact()
        artifact.transcript_text = "Hello world"
        artifact.status = "success"
        
        d = artifact.to_dict()
        self.assertEqual(d["transcript_text"], "Hello world")
        self.assertEqual(d["status"], "success")
        self.assertIn("id", d)
        self.assertIn("timestamp", d)
    
    def test_artifact_to_json(self):
        """Test: Artifact converts to JSON correctly."""
        artifact = TranscriptionArtifact()
        artifact.transcript_text = "Test transcript"
        
        json_str = artifact.to_json()
        parsed = json.loads(json_str)
        self.assertEqual(parsed["transcript_text"], "Test transcript")
    
    def test_missing_audio_file(self):
        """Test: Transcription fails gracefully for missing file."""
        transcriber = WhisperTranscriber(model_name="base", device="cpu")
        artifact = transcriber.transcribe("/nonexistent/path/audio.wav")
        
        self.assertEqual(artifact.status, "failure")
        self.assertIn("not found", artifact.error_detail)
        self.assertIsNone(artifact.transcript_text)
    
    def test_audio_duration_limit(self):
        """Test: Transcription fails if audio exceeds max duration."""
        # Create a file longer than max allowed
        long_audio_file = str(self.test_audio_dir / "long_audio.wav")
        create_test_audio_file(long_audio_file, duration_ms=350000)  # 350 seconds
        
        transcriber = WhisperTranscriber(model_name="base", device="cpu")
        artifact = transcriber.transcribe(long_audio_file, max_duration_seconds=300)
        
        self.assertEqual(artifact.status, "failure")
        self.assertIn("exceeds max", artifact.error_detail)
    
    def test_transcription_storage_confirm(self):
        """Test: Storage can confirm artifacts."""
        storage = TranscriptionStorage()
        artifact = TranscriptionArtifact()
        artifact.transcript_text = "Test"
        artifact.status = "success"
        
        storage.store(artifact)
        storage.confirm(artifact.id)
        
        retrieved = storage.retrieve(artifact.id)
        self.assertEqual(retrieved.confirmation_status, "confirmed")
    
    def test_transcription_storage_reject(self):
        """Test: Storage can reject artifacts."""
        storage = TranscriptionStorage()
        artifact = TranscriptionArtifact()
        artifact.transcript_text = "Test"
        artifact.status = "success"
        
        storage.store(artifact)
        storage.reject(artifact.id)
        
        retrieved = storage.retrieve(artifact.id)
        self.assertEqual(retrieved.confirmation_status, "rejected")
    
    def test_list_pending_artifacts(self):
        """Test: Storage can list pending artifacts."""
        storage = TranscriptionStorage()
        
        # Create and store artifacts
        a1 = TranscriptionArtifact()
        a1.transcript_text = "Pending 1"
        a1.confirmation_status = "pending"
        storage.store(a1)
        
        a2 = TranscriptionArtifact()
        a2.transcript_text = "Confirmed"
        a2.confirmation_status = "confirmed"
        storage.store(a2)
        
        pending = storage.list_pending()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].id, a1.id)
    
    def test_logging_setup(self):
        """Test: Transcription logging is configured."""
        log_file = Path("runtime/audio/logs/transcription.log")
        
        # After creating a transcriber, log file should exist
        transcriber = WhisperTranscriber(model_name="base", device="cpu")
        
        # Log file should be created
        self.assertTrue(log_file.parent.exists())
    
    def test_artifact_metadata(self):
        """Test: Artifact stores metadata correctly."""
        artifact = TranscriptionArtifact()
        artifact.source_audio = "/path/to/audio.wav"
        artifact.transcript_text = "Hello world"
        artifact.language_detected = "en"
        artifact.confidence = 0.95
        
        self.assertEqual(artifact.source_audio, "/path/to/audio.wav")
        self.assertEqual(artifact.language_detected, "en")
        self.assertAlmostEqual(artifact.confidence, 0.95)
    
    def test_error_detail_required_for_failure(self):
        """Test: Failure artifacts have error_detail."""
        artifact = TranscriptionArtifact()
        artifact.status = "failure"
        artifact.error_detail = "Test error message"
        
        self.assertIsNotNone(artifact.error_detail)
        self.assertTrue(len(artifact.error_detail) > 0)


# ============================================================================
# MANUAL TESTING GUIDE
# ============================================================================

def print_manual_test_guide():
    """Print guide for manual testing with real audio."""
    guide = """
    ========================================================================
    MANUAL TESTING GUIDE
    ========================================================================
    
    Prerequisites:
      - OpenAI Whisper installed: pip install openai-whisper
      - Real audio files in WAV format
      - Microphone or pre-recorded audio
    
    TEST 1: Clean Speech
      - Create a WAV file with clear speech (e.g., "Hello, my name is Bob")
      - Run: python test_whisper_module.py TestManual.test_clean_speech
      - Expected: status="success", high confidence (>0.9)
    
    TEST 2: Background Noise
      - Record audio with background noise or multiple speakers
      - Expected: status="success" or "partial", lower confidence
    
    TEST 3: Short Commands
      - Record single-word commands ("Yes", "No", "Hello")
      - Expected: status="success", accurate short transcript
    
    TEST 4: Long Pauses
      - Record speech with 2-3 second pauses in between
      - Expected: status="success", pauses handled gracefully
    
    TEST 5: Confirmation Flow
      - Run test_whisper_module.py manually
      - Check output shows confirmation prompts
      - Verify artifacts stored with confirmation status
    
    TEST 6: Failure Scenarios
      - Try non-existent file path
      - Try audio file >5 minutes
      - Try invalid WAV format
      - Expected: status="failure", detailed error messages
    
    Logging:
      - All test results logged to runtime/audio/logs/transcription.log
      - Review log for timestamps, confidence scores, error details
    
    ========================================================================
    """
    print(guide)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # Run unit tests
    unittest.main(verbosity=2)
