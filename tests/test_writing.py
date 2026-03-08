"""
Tests for the ARGO Writing & Productivity System.

Tests:
  - Draft creation (email, blog, note)
  - Draft listing / searching / reading
  - Draft editing
  - CSV export
  - Email request parsing
  - Blog request parsing
  - Edit instruction parsing
  - Spreadsheet request parsing
  - Intent parser routing (WRITE_EMAIL, WRITE_BLOG, WRITE_NOTE, etc.)
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.writing import (
    BASE_DIR,
    DRAFTS_DIR,
    EMAIL_DIR,
    BLOG_DIR,
    NOTES_DIR,
    EXPORTS_DIR,
    draft_email,
    draft_blog,
    save_note,
    get_latest_draft,
    list_drafts,
    search_drafts,
    update_draft,
    export_to_csv,
    parse_email_request,
    parse_blog_request,
    parse_edit_instruction,
    parse_spreadsheet_request,
    build_email_prompt,
    build_blog_prompt,
    build_edit_prompt,
    build_note_expansion_prompt,
    ensure_workspace,
    Draft,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def temp_workspace(tmp_path, monkeypatch):
    """Redirect all writing to a temp directory."""
    import tools.writing as w

    old_base = w.BASE_DIR
    old_drafts = w.DRAFTS_DIR
    old_email = w.EMAIL_DIR
    old_blog = w.BLOG_DIR
    old_notes = w.NOTES_DIR
    old_docs = w.DOCS_DIR
    old_published = w.PUBLISHED_DIR
    old_exports = w.EXPORTS_DIR

    w.BASE_DIR = tmp_path / "argo_data"
    w.DRAFTS_DIR = w.BASE_DIR / "drafts"
    w.EMAIL_DIR = w.DRAFTS_DIR / "emails"
    w.BLOG_DIR = w.DRAFTS_DIR / "blogs"
    w.NOTES_DIR = w.DRAFTS_DIR / "notes"
    w.DOCS_DIR = w.DRAFTS_DIR / "docs"
    w.PUBLISHED_DIR = w.BASE_DIR / "published"
    w.EXPORTS_DIR = w.BASE_DIR / "exports"
    w.ALL_DIRS = [w.EMAIL_DIR, w.BLOG_DIR, w.NOTES_DIR, w.DOCS_DIR, w.PUBLISHED_DIR, w.EXPORTS_DIR]

    w.ensure_workspace()

    yield tmp_path

    # Restore
    w.BASE_DIR = old_base
    w.DRAFTS_DIR = old_drafts
    w.EMAIL_DIR = old_email
    w.BLOG_DIR = old_blog
    w.NOTES_DIR = old_notes
    w.DOCS_DIR = old_docs
    w.PUBLISHED_DIR = old_published
    w.EXPORTS_DIR = old_exports
    w.ALL_DIRS = [old_email, old_blog, old_notes, old_docs, old_published, old_exports]


# ── Email Draft Tests ─────────────────────────────────────────────────

class TestEmailDraft:
    def test_draft_email_creates_file(self):
        draft = draft_email(to="Paul", subject="Photo drives", body="Hey, about those drives...")
        assert draft.path.exists()
        assert "Photo drives" in draft.content
        assert "Paul" in draft.content
        assert draft.word_count > 0

    def test_draft_email_filename_pattern(self):
        draft = draft_email(to="Jesse", subject="Dinner plans", body="Let's eat!")
        assert "email_" in draft.path.name
        assert "dinner_plans" in draft.path.name
        assert draft.path.suffix == ".txt"

    def test_draft_email_has_headers(self):
        draft = draft_email(to="Sarah", subject="Meeting", body="Tomorrow at 3?")
        content = draft.content
        assert "To: Sarah" in content
        assert "Subject: Meeting" in content
        assert "---" in content


class TestBlogDraft:
    def test_draft_blog_creates_file(self):
        draft = draft_blog(title="The Night at the Cat Club", body="It was a wild night...")
        assert draft.path.exists()
        assert "Cat Club" in draft.content
        assert draft.word_count > 0

    def test_draft_blog_has_frontmatter(self):
        draft = draft_blog(title="Fishing in Alaska", body="Content here", tags=["travel", "fishing"])
        content = draft.content
        assert "title: Fishing in Alaska" in content
        assert "tags: travel, fishing" in content
        assert "# Fishing in Alaska" in content

    def test_draft_blog_filename_pattern(self):
        draft = draft_blog(title="Test Post", body="Body text")
        assert "blog_" in draft.path.name
        assert draft.path.suffix == ".md"


class TestNotes:
    def test_save_note_creates_file(self):
        draft = save_note("Remember to call back the studio about the edit")
        assert draft.path.exists()
        assert "studio" in draft.content

    def test_save_note_with_title(self):
        draft = save_note("Buy groceries: eggs, milk, bread", title="Grocery list")
        assert "grocery_list" in draft.path.name

    def test_save_note_auto_title(self):
        draft = save_note("The quick brown fox jumped")
        assert "note_" in draft.path.name


# ── Draft Management Tests ────────────────────────────────────────────

class TestDraftManagement:
    def test_get_latest_draft(self):
        draft_email(to="A", subject="First", body="1")
        import time; time.sleep(0.05)
        d2 = draft_email(to="B", subject="Second", body="2")
        latest = get_latest_draft(category="email")
        assert latest is not None
        assert latest.path == d2.path

    def test_get_latest_draft_no_category(self):
        draft_blog(title="Blog", body="text")
        import time; time.sleep(0.05)
        note = save_note("latest note")
        latest = get_latest_draft()
        assert latest is not None
        assert latest.path == note.path

    def test_get_latest_draft_empty(self):
        assert get_latest_draft() is None

    def test_list_drafts(self):
        draft_email(to="A", subject="E1", body="1")
        draft_blog(title="B1", body="2")
        save_note("N1")
        drafts = list_drafts()
        assert len(drafts) == 3

    def test_list_drafts_by_category(self):
        draft_email(to="A", subject="E1", body="1")
        draft_email(to="B", subject="E2", body="2")
        draft_blog(title="B1", body="3")
        emails = list_drafts(category="email")
        assert len(emails) == 2
        blogs = list_drafts(category="blog")
        assert len(blogs) == 1

    def test_list_drafts_limit(self):
        for i in range(10):
            save_note(f"Note {i}")
        notes = list_drafts(category="note", limit=3)
        assert len(notes) == 3

    def test_search_drafts(self):
        draft_email(to="Jesse", subject="Dinner", body="Let's get tacos tonight")
        draft_blog(title="Alaska", body="The fishing was incredible")
        save_note("Remember tacos for Jesse")
        results = search_drafts("tacos")
        assert len(results) >= 1
        # All results should contain tacos
        for r in results:
            assert "tacos" in r.content.lower() or "tacos" in r.name.lower()

    def test_search_drafts_no_results(self):
        draft_email(to="A", subject="Test", body="Hello")
        results = search_drafts("xyznonexistent")
        assert len(results) == 0

    def test_update_draft(self):
        draft = save_note("Original content")
        assert "Original" in draft.content
        update_draft(draft, "Updated content here")
        assert "Updated" in draft.content
        assert "Original" not in draft.content


# ── Draft Object Tests ────────────────────────────────────────────────

class TestDraftObject:
    def test_draft_properties(self):
        d = draft_email(to="Test", subject="Props", body="One two three four five")
        assert d.name  # not empty
        assert d.category == "emails"
        assert d.word_count >= 5
        assert d.created  # non-empty string

    def test_draft_summary_short(self):
        d = save_note("Short note")
        assert d.summary() == "Short note"

    def test_draft_summary_truncated(self):
        long_text = " ".join([f"word{i}" for i in range(100)])
        d = save_note(long_text)
        summary = d.summary(max_words=10)
        assert summary.endswith("...")
        assert len(summary.split()) < 15


# ── CSV Export Tests ──────────────────────────────────────────────────

class TestCSVExport:
    def test_export_to_csv(self):
        data = [
            {"name": "Alice", "age": "30"},
            {"name": "Bob", "age": "25"},
        ]
        path = export_to_csv(data, title="people")
        assert path.exists()
        content = path.read_text()
        assert "name,age" in content
        assert "Alice,30" in content
        assert "Bob,25" in content

    def test_export_empty_data(self):
        path = export_to_csv([], title="empty")
        assert path.exists()
        assert "No data" in path.read_text()

    def test_export_filename(self):
        data = [{"col": "val"}]
        path = export_to_csv(data, title="test export")
        assert "test_export" in path.name
        assert path.suffix == ".csv"


# ── Parser Tests ──────────────────────────────────────────────────────

class TestEmailParsing:
    def test_parse_basic(self):
        result = parse_email_request("write an email to Paul about organizing the photo drives")
        assert result["to"].lower() == "paul"
        assert "photo drives" in result["subject"].lower()

    def test_parse_with_regarding(self):
        result = parse_email_request("draft an email to Jesse regarding dinner plans")
        assert result["to"].lower() == "jesse"
        assert "dinner" in result["subject"].lower()

    def test_parse_no_subject(self):
        result = parse_email_request("email Sarah")
        assert result["to"].lower() == "sarah"

    def test_parse_no_recipient(self):
        result = parse_email_request("write an email about the project")
        assert result["to"] == ""
        assert "project" in result["subject"].lower()


class TestBlogParsing:
    def test_parse_basic(self):
        result = parse_blog_request("write a blog post about the night the fire marshal shut down the Cat Club")
        assert "cat club" in result["title"].lower()

    def test_parse_titled(self):
        result = parse_blog_request("draft a blog titled fishing in Alaska")
        assert "alaska" in result["title"].lower()


class TestEditParsing:
    def test_parse_make_shorter(self):
        result = parse_edit_instruction("make it shorter")
        assert "shorter" in result["instruction"].lower()

    def test_parse_edit_email(self):
        result = parse_edit_instruction("edit the email to be more formal")
        assert result["category"] == "email"

    def test_parse_edit_blog(self):
        result = parse_edit_instruction("revise the blog post")
        assert result["category"] == "blog"


class TestSpreadsheetParsing:
    def test_parse_brain_facts(self):
        result = parse_spreadsheet_request("export my facts to a spreadsheet")
        assert result["data_source"] == "brain_facts"

    def test_parse_drafts(self):
        result = parse_spreadsheet_request("export my drafts to a spreadsheet")
        assert result["data_source"] == "drafts"


# ── Prompt Builder Tests ──────────────────────────────────────────────

class TestPromptBuilders:
    def test_email_prompt(self):
        prompt = build_email_prompt("Paul", "Photo drives")
        assert "Paul" in prompt
        assert "Photo drives" in prompt
        assert "email" in prompt.lower()

    def test_blog_prompt(self):
        prompt = build_blog_prompt("The Night at the Cat Club")
        assert "Cat Club" in prompt
        assert "blog" in prompt.lower()

    def test_edit_prompt(self):
        prompt = build_edit_prompt("Original text here", "make it shorter")
        assert "Original text here" in prompt
        assert "shorter" in prompt

    def test_note_expansion_prompt(self):
        prompt = build_note_expansion_prompt("rough notes here")
        assert "rough notes here" in prompt


# ── Intent Parser Routing Tests ───────────────────────────────────────

class TestIntentRouting:
    @pytest.fixture(autouse=True)
    def setup_parser(self):
        from core.intent_parser import RuleBasedIntentParser, IntentType
        self.parser = RuleBasedIntentParser()
        self.IntentType = IntentType

    def test_write_email_intent(self):
        result = self.parser.parse("write an email to Paul about the photo drives")
        assert result.intent_type == self.IntentType.WRITE_EMAIL

    def test_draft_email_intent(self):
        result = self.parser.parse("draft an email to Jesse about dinner")
        assert result.intent_type == self.IntentType.WRITE_EMAIL

    def test_compose_email_intent(self):
        result = self.parser.parse("compose an email to Sarah about the project")
        assert result.intent_type == self.IntentType.WRITE_EMAIL

    def test_write_blog_intent(self):
        result = self.parser.parse("write a blog post about fishing in Alaska")
        assert result.intent_type == self.IntentType.WRITE_BLOG

    def test_draft_blog_intent(self):
        result = self.parser.parse("draft a blog about the night at the Cat Club")
        assert result.intent_type == self.IntentType.WRITE_BLOG

    def test_take_note_intent(self):
        result = self.parser.parse("take a note remember to call the studio")
        assert result.intent_type == self.IntentType.WRITE_NOTE

    def test_save_note_intent(self):
        result = self.parser.parse("save a note about the meeting")
        assert result.intent_type == self.IntentType.WRITE_NOTE

    def test_jot_down_intent(self):
        result = self.parser.parse("jot down that the delivery is Thursday")
        assert result.intent_type == self.IntentType.WRITE_NOTE

    def test_edit_draft_intent(self):
        result = self.parser.parse("edit the email to be more professional")
        assert result.intent_type == self.IntentType.EDIT_DRAFT

    def test_make_shorter_intent(self):
        result = self.parser.parse("make it shorter the email draft")
        assert result.intent_type == self.IntentType.EDIT_DRAFT

    def test_list_drafts_intent(self):
        result = self.parser.parse("list my drafts")
        assert result.intent_type == self.IntentType.LIST_DRAFTS

    def test_show_drafts_intent(self):
        result = self.parser.parse("show my drafts")
        assert result.intent_type == self.IntentType.LIST_DRAFTS

    def test_read_draft_intent(self):
        result = self.parser.parse("read my last draft")
        assert result.intent_type == self.IntentType.READ_DRAFT

    def test_send_email_intent(self):
        result = self.parser.parse("send that email")
        assert result.intent_type == self.IntentType.SEND_EMAIL

    def test_send_the_draft_intent(self):
        result = self.parser.parse("send the draft")
        assert result.intent_type == self.IntentType.SEND_EMAIL

    def test_search_docs_intent(self):
        result = self.parser.parse("search my documents for tacos")
        assert result.intent_type == self.IntentType.SEARCH_DOCS

    def test_find_email_intent(self):
        result = self.parser.parse("find the email about dinner plans")
        assert result.intent_type == self.IntentType.SEARCH_DOCS

    def test_export_spreadsheet_intent(self):
        result = self.parser.parse("export my facts to a spreadsheet")
        assert result.intent_type == self.IntentType.EXPORT_DATA

    def test_csv_export_intent(self):
        result = self.parser.parse("create a csv of my brain data")
        assert result.intent_type == self.IntentType.EXPORT_DATA

    def test_normal_question_not_writing(self):
        """Ensure normal questions don't trigger writing intents."""
        result = self.parser.parse("what is the capital of France?")
        assert result.intent_type == self.IntentType.QUESTION

    def test_greeting_not_writing(self):
        """Ensure greetings don't trigger writing intents."""
        result = self.parser.parse("hey Argo how are you")
        assert result.intent_type != self.IntentType.WRITE_EMAIL


# ── Email Sender Tests ────────────────────────────────────────────────

class TestEmailSender:
    def test_is_email_configured_false(self, tmp_path, monkeypatch):
        from tools import email_sender as es
        monkeypatch.setattr(es, "CONFIG_PATH", tmp_path / "nonexistent.json")
        assert es.is_email_configured() is False

    def test_is_email_configured_true(self, tmp_path, monkeypatch):
        from tools import email_sender as es
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text('{"email": {"sender_email": "test@gmail.com", "sender_password": "abc123"}}')
        monkeypatch.setattr(es, "CONFIG_PATH", cfg_path)
        assert es.is_email_configured() is True

    def test_send_email_no_config(self, tmp_path, monkeypatch):
        from tools import email_sender as es
        monkeypatch.setattr(es, "CONFIG_PATH", tmp_path / "nonexistent.json")
        result = es.send_email("test@example.com", "Subject", "Body")
        assert result is False

    def test_send_email_invalid_address(self, tmp_path, monkeypatch):
        from tools import email_sender as es
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text('{"email": {"sender_email": "test@gmail.com", "sender_password": "abc123"}}')
        monkeypatch.setattr(es, "CONFIG_PATH", cfg_path)
        result = es.send_email("notanemail", "Subject", "Body")
        assert result is False
