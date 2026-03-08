"""
ARGO Task Planner — "Teach ARGO to execute multi-step tasks."

Decomposes complex voice requests into ordered steps, executes each
sequentially using ARGO's existing tool modules, and reports results.
"""

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger("argo.tools.task_planner")


# ---------------------------------------------------------------------------
# Step definitions
# ---------------------------------------------------------------------------

AVAILABLE_ACTIONS = {
    "search_files":       "Search for files by name or type",
    "describe_screen":    "Take a screenshot and describe what's on screen",
    "read_screen_error":  "Take a screenshot and read any error messages",
    "send_email":         "Send an email",
    "draft_email":        "Draft an email",
    "draft_blog":         "Draft a blog post",
    "save_note":          "Save a note",
    "set_reminder":       "Set a reminder",
    "add_calendar_event": "Add a calendar event",
    "list_reminders":     "List active reminders",
    "list_calendar":      "List upcoming calendar events",
    "smart_home":         "Control a smart home device",
    "web_search":         "Answer a question using knowledge",
    "llm_generate":       "Generate text using the LLM",
    "summarize":          "Summarize provided text",
}


class PlanStep:
    """A single step in a task plan."""
    __slots__ = ("action", "params", "description", "status", "result")

    def __init__(self, action: str, params: dict, description: str = ""):
        self.action = action
        self.params = params
        self.description = description or f"Execute {action}"
        self.status = "pending"   # pending | running | done | failed
        self.result = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "params": self.params,
            "description": self.description,
            "status": self.status,
            "result": self.result[:200] if self.result else "",
        }


class TaskPlan:
    """An ordered plan of steps to execute."""
    __slots__ = ("goal", "steps", "status")

    def __init__(self, goal: str, steps: list[PlanStep]):
        self.goal = goal
        self.steps = steps
        self.status = "pending"  # pending | running | done | partial | failed

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
        }


# ---------------------------------------------------------------------------
# LLM-based plan generation
# ---------------------------------------------------------------------------

def generate_plan_with_llm(user_request: str, llm_call) -> Optional[TaskPlan]:
    """Use the LLM to decompose a complex request into a TaskPlan.

    Args:
        user_request: The user's natural language request.
        llm_call: A callable(prompt: str) -> str for LLM generation.

    Returns:
        A TaskPlan or None if planning fails.
    """
    actions_desc = "\n".join(f'  - "{k}": {v}' for k, v in AVAILABLE_ACTIONS.items())

    prompt = f"""You are ARGO's task planner. Break the following user request into sequential steps.

Available actions:
{actions_desc}

Rules:
- Output ONLY a JSON array of step objects, nothing else.
- Each step: {{"action": "<action_name>", "params": {{}}, "description": "<what this step does>"}}
- params should contain relevant data extracted from the request (e.g., "to", "subject", "body", "query", "message", "time", "device", "text").
- If a later step needs the result of an earlier step, set "use_previous": true in params.
- Keep it to 2-5 steps. Don't over-decompose.
- If the request is simple (single action), return just one step.

User request: "{user_request}"

JSON array:"""

    try:
        raw = llm_call(prompt)
        # Extract JSON from response (may have markdown fences)
        json_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not json_match:
            logger.error(f"[PLANNER] No JSON array in LLM response: {raw[:200]}")
            return None

        steps_data = json.loads(json_match.group())
        if not isinstance(steps_data, list) or not steps_data:
            return None

        steps = []
        for sd in steps_data:
            action = sd.get("action", "llm_generate")
            if action not in AVAILABLE_ACTIONS:
                action = "llm_generate"
            params = sd.get("params", {})
            if not isinstance(params, dict):
                params = {}
            desc = sd.get("description", f"Execute {action}")
            steps.append(PlanStep(action=action, params=params, description=desc))

        return TaskPlan(goal=user_request, steps=steps)
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.error(f"[PLANNER] Failed to parse plan: {e}")
        return None


# ---------------------------------------------------------------------------
# Rule-based plan generation (fallback / common patterns)
# ---------------------------------------------------------------------------

def generate_plan_rules(user_request: str) -> Optional[TaskPlan]:
    """Try to build a plan from common multi-step patterns without LLM.

    Returns None if no pattern matches (caller should use LLM planner).
    """
    lower = user_request.lower()

    # Pattern: "research X and email/send it to Y"
    m = re.search(r"\b(?:research|look up|find out about)\s+(.+?)\s+(?:and|then)\s+(?:email|send|draft)\b.*?\bto\s+(\w+)", lower)
    if m:
        topic = m.group(1).strip()
        recipient = m.group(2).strip()
        return TaskPlan(goal=user_request, steps=[
            PlanStep("llm_generate", {"text": f"Research and summarize: {topic}"}, f"Research {topic}"),
            PlanStep("draft_email", {"to": recipient, "subject": topic, "use_previous": True}, f"Draft email to {recipient}"),
        ])

    # Pattern: "find X files and tell me about them"
    m = re.search(r"\b(?:find|search|look for)\s+(.+?)\s+(?:and|then)\s+(?:tell|describe|summarize)", lower)
    if m:
        query = m.group(1).strip()
        return TaskPlan(goal=user_request, steps=[
            PlanStep("search_files", {"query": query}, f"Search for {query}"),
            PlanStep("summarize", {"use_previous": True}, "Summarize the results"),
        ])

    # Pattern: "look at my screen and then ..."
    m = re.search(r"\b(?:look at|check|read)\s+(?:my\s+)?screen\s+(?:and|then)\s+(.+)", lower)
    if m:
        followup = m.group(1).strip()
        steps = [PlanStep("describe_screen", {}, "Capture and analyze screen")]
        if re.search(r"\bemail|send|draft\b", followup):
            steps.append(PlanStep("draft_email", {"use_previous": True}, "Draft email about screen content"))
        elif re.search(r"\bnote|save\b", followup):
            steps.append(PlanStep("save_note", {"use_previous": True}, "Save a note about screen content"))
        elif re.search(r"\bremind\b", followup):
            steps.append(PlanStep("set_reminder", {"use_previous": True, "message": followup}, "Set a reminder"))
        else:
            steps.append(PlanStep("llm_generate", {"text": followup, "use_previous": True}, followup))
        return TaskPlan(goal=user_request, steps=steps)

    # Pattern: "remind me to X and also add it to my calendar"
    m = re.search(r"\bremind\s+me\s+to\s+(.+?)\s+(?:and\s+)?(?:also\s+)?(?:add|put|schedule)\s+(?:it\s+)?(?:on|to|in)\s+(?:my\s+)?calendar", lower)
    if m:
        task = m.group(1).strip()
        return TaskPlan(goal=user_request, steps=[
            PlanStep("set_reminder", {"message": task}, f"Set reminder: {task}"),
            PlanStep("add_calendar_event", {"title": task, "use_previous": True}, f"Add calendar event: {task}"),
        ])

    return None


# ---------------------------------------------------------------------------
# Plan execution
# ---------------------------------------------------------------------------

def execute_plan(plan: TaskPlan, executor) -> TaskPlan:
    """Execute a TaskPlan using the provided executor callbacks.

    Args:
        plan: The TaskPlan to execute.
        executor: An object/dict with callables keyed by action name.
                  Each callable: (params: dict, previous_result: str) -> str

    Returns:
        The plan with updated step statuses and results.
    """
    plan.status = "running"
    previous_result = ""

    for step in plan.steps:
        step.status = "running"
        logger.info(f"[PLANNER] Executing step: {step.description}")

        try:
            if step.params.get("use_previous") and previous_result:
                step.params["previous_result"] = previous_result

            action_fn = None
            if isinstance(executor, dict):
                action_fn = executor.get(step.action)
            else:
                action_fn = getattr(executor, step.action, None)

            if action_fn is None:
                step.status = "failed"
                step.result = f"Unknown action: {step.action}"
                logger.warning(f"[PLANNER] No executor for action: {step.action}")
                continue

            result = action_fn(step.params, previous_result)
            step.result = str(result) if result else ""
            step.status = "done"
            previous_result = step.result

        except Exception as e:
            step.status = "failed"
            step.result = f"Error: {e}"
            logger.error(f"[PLANNER] Step failed: {step.description} — {e}")

    # Determine overall plan status
    statuses = [s.status for s in plan.steps]
    if all(s == "done" for s in statuses):
        plan.status = "done"
    elif all(s == "failed" for s in statuses):
        plan.status = "failed"
    else:
        plan.status = "partial"

    return plan


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_plan_for_speech(plan: TaskPlan) -> str:
    """Format a completed plan into a speakable summary."""
    if plan.status == "failed":
        return f"I tried to {plan.goal} but all steps failed. Let me know what to try differently."

    done_steps = [s for s in plan.steps if s.status == "done"]
    failed_steps = [s for s in plan.steps if s.status == "failed"]

    # Get the last successful result as the main content
    last_result = ""
    for s in reversed(done_steps):
        if s.result:
            last_result = s.result
            break

    if plan.status == "done":
        if last_result:
            return f"Done. {last_result}"
        return f"All {len(plan.steps)} steps completed for: {plan.goal}."

    # Partial
    summary = f"Completed {len(done_steps)} of {len(plan.steps)} steps."
    if failed_steps:
        summary += f" {len(failed_steps)} failed."
    if last_result:
        summary += f" {last_result}"
    return summary


def format_plan_preview_for_speech(plan: TaskPlan) -> str:
    """Format a plan preview (before execution) for speech."""
    step_descs = [f"Step {i+1}: {s.description}" for i, s in enumerate(plan.steps)]
    return f"I'll break this into {len(plan.steps)} steps. " + ". ".join(step_descs) + "."


# ---------------------------------------------------------------------------
# Voice command detection
# ---------------------------------------------------------------------------

def is_multi_step_request(text: str) -> bool:
    """Check if a voice command looks like a multi-step task."""
    lower = text.lower()
    # Must contain a connector indicating sequencing
    connectors = [" and then ", " then ", " and also ", " after that ", " followed by ", " plus "]
    if not any(c in lower for c in connectors):
        return False

    # Must reference at least two action domains
    domains_found = 0
    domain_patterns = [
        r"\b(email|send|draft|write)\b",
        r"\b(remind|reminder)\b",
        r"\b(calendar|schedule|event|appointment)\b",
        r"\b(search|find|look for|locate)\b",
        r"\b(screen|screenshot|look at)\b",
        r"\b(note|save|jot)\b",
        r"\b(research|look up|summarize)\b",
        r"\b(light|thermostat|smart home|turn on|turn off)\b",
    ]
    for pattern in domain_patterns:
        if re.search(pattern, lower):
            domains_found += 1
    return domains_found >= 2
