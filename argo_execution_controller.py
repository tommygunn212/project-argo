#!/usr/bin/env python3
"""ARGO Execution Controller v0

Purpose: Answer one question: "May ARGO proceed with execution for this approved intent, right now?"

This is a traffic light, not a car. Green = allowed, Red = denied.

Responsibilities:
- Verify intent was approved (delegate to intent_execute.py)
- Check if intent was already executed (prevent replay)
- Signal eligibility to ARGO (exit 0 = yes, exit 1 = no)

What it must NOT do:
- Execute tools or commands
- Parse intent text
- Infer intent meaning
- Retry anything
- Cache anything
- Log anything
- Modify approval files
- Write to executed.jsonl
- Schedule execution
- Be helpful
"""

import sys
import json
import subprocess
from pathlib import Path


def main():
    # Precondition 0: Validate CLI arguments
    if len(sys.argv) != 3:
        print("[ERROR] Usage: python argo_execution_controller.py <intent_id> <hash>")
        sys.exit(1)

    intent_id = sys.argv[1]
    hash_value = sys.argv[2]

    # Get the directory where this script is located
    controller_dir = Path(__file__).parent

    # Precondition 1: intent_execute.py must exist and be callable
    intent_execute_path = controller_dir / "intent_execute.py"
    if not intent_execute_path.exists():
        print("[ERROR] Precondition failed: intent_execute.py not found")
        sys.exit(1)

    # Step 1: Call intent_execute.py to verify approval
    try:
        result = subprocess.run(
            [sys.executable, str(intent_execute_path), intent_id, hash_value],
            capture_output=True,
            text=True,
            timeout=10
        )
    except subprocess.TimeoutExpired:
        print("[ERROR] Verification timeout")
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Verification failed: {e}")
        sys.exit(1)

    # Step 2: Check intent_execute.py exit code
    if result.returncode != 0:
        # Intent is not approved
        print(result.stdout.strip() if result.stdout.strip() else "[ERROR] Intent not approved")
        sys.exit(1)

    # Step 3: Check executed.jsonl for replay prevention
    executed_file = controller_dir / "intent_queue" / "executed.jsonl"

    # If executed.jsonl doesn't exist, treat as empty (no executions yet)
    if executed_file.exists():
        try:
            with open(executed_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            entry = json.loads(line)
                            if entry.get("id") == intent_id:
                                # Intent was already executed
                                print(f"[ERROR] Intent already executed (replay prevention): {intent_id}")
                                sys.exit(1)
                        except json.JSONDecodeError:
                            # Malformed entry in executed.jsonl
                            print("[ERROR] Malformed entry in executed queue")
                            sys.exit(1)
        except IOError:
            print("[ERROR] Cannot read executed queue")
            sys.exit(1)

    # Step 4: Intent is approved and not yet executed → eligible
    print(f"[OK] Intent eligible for execution: {intent_id}")
    sys.exit(0)


if __name__ == "__main__":
    main()
