#!/usr/bin/env python3
"""Debug execution context detection"""

import os
import sys

# Set VOICE_ENABLED before anything else
os.environ['VOICE_ENABLED'] = 'true'

sys.path.insert(0, 'wrapper')

# Now load and run argo to see what context is detected
if __name__ == "__main__":
    # Import after path is set
    from argo import detect_context
    
    result = detect_context()
    print(f"detect_context() = {result}")
    print(f"VOICE_ENABLED = {os.getenv('VOICE_ENABLED')}")
    print(f"stderr.isatty() = {sys.stderr.isatty()}")
