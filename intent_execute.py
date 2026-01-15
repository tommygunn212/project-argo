#!/usr/bin/env python3
"""
Intent Execution Verifier

Verify approved intent before any execution.

This tool:
1. Accepts UUID and hash
2. Verifies against approved.jsonl
3. Returns yes (exit 0) or no (exit 1)

Does NOT:
- Execute anything
- Reconstruct intent text
- Import from other intent modules
- Cache or optimize
- Make any decision beyond "approved or not"

Usage:
    python intent_execute.py <uuid> <hash>

Example:
    python intent_execute.py b2831d73-2708-4f50-944b-7b54f11bfbb4 d74524813b020264...

Output:
    [OK] Intent approved: b2831d73...
    Exit 0

    or

    [ERROR] Intent not in approved queue
    Exit 1
"""

import sys
import json
from pathlib import Path


def validate_uuid(uuid_str: str) -> bool:
    """Check if string is valid UUID format."""
    if not uuid_str:
        return False
    
    # Standard UUID is 36 chars: 8-4-4-4-12
    if len(uuid_str) != 36:
        return False
    
    parts = uuid_str.split("-")
    if len(parts) != 5:
        return False
    
    if len(parts[0]) != 8 or len(parts[1]) != 4 or len(parts[2]) != 4 or len(parts[3]) != 4 or len(parts[4]) != 12:
        return False
    
    # Check all characters are hex + hyphens
    for char in uuid_str:
        if not (char.isdigit() or char.lower() in "abcdef" or char == "-"):
            return False
    
    return True


def validate_hash(hash_str: str) -> bool:
    """Check if string is valid SHA256 hash format."""
    if not hash_str:
        return False
    
    # SHA256 is 64 hex characters
    if len(hash_str) != 64:
        return False
    
    # Check all characters are hex
    for char in hash_str.lower():
        if not (char.isdigit() or char in "abcdef"):
            return False
    
    return True


def get_approved_file() -> Path:
    """Get path to approved.jsonl."""
    return Path(__file__).parent / "intent_queue" / "approved.jsonl"


def verify_intent(intent_id: str, intent_hash: str) -> int:
    """
    Verify intent is approved.
    
    Returns:
        0 if approved and valid
        1 otherwise
    """
    
    # Validate inputs
    if not validate_uuid(intent_id):
        print("[ERROR] Invalid intent ID format", file=sys.stderr)
        return 1
    
    if not validate_hash(intent_hash):
        print("[ERROR] Invalid hash format", file=sys.stderr)
        return 1
    
    # Check file exists
    approved_file = get_approved_file()
    if not approved_file.exists():
        print("[ERROR] Approved queue not initialized", file=sys.stderr)
        return 1
    
    # Read and verify
    try:
        with open(approved_file, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    print(f"[ERROR] Malformed entry in approved queue (line {line_num})", file=sys.stderr)
                    return 1
                
                # Check for required fields
                if "id" not in record or "hash" not in record:
                    print(f"[ERROR] Malformed entry in approved queue (line {line_num})", file=sys.stderr)
                    return 1
                
                # Match found
                if record["id"] == intent_id:
                    # Verify hash
                    if record["hash"] == intent_hash:
                        print(f"[OK] Intent approved: {intent_id[:8]}...")
                        return 0
                    else:
                        print("[ERROR] Hash mismatch - intent may have been modified", file=sys.stderr)
                        return 1
        
        # No match found
        print("[ERROR] Intent not in approved queue", file=sys.stderr)
        return 1
    
    except IOError as e:
        print(f"[ERROR] Cannot read approved queue: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR] Unexpected error: {type(e).__name__}", file=sys.stderr)
        return 1


def main():
    """Main entry point."""
    
    # Validate arguments
    if len(sys.argv) != 3:
        print("[ERROR] Usage: intent_execute.py <uuid> <hash>", file=sys.stderr)
        return 1
    
    intent_id = sys.argv[1]
    intent_hash = sys.argv[2]
    
    return verify_intent(intent_id, intent_hash)


if __name__ == "__main__":
    sys.exit(main())
