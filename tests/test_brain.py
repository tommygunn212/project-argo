"""
Test ARGO Brain: 3-Layer Memory System
Run: python -m pytest tests/test_brain.py -v
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from core.brain import ArgoBrain


@pytest.fixture
def brain(tmp_path):
    """Fresh brain with temp database for each test."""
    db = tmp_path / "test_brain.db"
    b = ArgoBrain(db_path=db)
    return b


class TestShortTermMemory:
    def test_empty_initially(self, brain):
        assert brain.short_term.last_user == ""
        assert brain.short_term.last_assistant == ""
        assert brain.get_short_term_block() == ""

    def test_stores_last_exchange(self, brain):
        brain.update_short_term("what is jazz?", "A form of American music.")
        assert brain.short_term.last_user == "what is jazz?"
        assert brain.short_term.last_assistant == "A form of American music."

    def test_only_keeps_last_exchange(self, brain):
        brain.update_short_term("first question", "first answer")
        brain.update_short_term("second question", "second answer")
        assert brain.short_term.last_user == "second question"
        assert brain.short_term.last_assistant == "second answer"

    def test_context_block_format(self, brain):
        brain.update_short_term("what is jazz?", "A form of music.")
        block = brain.get_short_term_block()
        assert "User: what is jazz?" in block
        assert "ARGO: A form of music." in block


class TestWorkingMemory:
    def test_initial_state(self, brain):
        assert brain.working.current_topic == ""
        assert brain.working.current_task == ""
        assert brain.working.current_mood == "neutral"

    def test_topic_detection(self, brain):
        brain.update_working_state("let's fix the argo voice system")
        # "voice" is matched before "argo" in signal ordering
        assert brain.working.current_topic == "voice_system"

    def test_topic_shift(self, brain):
        brain.update_working_state("tell me about music")
        assert brain.working.current_topic == "music"
        brain.update_working_state("now let's talk about cooking")
        assert brain.working.current_topic == "cooking"

    def test_task_detection(self, brain):
        brain.update_working_state("debug the audio latency")
        assert "debugging" in brain.working.current_task

    def test_mood_detection(self, brain):
        brain.update_working_state("this is awesome, let's go!")
        assert brain.working.current_mood == "excited"

    def test_working_block_format(self, brain):
        brain.update_working_state("build the memory system for argo")
        block = brain.get_working_block()
        assert "Topic:" in block

    def test_persistence_across_restart(self, brain):
        brain.update_working_state("working on argo memory system")
        # Create new brain pointing to same DB
        brain2 = ArgoBrain(db_path=brain.db_path)
        assert brain2.working.current_topic == brain.working.current_topic


class TestLongTermMemory:
    def test_store_and_retrieve(self, brain):
        brain.store_fact("relationship", "Jesse", "is_user_son", "son")
        facts = brain.retrieve_relevant_facts("who is Jesse?")
        assert any(f.subject == "Jesse" for f in facts)

    def test_deduplication(self, brain):
        brain.store_fact("identity", "Tommy", "is", "a filmmaker")
        brain.store_fact("identity", "Tommy", "is", "a filmmaker")  # duplicate
        all_facts = brain.get_all_facts()
        tommy_is = [f for f in all_facts if f.subject == "Tommy" and f.relation == "is"]
        assert len(tommy_is) == 1

    def test_multiple_values_same_relation(self, brain):
        brain.store_fact("project", "Tommy", "built", "ARGO")
        brain.store_fact("project", "Tommy", "built", "ChefsByte")
        all_facts = brain.get_all_facts()
        built = [f for f in all_facts if f.relation == "built"]
        assert len(built) == 2

    def test_delete_fact(self, brain):
        brain.store_fact("relationship", "Bandit", "is_user_dog", "dog")
        assert brain.delete_fact("Bandit", "is_user_dog")
        facts = brain.get_all_facts()
        assert not any(f.subject == "Bandit" for f in facts)

    def test_relevance_scoring(self, brain):
        brain.store_fact("relationship", "Bandit", "is_user_dog", "dog")
        brain.store_fact("project", "Tommy", "built", "ChefsByte")
        brain.store_fact("preference", "user", "likes", "jazz")
        
        # "dog" query should rank Bandit highest
        facts = brain.retrieve_relevant_facts("tell me about the dog", limit=2)
        assert facts[0].subject == "Bandit"

    def test_seed_facts(self, brain):
        count = brain.seed_facts([
            {"category": "identity", "subject": "Tommy", "relation": "is_the_user", "value": "owner"},
            {"category": "relationship", "subject": "Jesse", "relation": "is_user_son", "value": "son"},
        ])
        assert count == 2
        assert brain.get_fact_count() == 2


class TestMemoryCommands:
    def test_remember_dog(self, brain):
        cmd = brain.parse_memory_command("remember my dog's name is Bandit")
        assert cmd is not None
        assert cmd["action"] == "store"
        assert cmd["subject"] == "Bandit"

    def test_remember_son(self, brain):
        cmd = brain.parse_memory_command("remember my son is Jesse")
        assert cmd is not None
        assert cmd["action"] == "store"
        assert "Jesse" in cmd["subject"]

    def test_remember_like(self, brain):
        cmd = brain.parse_memory_command("remember that I like sarcasm")
        assert cmd is not None
        assert cmd["action"] == "store"
        assert cmd["category"] == "preference"

    def test_recall_all(self, brain):
        cmd = brain.parse_memory_command("what do you know about me?")
        assert cmd is not None
        assert cmd["action"] == "recall_all"

    def test_recall_subject(self, brain):
        cmd = brain.parse_memory_command("what do you remember about Jesse?")
        assert cmd is not None
        assert cmd["action"] == "recall_subject"
        assert "jesse" in cmd["subject"].lower()

    def test_forget(self, brain):
        cmd = brain.parse_memory_command("forget about Bandit")
        assert cmd is not None
        assert cmd["action"] == "forget"

    def test_implicit_name(self, brain):
        cmd = brain.parse_memory_command("my name is Tommy")
        assert cmd is not None
        assert cmd["action"] == "store"
        assert cmd["subject"] == "Tommy"

    def test_no_command(self, brain):
        cmd = brain.parse_memory_command("what is the weather today?")
        assert cmd is None

    def test_built_something(self, brain):
        cmd = brain.parse_memory_command("remember I built ChefsByte")
        assert cmd is not None
        assert cmd["action"] == "store"
        assert "chefsbyte" in cmd["value"].lower()


class TestPromptContext:
    def test_empty_context(self, brain):
        ctx = brain.get_prompt_context("hello")
        # No facts stored, should be minimal
        assert isinstance(ctx, str)

    def test_full_context_assembly(self, brain):
        # Seed facts
        brain.store_fact("relationship", "Jesse", "is_user_son", "son")
        brain.store_fact("relationship", "Bandit", "is_user_dog", "dog")
        brain.store_fact("preference", "user", "likes", "sarcasm")
        
        # Set working state
        brain.update_working_state("let's build the argo memory system")
        
        # Set short-term
        brain.update_short_term("switch to gpt mini", "Done, switched to GPT-4o-mini")
        
        # Get context
        ctx = brain.get_prompt_context("how should I handle memory?")
        
        assert "KNOWN FACTS" in ctx
        assert "CURRENT STATE" in ctx
        assert "LAST EXCHANGE" in ctx
        assert "switch to gpt mini" in ctx

    def test_context_is_small(self, brain):
        """Context should be ~200 tokens, not 1500."""
        brain.store_fact("identity", "Tommy", "is_the_user", "owner")
        brain.store_fact("relationship", "Jesse", "is_user_son", "son")
        brain.store_fact("preference", "user", "likes", "sarcasm")
        brain.update_working_state("building memory system")
        brain.update_short_term("hello", "hey there")
        
        ctx = brain.get_prompt_context("tell me about yourself")
        # Rough token estimate: ~4 chars per token
        estimated_tokens = len(ctx) / 4
        assert estimated_tokens < 400, f"Context too large: ~{estimated_tokens:.0f} tokens"


class TestEpisodes:
    def test_store_episode(self, brain):
        eid = brain.store_episode("Tommy switched to GPT-4o-mini for speed", topic="argo_development", emotion="excited")
        assert eid > 0

    def test_retrieve_episodes(self, brain):
        brain.store_episode("Started building memory system", topic="argo_development")
        brain.store_episode("Seeded first facts", topic="argo_development")
        episodes = brain.get_recent_episodes(limit=2)
        assert len(episodes) == 2

    def test_episode_count(self, brain):
        brain.store_episode("Test episode 1")
        brain.store_episode("Test episode 2")
        assert brain.get_episode_count() == 2


class TestSpeechOutput:
    def test_format_all_facts_empty(self, brain):
        output = brain.format_all_facts_for_speech()
        assert "don't have anything" in output

    def test_format_all_facts_with_data(self, brain):
        brain.store_fact("identity", "Tommy", "is_the_user", "owner")
        brain.store_fact("relationship", "Bandit", "is_user_dog", "dog")
        brain.store_fact("preference", "user", "likes", "sarcasm")
        
        output = brain.format_all_facts_for_speech()
        assert "Tommy" in output
        assert "Bandit" in output
        assert "sarcasm" in output
