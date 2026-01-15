#!/usr/bin/env python3
"""
Intent Review - Manual approval of queued intents.

This script:
1. Lists all pending intents
2. User reviews each
3. User types intent ID to approve
4. Approved intent moved to approved.jsonl
5. Pending entry remains (append-only)

Does NOT:
- Auto-approve
- Delete records
- Modify pending.jsonl
- Execute anything
- Create new entries

Usage:
    python intent_review.py

Output:
    [Pending Intents]
    ID: <uuid>
    Timestamp: <iso>
    Hash: <sha256>
    
    Approve ID or skip? [ID or press Enter]: <uuid>
    
    [OK] Intent approved: <uuid>
    [Appended to approved.jsonl]
"""

import sys
import json
from pathlib import Path


def ensure_queue_dir() -> Path:
    """Ensure intent_queue directory exists."""
    queue_dir = Path(__file__).parent / "intent_queue"
    try:
        queue_dir.mkdir(exist_ok=True)
        return queue_dir
    except Exception as e:
        print(f"\n[ERROR] Failed to create queue directory: {e}", file=sys.stderr)
        sys.exit(1)


def read_pending_intents(queue_dir: Path) -> list:
    """Read all pending intents from pending.jsonl."""
    pending_file = queue_dir / "pending.jsonl"
    
    if not pending_file.exists():
        return []
    
    intents = []
    try:
        with open(pending_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        record = json.loads(line)
                        intents.append(record)
                    except json.JSONDecodeError:
                        print(f"[WARNING] Skipped malformed line: {line}", file=sys.stderr)
    except IOError as e:
        print(f"\n[ERROR] Failed to read pending intents: {e}", file=sys.stderr)
        sys.exit(1)
    
    return intents


def read_approved_intents(queue_dir: Path) -> set:
    """Read set of already-approved intent IDs."""
    approved_file = queue_dir / "approved.jsonl"
    
    if not approved_file.exists():
        return set()
    
    approved_ids = set()
    try:
        with open(approved_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        record = json.loads(line)
                        if "id" in record:
                            approved_ids.add(record["id"])
                    except json.JSONDecodeError:
                        pass
    except IOError as e:
        print(f"\n[ERROR] Failed to read approved intents: {e}", file=sys.stderr)
        sys.exit(1)
    
    return approved_ids


def approve_intent(intent_id: str, record: dict, queue_dir: Path) -> bool:
    """
    Approve a single intent.
    
    Appends approval record to approved.jsonl
    Does NOT modify pending.jsonl (append-only)
    
    Returns True if successful
    """
    approved_file = queue_dir / "approved.jsonl"
    
    try:
        with open(approved_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return True
    except IOError as e:
        print(f"\n[ERROR] Failed to write approval: {e}", file=sys.stderr)
        return False


def main():
    """Main entry point."""
    
    queue_dir = ensure_queue_dir()
    
    # Read all pending intents
    pending = read_pending_intents(queue_dir)
    approved_ids = read_approved_intents(queue_dir)
    
    # Filter to only unapproved intents
    unapproved = [i for i in pending if i["id"] not in approved_ids]
    
    if not unapproved:
        print("\n[OK] No pending intents to review")
        print()
        return 0
    
    # Display pending intents
    print("\n" + "=" * 70)
    print("PENDING INTENTS")
    print("=" * 70)
    print(f"Total: {len(unapproved)} unapproved intent(s)")
    print()
    
    for i, intent in enumerate(unapproved, 1):
        print(f"[{i}] ID:        {intent['id']}")
        print(f"    Timestamp:  {intent['timestamp']}")
        print(f"    Hash:       {intent['hash'][:16]}...")
        print()
    
    print("=" * 70)
    print()
    
    # Ask for approval
    try:
        user_input = input("Approve intent ID (or press Enter to skip): ").strip()
    except KeyboardInterrupt:
        print(f"\n[INTERRUPTED] User cancelled", file=sys.stderr)
        return 130
    except EOFError:
        print(f"\n[ERROR] No input provided", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR] Failed to read input: {e}", file=sys.stderr)
        return 1
    
    # If no input, skip
    if not user_input:
        print("[OK] No approval given")
        print()
        return 0
    
    # Find matching intent
    matching = [i for i in unapproved if i["id"] == user_input]
    
    if not matching:
        print(f"[ERROR] No pending intent with ID: {user_input}")
        return 1
    
    intent = matching[0]
    
    # Approve (append to approved.jsonl)
    if approve_intent(intent["id"], intent, queue_dir):
        approved_file = queue_dir / "approved.jsonl"
        print(f"\n[OK] Intent approved: {intent['id']}")
        print(f"Appended to: {approved_file}")
        print()
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
