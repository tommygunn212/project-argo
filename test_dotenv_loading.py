#!/usr/bin/env python3
"""Test if dotenv is loading variables"""

import sys
sys.path.insert(0, 'i:/argo/wrapper')
from pathlib import Path

# Simulate what wrapper/argo.py does
try:
    from dotenv import load_dotenv
    env_file = Path('i:/argo/wrapper/argo.py').parent.parent / '.env'
    print(f'Loading from: {env_file}')
    load_dotenv(env_file)
    print('✓ dotenv loaded')
except ImportError as e:
    print(f'✗ dotenv import failed: {e}')

import os
print(f"VOICE_ENABLED={os.getenv('VOICE_ENABLED', 'NOT SET')}")
print(f"PIPER_ENABLED={os.getenv('PIPER_ENABLED', 'NOT SET')}")
print(f"PIPER_PATH={os.getenv('PIPER_PATH', 'NOT SET')}")
