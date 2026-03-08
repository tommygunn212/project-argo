"""
ARGO Writing & Productivity System

Handles: emails, blog posts, voice notes, draft editing, spreadsheet export,
document search — all triggered by voice.

Storage:
  argo_data/drafts/emails/     — email drafts
  argo_data/drafts/blogs/      — blog post drafts
  argo_data/drafts/notes/      — quick voice notes
  argo_data/drafts/docs/       — general documents
  argo_data/published/         — final versions
  argo_data/exports/           — spreadsheet exports
"""

import csv
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("ARGO.Writing")

# ── Workspace paths ───────────────────────────────────────────────────

BASE_DIR = Path("argo_data")
DRAFTS_DIR = BASE_DIR / "drafts"
EMAIL_DIR = DRAFTS_DIR / "emails"
BLOG_DIR = DRAFTS_DIR / "blogs"
NOTES_DIR = DRAFTS_DIR / "notes"
DOCS_DIR = DRAFTS_DIR / "docs"
PUBLISHED_DIR = BASE_DIR / "published"
EXPORTS_DIR = BASE_DIR / "exports"

ALL_DIRS = [EMAIL_DIR, BLOG_DIR, NOTES_DIR, DOCS_DIR, PUBLISHED_DIR, EXPORTS_DIR]


def ensure_workspace():
    """Create the writing workspace directories if they don't exist."""
    for d in ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


ensure_workspace()


# ── Draft Management ──────────────────────────────────────────────────

def _timestamp_slug() -> str:
    return datetime.now().strftime("%Y_%m_%d_%H%M%S")


def _safe_filename(text: str, max_len: int = 40) -> str:
    """Turn arbitrary text into a safe filename slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower().strip())
    slug = slug.strip("_")[:max_len]
    return slug or "untitled"


class Draft:
    """Represents a single draft document."""

    def __init__(self, path: Path):
        self.path = path

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def category(self) -> str:
        return self.path.parent.name

    @property
    def content(self) -> str:
        return self.path.read_text(encoding="utf-8") if self.path.exists() else ""

    @content.setter
    def content(self, text: str):
        self.path.write_text(text, encoding="utf-8")

    @property
    def created(self) -> str:
        if self.path.exists():
            ts = self.path.stat().st_ctime
            return datetime.fromtimestamp(ts).strftime("%B %d, %Y at %I:%M %p")
        return "unknown"

    @property
    def word_count(self) -> int:
        return len(self.content.split())

    def summary(self, max_words: int = 30) -> str:
        words = self.content.split()
        if len(words) <= max_words:
            return self.content
        return " ".join(words[:max_words]) + "..."

    def __repr__(self):
        return f"Draft({self.category}/{self.name})"


# ── Email Drafting ────────────────────────────────────────────────────

def draft_email(
    to: str,
    subject: str,
    body: str,
    from_name: str = "Tommy",
) -> Draft:
    """Create an email draft file."""
    ensure_workspace()
    slug = _safe_filename(subject)
    filename = f"email_{_timestamp_slug()}_{slug}.txt"
    path = EMAIL_DIR / filename

    content = (
        f"To: {to}\n"
        f"Subject: {subject}\n"
        f"From: {from_name}\n"
        f"Date: {datetime.now().strftime('%B %d, %Y')}\n"
        f"---\n\n"
        f"{body}\n"
    )
    path.write_text(content, encoding="utf-8")
    logger.info(f"[WRITING] Email draft created: {path}")
    return Draft(path)


def parse_email_request(text: str) -> Dict[str, str]:
    """
    Parse voice command into email components.

    Examples:
      "write an email to Paul about organizing the photo drives"
      "draft an email to Jesse about dinner plans"
      "email Sarah about the project update"
      "send an email to me about the meeting notes"
    """
    result = {"to": "", "subject": "", "raw": text}

    # Extract recipient
    to_match = re.search(
        r"(?:to|for)\s+([a-zA-Z][a-zA-Z\s.'-]+?)(?:\s+about|\s+regarding|\s+saying|\s+that|\s+with|\s*$)",
        text, re.IGNORECASE,
    )
    if not to_match:
        # Fallback: "email Sarah" or "to Sarah" (no trailing context word)
        to_match = re.search(
            r"(?:to|for)\s+([a-zA-Z][a-zA-Z.'-]+)",
            text, re.IGNORECASE,
        )
    if not to_match:
        # Fallback: "email {Name}" pattern (direct object after email verb)
        to_match = re.search(
            r"\b(?:email|mail)\s+([A-Z][a-zA-Z.'-]+)",
            text,
        )
    if to_match:
        result["to"] = to_match.group(1).strip().rstrip(",.")

    # Extract subject/topic
    about_match = re.search(
        r"(?:about|regarding|on|with subject)\s+(.+)",
        text, re.IGNORECASE,
    )
    if about_match:
        result["subject"] = about_match.group(1).strip().rstrip(".,!?")

    return result


# ── Blog Post Drafting ────────────────────────────────────────────────

def draft_blog(
    title: str,
    body: str,
    tags: Optional[List[str]] = None,
) -> Draft:
    """Create a blog post draft."""
    ensure_workspace()
    slug = _safe_filename(title)
    filename = f"blog_{_timestamp_slug()}_{slug}.md"
    path = BLOG_DIR / filename

    tag_line = ""
    if tags:
        tag_line = f"tags: {', '.join(tags)}\n"

    content = (
        f"---\n"
        f"title: {title}\n"
        f"date: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"author: Tommy\n"
        f"{tag_line}"
        f"---\n\n"
        f"# {title}\n\n"
        f"{body}\n"
    )
    path.write_text(content, encoding="utf-8")
    logger.info(f"[WRITING] Blog draft created: {path}")
    return Draft(path)


def parse_blog_request(text: str) -> Dict[str, str]:
    """
    Parse voice command into blog components.

    Examples:
      "write a blog post about the night the fire marshal shut down the Cat Club"
      "draft a blog about fishing in Alaska"
    """
    result = {"title": "", "raw": text}

    about_match = re.search(
        r"(?:about|on|titled|called)\s+(.+)",
        text, re.IGNORECASE,
    )
    if about_match:
        result["title"] = about_match.group(1).strip().rstrip(".,!?")

    return result


# ── Voice Notes ───────────────────────────────────────────────────────

def save_note(content: str, title: Optional[str] = None) -> Draft:
    """Save a quick voice note."""
    ensure_workspace()
    if title:
        slug = _safe_filename(title)
    else:
        # Use first few words as title
        words = content.split()[:5]
        slug = _safe_filename(" ".join(words))
    filename = f"note_{_timestamp_slug()}_{slug}.txt"
    path = NOTES_DIR / filename
    path.write_text(content, encoding="utf-8")
    logger.info(f"[WRITING] Note saved: {path}")
    return Draft(path)


# ── Draft Editing ─────────────────────────────────────────────────────

def get_latest_draft(category: Optional[str] = None) -> Optional[Draft]:
    """Get the most recent draft, optionally filtered by category."""
    search_dirs = []
    if category == "email":
        search_dirs = [EMAIL_DIR]
    elif category == "blog":
        search_dirs = [BLOG_DIR]
    elif category == "note":
        search_dirs = [NOTES_DIR]
    elif category == "doc":
        search_dirs = [DOCS_DIR]
    else:
        search_dirs = [EMAIL_DIR, BLOG_DIR, NOTES_DIR, DOCS_DIR]

    latest = None
    latest_time = 0.0
    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file() and f.stat().st_mtime > latest_time:
                latest_time = f.stat().st_mtime
                latest = f
    return Draft(latest) if latest else None


def list_drafts(category: Optional[str] = None, limit: int = 5) -> List[Draft]:
    """List recent drafts."""
    search_dirs = []
    if category == "email":
        search_dirs = [EMAIL_DIR]
    elif category == "blog":
        search_dirs = [BLOG_DIR]
    elif category == "note":
        search_dirs = [NOTES_DIR]
    elif category == "doc":
        search_dirs = [DOCS_DIR]
    else:
        search_dirs = [EMAIL_DIR, BLOG_DIR, NOTES_DIR, DOCS_DIR]

    all_files = []
    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file():
                all_files.append((f.stat().st_mtime, f))
    all_files.sort(key=lambda x: x[0], reverse=True)
    return [Draft(f) for _, f in all_files[:limit]]


def search_drafts(query: str, limit: int = 5) -> List[Draft]:
    """Search across all drafts by content keyword matching."""
    query_lower = query.lower()
    query_words = set(re.findall(r"[a-z]{2,}", query_lower))
    results = []

    for d in ALL_DIRS[:4]:  # drafts only, not published/exports
        if not d.exists():
            continue
        for f in d.iterdir():
            if not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8").lower()
                # Score by word overlap
                content_words = set(re.findall(r"[a-z]{2,}", content))
                overlap = len(query_words & content_words)
                if overlap > 0 or query_lower in content:
                    score = overlap + (5 if query_lower in content else 0)
                    results.append((score, f))
            except Exception:
                continue

    results.sort(key=lambda x: x[0], reverse=True)
    return [Draft(f) for _, f in results[:limit]]


def update_draft(draft: Draft, new_content: str) -> Draft:
    """Overwrite a draft with new content."""
    draft.content = new_content
    logger.info(f"[WRITING] Draft updated: {draft.path}")
    return draft


def publish_draft(draft: Draft) -> Path:
    """Move a draft to the published folder."""
    ensure_workspace()
    dest = PUBLISHED_DIR / draft.path.name
    draft.path.rename(dest)
    logger.info(f"[WRITING] Published: {dest}")
    return dest


# ── Spreadsheet Export ────────────────────────────────────────────────

def export_to_csv(
    data: List[Dict[str, str]],
    filename: Optional[str] = None,
    title: Optional[str] = None,
) -> Path:
    """
    Export structured data to CSV.

    Args:
        data: List of dicts, each dict is a row
        filename: Optional custom filename
        title: Optional descriptive title for auto-naming
    """
    ensure_workspace()
    if not filename:
        slug = _safe_filename(title or "export")
        filename = f"export_{_timestamp_slug()}_{slug}.csv"
    path = EXPORTS_DIR / filename

    if not data:
        path.write_text("No data\n", encoding="utf-8")
        return path

    fieldnames = list(data[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

    logger.info(f"[WRITING] CSV exported: {path} ({len(data)} rows)")
    return path


def export_brain_facts_to_csv() -> Path:
    """Export all brain facts to a CSV file."""
    from core.brain import get_brain
    brain = get_brain()
    facts = brain.get_all_facts()
    data = [
        {
            "category": f.category,
            "subject": f.subject,
            "relation": f.relation,
            "value": f.value,
            "confidence": str(f.confidence),
            "created_at": f.created_at,
        }
        for f in facts
    ]
    return export_to_csv(data, title="brain_facts")


# ── Prompt Builders (for LLM-powered writing) ────────────────────────

def build_email_prompt(
    to_name: str,
    subject: str,
    tone: str = "professional but friendly",
    context: str = "",
    from_name: str = "Tommy",
) -> str:
    """Build an LLM prompt for drafting an email."""
    return (
        f"Write a short email from {from_name} to {to_name}.\n"
        f"Subject: {subject}\n"
        f"Tone: {tone}\n"
        f"{'Context: ' + context + chr(10) if context else ''}"
        f"Keep it concise — 3-5 sentences max. No formal greeting like 'Dear'.\n"
        f"Start with 'Hey {to_name},' or just jump in.\n"
        f"End with a simple sign-off. No signature block.\n"
        f"Return ONLY the email body text, nothing else."
    )


def build_blog_prompt(
    title: str,
    tone: str = "storytelling, conversational",
    style_notes: str = "",
) -> str:
    """Build an LLM prompt for drafting a blog post."""
    return (
        f"Write a blog post.\n"
        f"Title: {title}\n"
        f"Tone: {tone}\n"
        f"{'Style: ' + style_notes + chr(10) if style_notes else ''}"
        f"Write in first person. Use vivid details and storytelling.\n"
        f"No bullet points or lists unless absolutely needed.\n"
        f"Keep it 300-500 words.\n"
        f"Return ONLY the blog post text, nothing else."
    )


def build_edit_prompt(current_text: str, instruction: str) -> str:
    """Build an LLM prompt for editing an existing draft."""
    return (
        f"Here is a draft:\n\n"
        f"---\n{current_text}\n---\n\n"
        f"Edit instruction: {instruction}\n\n"
        f"Apply the edit and return ONLY the updated text, nothing else."
    )


def build_note_expansion_prompt(raw_note: str) -> str:
    """Build an LLM prompt to expand rough voice notes into organized text."""
    return (
        f"Here are rough voice notes:\n\n"
        f"{raw_note}\n\n"
        f"Clean these up into organized, readable text.\n"
        f"Keep the original meaning and voice.\n"
        f"Fix grammar but keep it conversational.\n"
        f"Return ONLY the cleaned text, nothing else."
    )


# ── Parse Voice Commands ──────────────────────────────────────────────

def parse_edit_instruction(text: str) -> Dict[str, str]:
    """
    Parse voice edit commands.

    Examples:
      "make it shorter"
      "make it funnier"
      "add a paragraph about Jesse"
      "change the tone to serious"
      "fix the grammar"
    """
    result = {"instruction": text, "category": ""}

    # Detect which draft category to edit
    if re.search(r"\b(email|mail)\b", text, re.IGNORECASE):
        result["category"] = "email"
    elif re.search(r"\b(blog|post|article)\b", text, re.IGNORECASE):
        result["category"] = "blog"
    elif re.search(r"\b(note|notes)\b", text, re.IGNORECASE):
        result["category"] = "note"

    # Clean up the instruction
    instruction = text
    instruction = re.sub(r"^(edit|change|update|modify|fix|revise)\s+(the\s+)?(last\s+)?(draft|email|blog|note|post)\s*", "", instruction, flags=re.IGNORECASE)
    instruction = re.sub(r"^(make\s+)", "make ", instruction, flags=re.IGNORECASE)
    if instruction.strip():
        result["instruction"] = instruction.strip()

    return result


def parse_spreadsheet_request(text: str) -> Dict[str, str]:
    """
    Parse voice spreadsheet/export commands.

    Examples:
      "export my facts to a spreadsheet"
      "create a spreadsheet of my memories"
      "export brain data"
    """
    result = {"data_source": "brain_facts", "raw": text}

    if re.search(r"\b(drafts?|documents?|writings?)\b", text, re.IGNORECASE):
        result["data_source"] = "drafts"
    elif re.search(r"\b(notes?)\b", text, re.IGNORECASE):
        result["data_source"] = "notes"
    elif re.search(r"\b(facts?|memor|brain|know)\b", text, re.IGNORECASE):
        result["data_source"] = "brain_facts"

    return result


def export_drafts_to_csv(category: Optional[str] = None) -> Path:
    """Export draft metadata to CSV."""
    drafts = list_drafts(category=category, limit=100)
    data = [
        {
            "name": d.name,
            "category": d.category,
            "word_count": str(d.word_count),
            "created": d.created,
            "preview": d.summary(20),
        }
        for d in drafts
    ]
    return export_to_csv(data, title=f"drafts_{category or 'all'}")
