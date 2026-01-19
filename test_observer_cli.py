"""
PHASE 16B: OBSERVER CLI SMOKE TEST

Verify CLI runs, displays, and exits cleanly without any control/mutation imports.
"""

import unittest
import subprocess
import sys


class TestObserverCLI(unittest.TestCase):
    """Test observer CLI behavior."""
    
    def test_cli_runs_and_exits(self):
        """Verify CLI runs without errors and exits cleanly."""
        result = subprocess.run(
            [sys.executable, "run_observer_cli.py"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd="i:\\argo"
        )
        
        # Should exit successfully
        self.assertEqual(result.returncode, 0, f"CLI exited with error:\n{result.stderr}")
    
    def test_cli_displays_observer_header(self):
        """Verify CLI outputs the observer header."""
        result = subprocess.run(
            [sys.executable, "run_observer_cli.py"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd="i:\\argo"
        )
        
        self.assertIn("ARGO OBSERVER", result.stdout, "Observer header not found")
        self.assertIn("READ-ONLY", result.stdout, "Read-only disclaimer not found")
    
    def test_cli_displays_state_sections(self):
        """Verify CLI displays all state sections."""
        result = subprocess.run(
            [sys.executable, "run_observer_cli.py"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd="i:\\argo"
        )
        
        stdout = result.stdout
        
        # Check for all major sections
        self.assertIn("ITERATION STATE", stdout)
        self.assertIn("LAST INTERACTION", stdout)
        self.assertIn("SESSION MEMORY", stdout)
        self.assertIn("LATENCY STATISTICS", stdout)
    
    def test_cli_does_not_import_input_trigger(self):
        """Verify CLI doesn't import InputTrigger (no control)."""
        with open("run_observer_cli.py", "r", encoding="utf-8") as f:
            content = f.read()
            
        # Should NOT have these imports (control-related)
        self.assertNotIn("from core.input_trigger", content)
        self.assertNotIn("InputTrigger", content.replace("# InputTrigger", ""))
    
    def test_cli_does_not_import_stt(self):
        """Verify CLI doesn't import SpeechToText (no control)."""
        with open("run_observer_cli.py", "r", encoding="utf-8") as f:
            content = f.read()
            
        # Should NOT have SpeechToText imports
        self.assertNotIn("from core.speech_to_text", content)
        self.assertNotIn("SpeechToText", content.replace("# SpeechToText", ""))
    
    def test_cli_does_not_import_output_sink(self):
        """Verify CLI doesn't import OutputSink (no control)."""
        with open("run_observer_cli.py", "r", encoding="utf-8") as f:
            content = f.read()
            
        # Should NOT have OutputSink imports
        self.assertNotIn("from core.output_sink", content)
        self.assertNotIn("OutputSink", content.replace("# OutputSink", ""))
    
    def test_cli_uses_observer_snapshot(self):
        """Verify CLI uses observer_snapshot module (read-only)."""
        with open("run_observer_cli.py", "r", encoding="utf-8") as f:
            content = f.read()
            
        # SHOULD use observer_snapshot
        self.assertIn("observer_snapshot", content)
        self.assertIn("get_snapshot", content)


if __name__ == "__main__":
    unittest.main()
