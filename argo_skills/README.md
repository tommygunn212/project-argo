# argo_skills

Tools Argo wrote for herself. Every `*.py` file here is loaded when a voice
session starts (so a new skill is live the next time you say "Hey Argo" in a
fresh session - no full restart needed).

A skill file looks like this:

```python
"""One line about what this does."""

async def flip_coin(sides: int = 2) -> str:
    """Flip a coin or roll a die. Use when Tommy asks for a coin flip or a roll."""
    ...

TOOLS = [flip_coin]
```

Rules the loader enforces: functions are `async`, have type hints and a
docstring (the docstring is what tells the model when to use the tool), and
their names don't collide with a built-in tool. A skill that fails to import is
skipped and logged - it can never stop Argo starting. Each call has a time
limit and any error is returned to the model as text instead of crashing the
session.

Build one by voice: "Argo, figure out how to do that and add it."
Log of what was added: `runtime/logs/skills.jsonl`. Old versions of a skill are
kept in `argo_skills/_history/`.
