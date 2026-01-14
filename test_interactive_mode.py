#!/usr/bin/env python3
"""Test interactive mode with simulated input"""
import subprocess
import sys

# Simulate user input
test_input = """What is 2+2?
explain photosynthesis
exit
"""

proc = subprocess.Popen(
    [sys.executable, "wrapper/argo.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)

output, _ = proc.communicate(input=test_input)
print(output)
