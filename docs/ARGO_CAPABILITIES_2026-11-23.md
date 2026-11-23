# ARGO - What She Can Do Now (snapshot 2026-11-23)

Branch: `jarvis-upgrade`. Repo: `I:\argo`. This is a plain-language list for handing to another AI
(e.g. GPT) so it can suggest what to improve. Status tags: **PROVEN** = tested live and seen working,
**BUILT** = code + tests exist but not watched live end-to-end, **NOT YET** = not done.

## 1. How you talk to her
- **Smooth Voice** (main): OpenAI `gpt-realtime-2.1` (fallback `gpt-realtime-1.5`) over a self-hosted
  LiveKit server on this PC. The model only produces text; speech comes from ElevenLabs
  ("Argo Cockney", fallback OpenAI `gpt-4o-mini-tts` "ash"). PROVEN.
- **Classic pipeline** (fallback): gpt-4o-mini-transcribe -> model -> gpt-4o-mini-tts. BUILT.
- **Dashboard** at `http://localhost:8000/v2` (also usable from the iPad on the same network):
  avatar (Orb/Orbit/Cortana/Cyber Male), latency bars, voice status, quick actions, and the **Show** panel.
- **Wake / sleep**: starts asleep. Say "hey Argo" / "Argo wake up" to wake her; she stays awake until
  you say "go to sleep". While asleep she does not reply and does not run tools. PROVEN (4/4 spoken probes).
  Not done: start-awake default from the dashboard, an asleep/awake indicator on screen.
- **Urgent stop**: a bare "Stop." / "Wait." cuts her off. BUILT, live re-test pending.
  "Stop the print job" is not treated as a stop-talking command.
- Alexa / Echo: considered, dropped. Telegram, Pi satellite rooms: not built.

## 2. Who she is (her "prompt")
Assembled once per session in `core/persona_briefs.py` (version v4) from, in order:
1. CONVERSATION_CONTRACT - how every ARGO talks (short, natural, no reading tool output like a report).
2. TOMMY_PROFILE - facts about you she should just know without a lookup.
3. The selected persona: argo (default), tommy_gunn, tommy_mix, jarvis, rick, claptrap, cockney, plain.
4. DEEP_THINK_POLICY - when to hand a hard question to a bigger model (`think_deeply`; "not wired yet" on the dashboard).
5. TOOL_POLICY - use the tool, then answer from what it returned; never announce a lookup; if no tool
   covers the request, hand it to `delegate_task`; for a lasting ability, call `build_skill`.
Her personality right now is **cockney**, voice shown as nova/ElevenLabs on the dashboard.

## 3. Things she can do (about 70 tools)
- **Computer**: specs, drive space, system status, self-diagnostics, volume, PC power profile,
  list/open/close/focus apps, write into apps.
- **Files**: list/read/find/search drives, write/append/copy/move/remove, make folders - only inside
  `filesystem.allowed_folders`.
- **Music and video**: play by keyword/era/artist, stop, next, status, check library; play movie/episode,
  find something to watch, stop, status.
- **Home**: `control_smart_home` and AC control/status via Home Assistant. HA is up but has **no devices yet**
  (Feit lights and iRobot still need adding in HA). `open_app("home assistant")` wrongly looks for a desktop app.
- **Time and life**: time, reminders, calendar (add/list/cancel), morning briefing, "where we left off",
  "what's pending", drafts (save/list/read), email-sending check, knowledge-base search (RAG), `recall`.
- **Show board (NEW, PROVEN)**: she can put images and sandboxed SVG schematics on the dashboard Show panel
  (`/api/show`, token-guarded for writes). Seen rendering on the real dashboard.

## 4. Doing bigger jobs
- **delegate_task ("Dot mode")**: hands a multi-step errand to Codex (CLI 0.171.0-alpha.13 bundled with the Codex
  desktop app, signed in with your ChatGPT account, so it uses your plan, not API billing). Model `gpt-6-astra`.
  Check/cancel with `check_background_tasks` / `cancel_background_task`.
  **Known bug**: background jobs die if the voice session ends.
- **work_on_project / repair_argo / improve_argo**: Codex works in an isolated copy of committed code, runs tests,
  then you apply. Apply needs a clean working tree. Uncommitted edits no longer block starting a repair.
  Code-repair model is now `gpt-6.1-terra` (override with env `ARGO_CODEX_MODEL`).

## 5. Teaching herself (NEW)
- Say "figure out how and add it" -> `build_skill(name, request)`. Codex writes ONE skill file + ONE test, in the
  isolated copy. It installs only if its own test and the real loader both pass. Skills live in `argo_skills/`,
  load at the next session start, and are recorded on the git branch `argo-self` (never on your main work).
  `list_my_skills` shows them. Logs: `runtime/logs/skills.jsonl`.
- Skills she has built herself so far (both installed; PROVEN to build and install):
  - `show_image` - generates a picture with `gpt-image-1` and shows it. API-billed. Not yet run live.
  - `find_models` - searches Printables for 3D models, ranks by likes/downloads, drops novelty and duplicates,
    shows the top 3 with photos, saves them to `runtime/last_model_results.json`. PROVEN on "egg cup"
    and "skadis deburring tool holder". MakerWorld not included (no public API, blocks bots).

## 6. What is NOT done yet
- `print_model`: "print 2 in white PETG" on the Bambu H2D. Needs the H2D IP, serial and LAN access code.
  Plan: download STL, slice with Bambu Studio/Orca, send over LAN, and ALWAYS ask before starting.
- "Show me my table in white wash": needs a photo of the table + an image-edit step.
- "Show me a Skadis schematic": SVG diagram skill not built yet (`show_diagram`).
- Home Assistant devices, Home Assistant status check, memory saving (last saved turn 2026-09-26, needs investigating).
- Standalone job runner so Codex jobs survive the voice session ending.
- She sometimes spawns a Codex job for a quick lookup she could answer directly.
- Voice/face recognition gating (Tommy, Jesse, Kitty), camera on/off, Sonnet-as-brain "think deeply" hybrid.

## 7. Where the money goes
- Free on your plan: all Codex work (skill building, repairs, delegate jobs).
- Billed per use: OpenAI realtime voice, speech, transcription, `gpt-image-1` pictures (OPENAI_API_KEY);
  ElevenLabs voice credits (ELEVEN_API_KEY).

## 8. Questions worth asking another AI
- How to make her proactive (morning briefing, reminders, "the dryer finished") without being annoying.
- Best way to make her memory actually persist and be useful.
- Which tools should become skills she builds herself next, and which risky ones (printing, deleting, spending)
  should always require a spoken confirmation.
