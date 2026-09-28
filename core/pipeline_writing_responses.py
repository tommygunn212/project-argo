"""Draft generation and editing responses for the classic pipeline."""

from __future__ import annotations

from tools.writing import (
    build_blog_prompt,
    build_document_prompt,
    build_edit_prompt,
    build_email_prompt,
    draft_blog,
    draft_document,
    draft_email,
    get_latest_draft,
    parse_blog_request,
    parse_document_request,
    parse_edit_instruction,
    parse_email_request,
    save_note,
    update_draft,
)


class PipelineWritingResponseMixin:
    def _writing_llm_call(self, prompt: str, interaction_id: str) -> str:
        """Quick LLM generation for writing tasks (emails, blogs, edits)."""
        try:
            return self.generate_response(
                prompt,
                interaction_id=interaction_id,
                use_convo_buffer=False,
            )
        except Exception as e:
            self.logger.error(f"[WRITING] LLM call failed: {e}")
            return ""

    def _respond_with_write_email(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Draft an email using LLM and voice input."""
        self.logger.info(f"[WRITING] Write email: {user_text}")
        parsed = parse_email_request(user_text)
        to_name = parsed.get("to", "")
        subject = parsed.get("subject", "")

        if not subject:
            subject = user_text  # fallback to full text as subject hint

        prompt = build_email_prompt(to_name=to_name or "someone", subject=subject)
        self.transition_state("THINKING", interaction_id=interaction_id, source="llm")
        body = self._writing_llm_call(prompt, interaction_id)
        if not body.strip():
            return self._deliver_canonical_response(
                "I couldn't generate the email. Try again?",
                interaction_id, replay_mode, overrides,
            )

        draft = draft_email(
            to=to_name or "TBD",
            subject=subject,
            body=body.strip(),
        )
        desktop_status = self._desktop_write_status(draft.content, user_text, interaction_id)
        response = f"Email draft saved. Subject: {subject}."
        if to_name:
            response = f"Email to {to_name} drafted. Subject: {subject}."
        response += f" {draft.word_count} words."
        if desktop_status:
            response += f" {desktop_status}"
        response += " Say 'read the draft' to hear it, or 'send the email' when ready."
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_write_document(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Draft a letter or document using LLM and optionally place it in a writable app."""
        self.logger.info(f"[WRITING] Write document: {user_text}")
        parsed = parse_document_request(user_text)
        title = parsed.get("title", "") or user_text
        recipient = parsed.get("recipient", "")
        doc_type = parsed.get("doc_type", "document")

        prompt = build_document_prompt(title=title, doc_type=doc_type, recipient=recipient)
        self.transition_state("THINKING", interaction_id=interaction_id, source="llm")
        body = self._writing_llm_call(prompt, interaction_id)
        if not body.strip():
            return self._deliver_canonical_response(
                "I couldn't generate that draft. Try again?",
                interaction_id, replay_mode, overrides,
            )

        draft = draft_document(
            title=title,
            body=body.strip(),
            doc_type=doc_type,
            recipient=recipient,
        )
        desktop_status = self._desktop_write_status(draft.content, user_text, interaction_id)
        noun = "Letter" if doc_type == "letter" else "Document"
        response = f"{noun} drafted. Title: {title}. {draft.word_count} words."
        if desktop_status:
            response += f" {desktop_status}"
        response += " Say 'read the draft' if you want it back out loud."
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_write_blog(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Draft a blog post using LLM."""
        self.logger.info(f"[WRITING] Write blog: {user_text}")
        parsed = parse_blog_request(user_text)
        title = parsed.get("title", "")
        if not title:
            title = user_text

        prompt = build_blog_prompt(title=title)
        self.transition_state("THINKING", interaction_id=interaction_id, source="llm")
        body = self._writing_llm_call(prompt, interaction_id)
        if not body.strip():
            return self._deliver_canonical_response(
                "I couldn't generate the blog post. Try again?",
                interaction_id, replay_mode, overrides,
            )

        draft = draft_blog(title=title, body=body.strip())
        response = f"Blog post drafted: {title}. {draft.word_count} words. Say 'read the draft' to hear it, or 'edit the blog' to revise."
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_write_note(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Save a quick voice note."""
        self.logger.info(f"[WRITING] Save note: {user_text}")
        # Strip the trigger words to get the note content
        import re as _re
        content = _re.sub(
            r"^(take\s+a\s+note|save\s+a\s+note|make\s+a\s+note|save\s+this\s+idea|write\s+(this\s+)?down|note\s+that|jot\s+(this\s+)?down|capture\s+(this\s+)?idea)\s*[:\-]?\s*",
            "", user_text, flags=_re.IGNORECASE,
        ).strip()
        if not content:
            content = user_text

        draft = save_note(content)
        desktop_status = self._desktop_write_status(draft.content, user_text, interaction_id)
        response = f"Note saved. {draft.word_count} words."
        if desktop_status:
            response += f" {desktop_status}"
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _respond_with_edit_draft(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Edit the most recent draft using LLM."""
        self.logger.info(f"[WRITING] Edit draft: {user_text}")
        parsed = parse_edit_instruction(user_text)
        category = parsed.get("category") or None
        instruction = parsed.get("instruction", user_text)

        draft = get_latest_draft(category=category)
        if not draft:
            return self._deliver_canonical_response(
                "No drafts found to edit. Write something first!",
                interaction_id, replay_mode, overrides,
            )

        prompt = build_edit_prompt(draft.content, instruction)
        self.transition_state("THINKING", interaction_id=interaction_id, source="llm")
        new_content = self._writing_llm_call(prompt, interaction_id)
        if not new_content.strip():
            return self._deliver_canonical_response(
                "I couldn't apply that edit. Try again?",
                interaction_id, replay_mode, overrides,
            )

        update_draft(draft, new_content.strip())
        response = f"Draft updated. Now {draft.word_count} words. Say 'read the draft' to hear changes."
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

