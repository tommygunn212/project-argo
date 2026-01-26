#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')

from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / ".env")

import os

# Check FORCE_BLOCKING_TTS is set
print(f'FORCE_BLOCKING_TTS env: {os.getenv("FORCE_BLOCKING_TTS")}')

from core.output_sink import FORCE_BLOCKING_TTS, get_output_sink
print(f'FORCE_BLOCKING_TTS loaded: {FORCE_BLOCKING_TTS}')

# Try to get output sink
try:
    sink = get_output_sink()
    print(f'Output sink type: {type(sink).__name__}')
    print(f'Testing speak() with blocking TTS...')
    sink.speak("Hello, testing ARGO with blocking TTS. This should play all audio before returning.")
    print(f'Speak completed! Audio should have finished.')
except Exception as e:
    print(f'ERROR: {e}')
    import traceback
    traceback.print_exc()
