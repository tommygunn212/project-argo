# ARGO — map for coding agents

Read this before touching anything. It exists because agents keep rebuilding
things ARGO already has: `core/` (with the `core/voice/` and
`core/realtime_tools/` packages), 50 voice tools, 118 Python test files.
Almost everything you are about to propose probably exists.

**Owner:** Tommy. Windows, repo at `I:\argo`, venv at `I:\argo\.venv`.

---

## The one thing that causes the most wasted work

**There are two conversation paths, and they are not the same.**

| | Classic | Smooth Voice |
|---|---|---|
| Entry | `core/pipeline.py` (340 KB) | `livekit_realtime_agent.py` -> `core/voice/` |
| Brain | local STT → LLM → TTS | OpenAI realtime model over LiveKit |
| Status | fallback / offline only | **canonical, this is the live one** |
| Memory | fully wired | wired via `core/voice_memory.py` |
| Tools | its own path | 50 `@function_tool` methods |

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

**Voice tools** — 50 of them on the realtime agent, including `repair_argo`,
`run_self_diagnostics`, `open_app` / `close_app` / `focus_app`,
`play_music_from_era(era, genre, artist)`, `write_file` / `move_file` /
`remove_file`, `write_in_app`, `set_volume`, `search_drives`, `think_deeply`,
`recall`. Grep `@function_tool` before adding one.

Where they live: `recall`, `repair_argo` and `think_deeply` are in
`core/voice/agent.py` (they need the agent's state); the other 47 are
one-line doors in `core/voice/tools.py`, grouped by domain, onto bodies in
`core/realtime_tools/` (a package: machine, files, music, apps, video,
writing, home, knowledge). A new capability is a `@capability` function in
the right `realtime_tools` module plus a one-line tool - its docstring is
what the model reads. `@capability` turns any exception into `ok: false`.
Tests that monkeypatch a `realtime_tools` global must patch the submodule
(`realtime_tools.music.ROOT`), not the package.

**Smooth Voice layout** — `livekit_realtime_agent.py` is a 26-line launcher
kept at the root because scripts find the worker by that path. The code is
`core/voice/`: `worker.py` (process, lock, drain, stale agents),
`session.py` (one room, start to finish, model fallback), `agent.py`,
`tools.py`, `model.py` (realtime model, turn detection, BVC),
`phrase_gates.py` ("stop" + sleep/wake), `activity.py` (log + events),
`avatars.py` (Simli; Hedra is retired and its code is gone).

**LiveKit configuration** — `core/livekit_config.py` is the stable public
facade and owns the realtime session schema. Persistence is in
`core/livekit_preferences.py`, token/dispatch work in `core/livekit_access.py`,
dashboard/network reporting in `core/livekit_status.py`, and avatar readiness
in `core/livekit_avatar.py`. Import public helpers from the facade unless a
test deliberately targets one owner module.

**Knowledge retrieval** — `core/knowledge_service.py` is the one RAG door for
both Classic and Smooth Voice. It uses the local AnythingLLM "Tommy Knowledge
Base" workspace. Do not restore a second repo-index RAG path; source-code
questions belong to normal code/search tools, not Tommy's authored knowledge.

**Backend composition** — `main.py` owns process startup, WebSocket control,
and the classic microphone loop. Browser HTTP routes live in
`core/frontend_http.py` and receive callbacks from `main.py`; do not import the
composition root from the route module. `core/pipeline.py` remains the classic
pipeline facade, while its memory policy methods are owned by
`core/pipeline_memory.py` through `PipelineMemoryMixin`.

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

## External LiveKit Participants

ARGO's LiveKit server is local: `config.json` -> `livekit.url`, default
`ws://127.0.0.1:7880`, exported as `LIVEKIT_URL` by `livekit_realtime_agent.py`.

Cloud-hosted avatar providers are **not** sent video frames by ARGO. They are
sent ARGO's `LIVEKIT_URL` plus a room token, and then join the room from their
own infrastructure - `livekit/plugins/simli/avatar.py` POSTs exactly that to
`https://api.simli.ai/integrations/livekit/agents`.

So a loopback or RFC1918 URL resolves to *the provider's* machine. Their
participant never arrives and the agent waits forever. Observed 2026-09-20:
`[Simli] live avatar session started; waiting for remote video track`, then
silence, plus `RuntimeError: room disconnected while waiting for participant`.

Simli therefore requires one of:

- LiveKit Cloud with a public `wss://` endpoint, or
- a genuinely internet-reachable self-hosted deployment - signalling **and**
  WebRTC media (ICE over the configured TCP/UDP ports, or TURN).

An HTTP/WebSocket tunnel to 7880 alone is **not** sufficient: it carries
signalling, not the media path. `livekit-server/livekit.yaml` uses TCP 7881 and
UDP 7882.

Epistemic note: Simli's docs do not state this requirement in words. What is
established is (a) the plugin source POSTs your `LIVEKIT_URL` to
`api.simli.ai`, (b) their own example comment reads "the agent will join the
room and wait for the avatar to join", (c) every example in their docs uses a
public `wss://` URL, and (d) the observed 2026-09-20 failure. The conclusion
that a loopback URL is the cause follows from (a) plus how loopback addressing
works, but it has not been confirmed by Simli directly. If you ever see a
Simli avatar join a localhost room, this section is wrong - correct it.

Never expose the development `devkey` / `devsecret...` pair in
`livekit-server/livekit.yaml` to the public internet. Rotate it first.

`_url_reachable_from_cloud()` enforces this and refuses to start the avatar
with an explanatory error. Override: `ARGO_AVATAR_ALLOW_LOCAL_URL=1`.

### Failure behaviour - an avatar must never cost ARGO its voice

`AvatarSession.start()` reassigns `session.output.audio` to a
`DataStreamAudioOutput` aimed at the avatar participant. **ARGO is mute from
that moment until the avatar joins.** On 2026-09-20 this took the voice down
completely: every word was transcribed, zero spoken replies.

Avatar rendering is optional. Audio is not. Any avatar path must bound its wait
and restore the previous `session.output.audio` on failure. Degrade forward,
never to silence:

    Simli  ->  local viseme renderer  ->  static portrait

ARGO owns speech; avatars subscribe to it.

---

## Local Viseme Prototype

`frontend-v2/assets/cortana-avatar.js` carries per-viseme mouth shaping
(`shapeWide` / `shapeRound` uniforms, optional 4th `shape` arg to
`Portrait.draw()`), driven by `avatar-portrait-preview.html`.

History, facts only: added in `b9bc600` (2026-09-19 04:06), reverted 76 minutes
later in `9ddd654`, restored in `2cf1743`. The revert carried only git's default
message, so **its reasoning is recorded nowhere**. Simli work began roughly 50
minutes after it.

What is verifiable: the patch is additive and preview-only.
`frontend-v2/index.html` never passes the 4th argument, so `shapeWide` and
`shapeRound` stay 0 and the live dashboard renders identically. There is no
recorded evidence it caused a regression.

Do not treat that revert as evidence that local visemes are architecturally
incompatible with ARGO. If they are dropped again, record why.

Still open: the coefficients are a rough first pass, uncalibrated per face, and
the contact viseme (sibilants/stops) is unmapped. Per-face landmarks are the
`eyeLandmarks` / `mouthLandmark` uniforms in `Portrait.draw()`, selected by
`halo` / `male` / default - adding a new portrait means adding a landmark set.

---

## How to work here

**Commit atomically.** Every time you write something, commit it — do not batch.
This is Tommy's standing instruction and it has been ignored before.

**The dashboard's restart button does not restart the voice worker.** `main.py`
and `livekit_realtime_agent.py` are separate processes. A "Server restart
requested" from the dashboard reloads the backend only - the worker keeps
serving jobs from whatever it imported at startup, so edits to
`livekit_realtime_agent.py` appear to do nothing at all. The entrypoint runs
once per room session, which makes it look like fresh code is running when it
is not. Observed 2026-09-20: the worker registered once at 20:58 and was still
handling sessions at 21:38, straight through a backend restart at 21:37,
running pre-edit code the whole time. Confirm a real worker restart by looking
for a NEW `registered worker` banner in `runtime/logs/worker.out.log` - if the
only one is old, the worker never came back. Use `RESTART_ARGO.bat` (or
`scripts/start_argo_stack.ps1`), which drains and restarts both.

**Verify from disk, never from the write.** File syncs into this repo have
silently written stale bytes while reporting success. After any patch, read the
file back and assert on markers. `tools/fixups*.py` (32 of them) are the
on-box patch pattern, each with a read-back audit. They are history: the
ones that patch `livekit_realtime_agent.py` or `core/realtime_tools.py` target
a layout that no longer exists (2026-09-27 cleanup). Do not re-run them.

**`py_compile` is not proof.** It catches syntax, not imports. A bad regex or a
missing symbol passes compilation and fails at runtime. Import the module.

**Prove it, don't assert it.** A probe that passes with the thing switched off
is worthless — the dispatch probe once reported PASS with zero workers running,
because LiveKit creates placeholder participants. Require a real
`session_start` event. Add a negative control and watch it fail.

**Slow startup is not failure.** The backend takes ~30s (audio enumeration,
model warmup, ambient calibration). `start_argo_stack.ps1` now polls each port
for up to 60s before reporting it, instead of snapshotting once right after a
fixed sleep — it used to report `8000 NOT LISTENING` on a healthy boot; fixed
2026-09-17.

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

- **Code cleanup, 2026-09-28.** The Smooth Voice path (`core/voice/`,
  `core/realtime_tools/`, `core/voice_memory.py`) was restructured and its
  bugs fixed in atomic commits: see `git log --oneline 1faa6c0..`.
  `core/livekit_config.py` was then split behind its compatible facade, and
  AnythingLLM became the single RAG service for both voice paths. Next cleanup
  cleanup removed the tracked archives, completion reports, duplicate source
  backups, and stale documentation; Git history is the archive. HTTP routing
  was extracted from `main.py`, and memory behavior from `core/pipeline.py`.
  Next candidates are the classic pipeline's canonical-response handlers and
  `handle_user_text`; keep each extraction cohesive and compatibility-safe.
  Re-run the Windows suite and a live voice proof after runtime changes.

- Memory round trip unproven live: say a decision, stop Smooth Voice, reconnect,
  ask. `recall` is a tool the model *chooses* to call; if she answers from thin
  air that is a tool-description problem, not a storage one.
- Mic scenarios C, D, E, F never run: `tools\voice_scenarios.py --only c d e f`
- GE air conditioners built and tested; waiting only on two `.env` values.
- **Avatar motion — final art not started (note for whoever picks this up next).**
  The 5-layer rig in `frontend-v2/assets/avatar-motion.js` (jaw aperture blended
  across six visemes, eyes, posture/breathing, chamber-light detail, and
  IDLE/LISTENING/THINKING/SPEAKING/INTERRUPTED state) is proven only against
  the lab's own procedural neutral placeholder face, not any real ARGO
  portrait. Iterate on it with zero mic/voice budget: `tests/test_avatar_motion.cjs`
  runs the rig headless in Node, and `frontend-v2/avatar-motion-lab.html` is
  servable two ways — behind `main.py`'s `/v2/motion-lab` route with
  `ARGO_AVATAR_MOTION_LAB=1` set, or standalone via
  `tools/motion_lab_server.py` on `http://127.0.0.1:8777` (a throwaway server,
  not ARGO). What's actually live today is older and simpler:
  `frontend-v2/assets/cortana-avatar.js` drives the real portraits (Cortana /
  Cyber Male, see `docs/AVATAR_SELECTION.md`) with one audio-envelope mouth
  scale, no visemes. "Complete" means calibrating real per-face landmarks
  (eye positions, a mouth region per viseme, jaw pivot) for those portraits the
  way `cortana-avatar.js` is already calibrated for them, proving that on the
  lab page first, and only then wiring the richer rig into the live
  dashboard/voice avatar panels in place of (or blended with)
  `cortana-avatar.js`'s envelope. Do not skip the "prove it on the lab page
  first" step — a rig that looks right on a placeholder face is not proof it
  looks right on a real one, and this is exactly the kind of task that burns a
  lot of context/budget if picked up without reading this first.
