# ARGO — map for coding agents

Read this before touching anything. It exists because agents keep rebuilding
things ARGO already has. 74 modules in `core/`, 43 voice tools, 113 Python test
files. Almost everything you are about to propose probably exists.

**Owner:** Tommy. Windows, repo at `I:\argo`, venv at `I:\argo\.venv`.

---

## The one thing that causes the most wasted work

**There are two conversation paths, and they are not the same.**

| | Classic | Smooth Voice |
|---|---|---|
| Entry | `core/pipeline.py` (340 KB) | `livekit_realtime_agent.py` |
| Brain | local STT → LLM → TTS | OpenAI realtime model over LiveKit |
| Status | fallback / offline only | **canonical, this is the live one** |
| Memory | fully wired | wired via `core/voice_memory.py` |
| Tools | its own path | 43 `@function_tool` methods |

When Smooth Voice became canonical it inherited the voice and *not* the rest of
the stack. Anything that "looks missing" from Smooth Voice may simply be wired
to `pipeline.py` instead. **Check both before building.**

---

## What already exists (do not rebuild)

**Memory** — `memory_store.py` (SQLite *and* Postgres behind one interface,
`add_turn` / `search_turns` / `list_memory`), `mem0_memory.py` (optional cloud
layer, currently disabled), `conversation_buffer.py` (short-term), `brain.py`
(3-layer facts/state/last-exchange), `session_memory.py`, `voice_memory.py`
(the Smooth Voice adapter).

**Voice tools** — 43 of them on the realtime agent, including `repair_argo`,
`run_self_diagnostics`, `open_app` / `close_app` / `focus_app`,
`play_music_from_era(era, genre, artist)`, `write_file` / `move_file` /
`remove_file`, `write_in_app`, `set_volume`, `search_drives`, `think_deeply`,
`recall`. Grep `@function_tool` before adding one.

**Personality** — `core/persona_briefs.py` is the single source of truth.
Seven personas, each producing a distinct instruction set with a
`v3-<sha>` fingerprint. Never stack persona text from more than one place.

**Deletion is already safe — do not "fix" it.** `remove_file` / `remove_item`
move things to a dated quarantine folder with `shutil.move`; Tommy empties it
himself. There is no `os.remove`, `os.unlink`, `.unlink()` or `shutil.rmtree`
anywhere in `core/` or the agent. An agent has already wasted a round proposing
to add Recycle Bin support that was neither needed nor as safe as what exists.

**Runtime safety** — `core/runtime_guard.py` (venv check via `sys.prefix`,
single-instance PID lock, orphan detection), `core/voice_active.py`,
`core/voice_events.py` (JSONL at `runtime/voice_tests/live_events.jsonl`).

**Smart home** — `core/smart_home.py` (GE SmartHQ air conditioners via
`gehomesdk`; credentials from `.env` only).

**Avatar motion** — `frontend-v2/assets/avatar-motion.js`, lab page at
`frontend-v2/avatar-motion-lab.html`, flag `ARGO_AVATAR_MOTION_LAB`.

---

## Invariants — do not break these

1. **BVC noise cancellation stays OFF.** It is a LiveKit *Cloud* filter and this
   server is self-hosted at `ws://127.0.0.1:7880`. It was on once and was a
   credible suspect when Smooth Voice connected and heard nothing.
   OpenAI's server-side `input_noise_reduction: far_field` is a *different*
   mechanism and stays on. `tests/test_realtime_audio.py` guards this.

2. **Never force-kill parentless Python on port 7880.** Default behaviour is
   report-and-refuse. Cleanup needs `-CleanOrphans` *and* ARGO-specific
   evidence. Regression tests prove an unrelated orphan is never killed.

3. **Only explicitly confirmed memory enters system instructions.** Provenance
   `explicit_user_request` is injected with its source and date; `brain`,
   `implicit`, `llm` are inference and are reachable only via the `recall` tool.
   Persona, safety rules and tool policy live in instructions *alone*.

4. **Remembered text is untrusted.** Sanitised on read, never on write, on both
   the instruction path and tool output. 51 injection tests cover it.

5. **`config.json` and `.env` are gitignored and hold live secrets.** Never
   commit them, never print their values, never paste them into logs or
   tracebacks.

6. **Preserve Tommy's drive access.** Documents, work drives and external drives
   stay readable/writable. Do not revert to an `I:\argo`-only sandbox. Keep the
   traversal / device-path / other-user-profile / credential-store protections.

7. **Model:** `gpt-realtime-2.1`, falling back to `gpt-realtime-1.5` if preflight
   rejects it. Session shape is the GA nested form (`session.type: "realtime"`,
   nested `audio.input.turn_detection` / `audio.output.voice`). The legacy flat
   shape is rejected outright.

---

## How to work here

**Commit atomically.** Every time you write something, commit it — do not batch.
This is Tommy's standing instruction and it has been ignored before.

**Verify from disk, never from the write.** File syncs into this repo have
silently written stale bytes while reporting success. After any patch, read the
file back and assert on markers. `tools/fixups*.py` (32 of them) are the
on-box patch pattern, each with a read-back audit.

**`py_compile` is not proof.** It catches syntax, not imports. A bad regex or a
missing symbol passes compilation and fails at runtime. Import the module.

**Prove it, don't assert it.** A probe that passes with the thing switched off
is worthless — the dispatch probe once reported PASS with zero workers running,
because LiveKit creates placeholder participants. Require a real
`session_start` event. Add a negative control and watch it fail.

**Slow startup is not failure.** The backend takes ~30s (audio enumeration,
model warmup, ambient calibration). `start_argo_stack.ps1` samples the ports too
early and will report `8000 NOT LISTENING` on a healthy boot.

---

## Commands

```powershell
.\scripts\start_argo_stack.ps1          # start everything (refuses on orphans)
.\.venv\Scripts\python.exe -m pytest tests -q --tb=line
node --test tests\test_avatar_motion.cjs
.\.venv\Scripts\python.exe -m core.runtime_guard --report
.\.venv\Scripts\python.exe .\tools\memory_peek.py
.\.venv\Scripts\python.exe .\tools\smart_home_probe.py
.\.venv\Scripts\python.exe .\tools\motion_lab_server.py   # http://127.0.0.1:8777
```

Dashboard: `http://localhost:8000/v2` — **not** `/`, which is the retired one.

---

## Open work

- Memory round trip unproven live: say a decision, stop Smooth Voice, reconnect,
  ask. `recall` is a tool the model *chooses* to call; if she answers from thin
  air that is a tool-description problem, not a storage one.
- Mic scenarios C, D, E, F never run: `tools\voice_scenarios.py --only c d e f`
- GE air conditioners built and tested; waiting only on two `.env` values.
- Avatar motion proven on a neutral placeholder; final art not started.
