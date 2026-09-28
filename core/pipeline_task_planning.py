"""Multi-step task planning and executor composition for the classic pipeline."""

from __future__ import annotations

from tools.email_sender import send_email
from tools.filesystem import format_file_list_for_speech, search_files
from tools.home_assistant import execute_smart_home_command, parse_smart_home_command
from tools.reminders import (
    add_calendar_event,
    add_reminder,
    format_calendar_for_speech,
    format_reminders_for_speech,
    list_calendar_events,
    list_reminders,
    parse_calendar_request,
    parse_reminder_request,
)
from tools.task_planner import (
    execute_plan,
    format_plan_for_speech,
    generate_plan_rules,
    generate_plan_with_llm,
)
from tools.vision import describe_screen, read_screen_error
from tools.writing import (
    build_blog_prompt,
    build_email_prompt,
    draft_blog,
    draft_email,
    save_note,
)


class PipelineTaskPlanningMixin:
    # ── Task Planner Handler ──────────────────────────────────────

    def _respond_with_task_plan(self, intent, user_text, interaction_id, replay_mode, overrides) -> bool:
        """Execute a multi-step task plan."""
        self.logger.info(f"[PLANNER] Multi-step request: {user_text}")

        # Try rule-based first, then LLM
        plan = generate_plan_rules(user_text)
        if plan is None:
            plan = generate_plan_with_llm(
                user_text,
                llm_call=lambda p: self._writing_llm_call(p, interaction_id),
            )

        if plan is None:
            return self._deliver_canonical_response(
                "I couldn't break that into steps. Try rephrasing with clearer actions.",
                interaction_id, replay_mode, overrides,
            )

        # Build executor callbacks that use ARGO's existing tools
        executor = self._build_plan_executor(interaction_id)
        plan = execute_plan(plan, executor)
        response = format_plan_for_speech(plan)
        return self._deliver_canonical_response(response, interaction_id, replay_mode, overrides)

    def _build_plan_executor(self, interaction_id: str) -> dict:
        """Build a dict of action_name → callable for the task planner."""

        def _search_files(params, prev):
            query = params.get("query", prev or "")
            files = search_files(query)
            return format_file_list_for_speech(files)

        def _describe_screen(params, prev):
            return describe_screen()

        def _read_screen_error(params, prev):
            return read_screen_error()

        def _do_draft_email(params, prev):
            subject = params.get("subject", "")
            to = params.get("to", "")
            body = params.get("body", "") or prev or ""
            if not body:
                return "No content to put in the email."
            prompt = build_email_prompt(to_name=to, subject=subject, body_hint=body)
            generated = self._writing_llm_call(prompt, interaction_id)
            if generated:
                draft_email(to_name=to, subject=subject, body=generated)
                return f"Email draft created for {to} about {subject}."
            return "Failed to generate email content."

        def _do_send_email(params, prev):
            content = params.get("body", "") or prev or ""
            to_addr = params.get("to", "")
            subject = params.get("subject", "")
            if to_addr and content:
                ok = send_email(to_addr, subject or "From ARGO", content)
                return "Email sent." if ok else "Failed to send email."
            return "Missing email address or content."

        def _save_note_fn(params, prev):
            content = params.get("text", "") or prev or ""
            if content:
                save_note(content)
                return "Note saved."
            return "Nothing to save."

        def _set_reminder_fn(params, prev):
            msg = params.get("message", "") or prev or ""
            time_str = params.get("time", "")
            if msg:
                parsed = parse_reminder_request(f"remind me to {msg} {time_str}")
                due = parsed.get("due_at")
                if due:
                    add_reminder(msg, due)
                    return f"Reminder set: {msg}."
            return "Couldn't set the reminder."

        def _add_calendar_fn(params, prev):
            title = params.get("title", "") or prev or ""
            if title:
                parsed = parse_calendar_request(f"schedule {title}")
                start = parsed.get("start_at")
                if start:
                    add_calendar_event(title, start)
                    return f"Calendar event added: {title}."
            return "Couldn't add the event."

        def _list_reminders_fn(params, prev):
            rems = list_reminders()
            return format_reminders_for_speech(rems)

        def _list_calendar_fn(params, prev):
            evts = list_calendar_events()
            return format_calendar_for_speech(evts)

        def _smart_home_fn(params, prev):
            cmd = params.get("command", "") or prev or ""
            if cmd:
                result = execute_smart_home_command(parse_smart_home_command(cmd))
                return result.get("message", str(result))
            return "No smart home command specified."

        def _llm_generate_fn(params, prev):
            text = params.get("text", "") or prev or ""
            if text:
                return self._writing_llm_call(text, interaction_id)
            return ""

        def _summarize_fn(params, prev):
            text = params.get("text", "") or prev or ""
            if text:
                return self._writing_llm_call(f"Summarize this concisely:\n\n{text}", interaction_id)
            return "Nothing to summarize."

        def _web_search_fn(params, prev):
            query = params.get("query", "") or prev or ""
            if query:
                return self._writing_llm_call(f"Answer concisely: {query}", interaction_id)
            return ""

        def _draft_blog_fn(params, prev):
            topic = params.get("topic", "") or prev or ""
            if topic:
                prompt = build_blog_prompt(topic=topic, body_hint=topic)
                generated = self._writing_llm_call(prompt, interaction_id)
                if generated:
                    draft_blog(topic=topic, body=generated)
                    return f"Blog draft created about {topic}."
            return "No topic for blog post."

        return {
            "search_files": _search_files,
            "describe_screen": _describe_screen,
            "read_screen_error": _read_screen_error,
            "draft_email": _do_draft_email,
            "send_email": _do_send_email,
            "save_note": _save_note_fn,
            "set_reminder": _set_reminder_fn,
            "add_calendar_event": _add_calendar_fn,
            "list_reminders": _list_reminders_fn,
            "list_calendar": _list_calendar_fn,
            "smart_home": _smart_home_fn,
            "llm_generate": _llm_generate_fn,
            "summarize": _summarize_fn,
            "web_search": _web_search_fn,
            "draft_blog": _draft_blog_fn,
        }

