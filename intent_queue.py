#!/usr/bin/env python3
"""
Intent Queue - Record pending intent with hash only.

This script:
1. Accepts intent text (stdin or CLI arg)
2. Generates UUID + timestamp
3. Computes SHA256 hash of intent
4. Appends to pending.jsonl

Does NOT:
- Store raw text
- Execute anything
- Auto-approve
- Create schedules

Usage:
    echo "Turn on the lights" | python intent_queue.py
    # or
    python intent_queue.py "Turn on the lights"

Output:
    [OK] Intent queued: <uuid>
    [timestamp] <hash>
"""

import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime
from uuid import uuid4


def get_intent_from_stdin() -> str:
    """Read intent from stdin."""
    try:
        text = sys.stdin.read().strip()
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] User cancelled", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n[ERROR] Failed to read stdin: {e}", file=sys.stderr)
        sys.exit(1)
    
    return text


def get_intent_from_args() -> str:
    """Read intent from command-line arguments."""
    if len(sys.argv) < 2:
        return None
    
    # Join all args after script name
    return " ".join(sys.argv[1:])


def compute_hash(text: str) -> str:
    """Compute SHA256 hash of intent text."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def ensure_queue_dir() -> Path:
    """Create intent_queue directory if missing."""
    queue_dir = Path(__file__).parent / "intent_queue"
    try:
        queue_dir.mkdir(exist_ok=True)
        return queue_dir
    except Exception as e:
        print(f"\n[ERROR] Failed to create queue directory: {e}", file=sys.stderr)
        sys.exit(1)


def queue_intent(intent: str) -> int:
    """
    Queue intent for later review.
    
    Args:
        intent: Text intent to queue
        
    Returns:
        Exit code (0 = success, 1 = failure)
    """
    
    # Validate intent is not empty
    if not intent:
        print("[ERROR] No intent provided", file=sys.stderr)
        return 1
    
    # Create queue directory
    queue_dir = ensure_queue_dir()
    pending_file = queue_dir / "pending.jsonl"
    
    # Generate metadata
    intent_id = str(uuid4())
    timestamp = datetime.utcnow().isoformat() + "Z"
    intent_hash = compute_hash(intent)
    
    # Create record (NO RAW TEXT)
    record = {
        "id": intent_id,
        "timestamp": timestamp,
        "hash": intent_hash
    }
    
    # Append to pending.jsonl
    try:
        with open(pending_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except IOError as e:
        print(f"\n[ERROR] Failed to write to queue: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\n[FATAL] Unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    
    # Report success
    print(f"\n[OK] Intent queued: {intent_id}")
    print(f"Timestamp: {timestamp}")
    print(f"Hash:      {intent_hash[:16]}...")
    print(f"File:      {pending_file}")
    print()
    
    return 0


def main():
    """Main entry point."""
    
    # Try to get intent from args first, then stdin
    intent = get_intent_from_args()
    if intent is None:
        intent = get_intent_from_stdin()
    
    # Queue the intent
    return queue_intent(intent)


if __name__ == "__main__":
    sys.exit(main())
