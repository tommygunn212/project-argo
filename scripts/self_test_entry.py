# ARGO Self-Test Entrypoint
# Usage: argo --self-test intents
import sys
import os
import subprocess

def main():
    script_path = os.path.join(os.path.dirname(__file__), 'run_intent_stress_test.py')
    if not os.path.exists(script_path):
        print('Intent stress test script not found.')
        sys.exit(1)
    result = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print('Self-test failed.')
        sys.exit(result.returncode)
    print('Self-test completed.')

if __name__ == '__main__':
    main()
