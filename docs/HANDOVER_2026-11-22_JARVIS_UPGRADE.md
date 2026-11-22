# ARGO: Jarvis upgrade handover (2026-11-22)

**Branch:** `jarvis-upgrade`, pushed to `origin`. **Not merged into `main`.**
**Full Windows suite on the branch: 2298 passed, 5 skipped, 0 failed.**
The goal for this round: everything OpenAI's "Dot" agents can do, ARGO should
do - faster, by voice, in every room, with the house behind her.

## What was built

| Area | Files | What it does | Proof |
|---|---|---|---|
| Action log | `core/voice/action_log.py` | Every tool call (voice, text and MCP) goes to `runtime/logs/actions.jsonl`, secrets redacted. `ARGO_ACTION_LOG=off` turns it off. | tests, including a secret-leak test with a negative control |
| MCP plug-ins | `core/voice/mcp_bridge.py` | `config.json` -> `mcp.servers` become voice tools. Each connects under a timeout before the session starts; a dead one is skipped and never costs the voice. Off by default; `ARGO_MCP_ENABLED=0` is the kill switch. | tests against a **real** stdio MCP server (tools listed and called) |
| Background agent ("Dot mode") | `core/delegate_jobs.py`, `delegate_task` / `check_background_tasks` / `cancel_background_task` | Headless Claude Code (`claude -p`) does research and errands in the background; ARGO says she's on it and reports back when done. Jobs are recorded in `runtime/agent_jobs/<id>/`. | tests with a stand-in CLI; a real CLI run reached Claude Code and **failed on an expired login** |
| Reminders and calendar on live voice | `core/realtime_tools/scheduling.py` | `set_reminder`, `list_reminders`, `cancel_reminder`, `add_calendar_event`, `list_calendar`, `what_time_is_it`. `tools/reminders.py` now claims due reminders atomically. | tests |
| Memory by day | `core/conversation_journal.py`, `MemoryStore.turns_between` | `where_we_left_off("two days ago")`, `whats_pending`, `mark_pending_done`, `morning_briefing`. Daily digests (summary, decisions, open items) are made by a text model and cached in `data/journal.db`. | tests |
| Proactive | `core/voice/proactive.py` | ARGO speaks up when a reminder is due (late ones are flagged as late) and offers the morning briefing once a day from 5am. The sleep gate still applies. `ARGO_PROACTIVE=0` turns it off. | tests |
| Cockney persona | `core/persona_briefs.py`, dashboard select | A cocky East London robot who takes the mickey, never when Tommy is stressed or something is broken. Jarvis is restored to its original text. All personas are told to use `delegate_task` instead of saying "I can't". | tests |
| ElevenLabs voice | `core/voice/voice_output.py`, `core/voice/model.py` | `voice_output.provider = "elevenlabs"` makes the realtime model reply in text and ElevenLabs speak it, with OpenAI TTS as fallback. A missing key, voice ID or plugin means the normal voice. | tests; **no key in ARGO's .env yet** |
| MilkDrop visuals | `frontend-v2/assets/milkdrop-visuals.js`, vendored butterchurn 2.6.7 + presets 2.4.7 (MIT) | New "Visuals" avatar mode: Winamp-style visuals that dance to ARGO's voice, idle on a quiet internal tone, change preset every 24s, and go full screen on double-click. | **seen rendering** in the dashboard page (idle) and in a harness with audio |
| Text ARGO from anywhere | `core/text_agent.py`, `core/telegram_bridge.py`, `telegram_bridge.py` | Same persona, tools and memory by text. The Telegram bot is outbound long-polling only (nothing opened to the internet), with an allowlist. Reminders go to Telegram when no voice session is live. `start_argo_stack.ps1` starts it, and it does nothing without a token. | tests; text brain **proven live** with the real model and reminders DB |

Packages installed in `.venv`, pinned so nothing else upgraded:
`mcp==1.30.0` and `livekit-plugins-elevenlabs==1.5.17`. An unpinned elevenlabs
install would have pulled livekit-agents 1.8 and openai 3.x. Don't do that.

## To switch it on (in order)
1. **Claude Code login on bigdog:** run `claude` in a terminal and log in. Dot mode needs it.
2. **ElevenLabs key:** add `ELEVEN_API_KEY=` to `I:\argo\.env`. The value is in `I:\deployment-chefsbyte\.env`.
3. **Voice:** three "cocky cockney robot" previews were designed in ElevenLabs. Save the one you like, then set `voice_output.provider: "elevenlabs"` and `voice_output.elevenlabs.voice_id` in `config.json`.
4. **Telegram:** create a bot with @BotFather and add `TELEGRAM_BOT_TOKEN=` to `.env`. Text the bot; it replies with your ID. Put that in `config.json` -> `telegram.allowed_user_ids`.
5. **Run it:** stay on `jarvis-upgrade`, run `RESTART_ARGO.bat`, test by voice and text, then merge to `main`.

The config sections for all of this are in `config.json.template`: `mcp`, `delegate`, `proactive`, `voice_output`, `telegram`.

## Worth knowing
- **Memory may not be saving.** The last conversation turn in `data/memory.db` is from **2026-09-26**. The one logged worker session (Oct 16) wrote 0 turns. That's either no use since then, or broken memory writes. First voice test: say something, reconnect, ask about it.
- **`OPENAI_API_KEY` is a Windows user environment variable, not in `.env`.** A process started from an old shell may not see it.
- **Wake/sleep word** (stay awake until the sleep phrase) already exists and is off: `ARGO_WAKE_SLEEP_GATE_ENABLED=true`. It's reactive: audio still reaches OpenAI while "asleep".
- **Voice recognition (Tommy / Jesse / Kitty):** only a placeholder exists (`speaker_identity`: Speechmatics, disabled, status-only). Real recognition needs each person to record a voice sample. Not started.
- **Remote voice:** use Tailscale on bigdog and the phone to open the dashboard privately. Never port-forward the dashboard or LiveKit (the dev key pair in `livekit-server/livekit.yaml` must never face the internet).
- **OpenClaw:** we borrowed its ideas (messaging, heartbeat), not the code. Never install ClawHub skills: the marketplace has a large, well-documented malware problem.
- The "5 gates" are in `config.json.template` -> `canonical` and guard the classic pipeline only.
- `improve_argo` / `work_on_project` call `codex` on PATH; `codex` wasn't found from a fresh shell. Unverified whether that's a problem.

## Next on the roadmap
Unify the three memory systems; voice recognition; the print pipeline (Bambu
Studio command line -> `bambu-connect://import-file`); the Pi 4 living-room
satellite (run the HDMI-CEC test first: `echo 'as' | cec-client -s -d 1`);
email/package tracking via an MCP server; The Conversation as ARGO's coding
team. See also the project doc "Jarvis Roadmap".
