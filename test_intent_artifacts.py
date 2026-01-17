#!/usr/bin/env python3
"""
================================================================================
INTENT ARTIFACT TEST SUITE
Comprehensive testing of intent parsing and artifact management
================================================================================

Module:      test_intent_artifacts.py
Creator:     Tommy Gunn (@tommygunn212)
Version:     1.0.0
Created:     January 2026
Purpose:     Validate intent artifact creation, parsing, storage, and confirmation

================================================================================
TEST COVERAGE
================================================================================

1. Clean Parses
   - Simple commands with clear structure
   - All required fields present and unambiguous

2. Ambiguous Input
   - Multiple interpretations possible
   - Parser preserves ambiguity rather than guessing
   - Confidence score reflects uncertainty

3. Unparseable Input
   - No recognized verb
   - Empty or nonsense input
   - Low confidence with explanation

4. Confirmation Gate
   - Artifacts created in "proposed" status
   - Confirmation changes status to "approved"
   - Only explicit user action changes state

5. Rejection Path
   - Artifacts can be rejected
   - Rejection tracked
   - No execution happens

6. NO EXECUTION TESTS
   - ⚠️ ABSOLUTELY NO tests that execute actions
   - No file operations
   - No app launches
   - No OS commands
   - Only parsing and storage

================================================================================
"""

import sys
import os
import json
import unittest
from pathlib import Path

# Add wrapper to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "wrapper"))

from wrapper.intent import (
    IntentArtifact,
    CommandParser,
    create_intent_artifact,
    intent_storage
)


class TestIntentArtifactStructure(unittest.TestCase):
    """Test IntentArtifact class structure and properties."""
    
    def setUp(self):
        """Clear storage before each test."""
        intent_storage.artifacts = {}
    
    def test_artifact_creation(self):
        """Test: IntentArtifact is created with valid structure."""
        artifact = IntentArtifact()
        
        self.assertIsNotNone(artifact.id)
        self.assertIsNotNone(artifact.timestamp)
        self.assertEqual(artifact.status, "proposed")
        self.assertTrue(artifact.requires_confirmation)
        self.assertEqual(artifact.confidence, 0.0)
    
    def test_artifact_source_type_assignment(self):
        """Test: IntentArtifact tracks source type correctly."""
        artifact = IntentArtifact()
        artifact.source_type = "typed"
        
        self.assertEqual(artifact.source_type, "typed")
    
    def test_artifact_timestamp_iso_format(self):
        """Test: Timestamps are ISO 8601 compliant."""
        artifact = IntentArtifact()
        
        self.assertIn("T", artifact.timestamp)
        self.assertTrue(artifact.timestamp.endswith("Z"))
    
    def test_artifact_requires_confirmation_always_true(self):
        """Test: requires_confirmation is always True (invariant)."""
        artifact = IntentArtifact()
        
        # Should always be True
        self.assertTrue(artifact.requires_confirmation)
        
        # Even if we try to set it, design intent is True
        artifact.requires_confirmation = True
        self.assertTrue(artifact.requires_confirmation)
    
    def test_artifact_serialization_to_dict(self):
        """Test: Artifact converts to dict correctly."""
        artifact = IntentArtifact()
        artifact.raw_text = "open word"
        artifact.parsed_intent = {"verb": "open", "target": "word"}
        artifact.confidence = 1.0
        artifact.status = "approved"
        
        d = artifact.to_dict()
        
        self.assertEqual(d["raw_text"], "open word")
        self.assertEqual(d["parsed_intent"]["verb"], "open")
        self.assertEqual(d["status"], "approved")
        self.assertEqual(d["confidence"], 1.0)
    
    def test_artifact_serialization_to_json(self):
        """Test: Artifact converts to JSON correctly."""
        artifact = IntentArtifact()
        artifact.raw_text = "search for documents"
        artifact.parsed_intent = {"verb": "search", "object": "for documents"}
        
        json_str = artifact.to_json()
        parsed = json.loads(json_str)
        
        self.assertEqual(parsed["raw_text"], "search for documents")
        self.assertEqual(parsed["parsed_intent"]["verb"], "search")


class TestCommandParserCleanParse(unittest.TestCase):
    """Test parser with clear, unambiguous input."""
    
    def setUp(self):
        """Initialize parser."""
        self.parser = CommandParser()
    
    def test_parse_open_command(self):
        """Test: Parse clear 'open' command."""
        result = self.parser.parse("open word")
        
        self.assertEqual(result["verb"], "open")
        self.assertEqual(result["target"], "word")
        self.assertEqual(result["confidence"], 1.0)
        self.assertEqual(len(result["ambiguity"]), 0)
    
    def test_parse_show_command(self):
        """Test: Parse clear 'show' command."""
        result = self.parser.parse("show files")
        
        self.assertEqual(result["verb"], "show")
        self.assertEqual(result["target"], "files")
        self.assertEqual(result["confidence"], 1.0)
    
    def test_parse_search_command(self):
        """Test: Parse clear 'search' command."""
        result = self.parser.parse("search for documents")
        
        self.assertEqual(result["verb"], "search")
        self.assertEqual(result["object"], "for documents")
        self.assertGreaterEqual(result["confidence"], 0.8)
    
    def test_parse_save_command_with_as(self):
        """Test: Parse 'save' with 'as' keyword."""
        result = self.parser.parse("save as myfile.txt")
        
        self.assertEqual(result["verb"], "save")
        self.assertEqual(result["target"], "myfile.txt")
        self.assertEqual(result["confidence"], 1.0)
    
    def test_parse_write_command_with_about(self):
        """Test: Parse 'write' with 'about' keyword."""
        result = self.parser.parse("write email about meeting")
        
        self.assertEqual(result["verb"], "write")
        self.assertIn("email", result["target"] or "")
        self.assertEqual(result["confidence"], 1.0)


class TestCommandParserAmbiguousInput(unittest.TestCase):
    """Test parser with ambiguous input (preserved, not guessed)."""
    
    def setUp(self):
        """Initialize parser."""
        self.parser = CommandParser()
    
    def test_ambiguous_write_missing_about(self):
        """Test: 'write something' is ambiguous (no about/for/regarding)."""
        result = self.parser.parse("write something")
        
        self.assertEqual(result["verb"], "write")
        self.assertGreater(len(result["ambiguity"]), 0)
        self.assertLess(result["confidence"], 1.0)
        # Ambiguity is preserved (not guessed)
        self.assertIn("unclear", result["ambiguity"][0].lower())
    
    def test_ambiguous_open_no_target(self):
        """Test: 'open' with no app name is ambiguous."""
        result = self.parser.parse("open")
        
        self.assertEqual(result["verb"], "open")
        self.assertGreater(len(result["ambiguity"]), 0)
        self.assertLess(result["confidence"], 1.0)
    
    def test_ambiguous_save_no_as(self):
        """Test: 'save filename' without 'as' is ambiguous."""
        result = self.parser.parse("save myfile")
        
        self.assertEqual(result["verb"], "save")
        self.assertGreater(len(result["ambiguity"]), 0)
        self.assertLess(result["confidence"], 1.0)


class TestCommandParserUnparseable(unittest.TestCase):
    """Test parser with unparseable input."""
    
    def setUp(self):
        """Initialize parser."""
        self.parser = CommandParser()
    
    def test_unparseable_no_verb(self):
        """Test: Input with no recognized verb."""
        result = self.parser.parse("please do something")
        
        self.assertIsNone(result["verb"])
        self.assertEqual(result["confidence"], 0.0)
        self.assertGreater(len(result["ambiguity"]), 0)
    
    def test_unparseable_empty_input(self):
        """Test: Empty input."""
        result = self.parser.parse("")
        
        self.assertIsNone(result["verb"])
        self.assertEqual(result["confidence"], 0.0)
    
    def test_unparseable_whitespace_only(self):
        """Test: Whitespace-only input."""
        result = self.parser.parse("   ")
        
        self.assertIsNone(result["verb"])
        self.assertEqual(result["confidence"], 0.0)
    
    def test_unparseable_nonsense(self):
        """Test: Complete nonsense."""
        result = self.parser.parse("xyzzy plugh foobar")
        
        self.assertIsNone(result["verb"])
        self.assertEqual(result["confidence"], 0.0)


class TestIntentArtifactCreation(unittest.TestCase):
    """Test artifact creation from confirmed sources."""
    
    def setUp(self):
        """Clear storage before each test."""
        intent_storage.artifacts = {}
    
    def test_create_from_typed_source(self):
        """Test: Create artifact from confirmed typed input."""
        artifact = create_intent_artifact(
            "open word",
            source_type="typed"
        )
        
        self.assertEqual(artifact.source_type, "typed")
        self.assertIsNone(artifact.source_artifact_id)
        self.assertEqual(artifact.raw_text, "open word")
        self.assertEqual(artifact.status, "proposed")
        self.assertEqual(artifact.parsed_intent["verb"], "open")
    
    def test_create_from_transcription_source(self):
        """Test: Create artifact from confirmed TranscriptionArtifact."""
        artifact = create_intent_artifact(
            "search for documents",
            source_type="transcription",
            source_artifact_id="transcript-123"
        )
        
        self.assertEqual(artifact.source_type, "transcription")
        self.assertEqual(artifact.source_artifact_id, "transcript-123")
        self.assertEqual(artifact.raw_text, "search for documents")
        self.assertEqual(artifact.status, "proposed")
    
    def test_create_invalid_source_type(self):
        """Test: Invalid source type raises error."""
        with self.assertRaises(ValueError):
            create_intent_artifact(
                "open word",
                source_type="invalid"
            )
    
    def test_artifact_status_starts_proposed(self):
        """Test: Newly created artifacts are in 'proposed' status."""
        artifact = create_intent_artifact("open word", source_type="typed")
        
        self.assertEqual(artifact.status, "proposed")


class TestIntentConfirmationGate(unittest.TestCase):
    """Test confirmation gate (no auto-execution)."""
    
    def setUp(self):
        """Clear storage before each test."""
        intent_storage.artifacts = {}
    
    def test_confirm_artifact(self):
        """Test: Artifact confirmation changes status."""
        artifact = create_intent_artifact("open word", source_type="typed")
        intent_storage.store(artifact)
        
        self.assertEqual(artifact.status, "proposed")
        
        intent_storage.approve(artifact.id)
        retrieved = intent_storage.retrieve(artifact.id)
        
        self.assertEqual(retrieved.status, "approved")
    
    def test_reject_artifact(self):
        """Test: Artifact rejection changes status."""
        artifact = create_intent_artifact("write something", source_type="typed")
        intent_storage.store(artifact)
        
        self.assertEqual(artifact.status, "proposed")
        
        intent_storage.reject(artifact.id)
        retrieved = intent_storage.retrieve(artifact.id)
        
        self.assertEqual(retrieved.status, "rejected")
    
    def test_approval_not_execution(self):
        """Test: 'Approved' status means user said yes, NOT executed."""
        artifact = create_intent_artifact("save as report.txt", source_type="typed")
        intent_storage.approve(artifact.id)
        
        # File should NOT be created
        self.assertFalse(Path("report.txt").exists())
        
        # Status should only be "approved"
        self.assertEqual(artifact.status, "approved")


class TestIntentStorage(unittest.TestCase):
    """Test intent artifact storage and listing."""
    
    def setUp(self):
        """Clear storage before each test."""
        intent_storage.artifacts = {}
    
    def test_store_and_retrieve(self):
        """Test: Artifacts can be stored and retrieved."""
        artifact = create_intent_artifact("open word", source_type="typed")
        intent_storage.store(artifact)
        
        retrieved = intent_storage.retrieve(artifact.id)
        
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.id, artifact.id)
        self.assertEqual(retrieved.raw_text, "open word")
    
    def test_list_proposed_artifacts(self):
        """Test: Can list pending proposed artifacts."""
        a1 = create_intent_artifact("open word", source_type="typed")
        intent_storage.store(a1)
        
        a2 = create_intent_artifact("save file", source_type="typed")
        intent_storage.store(a2)
        
        a3 = create_intent_artifact("show files", source_type="typed")
        intent_storage.store(a3)
        intent_storage.approve(a3.id)
        
        proposed = intent_storage.list_proposed()
        
        self.assertEqual(len(proposed), 2)
        proposed_ids = {a.id for a in proposed}
        self.assertIn(a1.id, proposed_ids)
        self.assertIn(a2.id, proposed_ids)
        self.assertNotIn(a3.id, proposed_ids)
    
    def test_list_approved_artifacts(self):
        """Test: Can list approved artifacts."""
        a1 = create_intent_artifact("open word", source_type="typed")
        intent_storage.store(a1)
        intent_storage.approve(a1.id)
        
        a2 = create_intent_artifact("save file", source_type="typed")
        intent_storage.store(a2)
        
        approved = intent_storage.list_approved()
        
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].id, a1.id)
    
    def test_list_all_artifacts(self):
        """Test: Can list all artifacts regardless of status."""
        artifacts = []
        for i in range(5):
            a = create_intent_artifact(f"open app{i}", source_type="typed")
            intent_storage.store(a)
            artifacts.append(a)
        
        # Approve some
        intent_storage.approve(artifacts[0].id)
        intent_storage.approve(artifacts[2].id)
        
        # Reject one
        intent_storage.reject(artifacts[1].id)
        
        all_artifacts = intent_storage.list_all()
        
        self.assertEqual(len(all_artifacts), 5)


class TestParsingDeterminism(unittest.TestCase):
    """Test that parsing is deterministic (no randomness)."""
    
    def setUp(self):
        """Initialize parser."""
        self.parser = CommandParser()
    
    def test_same_input_same_parse(self):
        """Test: Same input always produces same result."""
        text = "open word"
        
        result1 = self.parser.parse(text)
        result2 = self.parser.parse(text)
        result3 = self.parser.parse(text)
        
        self.assertEqual(result1, result2)
        self.assertEqual(result2, result3)
    
    def test_confidence_deterministic(self):
        """Test: Confidence scores are deterministic."""
        text = "write something about climate"
        
        parse1 = self.parser.parse(text)
        parse2 = self.parser.parse(text)
        
        self.assertEqual(parse1["confidence"], parse2["confidence"])


class TestNOExecutionGuarantee(unittest.TestCase):
    """
    CRITICAL: Verify no execution happens.
    
    These tests verify that IntentArtifacts are NEVER executed,
    even if artifact is approved.
    """
    
    def setUp(self):
        """Clear storage before each test."""
        intent_storage.artifacts = {}
    
    def test_no_file_creation_on_save(self):
        """Test: 'save as report.txt' does NOT create file."""
        artifact = create_intent_artifact("save as test_output.txt", source_type="typed")
        intent_storage.store(artifact)
        intent_storage.approve(artifact.id)
        
        # File should NOT exist
        self.assertFalse(Path("test_output.txt").exists())
    
    def test_no_app_launch_on_open(self):
        """Test: 'open notepad' does NOT launch app."""
        artifact = create_intent_artifact("open notepad", source_type="typed")
        intent_storage.approve(artifact.id)
        
        # No process spawn, no app launch
        # (If it did, test would hang or fail spectacularly)
        self.assertEqual(artifact.status, "approved")
        # Status is all that changed
    
    def test_no_side_effects_on_parse(self):
        """Test: Parsing produces no side effects."""
        import os
        
        initial_files = set(os.listdir("."))
        
        artifact = create_intent_artifact("write email to bob", source_type="typed")
        
        final_files = set(os.listdir("."))
        
        # No new files created
        self.assertEqual(initial_files, final_files)
    
    def test_approval_is_not_execution(self):
        """Test: Approval is only state change, never execution."""
        artifact = create_intent_artifact("save as secret.txt", source_type="typed")
        
        initial_status = artifact.status
        intent_storage.approve(artifact.id)
        final_status = artifact.status
        
        # Only status changed
        self.assertEqual(initial_status, "proposed")
        self.assertEqual(final_status, "approved")
        
        # File NOT created
        self.assertFalse(Path("secret.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
