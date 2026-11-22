"""Stands in for `claude -p --output-format json` in tests: reads the prompt on
stdin, does what the task says, prints a result line like the real CLI."""

import json
import sys
import time
from pathlib import Path

prompt = sys.stdin.read()
if "SLEEP" in prompt:
    time.sleep(30)
if "FAIL" in prompt:
    print(json.dumps({"type": "result", "subtype": "error_during_execution",
                      "is_error": True, "result": "could not do it"}))
    sys.exit(1)
Path("made_by_agent.txt").write_text("hi from argo", encoding="utf-8")
if "-o" in sys.argv:  # codex exec style: the last message goes to a file
    Path(sys.argv[sys.argv.index("-o") + 1]).write_text(
        "I created made_by_agent.txt in the work folder.", encoding="utf-8")
    sys.exit(0)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                  "result": "I created made_by_agent.txt in the work folder.",
                  "total_cost_usd": 0.01}))
