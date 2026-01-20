#!/usr/bin/env python3
"""
Debug: Trace voice pipeline step-by-step
Tests: Transcription → Intent → LLM → Piper
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

# Fix Unicode for Windows PowerShell
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

print("="*70)
print("[DEBUG] Voice Pipeline Trace")
print("="*70)

# Step 1: Test Ollama connection
print("\n[1] Testing Ollama connection...")
try:
    import requests
    response = requests.get("http://localhost:11434/api/tags", timeout=2)
    print(f"    Status: {response.status_code}")
    print(f"    Response: {response.text[:200]}")
    if response.status_code == 200:
        print("    ✓ Ollama is running")
    else:
        print("    ✗ Ollama not responding correctly")
except Exception as e:
    print(f"    ✗ Ollama connection failed: {e}")
    print("    → Start Ollama with: ollama serve")

# Step 2: Test Whisper
print("\n[2] Testing Whisper STT...")
try:
    from core.speech_to_text import WhisperSTT
    stt = WhisperSTT()
    print("    ✓ Whisper loaded")
except Exception as e:
    print(f"    ✗ Whisper failed: {e}")

# Step 3: Test Intent Parser
print("\n[3] Testing Intent Parser...")
try:
    from core.intent_parser import RuleBasedIntentParser
    parser = RuleBasedIntentParser()
    test_text = "count to five"
    intent = parser.parse(test_text)
    print(f"    Input: '{test_text}'")
    print(f"    Intent: {intent}")
    print("    ✓ Intent parser works")
except Exception as e:
    print(f"    ✗ Intent parser failed: {e}")

# Step 4: Test LLM Response Generator
print("\n[4] Testing LLM Response Generator...")
try:
    from core.response_generator import LLMResponseGenerator
    from core.intent_parser import RuleBasedIntentParser
    generator = LLMResponseGenerator()
    parser = RuleBasedIntentParser()
    
    # Test with a simple request - use the Intent object from parser
    test_text = "count to five"
    intent = parser.parse(test_text)
    
    print(f"    Input: '{test_text}'")
    print(f"    Intent object: {intent}")
    print("    Generating response...")
    response = generator.generate(intent, None)
    print(f"    Response: '{response}'")
    if response and len(response) > 5:
        print("    ✓ LLM generated response")
    else:
        print(f"    ⚠ LLM response too short: '{response}'")
except Exception as e:
    print(f"    ✗ LLM generator failed: {e}")
    import traceback
    traceback.print_exc()

# Step 5: Test Piper TTS
print("\n[5] Testing Piper TTS...")
try:
    from core.output_sink import get_output_sink
    sink = get_output_sink()
    print(f"    Output sink: {sink.__class__.__name__}")
    
    test_phrase = "One, two, three, four, five"
    print(f"    Speaking: '{test_phrase}'")
    sink.speak(test_phrase)
    print("    ✓ Piper spoke successfully")
except Exception as e:
    print(f"    ✗ Piper failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70)
print("[DEBUG] Pipeline trace complete")
print("="*70)
