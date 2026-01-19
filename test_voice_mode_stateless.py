#!/usr/bin/env python3
"""
Validation Test: Voice Mode Stateless Execution (Option B Compliance)

Test Requirement:
- Voice input: "Please count to ten."
- Expected output: "One, two, three, four, five, six, seven, eight, nine, ten."
- Nothing else: no intro, no explanation, no followup, no meta-language

This ensures voice mode is truly stateless and memory-free.
"""

import subprocess
import sys

def run_argo_with_query(query: str, voice_mode: bool = False) -> str:
    """Run ARGO with a specific query and capture output"""
    
    # Create a test script that calls ARGO programmatically
    test_code = f"""
import sys
sys.path.insert(0, 'wrapper')

from argo import run_argo

# Call with voice_mode=True to test stateless execution
run_argo(
    "{query}",
    voice_mode={voice_mode}
)
"""
    
    result = subprocess.run(
        ['python', '-c', test_code],
        capture_output=True,
        text=True,
        cwd='i:\\argo'
    )
    
    return result.stdout + result.stderr


def validate_output(output: str) -> tuple[bool, str]:
    """Validate that output matches requirements"""
    
    lines = output.strip().split('\n')
    
    # Filter out debug/logging lines
    response_lines = [l for l in lines if not l.startswith('[') and not l.startswith('WHISPER')]
    response_text = ' '.join(response_lines).strip()
    
    # Expected: simple numbered list
    expected = "One, two, three, four, five, six, seven, eight, nine, ten."
    
    # Check for violations
    violations = []
    
    if "**" in response_text:
        violations.append("❌ Contains bold formatting (**)")
    
    if "1." in response_text or "2." in response_text:
        violations.append("❌ Contains numbered lists")
    
    if "previous" in response_text.lower() or "before" in response_text.lower():
        violations.append("❌ References previous interactions")
    
    if "we've" in response_text.lower() or "we had" in response_text.lower():
        violations.append("❌ Meta-language about conversation")
    
    if "?" in response_text:
        violations.append("❌ Contains follow-up questions")
    
    # Check if output is roughly correct (contains the numbers)
    has_numbers = all(str(i) in response_text for i in range(1, 11))
    
    if has_numbers and not violations:
        return True, "✅ PASS: Stateless, single-turn execution"
    elif has_numbers:
        return False, f"⚠️  PARTIAL: Correct answer but format violations:\n" + "\n".join(violations)
    else:
        return False, f"❌ FAIL: Incorrect output\nExpected: {expected}\nGot: {response_text[:100]}..."


if __name__ == "__main__":
    print("=" * 70)
    print("VALIDATION TEST: Voice Mode Stateless Execution")
    print("=" * 70)
    print()
    
    print("Test Query: 'Please count to ten.'")
    print()
    print("Running with voice_mode=True...")
    print()
    
    output = run_argo_with_query("Please count to ten.", voice_mode=True)
    
    passed, message = validate_output(output)
    
    print(message)
    print()
    
    if passed:
        print("✅ VALIDATION PASSED - Option B compliance confirmed")
        sys.exit(0)
    else:
        print("❌ VALIDATION FAILED - Check prompt hygiene")
        print()
        print("=== Full Output ===")
        print(output)
        sys.exit(1)
