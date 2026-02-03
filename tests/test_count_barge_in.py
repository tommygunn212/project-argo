#!/usr/bin/env python3
"""
Manual Test: Count + Barge-in

Goal:
- Verify count output stops cleanly on barge-in
- Ensure UI only shows numbers spoken before interruption

Steps:
1) Start Argo in voice mode.
2) Say: "Count to five."
3) While it is speaking, interrupt at "three" with the wake word + any phrase.

Expected:
- UI shows: 1, 2, 3 (and stops)
- TTS stops immediately on barge-in
- No 4 or 5 logged after interruption
- State returns to LISTENING
"""

print("Manual test: Count + barge-in. Follow instructions in file header.")
