# Working with Claude on ARGO — staying fast and cheap

Written from what actually burned context on this project, not from general
advice. Every item below is something that really happened here.

---

## Start a new chat when any of these is true

Context is a snowball. It does not melt, and everything you say gets re-read
against everything already in it.

- [ ] **The task changed.** Voice bug → smart home → avatar is three chats.
- [ ] **A thing got finished and committed.** That is a clean cut. Take it.
- [ ] **You got compacted.** A summary replaced the real history. Anything not
      in that summary is gone — start fresh with `AGENTS.md` instead of paying
      to re-derive it.
- [ ] **You are scrolling to find what was decided.** If you can't find it, the
      model is wading through it too.
- [ ] **Answers feel slower or vaguer than they did an hour ago.**
- [ ] **It's a new day.**

**How to cut cleanly** — before ending a chat, say:

> Write what you learned to AGENTS.md and commit it.

Then open a new chat with one line:

> Read AGENTS.md. Today: <the one thing>.

That is the whole handoff. The map does the work the old chat was doing.

---

## The five things that cost the most here

**1. Rediscovering your own codebase.** The single biggest waste. Hours went
into finding out `memory_store.py`, `brain.py`, `conversation_buffer.py` and 43
voice tools already existed — after proposing to build them. `AGENTS.md` exists
to end this. Point every agent at it first.

**2. Full command output.** A whole pytest run is thousands of tokens of dots.

```powershell
# expensive                          # cheap
pytest tests                         pytest tests -q --tb=line | Select-Object -Last 5
Get-Content big.log                  Get-Content big.log -Tail 30
git status                           git status --porcelain
```

Ask for **the answer**, not the transcript: "how many failed" beats "run the
tests."

**3. Screenshots.** A screenshot costs roughly as much as several pages of text.
Use them when the *look* is the point — the avatar rig, a broken layout. For
reading a page, ask for the text instead.

**4. Pasting logs into chat.** Don't. Say "the error is in
`runtime\logs\main.err.log`" and let it tail the file. You paste 400 lines; it
would have read 20.

**5. Open-ended scope.** "Look at the codebase and tell me what's wrong" reads
everything. "Why does the backend not bind 8000?" reads one log.

---

## Phrases that save real money

| Say this | Instead of |
|---|---|
| "Read AGENTS.md first." | letting it explore |
| "Just the failure count." | "run the tests" |
| "Tail the last 30 lines." | "show me the log" |
| "Answer in chat, no file." | it writing a doc you didn't want |
| "Don't re-run what already passed." | full suite every time |
| "One question max, then proceed." | a back-and-forth |
| "Assume AGENTS.md is true." | it re-verifying known facts |

And the one that matters most when you step away:

> "I'm going to bed. Make reasonable calls, state your assumptions, don't wait
> on me."

That turns a stalled session into a working one.

---

## Which model for what

Match the model to the job instead of using the strongest one for everything.

**Use the heavier model for:** architecture and design decisions, debugging
something where the obvious answer was already wrong, security boundaries (the
memory-injection work), anything where a confident wrong answer costs hours.

**Use a lighter/faster one for:** running commands and reporting results, file
renames and moves, formatting, "what does this log say", mechanical edits with
a clear spec, status checks.

Rough rule: **if being wrong is cheap to detect, use the fast one.** A failed
test tells you immediately. A bad architecture decision doesn't surface for a
week.

---

## Habits that paid off here

- **Atomic commits.** Ten small commits beat one giant one — you can read them,
  and revert one without losing the rest.
- **Make it prove things.** "Show me the log line that says so." The dispatch
  probe once reported PASS with zero workers running.
- **Push back.** Telling it "do not kill those PIDs without re-resolving them
  live" prevented a real mistake. Being wrong is normal; being caught is cheap.
- **One task per chat.** The cheapest optimisation available, and the one most
  often skipped.

---

## A weekly 10 minutes

Ask, in a fresh chat:

> Read AGENTS.md. Is any of it now wrong? Update it and commit.

A stale map is worse than none — it teaches the next agent something false with
confidence.
