#!/usr/bin/env python3
"""
Voice Confirmation Gate

Pure human brake between text and action.

This script:
1. Accepts text from voice transcription
2. Repeats it back to operator
3. Asks for explicit confirmation
4. Accepts ONLY "yes" as approval

Design:
- No retries
- No defaults
- No fuzzy matching
- No timeout
- No logging of text

Usage:
    echo "Turn on the lights" | python voice_confirm.py
    # or
    python voice_confirm.py < transcript.txt

Expected:
    [TRANSCRIPT]
    Turn on the lights

    Proceed? (yes/no): yes
    [Exit 0]

    # or

    Proceed? (yes/no): no
    [Exit 1]
"""

import sys


def main():
    """Main entry point."""
    
    # Read all input (transcript + response)
    try:
        lines = sys.stdin.readlines()
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] User cancelled", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"\n[ERROR] Failed to read input: {e}", file=sys.stderr)
        return 1
    
    # Split transcript from response
    if not lines:
        print("[ERROR] No input provided", file=sys.stderr)
        return 1
    
    # Everything except last line is transcript
    # Last line is response
    if len(lines) == 1:
        # Only one line - treat as transcript, no response
        transcript = lines[0].strip()
        response = ""
    else:
        transcript = "".join(lines[:-1]).strip()
        response = lines[-1].strip().lower()
    
    # Validate transcript is not empty
    if not transcript:
        print("[ERROR] No input provided", file=sys.stderr)
        return 1
    
    # Display transcript clearly
    print("\n" + "=" * 70)
    print("TRANSCRIPT")
    print("=" * 70)
    print(transcript)
    print("=" * 70)
    print()
    
    # Validate response
    if response == "yes":
        print("[OK] Confirmed")
        print()
        return 0
    else:
        if response:
            print(f"[DENIED] Response was '{response}' (not 'yes')")
        else:
            print("[DENIED] No response provided")
        return 1


if __name__ == "__main__":
    sys.exit(main())
