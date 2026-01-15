#!/usr/bin/env python3
"""ARGO Tool Execution Adapter v0

Purpose: Execute exactly one approved tool once, record result, stop.

This is a single-shot cannon with a safety. Treat it like it's radioactive.

Responsibilities:
- Verify controller says OK (exit 0)
- Load tool registry (read-only)
- Execute exactly one tool synchronously
- Record to executed.jsonl ONLY on success
- Fail closed on any ambiguity

What it must NOT do:
- Chain tools
- Retry
- Fallback
- Infer intent
- Execute without controller approval
- Modify approvals
- Be helpful
"""

import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
import os


# === TOOL REGISTRY FOR v0 ===
# One safe tool only: echo_text
# This proves the adapter pipeline before giving it real teeth.

TOOL_REGISTRY = {
    "echo_text": {
        "function": "echo_text_tool",
        "schema": {
            "text": {"type": "string", "required": True}
        }
    }
}


def echo_text_tool(text: str) -> tuple[int, str, str]:
    """Safe tool: echo text back. No side effects."""
    try:
        return (0, f"Echo: {text}", "")
    except Exception as e:
        return (1, "", f"Error: {e}")


def call_controller(intent_id: str, hash_value: str) -> bool:
    """Call argo_execution_controller.py and check eligibility."""
    controller_path = Path(__file__).parent / "argo_execution_controller.py"
    
    if not controller_path.exists():
        print("[ERROR] Controller not found")
        return False
    
    try:
        result = subprocess.run(
            [sys.executable, str(controller_path), intent_id, hash_value],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("[ERROR] Controller timeout")
        return False
    except Exception as e:
        print(f"[ERROR] Controller call failed: {e}")
        return False


def validate_uuid(value: str) -> bool:
    """Validate UUID format."""
    if not value:
        return False
    parts = value.split('-')
    if len(parts) != 5:
        return False
    if len(parts[0]) != 8 or len(parts[1]) != 4 or len(parts[2]) != 4 or len(parts[3]) != 4 or len(parts[4]) != 12:
        return False
    try:
        int(value.replace('-', ''), 16)
        return True
    except ValueError:
        return False


def validate_hash(value: str) -> bool:
    """Validate SHA256 hash format."""
    if len(value) != 64:
        return False
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


def validate_json_string(value: str) -> dict | None:
    """Parse and validate JSON string."""
    try:
        obj = json.loads(value)
        if not isinstance(obj, dict):
            return None
        return obj
    except json.JSONDecodeError:
        return None


def validate_tool_args(tool_name: str, args: dict) -> bool:
    """Validate args against tool schema."""
    if tool_name not in TOOL_REGISTRY:
        return False
    
    schema = TOOL_REGISTRY[tool_name].get("schema", {})
    
    for key, spec in schema.items():
        if spec.get("required", False) and key not in args:
            return False
        if key in args:
            if spec.get("type") == "string" and not isinstance(args[key], str):
                return False
    
    return True


def execute_tool(tool_name: str, args: dict) -> tuple[int, str, str]:
    """Execute tool by name with args."""
    if tool_name not in TOOL_REGISTRY:
        return (1, "", f"Unknown tool: {tool_name}")
    
    registry_entry = TOOL_REGISTRY[tool_name]
    func_name = registry_entry.get("function")
    
    if func_name == "echo_text_tool":
        return echo_text_tool(args.get("text", ""))
    
    return (1, "", "Tool not implemented")


def record_execution(intent_id: str, hash_value: str, tool_name: str, exit_code: int, executed_file: Path) -> bool:
    """Record execution to executed.jsonl atomically."""
    record = {
        "id": intent_id,
        "hash": hash_value,
        "ts": datetime.utcnow().isoformat() + "Z",
        "tool": tool_name,
        "exit_code": exit_code,
        "outcome": "success" if exit_code == 0 else "failure"
    }
    
    try:
        # Ensure parent directory exists
        executed_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Atomic write: temp file then move
        temp_file = executed_file.parent / f".{executed_file.name}.tmp.{os.getpid()}"
        
        try:
            # Read existing content
            existing_lines = []
            if executed_file.exists():
                with open(executed_file, 'r') as f:
                    existing_lines = f.readlines()
            
            # Write existing + new record to temp
            with open(temp_file, 'w') as f:
                for line in existing_lines:
                    f.write(line)
                f.write(json.dumps(record) + "\n")
            
            # Atomic move (Windows-safe)
            if executed_file.exists():
                executed_file.unlink()
            temp_file.rename(executed_file)
            return True
        except Exception as e:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except:
                    pass
            raise
    except Exception as e:
        print(f"[ERROR] Recording failed: {e}")
        return False


def main():
    # Parse CLI arguments
    args_dict = {}
    i = 1
    while i < len(sys.argv):
        if sys.argv[i].startswith("--"):
            key = sys.argv[i][2:]
            if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
                args_dict[key] = sys.argv[i + 1]
                i += 2
            else:
                args_dict[key] = True
                i += 1
        else:
            i += 1

    # Validate required args
    intent_id = args_dict.get("intent-id")
    hash_value = args_dict.get("hash")
    tool_name = args_dict.get("tool")
    tool_args_str = args_dict.get("args", "{}")
    dry_run = "dry-run" in args_dict
    executed_file = Path(args_dict.get("executed-file", "intent_queue/executed.jsonl"))

    if not intent_id or not hash_value or not tool_name:
        print("[ERROR] Required args missing: --intent-id, --hash, --tool, --args")
        sys.exit(1)

    # Validate UUID and hash
    if not validate_uuid(intent_id):
        print(f"[ERROR] Invalid intent ID format: {intent_id}")
        sys.exit(1)

    if not validate_hash(hash_value):
        print(f"[ERROR] Invalid hash format: {hash_value}")
        sys.exit(1)

    # Validate tool args JSON
    tool_args = validate_json_string(tool_args_str)
    if tool_args is None:
        print(f"[ERROR] Invalid tool args JSON: {tool_args_str}")
        sys.exit(1)

    # Validate tool exists
    if tool_name not in TOOL_REGISTRY:
        print(f"[ERROR] Unknown tool: {tool_name}")
        sys.exit(1)

    # Validate args against schema
    if not validate_tool_args(tool_name, tool_args):
        print(f"[ERROR] Tool args do not match schema")
        sys.exit(1)

    # Call controller for eligibility (precondition)
    print(f"[OK] Verifying eligibility...")
    if not call_controller(intent_id, hash_value):
        print(f"[ERROR] Intent not eligible")
        sys.exit(1)

    print(f"[OK] Eligible")

    # Dry-run mode: validate only, don't execute or record
    if dry_run:
        print(f"[OK] Dry-run: validated, not executing")
        sys.exit(0)

    # Execute tool
    print(f"[OK] Executing tool: {tool_name}")
    exit_code, stdout, stderr = execute_tool(tool_name, tool_args)

    if exit_code != 0:
        print(f"[ERROR] Tool failed with exit code {exit_code}")
        if stderr:
            print(f"  {stderr}")
        sys.exit(1)

    # Record execution (only on success)
    print(f"[OK] Tool executed successfully")
    if not record_execution(intent_id, hash_value, tool_name, exit_code, executed_file):
        print(f"[ERROR] Execution occurred but recording failed")
        sys.exit(1)

    print(f"[OK] Recorded: {executed_file}")
    print(f"[OK] Execution ID: {intent_id}")
    sys.exit(0)


if __name__ == "__main__":
    main()
