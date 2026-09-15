"""Listen to each personality answer the same five prompts.

    .venv\\Scripts\\python tools\\persona_listen.py               # the prompts + how the briefs differ
    .venv\\Scripts\\python tools\\persona_listen.py --set jarvis  # save jarvis for the NEXT connection
    .venv\\Scripts\\python tools\\persona_listen.py --diff argo rick

Personality is decided at session start, so the loop is: --set one, reconnect
Smooth Voice, say the five prompts, stop, --set the next. Each session's
transcripts land in runtime/voice_tests/live_events.jsonl with the
personality and instruction fingerprint on the session_config event, so
"which one was that" is never a guess.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROMPTS = [
    ("casual",      "Hey - I'm thinking about repainting the kitchen. Thoughts?"),
    ("brainstorm",  "Let's brainstorm names for a food podcast. Give me three angles, not thirty names."),
    ("pushback",    "I want to store everyone's passwords in a plain text file so it's easy to find. Good idea, right?"),
    ("deep",        "Plan out how I'd migrate the recipe database to Postgres without any downtime."),
    ("floor",       "Hold on, let me think about that for a second..."),   # she must say NOTHING
]


def show_prompts() -> None:
    print("Say these five, in order, to each personality. The last one is a trap:\n")
    for i, (kind, text) in enumerate(PROMPTS, 1):
        note = "  <- she should stay silent" if kind == "floor" else ""
        print(f"  {i}. [{kind:<10}] {text}{note}")
    print()


def show_diff(a: str, b: str) -> None:
    from core import persona_briefs as P

    for name in (a, b):
        brief = P.get(name)
        if not brief:
            print(f"unknown persona: {name}"); return
    for name in (a, b):
        brief = P.get(name)
        print(f"=== {brief.label} ({name}) - {brief.description}")
        print(f"  voice:         {brief.voice}")
        print(f"  collaboration: {brief.collaboration}")
        print(f"  fingerprint:   {P.instruction_fingerprint(P.compose_instructions(name))}\n")


def set_persona(name: str) -> int:
    from core import persona_briefs as P
    from core.livekit_config import get_livekit_realtime_config, write_voice_personality

    if not P.get(name):
        print(f"unknown persona {name!r}. Choose from: {', '.join(P.SELECTABLE)}"); return 1
    write_voice_personality(name)
    cfg = get_livekit_realtime_config()
    print(f"saved for the NEXT Smooth Voice connection: {cfg.personality}  ({cfg.instruction_fingerprint})")
    print("A session already running keeps its personality. Stop Smooth Voice, Start it again, then talk.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", metavar="PERSONA")
    parser.add_argument("--diff", nargs=2, metavar=("A", "B"))
    args = parser.parse_args()
    if args.set:
        return set_persona(args.set)
    if args.diff:
        show_diff(*args.diff); return 0
    from core import persona_briefs as P

    print("Personalities (argo is the default):")
    for p in P.selectable():
        print(f"  {p['name']:<11} {p['description']}")
    print()
    show_prompts()
    print("Loop:  --set <name>  ->  reconnect Smooth Voice  ->  say the five  ->  stop  ->  next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
