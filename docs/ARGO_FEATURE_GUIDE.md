# ARGO — Complete Feature Guide

> **Version**: 1.6.24+  
> **Last Updated**: March 2026  
> **Branch**: tommy-personal-argo

ARGO is a voice-first AI assistant built to run locally on your machine. This guide covers every feature, voice command, and integration available today.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Brain Memory System](#brain-memory-system)
3. [Writing & Productivity](#writing--productivity)
4. [Email Sending](#email-sending)
5. [Music Control](#music-control)
6. [System Health & Hardware](#system-health--hardware)
7. [Bluetooth Control](#bluetooth-control)
8. [Volume Control](#volume-control)
9. [Application Control](#application-control)
10. [Time & Date](#time--date)
11. [Smart Home Control](#smart-home-control)
12. [Reminders](#reminders)
13. [Calendar](#calendar)
14. [Computer Vision](#computer-vision)
15. [File System Agent](#file-system-agent)
16. [Task Planner](#task-planner)
17. [ARGO Identity & Governance](#argo-identity--governance)
18. [Self-Diagnostics](#self-diagnostics)
19. [Audio Routing](#audio-routing)
20. [Configuration Reference](#configuration-reference)

---

## Quick Start

```
# Activate the environment
.\.venv\Scripts\activate

# Run ARGO
python main.py
```

Say the wake word **"ARGO"**, then speak your command. ARGO processes your speech, classifies the intent, and either handles it deterministically (music, system queries, Bluetooth, volume, etc.) or routes through the LLM for conversational responses.

---

## Brain Memory System

ARGO has a 3-layer memory architecture that lets it remember facts about you across sessions.

### Architecture

| Layer | Storage | Lifetime | Purpose |
|-------|---------|----------|---------|
| **Short-Term** | RAM only | Last exchange only | Maintains conversational flow |
| **Working** | RAM + SQLite | Current session + persisted | Tracks current topic, task, and mood |
| **Long-Term** | SQLite (`data/brain.db`) | Permanent | Stores facts, relationships, preferences |

### Storing Facts

Tell ARGO to remember something. Use any of these trigger phrases:

| Trigger Phrase | Example |
|---|---|
| **"Remember that..."** | "Remember that my dog's name is Bandit" |
| **"Remember this..."** | "Remember this — I like my coffee black" |
| **"Don't forget..."** | "Don't forget my son is Jesse" |
| **"Save this..."** | "Save this — the WiFi password is blueberry42" |
| **"Store this..."** | "Store this — I'm working on the ARGO project" |

ARGO automatically categorizes facts into:

- **Identity** — who you are ("I'm a filmmaker", "my name is Tommy")
- **Relationship** — people and pets ("my son is Jesse", "Bandit is my dog")
- **Preference** — likes and dislikes ("I like jazz", "I hate corporate filler")
- **Project** — things you've built ("I built ChefsByte", "I created ARGO")
- **General** — everything else

### Implicit Identity

You don't always need a trigger word. These are recognized automatically:

```
"My name is Tommy"          → stores your name
"Call me T"                  → stores preferred nickname
```

### Structured Patterns (after trigger word)

```
"Remember that my wife is Sarah"        → relationship: Sarah is wife
"Remember that my dog's name is Bandit" → relationship: Bandit is dog
"Remember that I like sarcasm"          → preference: likes sarcasm
"Remember that I'm a software builder"  → identity: is software builder
"Remember that I built ChefsByte"       → project: built ChefsByte
"Remember that Jesse is my son"         → relationship: Jesse is son
```

### Recalling Facts

| Voice Command | What It Does |
|---|---|
| **"What do you know about me?"** | Lists all stored facts in natural language |
| **"What do you remember about me?"** | Same as above |
| **"What do you know about Jesse?"** | Retrieves facts about a specific subject |
| **"What do you remember about Bandit?"** | Same — searches by subject keyword |

### Forgetting Facts

| Voice Command | What It Does |
|---|---|
| **"Forget about Bandit"** | Deletes facts where subject matches "bandit" |
| **"Forget that"** | Deletes the most recently stored fact |

### How Memory Enhances Conversations

Every time you talk to ARGO, the brain injects relevant context into the LLM prompt:

```
KNOWN FACTS:
- Tommy built ChefsByte
- Bandit is Tommy's dog
- Tommy likes blunt responses

CURRENT STATE:
Topic: argo_development | Task: building features | Mood: focused

LAST EXCHANGE:
User: what's the status on the project?
ARGO: All tests passing, writing system is live.
```

This means ARGO naturally references what it knows about you in conversations — without you having to repeat yourself.

---

## Writing & Productivity

ARGO can draft emails, blog posts, notes, and documents using the LLM, then save, edit, search, and export them.

### Writing an Email

| Voice Command | What Happens |
|---|---|
| **"Write an email to Paul about the project deadline"** | Drafts email with recipient "Paul", subject inferred from context |
| **"Draft an email to Sarah"** | Creates email draft addressed to Sarah |
| **"Email John about the meeting"** | Creates email draft for John about the meeting |
| **"Compose an email to the team"** | Drafts a team email |

ARGO extracts the **recipient** and **subject** from your voice command, then uses the LLM to generate a professional email body. The draft is saved to `argo_data/drafts/emails/`.

### Writing a Blog Post

| Voice Command | What Happens |
|---|---|
| **"Write a blog post about AI assistants"** | Drafts a markdown blog post |
| **"Draft an article about home automation"** | Same — creates `.md` file with title and body |
| **"Write a blog about my experience building ARGO"** | Personal blog draft |

Blog posts are saved as markdown files in `argo_data/drafts/blogs/`.

### Taking Notes

| Voice Command | What Happens |
|---|---|
| **"Take a note"** | Starts note capture |
| **"Note that I need to buy milk"** | Quick note with inline content |
| **"Save a note about the meeting"** | Saves note to `argo_data/drafts/notes/` |
| **"Jot down this idea"** | Same as note |
| **"Memo — call the dentist tomorrow"** | Simple memo capture |

### Editing Drafts

| Voice Command | What Happens |
|---|---|
| **"Edit the draft"** | Opens the most recent draft for editing |
| **"Make it shorter"** | Rewrites with instructions to condense |
| **"Make the email more formal"** | Rewrites with tone adjustment |
| **"Revise the blog post"** | Re-edits the latest blog draft |

Editing sends the current draft + your instructions to the LLM, which rewrites it. The updated version replaces the original.

### Listing Drafts

| Voice Command | What Happens |
|---|---|
| **"List my drafts"** | Shows the 5 most recent drafts across all categories |
| **"Show my email drafts"** | Lists recent email drafts |
| **"What drafts do I have?"** | Same as list |
| **"Show my blog posts"** | Lists blog drafts |

### Reading a Draft

| Voice Command | What Happens |
|---|---|
| **"Read the draft"** | Reads back the most recent draft |
| **"Read my last email"** | Reads the latest email draft aloud |
| **"Read the blog"** | Reads the latest blog draft |

### Searching Drafts & Documents

| Voice Command | What Happens |
|---|---|
| **"Search my documents for project deadline"** | Full-text search across all drafts |
| **"Find the email about the budget"** | Searches email drafts for "budget" |
| **"Search my notes for dentist"** | Searches note files |

### Exporting to Spreadsheet (CSV)

| Voice Command | What Happens |
|---|---|
| **"Export my brain facts"** | Creates a CSV file of all stored memory facts |
| **"Export my drafts to a spreadsheet"** | Exports draft metadata to CSV |
| **"Export my documents"** | Same — includes title, type, date, path |

Exports are saved to `argo_data/exports/` as `.csv` files.

### File Storage Structure

```
argo_data/
├── drafts/
│   ├── emails/         email_20260308_143022_paul.txt
│   ├── blogs/          blog_20260308_150500_ai_assistants.md
│   ├── notes/          note_20260308_160000_dentist.txt
│   └── docs/           (general documents)
├── published/          (drafts moved here after "publish" command)
└── exports/            brain_facts_20260308.csv
```

---

## Email Sending

Once you've drafted an email, ARGO can send it directly via SMTP.

### Setup

Add an email configuration block to your `config.json`:

```json
{
  "email": {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "your.email@gmail.com",
    "sender_password": "your-16-char-app-password"
  }
}
```

> **Gmail users**: You need a [Google App Password](https://myaccount.google.com/apppasswords), not your regular password. Enable 2FA first, then generate an app password for "Mail".

### Sending

| Voice Command | What It Does |
|---|---|
| **"Send the email"** | Sends the most recently drafted email |
| **"Send that"** | Same — sends latest email draft |
| **"Send my last email"** | Sends the latest draft in `argo_data/drafts/emails/` |

ARGO will confirm the recipient and subject before sending. The email is sent as plain text from the configured sender account.

---

## Music Control

ARGO can play music from your local library, control playback, and identify what's playing.

### Playing Music

| Voice Command | What Happens |
|---|---|
| **"Play music"** | Starts playing from your music library |
| **"Play some jazz"** | Plays music matching the genre "jazz" |
| **"Play David Bowie"** | Plays tracks by David Bowie |
| **"Play rock"** | Plays rock genre tracks |
| **"Surprise me"** | Random selection from your library |

### Playback Control

| Voice Command | What Happens |
|---|---|
| **"Stop"** / **"Pause"** | Stops current playback |
| **"Next"** / **"Skip"** | Skips to next track |
| **"Stop music"** / **"Stop the music"** | Stops playback |

### Now Playing

| Voice Command | What Happens |
|---|---|
| **"What's playing?"** | Tells you the current track and artist |
| **"What song is this?"** | Same |
| **"What am I listening to?"** | Same |

### Configuration

Set your music library path in `config.json`:

```json
{
  "music": {
    "enabled": true,
    "library_path": "I:\\My Music"
  }
}
```

You can also set up artist aliases in `music_aliases.json` for common name variations.

---

## System Health & Hardware

Ask ARGO about your computer's hardware, performance, and health — all processed locally without the LLM.

### Full System Report

| Voice Command | What It Returns |
|---|---|
| **"Give me a status report"** | CPU, RAM, disk, GPU — full overview |
| **"Full system status"** | Same |
| **"How is my computer doing?"** | Same |
| **"Anything wrong with my system?"** | Same |

### CPU

| Voice Command | What It Returns |
|---|---|
| **"What CPU do I have?"** | CPU model, cores, current usage |
| **"CPU specs"** | Same |
| **"What processor am I using?"** | Same |

### Memory / RAM

| Voice Command | What It Returns |
|---|---|
| **"How much memory do I have?"** | Total and available RAM |
| **"Total memory"** | Same |
| **"What's my RAM?"** | Same |

### GPU

| Voice Command | What It Returns |
|---|---|
| **"What GPU do I have?"** | GPU model AND current VRAM/usage if available |
| **"Graphics card info"** | Same |
| **"GPU health"** | Temperature and load if supported |

### Disk Space

| Voice Command | What It Returns |
|---|---|
| **"How much space do I have?"** | Free space on all drives |
| **"Disk space"** | Same |
| **"Which drive is fullest?"** | Same — ranks by usage |
| **"C drive status"** | Specific drive info |

### Temperature

| Voice Command | What It Returns |
|---|---|
| **"CPU temperature"** / **"CPU temp"** | Current CPU temperature |
| **"Is it overheating?"** | Temperature with warning if hot |
| **"How hot is my system?"** | Same |

### OS Info

| Voice Command | What It Returns |
|---|---|
| **"What OS am I running?"** | Windows version, build |
| **"Windows version"** | Same |
| **"Operating system info"** | Same |

---

## Bluetooth Control

Control Bluetooth adapters and device connections by voice.

### Status

| Voice Command | What It Returns |
|---|---|
| **"Bluetooth status"** | Whether Bluetooth is on/off and connected devices |
| **"Is Bluetooth on?"** | On/off status |
| **"What Bluetooth devices are connected?"** | List of connected devices |
| **"Is my headset connected?"** | Checks specific device |

### Control

| Voice Command | What It Does |
|---|---|
| **"Turn Bluetooth on"** / **"Enable Bluetooth"** | Enables the Bluetooth adapter |
| **"Turn Bluetooth off"** / **"Disable Bluetooth"** | Disables the adapter |
| **"Connect to AirPods"** | Connects to a named device |
| **"Disconnect my speaker"** | Disconnects a specific device |
| **"Pair my headset"** | Initiates pairing |

---

## Volume Control

All volume commands are handled deterministically (no LLM needed) for instant response.

### Status

| Voice Command | What It Returns |
|---|---|
| **"What's the volume?"** | Current system volume percentage |
| **"Current volume"** | Same |
| **"Is the system muted?"** | Mute status |

### Adjustment

| Voice Command | What It Does |
|---|---|
| **"Set volume to 50 percent"** | Sets exact level |
| **"Volume 80"** | Sets to 80% |
| **"Volume up"** / **"Louder"** | Increases volume |
| **"Volume down"** / **"Quieter"** | Decreases volume |
| **"Mute"** | Mutes system audio |
| **"Unmute"** | Unmutes system audio |

---

## Application Control

ARGO can open, close, check, and switch between Windows applications.

### Open / Launch

| Voice Command | What It Does |
|---|---|
| **"Open Notepad"** | Launches Notepad |
| **"Launch Calculator"** | Launches Calculator |
| **"Open Chrome"** | Launches Google Chrome |
| **"Start Word"** | Launches Microsoft Word |

### Close / Exit

| Voice Command | What It Does |
|---|---|
| **"Close Word"** | Closes Microsoft Word |
| **"Exit Chrome"** | Closes Chrome |

### Check Running Apps

| Voice Command | What It Returns |
|---|---|
| **"Is Notepad open?"** | Yes/no status |
| **"Is Word running?"** | Yes/no status |
| **"What apps are running?"** | List of running applications |
| **"List running applications"** | Same |

### Window Focus

| Voice Command | What It Does |
|---|---|
| **"What app is active?"** | Reports the foreground window |
| **"What's in the foreground?"** | Same |
| **"Focus Notepad"** | Brings Notepad to front |
| **"Switch to Word"** | Switches to Word window |

---

## Time & Date

Instant, deterministic time and date responses.

### Local Time

| Voice Command | What It Returns |
|---|---|
| **"What time is it?"** | Current local time |
| **"Current time"** | Same |
| **"Time now"** | Same |

### Day & Date

| Voice Command | What It Returns |
|---|---|
| **"What day is it?"** | Current day of the week |
| **"What's today's date?"** | Full date |
| **"What is the date?"** | Same |

### World Clock

| Voice Command | What It Returns |
|---|---|
| **"What time is it in London?"** | London time with timezone |
| **"Time in Tokyo"** | Tokyo time |
| **"Current time in New York"** | New York time |

---

## Smart Home Control

ARGO integrates with **Home Assistant** to control smart home devices — lights, switches, thermostats, TVs, fans, locks, blinds, and scenes.

### Setup

1. Install [Home Assistant](https://www.home-assistant.io/) on your network
2. Create a **Long-Lived Access Token** in Home Assistant: Profile → Long-Lived Access Tokens → Create Token
3. Add to `config.json`:

```json
{
  "home_assistant": {
    "url": "http://homeassistant.local:8123",
    "token": "YOUR_LONG_LIVED_ACCESS_TOKEN"
  }
}
```

### Lights

| Voice Command | What It Does |
|---|---|
| **"Turn on the living room lights"** | Turns on the light |
| **"Turn off the kitchen light"** | Turns off the light |
| **"Dim the bedroom light to 30%"** | Sets brightness |
| **"Set the living room light to blue"** | Changes color (red, green, blue, white, warm white, yellow, purple, orange, pink, cyan) |

### Switches & Plugs

| Voice Command | What It Does |
|---|---|
| **"Turn on the coffee maker"** | Turns on a smart plug/switch |
| **"Turn off the fan"** | Turns off the device |
| **"Toggle the office light"** | Toggles current state |

### Thermostat / AC / Heat

| Voice Command | What It Does |
|---|---|
| **"Set thermostat to 72"** | Sets target temperature |
| **"Set the AC to 68"** | Sets cooling mode + temperature |
| **"Set the heat to 74"** | Sets heating mode + temperature |

### TV / Media Players

| Voice Command | What It Does |
|---|---|
| **"Turn on the TV"** | Powers on the media player |
| **"Turn off the TV"** | Powers off |

### Locks

| Voice Command | What It Does |
|---|---|
| **"Lock the front door"** | Locks the device |
| **"Unlock the front door"** | Unlocks the device |

### Scenes

| Voice Command | What It Does |
|---|---|
| **"Activate the movie night scene"** | Activates a Home Assistant scene |
| **"Trigger the bedtime scene"** | Same |

### Device Status

| Voice Command | What It Does |
|---|---|
| **"Status of the thermostat"** | Reports current state, temperature |
| **"Is the kitchen light on?"** | Reports on/off state |
| **"List my smart home devices"** | Lists all controllable devices |
| **"Show me all lights"** | Lists lights with current state |

---

## Reminders

ARGO has a SQLite-backed reminder system with background monitoring. When a reminder comes due, ARGO speaks it aloud.

### Setting Reminders

| Voice Command | What Happens |
|---|---|
| **"Remind me to call Sarah in 30 minutes"** | Sets reminder 30 min from now |
| **"Remind me to take medicine at 8pm"** | Sets reminder for 8pm |
| **"Remind me tomorrow to submit the report"** | Sets reminder for 9am tomorrow |
| **"Set a reminder for Friday at 3pm to review code"** | Sets reminder for next Friday |
| **"Remind me to buy milk"** | Default: 1 hour from now |

Supported time expressions:
- **Relative**: "in 30 minutes", "in 2 hours", "in 3 days", "in 1 week"
- **Absolute**: "at 8pm", "at 3:30 am", "at 12pm"
- **Day names**: "on Friday", "on Monday"
- **Relative days**: "today", "tonight", "tomorrow", "day after tomorrow"

### Listing Reminders

| Voice Command | What Happens |
|---|---|
| **"What are my reminders?"** | Lists all active reminders |
| **"Show my reminders"** | Same |
| **"Any reminders?"** | Same |

### Cancelling Reminders

| Voice Command | What Happens |
|---|---|
| **"Cancel the reminder about Sarah"** | Cancels matching reminder |
| **"Delete the reminder to buy milk"** | Same |

### Storage

Reminders are stored in `data/reminders.db` (SQLite). A background thread checks every 30 seconds for due reminders and fires them through TTS.

---

## Calendar

ARGO includes a local calendar system for scheduling events and appointments.

### Adding Events

| Voice Command | What Happens |
|---|---|
| **"Add a calendar event: dentist appointment Friday at 2pm"** | Creates event |
| **"Schedule a meeting with Paul tomorrow at 10am"** | Creates event |
| **"Book an appointment at the office Monday at 9am"** | Creates event with location |

### Checking Your Calendar

| Voice Command | What Happens |
|---|---|
| **"What's on my calendar?"** | Lists events for the next 7 days |
| **"What's on my calendar today?"** | Lists today's events only |
| **"Show my schedule for tomorrow"** | Lists tomorrow's events |
| **"Check my agenda"** | Same as calendar query |

### Cancelling Events

| Voice Command | What Happens |
|---|---|
| **"Cancel the dentist appointment"** | Deletes matching event |
| **"Remove the meeting with Paul"** | Same |

### Storage

Calendar events are stored in `data/reminders.db` alongside reminders (same SQLite database, separate table).

---

## Computer Vision

ARGO can see your screen. Using screenshot capture and GPT-4o vision analysis, ARGO reads errors, describes what's on screen, and answers questions about what you're looking at.

### Requirements

- **mss** package: `pip install mss` (screenshot capture)
- **OpenAI API key** with GPT-4o access (vision analysis)

### Voice Commands

| Voice Command | What Happens |
|---|---|
| "What's on my screen?" | Captures screenshot, describes content |
| "Describe what you see" | Full visual description of screen |
| "Take a screenshot" | Capture and analyze screen |
| "Read the error on my screen" | Finds and reads error messages verbatim |
| "What does this exception mean?" | Reads error and explains with fix suggestions |
| "How many tabs do I have open?" | Answers specific questions about screen content |

### How It Works

1. ARGO captures your primary monitor using `mss`
2. Screenshot is base64-encoded and sent to GPT-4o vision API
3. GPT-4o analyzes the image and returns a concise answer
4. Answer is spoken via TTS

### Implementation

- Module: `tools/vision.py`
- Intents: `VISION_DESCRIBE`, `VISION_READ_ERROR`, `VISION_QUESTION`
- Model: GPT-4o (supports image input natively)

---

## File System Agent

ARGO can search your drives, find files by name or type, locate large files eating disk space, and show recent downloads — all by voice.

### Voice Commands

| Voice Command | What Happens |
|---|---|
| "Find my tax documents on D drive" | Searches by name across specified drive |
| "Search for PDF files" | Searches by file extension |
| "Locate my photos on E drive" | Searches for image files on a drive |
| "Find large files on C drive" | Lists files over 100MB (configurable) |
| "Show me the biggest files" | Finds largest files across drives |
| "What did I download today?" | Shows recently modified Downloads files |
| "Latest downloads" | Lists recent downloads |
| "Recent files this week" | Files modified in last 7 days |

### Supported File Categories

ARGO understands natural language file types:

- **Documents**: PDF, DOC, DOCX, TXT, RTF, MD
- **Images**: JPG, PNG, GIF, SVG, WEBP, BMP
- **Videos**: MP4, MKV, AVI, MOV, WMV
- **Audio**: MP3, WAV, FLAC, AAC, OGG
- **Spreadsheets**: XLSX, XLS, CSV
- **Code**: PY, JS, TS, Java, C, CPP, Go, Rust
- **Archives**: ZIP, RAR, 7Z, TAR, GZ

### Safety

- Scans are read-only — ARGO never moves, deletes, or modifies files
- Skips system directories (`$Recycle.Bin`, `System Volume Information`, `Windows`)
- Time-limited scans (15s max) to prevent hanging on large drives
- Depth-limited traversal (8 levels max)

### Implementation

- Module: `tools/filesystem.py`
- Intents: `FILE_SEARCH`, `FILE_LARGE`, `FILE_RECENT`, `FILE_INFO`

---

## Task Planner

ARGO can execute multi-step tasks. When you chain actions with "and then" or "and also", ARGO breaks the request into steps and executes them sequentially, passing results between steps.

### Voice Commands

| Voice Command | What Happens |
|---|---|
| "Research quantum computing and then email the summary to Sarah" | LLM research → draft email |
| "Find my PDF files and then remind me to review them tomorrow" | File search → set reminder |
| "Look at my screen and then email what you see to Sarah" | Screenshot → draft email |
| "Remind me about the dentist and also schedule it on my calendar" | Set reminder → add calendar event |

### How It Works

1. **Detection**: ARGO detects multi-step requests via connector words ("and then", "and also", "after that") spanning 2+ action domains
2. **Planning**: Rule-based decomposition for common patterns, LLM-based planning for novel requests
3. **Execution**: Steps run sequentially; each step's result feeds into the next via `use_previous`
4. **Reporting**: ARGO summarizes what was completed and what (if anything) failed

### Available Actions

The planner can chain any of ARGO's capabilities:

| Action | Description |
|---|---|
| `search_files` | Search for files by name or type |
| `describe_screen` | Capture and describe screen |
| `read_screen_error` | Read error messages on screen |
| `draft_email` | Draft an email |
| `send_email` | Send an email |
| `save_note` | Save a note |
| `set_reminder` | Set a reminder |
| `add_calendar_event` | Add a calendar event |
| `smart_home` | Control smart home devices |
| `llm_generate` | Generate text with the LLM |
| `summarize` | Summarize text |

### Implementation

- Module: `tools/task_planner.py`
- Intent: `TASK_PLAN`
- Planning: Rule-based patterns + LLM fallback (GPT-4o-mini)

---

## ARGO Identity & Governance

### Identity

| Voice Command | What It Returns |
|---|---|
| **"Who are you?"** | ARGO's identity statement |
| **"What are you?"** | Same |
| **"Who is ARGO?"** | Same |
| **"What's your name?"** | Same |
| **"Tell me about yourself"** | Same |

### Laws & Safety Gates

| Voice Command | What It Returns |
|---|---|
| **"ARGO laws"** | Lists ARGO's operational laws |
| **"What rules do you follow?"** | Same |
| **"Five gates"** | Explains the 5-gate safety system |
| **"Safety gates"** | Same |

ARGO operates under the **Five-Gate Governance Model**:
1. **DryRun** — simulate before executing
2. **Simulation** — verify in sandbox
3. **UserApproval** — get explicit confirmation
4. **PlanID** — log the plan
5. **ReportID** — log the result

---

## Self-Diagnostics

| Voice Command | What It Does |
|---|---|
| **"Run diagnostics"** | Checks all ARGO subsystems |
| **"Check yourself"** | Same |
| **"Are you okay?"** | Quick health check |
| **"Are you working?"** | Same |
| **"Check your systems"** | Full diagnostic report |

---

## Audio Routing

### Status

| Voice Command | What It Returns |
|---|---|
| **"Audio routing status"** | Current input/output device info |
| **"What audio device am I using?"** | Reports active playback/capture devices |

### Control

| Voice Command | What It Does |
|---|---|
| **"Switch audio to speakers"** | Changes output device |
| **"Route audio to headphones"** | Changes output device |

---

## Configuration Reference

ARGO is configured through `config.json`. Here are the key sections:

```json
{
  "system": {
    "log_level": "INFO",
    "debug_mode": false
  },
  "audio": {
    "sample_rate": 16000,
    "device_name": "default",
    "silence_timeout_seconds": 2.5
  },
  "wake_word": {
    "model": "argo",
    "access_key": "YOUR_PORCUPINE_KEY"
  },
  "speech_to_text": {
    "engine": "openai",
    "model": "base"
  },
  "text_to_speech": {
    "engine": "piper",
    "voice": "alan"
  },
  "llm": {
    "model": "qwen:latest",
    "base_url": "http://localhost:11434"
  },
  "personality": {
    "mode": "tommy_gunn"
  },
  "music": {
    "enabled": true,
    "library_path": "I:\\My Music"
  },
  "email": {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "your.email@gmail.com",
    "sender_password": "your-app-password"
  },
  "home_assistant": {
    "url": "http://homeassistant.local:8123",
    "token": "YOUR_LONG_LIVED_ACCESS_TOKEN"
  }
}
```

### Engine Options

| Component | Options | Default |
|---|---|---|
| **STT** | `openai` (cloud Whisper), `whisper_local`, `whisper_cpp` | `openai` |
| **TTS** | `openai` (cloud), `piper` (local) | `piper` |
| **LLM** | `gpt-4o-mini` (cloud), `qwen` (local via Ollama) | `qwen:latest` |

---

## Command Processing Architecture

Every voice command follows this pipeline:

```
Wake Word → STT → Intent Parser → Handler → TTS → Speaker
              ↓
        Brain Memory
     (context injection)
```

1. **Wake Word Detection** — Porcupine listens for "ARGO"
2. **Speech-to-Text** — Converts your voice to text
3. **Brain Pre-Processing** — Updates working memory with your statement
4. **Intent Classification** — Rule-based pattern matching (no LLM latency)
5. **Handler Dispatch** — Deterministic handlers for system commands; LLM for conversational and writing tasks
6. **Brain Post-Processing** — Stores the exchange in short-term memory
7. **Text-to-Speech** — Speaks the response

### Deterministic vs. LLM-Powered

| Deterministic (instant) | LLM-Powered (1-2 sec) |
|---|---|
| Music controls | Email drafting |
| System health queries | Blog writing |
| Bluetooth on/off | Note expansion |
| Volume up/down | Draft editing |
| Time/date | General questions |
| App launch/close | Conversational responses |
| Identity/governance | Search results |
| Smart home control | |
| Reminders & calendar | |

---

*Built by Tommy Gunn. ARGO — your personal Jarvis.*
